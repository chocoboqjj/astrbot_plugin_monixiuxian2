"""概率透明化工具

设计目标：让玩家在参与随机玩法时，能清楚知道
1. 这次判定的**概率**是多少
2. 判定是**成功还是失败**
3. 是否属于**幸运/不幸**（用于正反馈强化）

统一措辞，避免各玩法各说一套。
"""

from typing import Optional, Tuple

__all__ = [
    "describe_roll",
    "format_chance",
    "lucky_tag",
    "build_roll_line",
]


def format_chance(percent: float) -> str:
    """把概率格式化为易读文本

    Args:
        percent: 概率百分数（0-100）

    Returns:
        如 "70%" / "12.5%" / "必出"
    """
    if percent >= 100:
        return "必出"
    if percent <= 0:
        return "0%"
    if float(percent).is_integer():
        return f"{int(percent)}%"
    return f"{percent:.1f}%"


def lucky_tag(percent: float, success: bool) -> str:
    """根据概率与结果给出正/负反馈标签

    低概率成功 → 幸运；高概率失败 → 不幸；其余为中性。
    """
    if success:
        if percent <= 30:
            return "🍀 大吉！"
        if percent <= 60:
            return "✨ 侥幸成功"
        return ""
    if percent >= 70:
        return "💫 命数如此"
    return ""


def describe_roll(
    label: str,
    percent: float,
    success: bool,
    *,
    result_text: str = "",
) -> str:
    """生成一行概率判定说明

    Args:
        label: 判定名称，如 "物品掉落"
        percent: 概率百分数
        success: 是否判定成功
        result_text: 成功时的附加结果描述（可选）

    Returns:
        形如 "🎲 物品掉落判定：命中（概率 30%）· 获得 灵草 x1"
    """
    status = "命中" if success else "未命中"
    line = f"🎲 {label}判定：{status}（概率 {format_chance(percent)}）"
    tag = lucky_tag(percent, success)
    if tag:
        line = f"{tag} {line}"
    if success and result_text:
        line = f"{line} · {result_text}"
    return line


def build_roll_line(
    label: str,
    percent: float,
    success: bool,
    *,
    result_text: str = "",
    show_miss: bool = True,
) -> str:
    """同 describe_roll，但可选择在失败时隐藏整行

    Args:
        show_miss: False 时，未命中则返回空字符串
    """
    if not success and not show_miss:
        return ""
    return describe_roll(label, percent, success, result_text=result_text)
