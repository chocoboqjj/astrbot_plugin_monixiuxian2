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


# ===== @目标用户 ID 解析 =====
# QQ 官方机器人（qq_official 适配器）的入站消息里，被 @ 的**其他用户**不会进入消息链，
# 而是以文本标记的形式留在纯文本中：
#   <@!member_openid>          旧版协议
#   <qqbot-at-user id="..."/>  新版协议
# 其中 member_openid 与 event.get_sender_id() 同源，可直接作为玩家库主键
# （参见腾讯官方 openclaw-qqbot 的 stripMentionText：优先取 member_openid）。
# OneBot 侧则是结构化 At 组件 + "@昵称(QQ号)" 文本表示。
_AT_MARKUP_PATTERNS = (
    re.compile(r"<@!?(?P<id>[^<>\s\"']+)>"),
    re.compile(r"<qqbot-at-user\s+id=[\"'](?P<id>[^\"']+)[\"']\s*/?>", re.IGNORECASE),
    # OneBot v11：数组格式下 CQ 码不会残留，兼容字符串格式与历史数据
    re.compile(r"\[CQ:at,qq=(?P<id>\d+)\]"),
    # OneBot v11：aiocqhttp 适配器把 @ 合成为 "@昵称(QQ号)" 文本
    re.compile(r"@[^\s(@]{0,30}\((?P<id>\d{5,})\)"),
)

# 这些值不是真实用户 ID：AstrBot 的 qq_official 适配器在消息链里放的 At 只代表"机器人自己"
_PLACEHOLDER_IDS = {
    "",
    "0",
    "all",
    "everyone",
    "here",
    "none",
    "qq_official",
    "unknown_selfid",
}


def _clean_candidate_id(value) -> str:
    """规范化候选 ID；占位符（机器人自身/全体成员等）与纯符号一律返回空串。"""
    text = str(value if value is not None else "").strip().lstrip("@").strip()
    if not text or text.lower() in _PLACEHOLDER_IDS:
        return ""
    if not any(ch.isalnum() for ch in text):
        return ""
    return text


def _get_message_text(event) -> str:
    """安全获取消息纯文本。"""
    try:
        if hasattr(event, "get_message_str"):
            return event.get_message_str() or ""
    except Exception:
        pass
    return ""


def _iter_self_ids(event) -> set:
    """机器人自身 ID 与发送者 ID：消息链里代表这两个身份的 At 必须跳过。"""
    values = set()
    for name in ("get_self_id", "get_sender_id"):
        try:
            getter = getattr(event, name, None)
            value = getter() if callable(getter) else None
        except Exception:
            value = None
        if value:
            values.add(str(value))
    return values


def _iter_text_at_ids(text: str):
    """按在文本中出现的顺序产出所有 @ 标记的用户 ID。"""
    if not text:
        return
    hits = []
    for pattern in _AT_MARKUP_PATTERNS:
        for match in pattern.finditer(text):
            candidate = _clean_candidate_id(match.group("id"))
            if candidate:
                hits.append((match.start(), candidate))
    for _, candidate in sorted(hits, key=lambda item: item[0]):
        yield candidate


def strip_at_markup(text: str) -> str:
    """移除文本中所有已识别的 @ 标记，避免污染后续的物品名/数量等参数解析。"""
    if not text:
        return text
    for pattern in _AT_MARKUP_PATTERNS:
        text = pattern.sub(" ", text)
    return text


def strip_target_from_text(text: str, target_id: str = "") -> str:
    """剔除 @ 标记以及已解析出的目标 ID（含可选的 @ 前缀）。"""
    cleaned = strip_at_markup(text)
    if target_id:
        cleaned = re.sub(
            r"(?<!\S)@?" + re.escape(str(target_id)) + r"(?!\S)",
            " ",
            cleaned,
        )
    return cleaned


