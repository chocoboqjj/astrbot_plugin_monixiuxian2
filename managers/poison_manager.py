# managers/poison_manager.py
"""
投毒系统管理器（v3.3.8）

对应用户诉求：「增加投毒功能，将减益丹喂出去，有概率被发现受惩罚，参考电鱼」。

机制设计（参考「电鱼」式博弈：出手有风险，收益与风险同在）：
1. **材料消耗**：投毒需要消耗「减益丹」（utility_pills.json 中 subtype ∈ {debuff, breakthrough_debuff}）。
   没有减益丹 ⇒ 无法投毒。
2. **被发现概率**：每次投毒有基础概率被发现（受目标境界、精神力影响）。
   - 目标境界越高 ⇒ 越难被发现（高人难欺）。
   - 目标精神力越高 ⇒ 越难被发现。
   - 投毒者境界越低 ⇒ 越容易被察觉。
3. **被发现惩罚**：
   - 灵石损失（按目标境界与投毒丹品级计算罚款）。
   - 投毒者获得「劣迹」标记（短期不能再投毒）。
   - 目标获得「定魂丹」式免疫提示：被投毒者下次免疫同类减益（可选）。
4. **投毒成功**：给目标挂上该减益丹的临时效果（负值倍率），持续时间取丹药配置。

⚠️ 数据一致性：所有共享同一 aiosqlite 连接 ⇒ 事务边界是**连接级**，
   因此扣灵石必须用「原地加减」（`gold = MAX(0, gold - ?)`），
   绝不能「读旧值 → 写回绝对值」（会丢更新）。
"""

import random
import time
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from ..models import Player

if TYPE_CHECKING:
    from ..data.data_manager import DataBase
    from ..config_manager import ConfigManager

__all__ = ["PoisonManager"]


