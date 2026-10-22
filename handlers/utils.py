# handlers/utils.py
# 通用工具函数和装饰器

import re
import time
from functools import wraps
from typing import Callable, Coroutine, AsyncGenerator

from astrbot.api.event import AstrMessageEvent
from astrbot.api.all import At
from astrbot.api import logger
from ..models import Player

# 指令常量
CMD_START_XIUXIAN = "我要修仙"
CMD_PLAYER_INFO = "我的信息"
CMD_START_CULTIVATION = "闭关"
CMD_END_CULTIVATION = "出关"
CMD_CHECK_IN = "签到"

# ===== 多活动并行辅助 =====
# 闭关 / 历练 / 秘境 现在是三种**可并行**的离线收益，
# 玩家可以同时挂机，且挂机期间不影响任何其他指令。

def get_activity_manager(db):
    """获取活动管理器（未注入时返回 None）"""
    return getattr(db, "activity_mgr", None)


async def is_activity_active(db, user_id: str, activity_type: str) -> bool:
    """判断某项活动是否正在进行"""
    mgr = get_activity_manager(db)
    if mgr is None:
        # 降级：回退到旧 user_cd 单槽位判断
        try:
            cd = await db.ext.get_user_cd(user_id)
        except Exception:
            return False
        legacy_map = {
            "cultivation": 1,
            "adventure": 2,
            "rift": 3,
        }
        return bool(cd and cd.type == legacy_map.get(activity_type, -1))
    return await mgr.is_active(user_id, activity_type)


async def get_active_activity_names(db, user_id: str) -> list:
    """获取玩家进行中的活动名称列表（用于提示文案）"""
    mgr = get_activity_manager(db)
    names = {
        "cultivation": "闭关中",
        "adventure": "历练中",
        "rift": "探索秘境中",
    }
    if mgr is None:
        return []
    types = await mgr.active_types(user_id)
    return [names.get(t, t) for t in types]


def extract_target_id(event: AstrMessageEvent, arg: str = "") -> str:
    """统一提取目标用户ID，兼容 OneBot(CQ码/At/纯数字) 与 QQ 官方机器人(At/openid)。

    提取优先级：
      1. 消息链中的 At 组件（取 qq/target/uin/user_id，并去掉可能的 @ 前缀）
      2. 指令参数 arg（去掉 @ 前缀后直接作为 ID，兼容 openid 等非数字 ID）
      3. 消息纯文本兜底（主要服务 OneBot 场景：残留 CQ 码 / 纯数字 ID）

    说明：QQ 官方机器人的 user_id / group_openid 为非数字字符串，
    因此不能再使用 isdigit() 来判断一个 ID 是否有效。
    """
    # 1) 消息链 At 组件优先（两个平台均可靠）
    if hasattr(event, "message_obj") and event.message_obj:
        chain = getattr(event.message_obj, "message", []) or []
        for comp in chain:
            if isinstance(comp, At):
                for attr in ("qq", "target", "uin", "user_id"):
                    val = getattr(comp, attr, None)
                    if val:
                        return str(val).lstrip("@")

    # 2) 指令参数（兼容 /指令 @某人 或 /指令 用户ID）
    if arg:
        cleaned = arg.strip().lstrip("@").strip()
        if cleaned:
            return cleaned

    # 3) 纯文本兜底（主要服务 OneBot 场景）
    if hasattr(event, "get_message_str"):
        text = event.get_message_str() or ""
        at_match = re.search(r"\[CQ:at,qq=(\d+)\]", text)
        if at_match:
            return at_match.group(1)
        num_match = re.search(r"(\d{5,})", text)
        if num_match:
            return num_match.group(1)

    return ""


def player_required(func: Callable[..., Coroutine[any, any, AsyncGenerator[any, None]]]):
    """
    一个装饰器，用于需要玩家登录才能执行的指令。
    它会自动检查玩家是否存在，否则将玩家对象作为参数注入。
    同时检查贷款状态，如有贷款则显示还款提示。

    ⚠️ 状态互锁说明（v3.1.8 起）：
    此前本装饰器会在玩家「闭关中/历练中/秘境中」时封锁几乎所有指令，
    导致玩家离线挂机期间完全无法互动。现已移除全局封锁：
    闭关 / 历练 / 秘境 三种活动**可同时进行**且**不限制其他指令**，
    只有各玩法自身会拒绝「重复启动同类活动」。
    """
    @wraps(func)
    async def wrapper(self, event: AstrMessageEvent, *args, **kwargs):
        # self 是 Handler 类的实例 (e.g., PlayerHandler)
        player = await self.db.get_player_by_id(event.get_sender_id())

        if not player:
            yield event.plain_result(f"道友尚未踏入仙途，请发送「{CMD_START_XIUXIAN}」开启你的旅程。")
            return

        # 检查贷款状态并处理逾期
        loan_warning = await _check_loan_status(self.db, player)
        if loan_warning:
            if loan_warning.get("is_dead"):
                # 玩家因逾期被追杀，删除数据
                yield event.plain_result(loan_warning["message"])
                return
        
        # 将 player 对象作为第一个参数传递给原始函数
        async for result in func(self, player, event, *args, **kwargs):
            yield result
        
        # 如果有贷款警告，在指令执行完后显示
        if loan_warning and loan_warning.get("warning_message"):
            yield event.plain_result(loan_warning["warning_message"])

    return wrapper


