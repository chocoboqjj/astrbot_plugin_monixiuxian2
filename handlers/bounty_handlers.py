# handlers/bounty_handlers.py
"""悬赏令处理器"""
from astrbot.api.event import AstrMessageEvent
from ..data import DataBase
from ..managers.bounty_manager import BountyManager
from ..models import Player
from .utils import player_required

__all__ = ["BountyHandlers"]

class BountyHandlers:
    """悬赏令处理器"""
    
    def __init__(self, db: DataBase, bounty_mgr: BountyManager):
        self.db = db
        self.bounty_mgr = bounty_mgr
    
    @player_required
    async def handle_bounty_list(self, player: Player, event: AstrMessageEvent):
        """显示悬赏列表"""
        bounties = await self.bounty_mgr.get_bounty_list(player)
        
        lines = ["📜 悬赏令 · 今日委托", "━━━━━━━━━━━━━━━"]
        for b in bounties:
            reward = b.get("reward", {})
            time_limit = b.get("time_limit", 0) or 0
            # 单位时间收益：让玩家能直接对比不同难度/时长的性价比
            rate_suffix = ""
            if time_limit > 0 and reward.get("stone", 0) > 0:
                rate = reward["stone"] / (time_limit / 3600)
                rate_suffix = f"（约 {rate:.0f} 灵石/时）"
            lines.append(
                f"[{b['id']}] {b['name']}（{b.get('difficulty_name', '未知')}·{b.get('category', '任务')}）\n"
                f"  - 目标：完成 {b.get('count')} 次 | 时限：{time_limit // 60} 分钟\n"
                f"  - 奖励：{reward.get('stone', 0):,} 灵石 + {reward.get('exp', 0):,} 修为{rate_suffix}\n"
                f"  - 说明：{b.get('description', '')}\n"
                f"  - 完成：{self.bounty_mgr.format_completion_hint_short(b.get('progress_tags', []))}"
            )
        lines.append("━━━━━━━━━━━━━━━")
        lines.append("💡 使用 /接取悬赏 <编号> 接取任务")
        
        yield event.plain_result("\n".join(lines))
    
    @player_required
    async def handle_accept_bounty(self, player: Player, event: AstrMessageEvent, bounty_id: int = 0):
        """接取悬赏"""
        if bounty_id <= 0:
            yield event.plain_result("❌ 请指定悬赏编号，例如：/接取悬赏 1")
            return
        
        success, msg = await self.bounty_mgr.accept_bounty(player, bounty_id)
        prefix = "✅" if success else "❌"
        yield event.plain_result(f"{prefix} {msg}")
    
    @player_required
    async def handle_bounty_status(self, player: Player, event: AstrMessageEvent):
        """查看悬赏状态"""
        success, msg = await self.bounty_mgr.check_bounty_status(player)
        yield event.plain_result(msg)
    
    @player_required
    async def handle_complete_bounty(self, player: Player, event: AstrMessageEvent):
        """完成悬赏"""
        success, msg = await self.bounty_mgr.complete_bounty(player)
        prefix = "✅" if success else "❌"
        yield event.plain_result(f"{prefix} {msg}")
    
    @player_required
    async def handle_abandon_bounty(self, player: Player, event: AstrMessageEvent):
        """放弃悬赏"""
        success, msg = await self.bounty_mgr.abandon_bounty(player)
        prefix = "✅" if success else "❌"
        yield event.plain_result(f"{prefix} {msg}")
