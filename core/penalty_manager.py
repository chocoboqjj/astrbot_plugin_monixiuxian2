"""统一惩罚入口

本模块把所有会导致玩家「身死道消 / 数据清除」的场景收敛到同一套流程，
避免各系统各自调用 `delete_player_cascade` 而遗漏副作用（例如宗门传位）。

覆盖的惩罚场景：
1. 突破失败走火入魔（core/breakthrough_manager.py）
2. 银行逾期追杀（managers/bank_manager.py、handlers/utils.py）
3. 弃道重修（handlers/player_handler.py）

核心副作用（统一处理，不再散落）：
- 若玩家为某宗门宗主 → 自动传位给合适成员；无成员则解散宗门（避免孤儿宗门）
- 成员关系清理：解散宗门时将成员 sect_id 归零
- 级联清除玩家全部关联数据
- 统一落库「惩罚原因」，便于日志与后续统计
"""

from typing import Optional, Tuple

from ..data import DataBase
from ..models import Player

__all__ = ["PenaltyManager", "PenaltyReason"]


class PenaltyReason:
    """惩罚原因常量（用于日志/流水/后续扩展）"""

    BREAKTHROUGH_DEATH = "breakthrough_death"      # 突破失败走火入魔
    BANK_KILL = "bank_kill"                        # 银行逾期追杀
    ABANDON_REBUILD = "abandon_rebuild"            # 弃道重修

    @classmethod
    def descriptions(cls) -> dict:
        return {
            cls.BREAKTHROUGH_DEATH: "突破失败，走火入魔",
            cls.BANK_KILL: "逾期未还款，被银行追杀",
            cls.ABANDON_REBUILD: "主动弃道重修",
        }


class PenaltyManager:
    """玩家惩罚的统一调度器"""

    def __init__(self, db: DataBase, sect_manager=None):
        self.db = db
        # 延迟注入 sect_manager，避免 core -> managers 的循环依赖
        self.sect_manager = sect_manager

    # ------------------------------------------------------------------
    # 对外主入口
    # ------------------------------------------------------------------
    async def punish(
        self,
        player: Player,
        reason: str = PenaltyReason.BREAKTHROUGH_DEATH,
        *,
        extra_note: str = "",
    ) -> Tuple[bool, str]:
        """执行惩罚：处理宗门关系 + 级联删除玩家数据

        Args:
            player: 目标玩家
            reason: 惩罚原因（见 PenaltyReason）
            extra_note: 附加说明（写入日志，不影响流程）

        Returns:
            (是否成功, 面向玩家的结果说明)
        """
        user_id = player.user_id
        sect_note = ""

        try:
            # 1) 宗门关系处理（传位 / 解散）
            sect_note = await self._handle_sect_membership(player)

            # 2) 级联删除玩家全部关联数据
            await self.db.delete_player_cascade(user_id)

            # 3) 记录日志
            desc = PenaltyReason.descriptions().get(reason, reason)
            if extra_note:
                desc = f"{desc}（{extra_note}）"
            self._log_punish(user_id, player, desc)

            return True, sect_note
        except Exception as e:
            self._log_error(user_id, e)
            return False, f"惩罚执行失败：{e}"

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    async def _handle_sect_membership(self, player: Player) -> str:
        """处理玩家与宗门的关系，返回给玩家看的说明文本

        - 玩家是普通成员 → 直接脱离（sect_id 归零）
        - 玩家是宗主 → 优先自动传位；无合适成员则解散宗门
        """
        sect_id = getattr(player, "sect_id", 0) or 0
        if not sect_id:
            return ""

        try:
            if self.sect_manager is not None:
                # 走 SectManager 的权威逻辑（内部已包含传位/解散与成员清理）
                ok, msg = await self.sect_manager.handle_owner_death(sect_id, player.user_id)
                if ok:
                    return f"🏛 {msg}"
                # handle_owner_death 失败时退回本地清理
            return await self._fallback_clear_membership(player, sect_id)
        except Exception:
            return await self._fallback_clear_membership(player, sect_id)

    async def _fallback_clear_membership(self, player: Player, sect_id: int) -> str:
        """兜底：不经 SectManager，直接清理玩家的宗门关系

        玩家为宗主时删除该宗门并释放所有成员；否则仅将自身 sect_id 归零。
        """
        try:
            sect = await self.db.ext.get_sect_by_id(sect_id)
        except Exception:
            sect = None

        if sect is not None and sect.sect_owner == player.user_id:
            try:
                members = await self.db.ext.get_sect_members(sect_id)
            except Exception:
                members = []
            for m in members:
                if m.user_id == player.user_id:
                    continue
                try:
                    await self.db.ext.update_player_sect_info(m.user_id, 0, 4)
                except Exception:
                    continue
            try:
                await self.db.ext.delete_sect(sect_id)
            except Exception:
                pass
            return "🏛 你所创宗门因掌门身死而解散，门人已各奔前程。"

        try:
            await self.db.ext.update_player_sect_info(player.user_id, 0, 4)
        except Exception:
            pass
        return "🏛 你已脱离宗门。"

    def _log_punish(self, user_id: str, player: Player, desc: str) -> None:
        try:
            from astrbot.api import logger
            logger.info(
                f"[PenaltyManager] 玩家 {user_id}({player.user_name or '无名'}) 执行惩罚：{desc}"
            )
        except Exception:
            pass

    def _log_error(self, user_id: str, e: Exception) -> None:
        try:
            from astrbot.api import logger
            logger.error(f"[PenaltyManager] 惩罚执行异常 player={user_id}: {e}")
        except Exception:
            pass