async def _check_loan_status(db, player: Player) -> dict:
    """检查玩家贷款状态
    
    Returns:
        dict: {is_dead, message, warning_message} 或 None
    """
    try:
        loan = await db.ext.get_active_loan(player.user_id)
        if not loan:
            return None
        
        now = int(time.time())
        due_at = loan["due_at"]
        
        # 检查是否已逾期
        if now > due_at:
            # 使用事务保护，防止并发删除
            await db.conn.execute("BEGIN IMMEDIATE")
            try:
                # 重新检查贷款状态（可能已被其他请求处理）
                loan = await db.ext.get_active_loan(player.user_id)
                if not loan or loan["status"] != "active":
                    await db.conn.rollback()
                    return None
                
                # 再次检查是否逾期
                if now <= loan["due_at"]:
                    await db.conn.rollback()
                    return None
                
                player_name = player.user_name or f"道友{player.user_id[:6]}"
                
                # 统一惩罚入口：处理宗门善后 + 级联删除所有关联数据
                penalty_mgr = getattr(db, "penalty_mgr", None)
                sect_note = ""
                if penalty_mgr is not None:
                    from ..core.penalty_manager import PenaltyReason
                    ok, note = await penalty_mgr.punish(
                        player, PenaltyReason.BANK_KILL
                    )
                    if ok:
                        sect_note = note
                    else:
                        # 惩罚失败时兜底直接删除，保证「身死道消」语义一致
                        logger.error(f"[utils] 统一惩罚失败，兜底级联删除: {note}")
                        await db.delete_player_cascade(player.user_id)
                else:
                    # 降级：未注入 penalty_mgr 时保持原有行为
                    await db.delete_player_cascade(player.user_id)
                
                # 标记贷款逾期
                await db.ext.mark_loan_overdue(loan["id"])
                
                # 记录流水
                await db.ext.add_bank_transaction(
                    player.user_id, "bank_kill", 0, 0,
                    "逾期未还款，被银行追杀致死", now
                )
                
                await db.conn.commit()
                
                loan_type_name = "突破贷款" if loan["loan_type"] == "breakthrough" else "普通贷款"
                
                return {
                    "is_dead": True,
                    "message": (
                        f"💀 银行追杀令 💀\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"道友【{player_name}】因{loan_type_name}逾期未还\n"
                        f"欠款本金：{loan['principal']:,} 灵石\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"银行派出的追杀者已将你击杀！\n"
                        f"所有修为和装备化为虚无...\n"
                        f"━━━━━━━━━━━━━━━\n"
                        + (f"{sect_note}\n" if sect_note else "")
                        + f"若想重新修仙，请使用「我要修仙」命令"
                    )
                }
            except Exception:
                await db.conn.rollback()
                raise
        
        # 计算剩余时间
        remaining_seconds = due_at - now
        remaining_days = remaining_seconds // 86400
        remaining_hours = (remaining_seconds % 86400) // 3600
        
        # 计算应还金额
        days_borrowed = max(1, (now - loan["borrowed_at"]) // 86400)
        interest = int(loan["principal"] * loan["interest_rate"] * days_borrowed)
        total_due = loan["principal"] + interest
        
        loan_type_name = "突破贷款" if loan["loan_type"] == "breakthrough" else "普通贷款"
        
        # 根据剩余时间设置警告等级
        if remaining_days <= 0:
            urgency = "🔴 紧急"
            time_str = f"{remaining_hours} 小时"
        elif remaining_days <= 1:
            urgency = "🟠 警告"
            time_str = f"{remaining_days} 天 {remaining_hours} 小时"
        else:
            urgency = "🟡 提醒"
            time_str = f"{remaining_days} 天"
        
        warning_message = (
            f"\n━━━━━━━━━━━━━━━\n"
            f"{urgency}【{loan_type_name}还款提醒】\n"
            f"应还金额：{total_due:,} 灵石\n"
            f"剩余时间：{time_str}\n"
            f"⚠️ 逾期将被银行追杀致死！\n"
            f"请使用 /还款 命令还款"
        )
        
        return {
            "is_dead": False,
            "warning_message": warning_message
        }
        
    except Exception:
        return None
