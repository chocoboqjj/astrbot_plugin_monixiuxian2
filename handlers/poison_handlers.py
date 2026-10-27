# handlers/poison_handlers.py
"""投毒系统处理器（v3.3.8）"""

from astrbot.api.event import AstrMessageEvent
from ..data import DataBase
from ..managers.poison_manager import PoisonManager
from ..models import Player
from .utils import player_required, extract_target_id

__all__ = ["PoisonHandlers"]


class PoisonHandlers:
    """投毒处理器"""

    def __init__(self, db: DataBase, poison_mgr: PoisonManager):
        self.db = db
        self.mgr = poison_mgr

    @player_required
    async def handle_poison_info(self, player: Player, event: AstrMessageEvent):
        """查看投毒说明与可用毒丹"""
        yield event.plain_result(await self.mgr.get_poison_info(player))

    @player_required
    async def handle_poison(self, player: Player, event: AstrMessageEvent, args: str = ""):
        """投毒：/投毒 @某人 <减益丹名>"""
        arg = (args or "").strip()
        if not arg:
            yield event.plain_result(
                "❌ 请指定投毒目标与丹药。\n"
                "━━━━━━━━━━━━━━━\n"
                "💡 /投毒 @某人 <减益丹名>\n"
                "💡 /投毒 <用户ID> <减益丹名>"
            )
            return

        # 提取目标：只认 @ 标记与裸 ID，不把数字当用户 ID
        target_id = extract_target_id(event, arg, allow_bare_id=True, allow_text_number=False)
        if not target_id:
            yield event.plain_result(
                "❌ 未识别到投毒目标。\n"
                "━━━━━━━━━━━━━━━\n"
                "💡 请使用 @ 标记对方：/投毒 @某人 <减益丹名>"
            )
            return

        # 剩余文本为丹药名（剔除 @ 标记与目标 ID）
        from .utils import strip_target_from_text
        pill_name = strip_target_from_text(arg, target_id).strip()
        if not pill_name:
            yield event.plain_result(
                "❌ 请指定要使用的减益丹。\n"
                "💡 用法：/投毒 @某人 <减益丹名>"
            )
            return

        success, msg = await self.mgr.poison(player, target_id, pill_name)
        yield event.plain_result(msg)
