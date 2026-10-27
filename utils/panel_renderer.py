# utils/panel_renderer.py
"""v3.3.6 面板美化渲染器：把插件的长文本面板渲染成仙侠风格 HTML。

设计要点：
- **宽容解析**：逐行识别（标题/分隔线/段落头/kv/箭头指令/说明/普通行），
  任何行都有归宿，**绝不丢失内容**；解析不出的行按普通文本渲染。
- **零第三方依赖**（纯标准库），供 main.py 的转图钩子在 html_render 前调用。
- 输出为自包含 HTML（内联 CSS，宣纸+金主题），交由宿主 html_render 截图。
- ⚠️ CSS 全部使用 class 选择器、避免连续双大括号——html_render 用 Jinja2
  渲染模板字符串，`{{`/`{%`/`{#` 会被当作模板语法。
"""
import html as _html
import re
from typing import Optional

# ---------- 行类型正则 ----------
_SEP_RE = re.compile(r"^\s*[━═─]{4,}\s*$")                 # ━━━ 分隔线
_DASH_SEP_RE = re.compile(r"^\s*-{4,}\s*$")                # ---- 分隔线
_TITLE_EQ_RE = re.compile(r"^\s*=+\s*(.+?)\s*=+\s*$")      # === 标题 ===
_HEAD_RE = re.compile(r"^\s*([^\w\s【】─→]*?)\s*【(.+?)】\s*$")  # emoji【段落】
_SUB_RE = re.compile(r"^\s*└─\s*(.*)$")                    #     └─ 说明
_KV_RE = re.compile(r"^\s{0,8}([^：:\n【】─]{1,16})\s*[：:]\s*(.+?)\s*$")  # 键：值
_ARROW_RE = re.compile(r"^(.*?)\s+→\s*(.*)$")              # 指令 → 说明

# ---------- 主题 CSS ----------
# 注意：Jinja2 兼容——只用 class 选择器；不含 {{、{%、{#
_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{width:470px;background:#f5efe0;font-family:"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;color:#3b3226;padding:18px 14px}
.frame{border:1px solid #d8c9a3;border-radius:12px;padding:16px 18px 18px;background:linear-gradient(180deg,#f7f1e3,#f0e7d2)}
.p-title{text-align:center;font-size:18px;font-weight:700;letter-spacing:2px;color:#3b3226;padding:2px 0 6px}
.p-title .emo{margin-right:6px}
.p-div{width:56%;margin:8px auto 4px;border-top:2px solid #c9a85c;opacity:.6}
.sec{font-weight:700;color:#9a7b2d;font-size:14px;letter-spacing:1px;margin:12px 0 4px}
.sec .emo{margin-right:5px}
.row{display:flex;justify-content:space-between;align-items:baseline;font-size:13.5px;padding:2.5px 4px;gap:12px}
.row .k{color:#6b5f4d;flex-shrink:0}
.row .v{font-weight:600;text-align:right;word-break:break-all}
.row .v.up{color:#8c3b2e}
.row .v.dim{color:#8a7d63;font-weight:400}
.li{font-size:13.5px;padding:2.5px 4px;color:#4a4234;line-height:1.55}
.li .cmd{color:#9a7b2d;font-weight:700}
.cmdrow{display:flex;gap:10px;font-size:13.5px;padding:2.5px 4px;align-items:baseline}
.cmdrow .cmd{color:#9a7b2d;font-weight:700;flex-shrink:0}
.cmdrow .desc{color:#6b5f4d}
.num{color:#8c3b2e;font-weight:700}
.sub{font-size:12px;color:#8a7d63;padding:1px 4px 1px 26px;line-height:1.5}
.gap{height:7px}
.warn{color:#8c3b2e}
"""


def _esc(s: str) -> str:
    return _html.escape(s, quote=False)


def _value_class(v: str) -> str:
    """值高亮判定：+数字 / 百分比 → 强调；无/未装备 → 置灰。"""
    if v in ("无", "未装备", "无宗门", "散修"):
        return "v dim"
    if re.match(r"^[+＋]\d", v) or v.endswith("%") or v.endswith("％"):
        return "v up"
    return "v"


_NUM_RE = re.compile(r"([+＋]\d[\d,.]*%?)")


def _emphasize(escaped: str) -> str:
    """对已转义的普通行文本做「+数字/百分比」强调（如装备加成行无冒号格式）。"""
    return _NUM_RE.sub(r'<b class="num">\1</b>', escaped)


def _render_line(ln: str) -> Optional[str]:
    """渲染单行（不包含标题），返回 HTML 片段；空行由调用方处理。"""
    s = ln.strip()
    if not s:
        return '<div class="gap"></div>'
    if _SEP_RE.match(s) or _DASH_SEP_RE.match(s):
        return '<div class="p-div"></div>'

    # 段落头：emoji【xxx】或【xxx】
    m = _HEAD_RE.match(s)
    if m:
        emo = _esc(m.group(1)) if m.group(1) else ""
        return f'<div class="sec"><span class="emo">{emo}</span>{_esc(m.group(2))}</div>'

    # 说明行：└─ xxx
    m = _SUB_RE.match(s)
    if m:
        txt = _esc(m.group(1))
        cls = "sub warn" if ("⚠" in txt or "逾期" in txt or "死亡" in txt or "清除" in txt) else "sub"
        return f'<div class="{cls}">└─ {txt}</div>'

    # 指令 → 说明（帮助面板常见格式）
    m = _ARROW_RE.match(s)
    if m and len(m.group(1)) <= 30:
        return f'<div class="cmdrow"><span class="cmd">{_esc(m.group(1))}</span><span class="desc">{_esc(m.group(2))}</span></div>'

    # 键：值
    m = _KV_RE.match(s)
    if m:
        k, v = m.group(1).strip(), m.group(2)
        return f'<div class="row"><span class="k">{_esc(k)}</span><span class="{_value_class(v)}">{_esc(v)}</span></div>'

    # 普通行
    cls = "li warn" if ("⚠" in s or "逾期" in s or "致死" in s) else "li"
    return f'<div class="{cls}">{_emphasize(_esc(s))}</div>'


def render_panel_html(text: str) -> Optional[str]:
    """把面板文本渲染为仙侠风格完整 HTML；空文本返回 None。"""
    if not text or not text.strip():
        return None

    lines = text.splitlines()
    title_html = ""
    # 首个非空行作为标题
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            continue
        m = _TITLE_EQ_RE.match(s)
        raw = m.group(1) if m else s
        raw = raw.strip()
        # 标题拆 emoji 前缀
        tm = re.match(r"^([^\w\s【】]{1,3})\s*(.*)$", raw)
        emo, name = (tm.group(1), tm.group(2)) if tm and tm.group(2) else ("", raw)
        emo_html = f'<span class="emo">{_esc(emo)}</span>' if emo else ""
        title_html = f'<div class="p-title">{emo_html}{_esc(name)}</div><div class="p-div"></div>'
        lines = lines[i + 1:]
        break

    body_parts = [_render_line(ln) for ln in lines]
    body = "".join(p for p in body_parts if p)

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<style>{_CSS}</style></head>"
        f'<body><div class="frame">{title_html}{body}</div></body></html>'
    )
