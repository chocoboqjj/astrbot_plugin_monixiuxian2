# handlers/spirit_eye_handlers.py
"""天地灵眼处理器"""
import re

from astrbot.api.event import AstrMessageEvent
from ..data import DataBase
from ..managers.spirit_eye_manager import SpiritEyeManager
from ..models import Player
from .utils import player_required, extract_target_id

__all__ = ["SpiritEyeHandlers"]


class SpiritEyeHandlers:
    """天地灵眼处理器"""
    
    def __init__(self, db: DataBase, eye_mgr: SpiritEyeManager):
        self.db = db
        self.mgr = eye_mgr
    
    @player_required
    async def handle_spirit_eye_info(self, player: Player, event: AstrMessageEvent):
        """查看灵眼信息"""
        info = await self.mgr.get_spirit_eye_info(player.user_id)
        yield event.plain_result(info)
    
    @player_required
    async def handle_claim(self, player: Player, event: AstrMessageEvent, target: str = ""):
        """抢占灵眼：支持「编号抢占无主灵眼」与「@道号争夺他人灵眼」两种用法"""
        arg = (target or "").strip()
        
        # 1) 显式 @ 了某人 → 走 PVP 争夺
        #    只认"消息链 At 组件 / 文本 @ 标记"，不把裸数字当作用户 ID，
        #    否则「/抢占灵眼 3」会被误判成用户 3。
        at_target = extract_target_id(event, arg, allow_bare_id=False, allow_text_number=False)
        if at_target:
            success, msg = await self.mgr.challenge_spirit_eye(player, at_target)
            yield event.plain_result(msg)
            return
        
        # 2) 纯数字 → 灵眼编号
        if re.fullmatch(r"\d+", arg):
            eye_id = int(arg)
            if eye_id <= 0:
                yield event.plain_result("❌ 请指定灵眼ID，例如：/抢占灵眼 1")
                return
            success, msg = await self.mgr.claim_spirit_eye(player, eye_id)
            yield event.plain_result(msg)
            return
        
        # 3) 裸 ID（openid 等非数字标识）→ 也可能是争夺目标
        bare_target = extract_target_id(event, arg, allow_bare_id=True, allow_text_number=False)
        if bare_target:
            success, msg = await self.mgr.challenge_spirit_eye(player, bare_target)
            yield event.plain_result(msg)
            return
        
        yield event.plain_result(
            "❌ 请指定抢占目标。\n"
            "━━━━━━━━━━━━━━━\n"
            "💡 /抢占灵眼 <编号>  抢占无主灵眼\n"
            "💡 /抢占灵眼 @道号  争夺他人灵眼（切磋定胜负）"
        )
    
    @player_required
    async def handle_collect(self, player: Player, event: AstrMessageEvent):
        """收取灵眼收益"""
        success, msg = await self.mgr.collect_spirit_eye(player)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_release(self, player: Player, event: AstrMessageEvent):
        """释放灵眼"""
        success, msg = await self.mgr.release_spirit_eye(player.user_id)
        yield event.plain_result(msg)
