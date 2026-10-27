# handlers/forge_handlers.py
from astrbot.api.event import AstrMessageEvent
from ..data import DataBase
from ..models import Player
from ..managers.forge_manager import ForgeManager
from .utils import player_required

__all__ = ["ForgeHandlers"]


class ForgeHandlers:
    """炼器系统处理器（装备打造 + 精炼升星）"""

    def __init__(self, db: DataBase, forge_mgr: ForgeManager):
        self.db = db
        self.forge_mgr = forge_mgr

    async def handle_recipes(self, event: AstrMessageEvent):
        """炼器配方列表"""
        user_id = event.get_sender_id()
        success, msg = await self.forge_mgr.get_available_recipes(user_id)
        yield event.plain_result(msg)

    async def handle_forge(self, event: AstrMessageEvent, recipe_id: int = 0):
        """炼器（打造装备）"""
        user_id = event.get_sender_id()
        if not recipe_id:
            yield event.plain_result(
                "❌ 请输入配方ID。\n💡 使用 /炼器配方 查看可打造的装备"
            )
            return
        player = await self.db.get_player_by_id(user_id)
        if not player:
            yield event.plain_result("❌ 你还未踏入修仙之路！")
            return
        success, msg, _ = await self.forge_mgr.forge_equipment(player.user_id, int(recipe_id))
        yield event.plain_result(msg)

    @player_required
    async def handle_refine(self, player: Player, event: AstrMessageEvent, item_name: str = ""):
        """精炼升星"""
        success, msg, _ = await self.forge_mgr.refine_equipment(player.user_id, item_name)
        yield event.plain_result(msg)