def looks_like_user_id(token: str) -> bool:
    """判断 token 是否像"用户 ID"而非普通参数（如物品名）。

    QQ 官方机器人的 openid 与 OneBot 的 QQ 号都是非中文、长度 >= 5 的串；
    游戏内物品名均为中文，据此可在没有 @ 标记时区分二者。
    """
    text = str(token if token is not None else "").strip().lstrip("@").strip()
    if len(text) < 5:
        return False
    return not any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _extract_mention_from_raw(event) -> str:
    """QQ 官方兜底：从原始 payload 的 mentions 列表取第一个"非机器人"的 @。

    某些场景下平台不会把 @ 标记留在 content 里，此时只能从结构化 mentions 还原。
    """
    try:
        platform = str(event.get_platform_name() or "").lower()
    except Exception:
        platform = ""
    if "qq" not in platform:
        return ""
    try:
        raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
    except Exception:
        return ""
    mentions = raw.get("mentions") if isinstance(raw, dict) else getattr(raw, "mentions", None)
    if not mentions:
        return ""
    for mention in mentions:
        if isinstance(mention, dict):
            def field(key, _m=mention):
                return _m.get(key)
        else:
            def field(key, _m=mention):
                return getattr(_m, key, None)
        if field("is_you") or field("bot"):
            continue
        for key in ("member_openid", "id", "user_openid"):
            candidate = _clean_candidate_id(field(key))
            if candidate:
                return candidate
    return ""


def extract_target_id(
    event: AstrMessageEvent,
    arg: str = "",
    allow_bare_id: bool = True,
    allow_text_number: bool = True,
) -> str:
    """统一提取目标用户ID，兼容 OneBot(CQ码/At/纯数字) 与 QQ 官方机器人(At/openid)。

    提取优先级：
      1. 消息链中的 At 组件（OneBot 可靠；QQ 官方下只会有一个代表"机器人自己"的
         占位 At，已按 self_id / 占位符剔除，不会误取机器人自身）
      2. 指令参数与消息纯文本中的 @ 标记（QQ 官方：<@!member_openid> / <qqbot-at-user .../>）
      3. 原始 payload 的 mentions 列表（QQ 官方兜底）
      4. 指令参数本身作为裸 ID（兼容 openid 等非数字 ID）
      5. 消息纯文本中的独立数字 token（OneBot 历史兜底）

    说明：QQ 官方机器人的 user_id / group_openid 为非数字字符串，
    因此不能再使用 isdigit() 来判断一个 ID 是否有效。

    Args:
        event: 消息事件
        arg: 指令参数
        allow_bare_id: 是否允许把参数本身当作裸 ID（第 4 级）。
            关闭后仅返回"显式 @"的目标，用于与数字型参数（如灵眼编号）共存。
        allow_text_number: 是否允许从纯文本中捞独立数字 token（第 5 级）。
    """
    self_ids = _iter_self_ids(event)

    # 1) 消息链 At 组件（两个平台均可靠，但需剔除"机器人自己"那个）
    if hasattr(event, "message_obj") and event.message_obj:
        chain = getattr(event.message_obj, "message", []) or []
        for comp in chain:
            if not isinstance(comp, At):
                continue
            for attr in ("qq", "target", "uin", "user_id"):
                candidate = _clean_candidate_id(getattr(comp, attr, None))
                if not candidate or candidate in self_ids:
                    continue
                return candidate

    # 2) 指令参数 / 消息纯文本里的 @ 标记（先扫参数：参数就是用户 @ 的位置）
    for text in (arg or "", _get_message_text(event)):
        for candidate in _iter_text_at_ids(text):
            return candidate

    # 3) 原始 payload 的 mentions 兜底
    candidate = _extract_mention_from_raw(event)
    if candidate:
        return candidate

    # 4) 指令参数作为裸 ID（兼容 openid 等非数字 ID；拒绝仍未解析的标记文本）
    if arg and allow_bare_id:
        cleaned = str(arg).strip().lstrip("@").strip()
        if cleaned and not any(ch in cleaned for ch in "<>[]()"):
            candidate = _clean_candidate_id(cleaned)
            if candidate:
                return candidate

    # 5) 纯文本中的独立数字 token（OneBot 历史兜底）
    if allow_text_number:
        text = _get_message_text(event)
        if text:
            num_match = re.search(r"(?<![0-9A-Za-z])(\d{5,})(?![0-9A-Za-z])", text)
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
                        # 兜底路径同样走统一的债务处理（v3.2.7：BANK_KILL 债务免除，不追溯）
                        from ..core.penalty_manager import apply_death_debt
                        await apply_death_debt(
                            db, player.user_id, PenaltyReason.BANK_KILL
                        )
                        await db.delete_player_cascade(player.user_id)
                else:
                    # 降级：未注入 penalty_mgr 时保持原有行为
                    from ..core.penalty_manager import apply_death_debt, PenaltyReason
                    await apply_death_debt(
                        db, player.user_id, PenaltyReason.BANK_KILL
                    )
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
