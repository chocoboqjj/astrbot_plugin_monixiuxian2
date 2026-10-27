# handlers/technique_handlers.py
"""功法残页合成处理器（v3.3.8）"""

from astrbot.api.event import AstrMessageEvent
from ..data import DataBase
from ..managers.technique_manager import TechniqueManager
from ..models import Player
from .utils import player_required

__all__ = ["TechniqueHandlers"]


class TechniqueHandlers:
    """功法合成处理器"""

    def __init__(self, db: DataBase, technique_mgr: TechniqueManager):
        self.db = db
        self.mgr = technique_mgr

    @player_required
    async def handle_technique_recipes(self, player: Player, event: AstrMessageEvent):
        """查看功法合成配方"""
        success, msg = await self.mgr.get_available_recipes(player.user_id)
        yield event.plain_result(msg)

    @player_required
    async def handle_craft_technique(self, player: Player, event: AstrMessageEvent, pages: int = 1):
        """合成功法：/合成功法 <残页数量>"""
        success, msg, _ = await self.mgr.craft_technique(player.user_id, pages)
        yield event.plain_result(msg)