class PoisonManager:
    """投毒系统管理器"""

    # 可投毒的减益丹 subtype
    DEBUFF_SUBTYPES = {"debuff", "breakthrough_debuff"}

    # 投毒冷却（秒）：投毒人自身冷却，避免连续刷
    POISON_COOLDOWN = 1800  # 30 分钟

    def __init__(self, db: "DataBase", config_manager: "ConfigManager" = None):
        self.db = db
        self.config_manager = config_manager

    # ------------------------------------------------------------------
    # 减益丹清单
    # ------------------------------------------------------------------
    def get_poisonable_pills(self) -> Dict[str, dict]:
        """列出所有可投毒的减益丹（名称 → 配置）"""
        result: Dict[str, dict] = {}
        if not self.config_manager:
            return result
        for name, cfg in self.config_manager.utility_pills_data.items():
            if isinstance(cfg, dict) and cfg.get("subtype") in self.DEBUFF_SUBTYPES:
                result[name] = cfg
        return result

    def is_poisonable(self, pill_name: str) -> bool:
        """该丹药是否可用于投毒"""
        return pill_name in self.get_poisonable_pills()

    # ------------------------------------------------------------------
    # 发现概率与惩罚
    # ------------------------------------------------------------------
    def _discovery_rate(self, attacker: Player, target: Player) -> int:
        """计算本次投毒被发现的概率（百分比）。

        规则：
        - 基础 35%。
        - 目标境界每高于投毒者 3 层，+5%（高人难欺）。
        - 目标精神力每高于投毒者 1000 点，+3%（心志坚定者不易被暗算）。
        - 投毒者境界高于目标时，-5%（强者不易露怯）。
        - 上下限 10% ~ 85%。
        """
        rate = 35
        level_gap = target.level_index - attacker.level_index
        rate += (level_gap // 3) * 5
        mp_gap = (target.mental_power or 0) - (attacker.mental_power or 0)
        rate += (mp_gap // 1000) * 3
        if level_gap < 0:
            rate -= 5
        return max(10, min(85, rate))

    def _fine_amount(self, target: Player, pill_cfg: dict) -> int:
        """被发现时的灵石罚款。"""
        base = 500 + target.level_index * 200
        # 品级越高罚得越重
        rank_mult = {"凡品": 1, "灵品": 2, "地品": 3, "天品": 4, "皇品": 6,
                     "圣品": 8, "帝品": 12, "道品": 16, "仙品": 20, "神品": 25}
        base *= rank_mult.get(pill_cfg.get("rank", "凡品"), 1)
        return int(base)

    # ------------------------------------------------------------------
    # 冷却
    # ------------------------------------------------------------------
    async def _get_cooldown(self, user_id: str) -> int:
        async with self.db.conn.execute(
            "SELECT value FROM system_config WHERE key = ?",
            (f"poison_cd_{user_id}",)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return 0
            try:
                return int(row[0])
            except (TypeError, ValueError, IndexError):
                return 0

    async def _set_cooldown(self, user_id: str, until_ts: int):
        await self.db.conn.execute(
            "INSERT INTO system_config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"poison_cd_{user_id}", str(int(until_ts)))
        )

    # ------------------------------------------------------------------
    # 投毒主流程
    # ------------------------------------------------------------------
    async def poison(
        self,
        attacker: Player,
        target_id: str,
        pill_name: str
    ) -> Tuple[bool, str]:
        """执行投毒。

        Args:
            attacker: 投毒者
            target_id: 目标玩家 user_id
            pill_name: 减益丹名称

        Returns:
            (是否投毒成功, 提示文案)
        """
        if not attacker.user_id or not target_id:
            return False, "❌ 请指定投毒目标。"
        if attacker.user_id == target_id:
            return False, "❌ 不能给自己投毒。"

        # 1. 校验丹药
        pill_cfg = self.get_poisonable_pills().get(pill_name)
        if not pill_cfg:
            return False, f"❌ 【{pill_name}】不是可用于投毒的减益丹。"

        # 2. 检查背包
        inventory = attacker.get_pills_inventory()
        if inventory.get(pill_name, 0) <= 0:
            return False, f"❌ 你的丹药背包中没有【{pill_name}】！"

        # 3. 目标存在
        target = await self.db.get_player_by_id(target_id)
        if not target:
            return False, "❌ 目标尚未踏入修仙之路，无从投毒。"

        # 4. 冷却检查
        now = int(time.time())
        cd = await self._get_cooldown(attacker.user_id)
        if cd > now:
            remain = cd - now
            return False, (
                f"⏳ 投毒冷却中，还需 {remain // 60} 分 {remain % 60} 秒。\n"
                f"💡 投毒风险极大，需潜心等待风头过去。"
            )

        # 5. 扣除丹药（投毒必消耗，无论是否被发现）
        inventory[ pill_name] -= 1
        if inventory[pill_name] <= 0:
            del inventory[pill_name]
        attacker.set_pills_inventory(inventory)

        # 6. 判定是否被发现
        rate = self._discovery_rate(attacker, target)
        discovered = random.randint(1, 100) <= rate

        if discovered:
            # ===== 被发现：惩罚 =====
            fine = self._fine_amount(target, pill_cfg)
            await self.db.conn.execute(
                "UPDATE players SET gold = MAX(0, gold - ?) WHERE user_id = ?",
                (fine, attacker.user_id)
            )
            await self._set_cooldown(attacker.user_id, now + self.POISON_COOLDOWN)
            await self.db.update_player(attacker)

            return False, (
                f"🚨 投毒被发现了！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"你的毒计被【{target.user_name or target_id[:8]}】识破！\n"
                f"💸 赔偿灵石 -{fine:,}\n"
                f"⏳ 投毒冷却 {self.POISON_COOLDOWN // 60} 分钟\n"
                f"🎲 被发现概率：{rate}%"
            )

        # ===== 未被发现：投毒成功，给目标挂减益 =====
        effect = self._build_debuff_effect(pill_name, pill_cfg, now)
        target_effects = target.get_active_pill_effects()
        target_effects.append(effect)
        target.set_active_pill_effects(target_effects)
        await self.db.update_player(target)

        await self._set_cooldown(attacker.user_id, now + self.POISON_COOLDOWN)
        await self.db.update_player(attacker)

        desc = self._describe_debuff(pill_cfg)
        return True, (
            f"🧪 投毒成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"【{target.user_name or target_id[:8]}】服下了你的【{pill_name}】。\n"
            f"☠️ 减益效果：{desc}\n"
            f"⏳ 投毒冷却 {self.POISON_COOLDOWN // 60} 分钟\n"
            f"🎲 被发现概率：{rate}%"
        )

    def _build_debuff_effect(self, pill_name: str, pill_cfg: dict, now: int) -> dict:
        """构造挂在目标身上的减益效果记录"""
        duration_minutes = pill_cfg.get("duration_minutes", 60)
        effect = {
            "pill_name": pill_name,
            "pill_id": pill_cfg.get("id", ""),
            "subtype": "poisoned",
            "start_time": now,
            "expiry_time": now + duration_minutes * 60,
            "duration_minutes": duration_minutes,
            "last_tick_time": now,
        }
        # 复制所有负值效果键（倍率 / 突破加成）
        for key in (
            "physical_damage_multiplier", "magic_damage_multiplier",
            "physical_defense_multiplier", "magic_defense_multiplier",
            "cultivation_multiplier", "breakthrough_bonus",
        ):
            value = pill_cfg.get(key)
            if isinstance(value, (int, float)) and value < 0:
                effect[key] = value
        return effect

    def _describe_debuff(self, pill_cfg: dict) -> str:
        """减益效果的中文描述"""
        parts = []
        mapping = {
            "physical_damage_multiplier": "物伤",
            "magic_damage_multiplier": "法伤",
            "physical_defense_multiplier": "物防",
            "magic_defense_multiplier": "法防",
            "cultivation_multiplier": "修炼速度",
            "breakthrough_bonus": "突破成功率",
        }
        for key, label in mapping.items():
            value = pill_cfg.get(key)
            if isinstance(value, (int, float)) and value < 0:
                parts.append(f"{label} {value:.0%}")
        return "、".join(parts) if parts else "属性削弱"

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    async def get_poison_info(self, player: Player) -> str:
        """投毒说明与可用丹药清单"""
        lines = [
            "🧪 投毒",
            "━━━━━━━━━━━━━━━",
            "用减益丹暗算他人。出手有风险——被识破将赔灵石并进入冷却。",
            "",
            "🎯 可用毒丹：",
        ]
        pills = self.get_poisonable_pills()
        if not pills:
            lines.append("  （暂无减益丹）")
        else:
            for name, cfg in pills.items():
                owned = player.get_pills_inventory().get(name, 0)
                mark = "✅" if owned > 0 else "❌"
                lines.append(
                    f"  {mark} {name}（{cfg.get('rank', '凡品')}）×{owned} —— {self._describe_debuff(cfg)}"
                )
        cd = await self._get_cooldown(player.user_id)
        now = int(time.time())
        if cd > now:
            remain = cd - now
            lines.append(f"\n⏳ 投毒冷却中，还需 {remain // 60} 分 {remain % 60} 秒。")
        lines.append("\n💡 用法：/投毒 @某人 <减益丹名>")
        return "\n".join(lines)
