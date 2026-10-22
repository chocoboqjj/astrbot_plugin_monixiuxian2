# handlers/sect_handlers.py
from astrbot.api.event import AstrMessageEvent
from astrbot.api.all import *
from ..managers.sect_manager import SectManager
from ..data.data_manager import DataBase
from .utils import extract_target_id

class SectHandlers:
    def __init__(self, db: DataBase, sect_mgr: SectManager):
        self.db = db
        self.sect_mgr = sect_mgr

    async def handle_create_sect(self, event: AstrMessageEvent, name: str):
        """创建宗门"""
        user_id = event.get_sender_id()
        # 宗门操作为瞬时操作，不受闭关/历练/秘境影响
        success, msg = await self.sect_mgr.create_sect(user_id, name)
        yield event.plain_result(msg)

    async def handle_join_sect(self, event: AstrMessageEvent, name: str):
        """加入宗门"""
        user_id = event.get_sender_id()
        # 宗门操作为瞬时操作，不受闭关/历练/秘境影响
        success, msg = await self.sect_mgr.join_sect(user_id, name)
        yield event.plain_result(msg)
    
    async def handle_leave_sect(self, event: AstrMessageEvent):
        """退出宗门"""
        user_id = event.get_sender_id()
        # 宗门操作为瞬时操作，不受闭关/历练/秘境影响
        success, msg = await self.sect_mgr.leave_sect(user_id)
        yield event.plain_result(msg)

    async def handle_my_sect(self, event: AstrMessageEvent):
        """我的宗门"""
        user_id = event.get_sender_id()
        success, msg, _ = await self.sect_mgr.get_sect_info(user_id)
        yield event.plain_result(msg)
    
    async def handle_sect_list(self, event: AstrMessageEvent):
        """宗门列表"""
        success, msg = await self.sect_mgr.list_all_sects()
        yield event.plain_result(msg)
    
    async def handle_donate(self, event: AstrMessageEvent, amount: int):
        """宗门捐献"""
        user_id = event.get_sender_id()
        # 宗门操作为瞬时操作，不受闭关/历练/秘境影响
        success, msg = await self.sect_mgr.donate_to_sect(user_id, amount)
        yield event.plain_result(msg)
        
    async def handle_kick_member(self, event: AstrMessageEvent, target: str): # target 可能是 at 或者是 id
        """踢出宗门成员"""
        user_id = event.get_sender_id()
        target_id = extract_target_id(event, target)

        if not target_id:
            yield event.plain_result("❌ 请指定要踢出的成员（At或输入ID）")
            return

        success, msg = await self.sect_mgr.kick_member(user_id, target_id)
        yield event.plain_result(msg)

    async def handle_transfer(self, event: AstrMessageEvent, target: str):
        """宗主传位"""
        user_id = event.get_sender_id()
        target_id = extract_target_id(event, target)

        if not target_id:
            yield event.plain_result("❌ 请指定传位目标（At或输入ID）")
            return

        success, msg = await self.sect_mgr.transfer_ownership(user_id, target_id)
        yield event.plain_result(msg)

    async def handle_position_change(self, event: AstrMessageEvent, target: str, position: int):
        """职位变更"""
        user_id = event.get_sender_id()
        target_id = extract_target_id(event, target)

        if not target_id:
            yield event.plain_result("❌ 请指定目标（At或输入ID）")
            return

        success, msg = await self.sect_mgr.change_position(user_id, target_id, position)
        yield event.plain_result(msg)

    async def handle_sect_task(self, event: AstrMessageEvent):
        """执行宗门任务"""
        user_id = event.get_sender_id()
        success, msg = await self.sect_mgr.perform_sect_task(user_id)
        yield event.plain_result(msg)

    async def handle_sect_upgrade(self, event: AstrMessageEvent):
        """宗门建设（升级丹房）"""
        user_id = event.get_sender_id()
        success, msg = await self.sect_mgr.upgrade_elixir_room(user_id)
        yield event.plain_result(msg)

    async def handle_sect_elixir_info(self, event: AstrMessageEvent):
        """查看宗门丹房建设状态"""
        user_id = event.get_sender_id()
        success, msg = await self.sect_mgr.get_elixir_room_status(user_id)
        yield event.plain_result(msg)

    async def handle_sect_elixir_claim(self, event: AstrMessageEvent):
        """领取宗门每日丹药"""
        user_id = event.get_sender_id()
        success, msg = await self.sect_mgr.claim_sect_elixir(user_id)
        yield event.plain_result(msg)
