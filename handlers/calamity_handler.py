# handlers/calamity_handler.py
"""天灾人祸处理器（v3.2.9）"""
from astrbot.api.event import AstrMessageEvent

from ..data import DataBase
from ..managers.calamity_manager import CalamityManager
from ..models import Player
from .utils import player_required

__all__ = ["CalamityHandlers"]


class CalamityHandlers:
    """天灾人祸处理器"""

    def __init__(self, db: DataBase, calamity_mgr: CalamityManager):
        self.db = db
        self.mgr = calamity_mgr

    @player_required
    async def handle_calamity_info(self, player: Player, event: AstrMessageEvent):
        """查看天灾纪事与自己的受害档案"""
        # 近期纪事（全局）+ 自己的受害档案
        recent_text = await self.mgr.format_recent_text(10)
        name = player.user_name or f"道友{str(player.user_id)[:6]}"
        my_text = await self.mgr.format_history_text(player.user_id, name, 5)

        yield event.plain_result(f"{recent_text}\n\n{my_text}")
