# utils/panel_renderer.py
"""v3.3.7 面板美化渲染器（按面板类型的全新设计版式 + 双主题）。

三种专属布局 + 通用布局：
- **player**（我的信息）：游戏角色卡——道号主视觉 → 境界/灵根/职业徽章 →
  战力巨字 → 修为进度条 → 四维属性卡 → 灵石/精神力 → 装备 → 宗门脚注。
- **equip**（我的装备）：装备槽大条目 + 属性加成数值卡。
- **help**（修仙帮助）：色块段落标题 + 指令斑马纹列表。
- **generic**：其余长文本的玄金条目式排版。

**双主题**（v3.3.7 用户选定第一版「宣纸+金」为默认）：
- `paper`（默认）：宣纸底 + 墨字 + 金标题——第一版设计，用户认可。
- `gold`：玄金暗色 + 霓虹渐变——备选风格。
两套主题共用同一套 DOM 结构与类名，仅 CSS 不同 ⇒ 切换零成本。

依旧零 handler 侵入（从现有文本提取字段后按新布局重排）、宽容解析绝不丢字段、
纯标准库。⚠️ Jinja2 兼容：CSS 全 class 选择器、模板禁 `{{`/`{%`/`{#`。
"""
import html as _html
import re
from typing import Optional

# ---------- 行/结构正则 ----------
_SEP_RE = re.compile(r"^\s*[━═─=]{4,}\s*$")
_DASH_SEC_RE = re.compile(r"^\s*-{2,}\s*(.+?)\s*-{2,}\s*$")       # --- 段名 ---
_TITLE_EQ_RE = re.compile(r"^\s*=+\s*(.+?)\s*=+\s*$")
_SLOT_RE = re.compile(r"^\s*【(.+?)】\s*(.*)$")                    # 【槽】内容
_HEAD_RE = re.compile(r"^\s*([^\w\s【】─→]*?)\s*【(.+?)】\s*$")   # 【段落】（后随空）
_SUB_RE = re.compile(r"^\s*└─\s*(.*)$")
_KV_RE = re.compile(r"^\s{0,8}([^：:\n【】─]{1,16})\s*[：:]\s*(.+?)\s*$")
_ARROW_RE = re.compile(r"^(.*?)\s+→\s*(.*)$")
_PCT_STAT_RE = re.compile(r"^(.+?)\s+([+＋][\d,.]+%?)$")          # ⚔️ 物伤 +364
_NUM_RE = re.compile(r"([+＋]\d[\d,.]*%?)")
_NUMV_RE = re.compile(r"^([\d,]+)\s*/\s*([\d,]+)$")

# ---------- 商店（阁楼货架）专用解析 ----------
# 商品头：1. [凡品] 培元丹 (破境丹) [20%折]
_SHOP_ITEM_RE = re.compile(r"^(\d{1,3})\.\s*\[([^\]]{1,10})\]\s*(.+?)\s*\(([^)]{1,14})\)\s*(?:\[([^\]]{1,18})\])?\s*$")
# 价格行：价格: 100 灵石 库存:3 / 价格: 100 灵石 库存紧张:3
_SHOP_PRICE_RE = re.compile(r"^价格\s*[:：]\s*([\d,]+)\s*灵石\s*(库存紧张|库存)\s*[:：]\s*(\d+)\s*$")
# 效果行：效果: 修为+500
_SHOP_EFFECT_RE = re.compile(r"^效果\s*[:：]\s*(.*)$")
# 物品详情首行：名称: 筑基丹
_ITEM_NAME_RE = re.compile(r"^名称\s*[:：]\s*(.+)$")

# ---------- 丹药配方专用解析 ----------
# 配方头：【培元丹】(ID:1)
_RECIPE_HEAD_RE = re.compile(r"^【(.+?)】\s*\(\s*ID\s*[:：]\s*(\d+)\s*\)\s*$")
# 需求境界：Lv.0
_RECIPE_LV_RE = re.compile(r"^需求境界\s*[:：]\s*(.+)$")
# 突破目标：筑基期（✅ 可炼）/（🔒 未达境界）   仅破境丹有
_RECIPE_TARGET_RE = re.compile(r"^突破目标\s*[:：]\s*(.+)$")
# 材料：灵草×3, 灵石×100
_RECIPE_MAT_RE = re.compile(r"^材料\s*[:：]\s*(.+)$")
# 成功率：80%
_RECIPE_RATE_RE = re.compile(r"^成功率\s*[:：]\s*(.+)$")
# 效果：修为+500
_RECIPE_DESC_RE = re.compile(r"^效果\s*[:：]\s*(.+)$")

# ---------- 储物戒专用解析 ----------
# 戒名行：【乾坤戒】（地品）   —— 升级列表用半角括号，主面板用全角，两种都要认
_STORAGE_RING_RE = re.compile(r"^【(.+?)】\s*[（(](.+?)[）)]\s*$")
# 容量：12/60格
_STORAGE_CAP_RE = re.compile(r"^容量\s*[:：]\s*(\d+)\s*/\s*(\d+)\s*格?\s*$")
# 分类头：【材料】（独占一行）
_STORAGE_CAT_RE = re.compile(r"^【(.+?)】\s*$")
# 物品行：· 灵草×5 / · 精铁
_STORAGE_ITEM_RE = re.compile(r"^·\s*(.+?)\s*(?:[x×*]\s*(\d+))?\s*$")
# 空分类：【存储物品】空
_STORAGE_EMPTY_RE = re.compile(r"^【(.+?)】\s*(?:空|无)\s*$")

# 品级阶梯（12 级，跨表统一）→ 6 档配色（rk0~rk5）
RANK_ORDER = ["凡品", "珍品", "灵品", "地品", "天品", "皇品",
              "圣品", "帝品", "道品", "仙品", "神品", "混元先天"]
RANK_TIER = {"凡品": 0, "珍品": 1, "灵品": 1, "地品": 1, "天品": 2, "皇品": 2,
             "圣品": 3, "帝品": 3, "道品": 4, "仙品": 4, "神品": 5, "混元先天": 5}

# 阁楼副标题
PAVILION_SUB = {"丹阁": "ELIXIR PAVILION", "器阁": "ARMORY PAVILION",
                 "百宝阁": "TREASURE PAVILION"}

# ---------- 语义表 ----------
SEC_ICONS = {"基本信息": "👤", "修炼属性": "☯", "装备信息": "🗡️", "宗门信息": "🏯",
             "贷款信息": "💰", "装备属性加成": "✦", "入门 & 基础": "📖",
             "装备丹药": "🎒", "商店系统": "🏪", "储物戒系统": "📦",
             "灵石银行": "🏦", "悬赏任务": "📜"}
STAT_ICONS = {"物伤": "⚔️", "法伤": "✨", "物防": "🛡", "法防": "🔮",
              "精神力": "🧠", "灵石": "💰", "气血": "❤", "灵气": "💠"}

# ---------- 主题变量（paper=宣纸金（默认，用户选定）/ gold=玄金暗色） ----------
_CSS_THEME_PAPER = """
:root{
--w:490px;
--bg:#efe6d0;
--panel-bg:linear-gradient(170deg,#fbf6e9,#f3ead4 62%,#ece0c4);
--panel-border:#cdb887;
--panel-inner:#e6d9b6;
--card-bg:linear-gradient(180deg,#fdfaf1,#f7f0dd);
--card-border:#e2d6b1;
--ink:#3b3226;
--ink-soft:#6b5f4d;
--ink-dim:#8a7d63;
--ink-faint:#a99c7e;
--gold:#9a7b2d;
--gold-deep:#7a601f;
--gold-soft:#c9a85c;
--accent:#a03a2c;
--accent-soft:#c25a3f;
--title-grad:linear-gradient(180deg,#7d6120,#c9a85c 58%,#8a6a24);
--corner:#b9974f;
--sec-line:#d6c79c;
--badge-bg:linear-gradient(180deg,#fdfaf1,#f2e9d1);
--bar-bg:#e6dcc0;
--bar-border:#d2c29a;
--bar-fill:linear-gradient(90deg,#c9a85c,#e6cd8d);
--bar-fill-hp:linear-gradient(90deg,#a8503a,#dd8f68);
--chip-bg:#fbf6e9;
--chip-border:#ddcfaa;
--chip-text:#4a4234;
--help-sec-bg:linear-gradient(90deg,#e3ca86,#c9a85c);
--help-sec-ink:#3b3226;
--zebra:rgba(201,168,92,.12);
--shadow:0 1px 2px rgba(120,95,50,.10);
--glow:none;
/* 品级 6 档（rk0 凡 → rk5 混元先天）*/
--rk0:#8a7d63;--rk1:#5e7d4a;--rk2:#3f6f8f;--rk3:#6b5a9e;--rk4:#a8622a;--rk5:#a03a2c;
--rk-bg0:rgba(138,125,99,.10);--rk-bg1:rgba(94,125,74,.12);
--rk-bg2:rgba(63,111,143,.12);--rk-bg3:rgba(107,90,158,.12);
--rk-bg4:rgba(168,98,42,.13);--rk-bg5:rgba(160,58,44,.13);
}
"""

_CSS_THEME_GOLD = """
:root{
--w:490px;
--bg:#0d0b07;
--panel-bg:radial-gradient(130% 100% at 50% 0%,#262013 0%,#181510 52%,#0f0d09 100%);
--panel-border:#6e5a2e;
--panel-inner:#3a3018;
--card-bg:linear-gradient(180deg,#1e1a10,#161209);
--card-border:#3f3419;
--ink:#e8dcbc;
--ink-soft:#cfc19b;
--ink-dim:#a08d63;
--ink-faint:#6f6448;
--gold:#d9b866;
--gold-deep:#a8863d;
--gold-soft:#c9a85c;
--accent:#e8926b;
--accent-soft:#e08a5a;
--title-grad:linear-gradient(180deg,#f6e6b5,#d9b866 62%,#a8863d);
--corner:#c9a85c;
--sec-line:#463a1c;
--badge-bg:linear-gradient(180deg,#241e11,#1a160d);
--bar-bg:#1c180d;
--bar-border:#463a1c;
--bar-fill:linear-gradient(90deg,#8a6d2b,#e8cf8e);
--bar-fill-hp:linear-gradient(90deg,#8a3423,#e08a5a);
--chip-bg:#1e1a10;
--chip-border:#463a1c;
--chip-text:#cfc19b;
--help-sec-bg:linear-gradient(90deg,#d9b866,#a8863d);
--help-sec-ink:#161209;
--zebra:rgba(201,168,92,.05);
--shadow:0 1px 2px rgba(0,0,0,.4);
--glow:0 0 30px rgba(224,181,88,.35);
/* 品级 6 档（rk0 凡 → rk5 混元先天）*/
--rk0:#a89a78;--rk1:#8fbe72;--rk2:#6fb0d8;--rk3:#a892e0;
--rk4:#e8a35c;--rk5:#ef8a68;
--rk-bg0:rgba(168,154,120,.14);--rk-bg1:rgba(143,190,114,.15);
--rk-bg2:rgba(111,176,216,.15);--rk-bg3:rgba(168,146,224,.16);
--rk-bg4:rgba(232,163,92,.16);--rk-bg5:rgba(239,138,104,.16);
}
"""

# ---------- 共享 CSS（结构 + 配色全部走 CSS 变量 ⇒ 双主题零成本切换） ----------
_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{width:var(--w);background:var(--bg);
     font-family:"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
     color:var(--ink);padding:12px}
.frame{position:relative;border:1px solid var(--panel-border);border-radius:14px;padding:20px 20px 22px;
       background:var(--panel-bg);
       box-shadow:inset 0 0 0 1px var(--panel-inner),0 6px 22px rgba(0,0,0,.18)}
.corner{position:absolute;width:16px;height:16px;border-color:var(--corner);border-style:solid}
.c-tl{top:7px;left:7px;border-width:2px 0 0 2px;border-radius:10px 0 0 0}
.c-tr{top:7px;right:7px;border-width:2px 2px 0 0;border-radius:0 10px 0 0}
.c-bl{bottom:7px;left:7px;border-width:0 0 2px 2px;border-radius:0 0 0 10px}
.c-br{bottom:7px;right:7px;border-width:0 2px 2px 0;border-radius:0 0 10px 0}
.gold-t{background:var(--title-grad);
        -webkit-background-clip:text;background-clip:text;color:transparent}
.num{color:var(--accent);font-weight:700}
.gap{height:7px}

/* ---- 装饰性分隔线（替代原文粗黑实线）---- */
.p-div{display:flex;align-items:center;gap:6px;margin:11px 2px;opacity:.85}
.p-div i{height:1px;flex:1;background:linear-gradient(90deg,transparent,var(--sec-line))}
.p-div i:last-child{background:linear-gradient(90deg,var(--sec-line),transparent)}
.p-div s{width:5px;height:5px;background:var(--gold-soft);transform:rotate(45deg);flex-shrink:0;
         display:block;border-radius:1px}

/* ---- hero / 徽章 ---- */
.hero{text-align:center;padding:2px 0 6px}
.h-deco{font-size:9px;color:var(--gold-soft);letter-spacing:8px;padding-bottom:4px}
.dname{font-size:27px;font-weight:900;letter-spacing:6px}
.p-sub{text-align:center;font-size:9.5px;letter-spacing:6px;color:var(--ink-faint);padding-top:4px}
.badges{display:flex;justify-content:center;gap:8px;padding-top:9px;flex-wrap:wrap}
.bd{font-size:11.5px;color:var(--ink);border:1px solid var(--gold-soft);border-radius:999px;
    padding:3px 13px;background:var(--badge-bg);letter-spacing:1px}

/* ---- 战力 ---- */
.power{text-align:center;margin:14px 6px 6px;padding:12px 0 14px;
       border:1px solid var(--card-border);border-radius:12px;
       background:var(--card-bg);
       box-shadow:inset 0 0 24px rgba(201,168,92,.07)}
.pw-label{font-size:11px;color:var(--ink-dim);letter-spacing:6px;padding-bottom:4px}
.pw-num{font-size:42px;font-weight:900;line-height:1.15;letter-spacing:2px;
        text-shadow:var(--glow)}

/* ---- 进度条 ---- */
.prog{margin:9px 2px}
.prog .ph{display:flex;justify-content:space-between;font-size:12px;padding:0 2px 4px}
.prog .pk{color:var(--ink-dim);letter-spacing:2px}
.prog .pn{color:var(--ink);font-weight:700}
.prog .pn i{color:var(--ink-faint);font-style:normal}
.prog .pb{height:10px;border-radius:6px;background:var(--bar-bg);border:1px solid var(--bar-border);overflow:hidden}
.prog .pb i{display:block;height:100%;border-radius:5px;background:var(--bar-fill)}
.prog .pb i.hp{background:var(--bar-fill-hp)}

/* ---- 属性卡 ---- */
.stat-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:10px 0 4px}
.stat{display:flex;align-items:center;gap:8px;border:1px solid var(--card-border);border-radius:11px;
      padding:8px 6px 8px 11px;background:var(--card-bg);box-shadow:var(--shadow)}
.stat .si{font-size:16px}
.stat .sk{display:block;font-size:9.5px;color:var(--ink-dim);letter-spacing:1px}
.stat .sv{display:block;font-size:15.5px;font-weight:800;color:var(--ink);line-height:1.25}

/* ---- 装备行 ---- */
.g-row{display:flex;align-items:center;gap:10px;border:1px solid var(--card-border);border-radius:11px;
       padding:9px 14px;margin:6px 0;background:var(--card-bg);box-shadow:var(--shadow)}
.g-icon{font-size:17px}
.g-slot{font-size:10px;color:var(--ink-dim);letter-spacing:2px;border:1px solid var(--chip-border);
        border-radius:4px;padding:2px 6px;flex-shrink:0}
.g-name{font-size:14.5px;font-weight:700;color:var(--ink)}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{font-size:11.5px;color:var(--chip-text);border:1px solid var(--chip-border);border-radius:999px;padding:2px 10px}

/* ---- 杂项/脚注 ---- */
.misc{margin-top:10px}
.row{display:flex;justify-content:space-between;align-items:baseline;font-size:12.5px;
     padding:3px 6px;gap:12px}
.row .k{color:var(--ink-dim);flex-shrink:0}
.row .v{font-weight:600;text-align:right;word-break:break-all;color:var(--ink)}
.row .v.up{color:var(--accent)}
.row .v.dim{color:var(--ink-faint);font-weight:400}
.li{font-size:12.5px;padding:3px 6px;color:var(--ink-soft);line-height:1.6}
.foot{display:flex;justify-content:center;gap:14px;margin-top:14px;padding-top:11px;
      border-top:1px dashed var(--sec-line);font-size:11.5px;color:var(--ink-dim);letter-spacing:1px}

/* ---- 段落头（通用/装备） ---- */
.sec{display:flex;align-items:center;gap:9px;font-weight:700;color:var(--gold);font-size:13px;
     letter-spacing:2px;margin:14px 2px 7px}
.sec .emo{font-size:13.5px}
.sec i{flex:1;border-top:1px solid var(--sec-line)}

/* ---- 帮助 ---- */
.h-sec{display:inline-flex;align-items:center;gap:7px;font-weight:800;font-size:12.5px;
       letter-spacing:2px;color:var(--help-sec-ink);border-radius:6px;padding:4px 14px;margin:13px 0 6px;
       background:var(--help-sec-bg)}
.h-sec .emo{font-size:13px}
.h-sec + .cmdrow, .h-sec + .li, .h-sec + .sub{margin-top:2px}
.cmdrow{display:flex;gap:12px;font-size:12.5px;padding:4px 10px;align-items:baseline;
        border-radius:6px}
.cmdrow:nth-child(odd){background:var(--zebra)}
.cmdrow .cmd{color:var(--gold);font-weight:700;flex-shrink:0}
.cmdrow .desc{color:var(--ink-soft)}
.sub{font-size:11.5px;color:var(--ink-dim);padding:1px 10px 1px 26px;line-height:1.5}
.sub.warn{color:var(--accent-soft)}
.warn{color:var(--accent)}

/* ---- 商店：商品卡网格 ---- */
.shop-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:10px 0 4px}
.s-item{border:1px solid var(--card-border);border-radius:11px;padding:9px 11px 10px;
        background:var(--card-bg);box-shadow:var(--shadow);position:relative;overflow:hidden}
.s-top{display:flex;align-items:baseline;gap:6px;margin-bottom:5px}
.s-no{font-size:10px;color:var(--ink-faint);font-weight:700;flex-shrink:0;
      font-family:"DIN Alternate","Menlo",monospace}
.s-name{font-size:14.5px;font-weight:800;color:var(--ink);line-height:1.25;
        flex:1;word-break:break-all}
.s-price{font-size:13px;font-weight:800;color:var(--gold-deep);white-space:nowrap}
.s-price i{font-style:normal;font-size:10px;color:var(--ink-dim);font-weight:600;margin-left:2px}
.s-meta{display:flex;align-items:center;gap:5px;flex-wrap:wrap;margin-top:5px}
.s-rank{font-size:9.5px;font-weight:700;padding:1.5px 6px;border-radius:4px;letter-spacing:1px;
        border:1px solid currentColor;line-height:1.5}
.s-type{font-size:9.5px;color:var(--ink-dim);border:1px solid var(--chip-border);
        border-radius:4px;padding:1.5px 6px;line-height:1.5}
.s-off{font-size:9.5px;font-weight:700;padding:1.5px 6px;border-radius:4px;line-height:1.5;
       color:var(--accent);border:1px solid var(--accent);background:rgba(160,58,44,.07)}
.s-off.up{color:var(--ink-dim);border-color:var(--chip-border);background:none}
.s-stock{font-size:10px;color:var(--ink-dim);margin-left:auto;white-space:nowrap}
.s-stock.low{color:var(--accent);font-weight:700}
.s-eff{font-size:11px;color:var(--ink-soft);line-height:1.5;margin-top:6px;
       padding-top:6px;border-top:1px dashed var(--sec-line);word-break:break-all}
.s-eff b{color:var(--accent);font-weight:700}
/* 品级配色 */
.rk0{color:var(--rk0);background:var(--rk-bg0)}
.rk1{color:var(--rk1);background:var(--rk-bg1)}
.rk2{color:var(--rk2);background:var(--rk-bg2)}
.rk3{color:var(--rk3);background:var(--rk-bg3)}
.rk4{color:var(--rk4);background:var(--rk-bg4)}
.rk5{color:var(--rk5);background:var(--rk-bg5)}
/* 阁楼头部 */
.shop-head{display:flex;align-items:center;gap:10px;margin-bottom:4px}
.shop-head .dname{font-size:24px}
.shop-note{display:flex;justify-content:space-between;align-items:baseline;gap:10px;
           margin-top:10px;padding:8px 11px;border:1px dashed var(--sec-line);border-radius:9px;
           font-size:11.5px;color:var(--ink-dim)}
.shop-note b{color:var(--gold);font-weight:700}

/* 丹药配方（单列卡片：配方字段多，双列会挤） */
.r-list{display:flex;flex-direction:column;gap:8px;margin:10px 0 4px}
.r-item{border:1px solid var(--card-border);border-radius:11px;padding:9px 11px 10px;
        background:var(--card-bg);box-shadow:var(--shadow)}
.r-top{display:flex;align-items:baseline;gap:7px}
.r-id{font-size:9.5px;font-weight:800;color:var(--ink-faint);flex-shrink:0;
      border:1px solid var(--chip-border);border-radius:4px;padding:1px 5px}
.r-name{font-size:15px;font-weight:800;color:var(--ink);line-height:1.25}
.r-rate{margin-left:auto;font-size:13px;font-weight:800;color:var(--gold-deep);white-space:nowrap}
.r-rate i{font-style:normal;font-size:9.5px;color:var(--ink-dim);font-weight:600;margin-left:1px}
.r-meta{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:6px}
.r-lv{font-size:9.5px;color:var(--chip-text);background:var(--chip-bg);
      border:1px solid var(--chip-border);border-radius:4px;padding:1.5px 6px}
.r-tg{font-size:9.5px;font-weight:700;padding:1.5px 6px;border-radius:4px}
.r-tg.ok{color:var(--rk1);background:var(--rk-bg1)}
.r-tg.lock{color:var(--ink-faint);background:var(--chip-bg);border:1px solid var(--chip-border)}
.r-mat{font-size:11px;color:var(--ink-soft);line-height:1.6;margin-top:6px}
.r-mat b{color:var(--ink);font-weight:700}
.r-eff{font-size:11px;color:var(--ink-soft);line-height:1.5;margin-top:4px}
.r-eff b{color:var(--accent);font-weight:700}

/* 储物戒 */
.st-head{display:flex;align-items:center;gap:10px;margin-bottom:2px}
.st-head .dname{font-size:24px}
.st-rank{font-size:10px;font-weight:700;padding:2px 7px;border-radius:5px;flex-shrink:0;
         color:var(--gold-deep);background:var(--badge-bg);border:1px solid var(--chip-border)}
.st-desc{font-size:11px;color:var(--ink-dim);line-height:1.55;margin:2px 0 8px}
.st-sec{margin-top:10px}
.st-sec-h{display:flex;align-items:center;gap:8px;font-size:11.5px;font-weight:800;
          color:var(--gold-deep);letter-spacing:2px;margin-bottom:6px}
.st-sec-h:after{content:"";flex:1;height:1px;background:var(--sec-line)}
.st-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.st-chip{display:flex;align-items:baseline;gap:6px;font-size:12px;color:var(--ink);
         background:var(--chip-bg);border:1px solid var(--chip-border);
         border-radius:8px;padding:6px 9px;line-height:1.35}
.st-chip .nm{flex:1;min-width:0;overflow-wrap:anywhere}
.st-chip .ct{font-size:11px;font-weight:800;color:var(--gold-deep);white-space:nowrap}
.st-empty{font-size:11.5px;color:var(--ink-faint);padding:8px 2px}
.st-note{margin-top:10px;padding:8px 11px;border:1px dashed var(--sec-line);border-radius:9px;
         font-size:11.5px;color:var(--ink-dim);line-height:1.75}
.st-note b{color:var(--gold);font-weight:700}
"""

THEMES = {"paper": _CSS_THEME_PAPER, "gold": _CSS_THEME_GOLD}
DEFAULT_THEME = "paper"

# 面板渲染宽度（CSS 中 body 的 width）。**必须与 _CSS 里的 --w 保持一致**——
# 宿主 t2i 服务默认视口 800px，若不显式指定 viewport_width，body 右侧会留下一条空白色块。
PANEL_WIDTH = 490



def _esc(s: str) -> str:
    return _html.escape(s, quote=False)


def _emph(escaped: str) -> str:
    return _NUM_RE.sub(r'<b class="num">\1</b>', escaped)


def _is_sep(raw: str) -> bool:
    """判断是否为纯分隔线行（━━━ / ==== / ---- / ────）。"""
    return bool(_SEP_RE.match(raw)) or bool(re.match(r"^[━═─=-]{4,}$", raw))


def _div_html() -> str:
    """装饰性分隔线（菱形节点 + 渐隐横线），替代原文里的粗黑实线。"""
    return '<div class="p-div"><i></i><s></s><i></i></div>'


def _frame(title_html: str, body: str, theme: str = DEFAULT_THEME) -> str:
    theme_css = THEMES.get(theme, THEMES[DEFAULT_THEME])
    # ⚠️ meta viewport 是「消除右侧空白色块」的第二道保险：
    # 宿主 t2i 服务的视口优先级为 ①options.viewport_width ②HTML meta viewport ③默认 800px。
    # 显式传 options 时用①即可；此处再写 meta，兼容不认①的老服务端。
    return ('<!DOCTYPE html><html><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width={PANEL_WIDTH}">'
            f"<style>{theme_css}{_CSS}</style></head>"
            '<body><div class="frame">'
            '<span class="corner c-tl"></span><span class="corner c-tr"></span>'
            '<span class="corner c-bl"></span><span class="corner c-br"></span>'
            f"{title_html}{body}</div></body></html>")


def _progress(k: str, cur: str, total: str, hp: bool = False) -> str:
    try:
        ratio = float(cur.replace(",", "")) / float(total.replace(",", "")) * 100
        ratio = max(0.0, min(100.0, ratio))
    except (ValueError, ZeroDivisionError):
        ratio = 0
    bar = "hp" if hp else ""
    return (f'<div class="prog"><div class="ph"><span class="pk">{_esc(k)}</span>'
            f'<span class="pn">{_esc(cur)} <i>/</i> {_esc(total)}</span></div>'
            f'<div class="pb"><i class="{bar}" style="width:{ratio:.1f}%"></i></div></div>')


def _stat(icon: str, k: str, v: str, small: str = "") -> str:
    return (f'<div class="stat"><span class="si">{icon}</span><div>'
            f'<span class="sk">{_esc(k)}{small}</span><span class="sv">{_esc(v)}</span></div></div>')


# ============================================================
# 文本 → 结构化数据
# ============================================================
def _parse_sections(text: str):
    """解析为 (title, [(sec_name, kvs, raw_lines)])。宽容：一切行都有归宿。"""
    lines = text.splitlines()
    title = ""
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            continue
        m = _TITLE_EQ_RE.match(s)
        title = (m.group(1) if m else s).strip()
        lines = lines[i + 1:]
        break

    sections: list = []
    cur = None

    def _new(name):
        nonlocal cur
        cur = {"name": name, "kvs": [], "raws": []}
        sections.append(cur)

    _new(None)
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        m = _SLOT_RE.match(s)
        if m and not m.group(2):
            _new(m.group(1).strip())   # 【段落】（后随空）→ 新段
            continue
        if _SLOT_RE.match(s):          # 【槽】内容（装备面板格式）→ kv
            mm = _SLOT_RE.match(s)
            cur["kvs"].append((mm.group(1).strip(), mm.group(2).strip()))
            continue
        m = _HEAD_RE.match(s)          # emoji【段落】（带 emoji 前缀的段头）
        if m:
            _new(m.group(2).strip())
            continue
        m = _DASH_SEC_RE.match(s)
        if m:
            _new(m.group(1).strip())
            continue
        m = _KV_RE.match(s)
        if m:
            cur["kvs"].append((m.group(1).strip(), m.group(2).strip()))
            continue
        cur["raws"].append(s)
    return title, sections


def _sec_get(sections, sec, key, default=None):
    for s in sections:
        if s["name"] == sec:
            for k, v in s["kvs"]:
                if k == key:
                    return v
    return default


def _is_player(title, sections) -> bool:
    names = {s["name"] for s in sections}
    return "基本信息" in names and ("修炼属性" in names or "战力" in str(sections))


def _is_equip(title, sections) -> bool:
    # 【武器】X 在文本中是 kv 而非段名，故以标题判定（"的装备"足够特异）
    return "的装备" in title


def _is_help(title, sections) -> bool:
    arrows = sum(len(s["raws"]) for s in sections) and sum(
        1 for s in sections for ln in s["raws"] if _ARROW_RE.match(ln))
    return ("指令" in title) or (arrows and arrows >= 3)


def _parse_shop_items(text: str):
    """解析阁楼货架文本 → (title, items, notes)。

    原文格式（每件商品 3 行）：
        1. [凡品] 培元丹 (破境丹) [20%折]
           价格: 100 灵石 库存:3
           效果: 修为+500

    通用解析会把它们拆散（商品名/价格/效果各归各的）⇒ 排版乱。
    这里按「商品头行」为锚点重新聚合，尾随的 价格/效果 行归入当前商品。
    """
    lines = [ln.strip() for ln in text.splitlines()]
    title = ""
    items = []
    notes = []
    cur = None
    for ln in lines:
        if not ln:
            continue
        m = _TITLE_EQ_RE.match(ln)
        if m and not title:
            title = m.group(1).strip()
            continue
        mi = _SHOP_ITEM_RE.match(ln)
        if mi:
            cur = {
                "no": mi.group(1),
                "rank": mi.group(2).strip(),
                "name": mi.group(3).strip(),
                "type": mi.group(4).strip(),
                "off": (mi.group(5) or "").strip(),
                "price": "",
                "stock": "",
                "tight": False,
                "effect": "",
            }
            items.append(cur)
            continue
        mp = _SHOP_PRICE_RE.match(ln)
        if mp and cur is not None:
            cur["price"] = mp.group(1)
            cur["tight"] = (mp.group(2) == "库存紧张")
            cur["stock"] = mp.group(3)
            continue
        me = _SHOP_EFFECT_RE.match(ln)
        if me and cur is not None:
            cur["effect"] = me.group(1).strip()
            continue
        # 非商品行（下次刷新 / 提示 / 其它说明）
        if cur is None:
            notes.append(ln)
        elif not cur["effect"] and cur["price"]:
            # 紧跟商品的额外说明行（如"效果"缺失时的补充）→ 并入效果
            cur["effect"] = ln
        else:
            notes.append(ln)
    return title, items, notes


def _is_shop(title: str, items) -> bool:
    """判定是否为阁楼货架面板。

    收紧条件（避免误伤其它「1. [xx] yy (zz)」格式的列表）：
    - 标题须是已知阁楼名，或含「阁」字；
    - 且至少有一件商品**带价格**（货架的标志性字段）。
    """
    if not items:
        return False
    if title not in PAVILION_SUB and "阁" not in title:
        return False
    return any(it.get("price") for it in items)


# ---------- 丹药配方 ----------
def _parse_recipes(text: str):
    """解析丹药配方文本 → (title, recipes, notes)。

    原文格式（配方头 + 若干缩进字段行，破境丹额外多一行「突破目标」）：
        🔥 丹药配方
        ━━━━━━━━━━━━━━━
        【培元丹】(ID:1)
          需求境界：Lv.0
          突破目标：筑基期（✅ 可炼）
          材料：灵草×3, 灵石×100
          成功率：80%
          效果：修为+500

    通用解析会把「材料/成功率/效果」拆成各自独立的 kv ⇒ 排版散成一长列。
    这里按「配方头行」为锚点重新聚合。
    """
    lines = [ln.strip() for ln in text.splitlines()]
    title = ""
    recipes = []
    notes = []
    cur = None
    for ln in lines:
        if not ln or _SEP_RE.match(ln):
            continue
        if not title:
            title = ln
            continue
        m = _RECIPE_HEAD_RE.match(ln)
        if m:
            cur = {"name": m.group(1).strip(), "id": m.group(2), "lv": "",
                   "target": "", "ok": False, "mats": "", "rate": "", "desc": ""}
            recipes.append(cur)
            continue
        if cur is None:
            notes.append(ln)
            continue
        hit = False
        for key, rex in (("lv", _RECIPE_LV_RE), ("mats", _RECIPE_MAT_RE),
                         ("rate", _RECIPE_RATE_RE), ("desc", _RECIPE_DESC_RE)):
            mm = rex.match(ln)
            if mm:
                cur[key] = mm.group(1).strip()
                hit = True
                break
        if hit:
            continue
        mm = _RECIPE_TARGET_RE.match(ln)
        if mm:
            raw = mm.group(1).strip()
            cur["ok"] = ("可炼" in raw) and ("未达" not in raw)
            cur["target"] = re.sub(r"[（(]\s*(?:✅?\s*可炼|🔒?\s*未达境界)\s*[）)]",
                                   "", raw).strip()
            continue
        notes.append(ln)
    return title, recipes, notes


def _is_recipe(title: str, recipes) -> bool:
    """判定是否为丹药配方面板。

    收紧条件（避免误伤其它「【x】(ID:n)」格式的列表）：
    - 标题含「配方」或「丹方」；
    - 且至少一个配方带「成功率」或「材料」（配方的标志性字段）。
    """
    if not recipes or not ("配方" in title or "丹方" in title):
        return False
    return any(r.get("rate") or r.get("mats") for r in recipes)


# ---------- 储物戒 ----------
def _parse_storage(text: str):
    """解析储物戒文本 → (title, info)。

    info = {ring, rank, desc, used, total, cats:[{name, items:[(名称, 数量)]}], notes}

    原文格式：
        === 张三 的储物戒 ===
        【乾坤戒】（地品）
        可纳万物的乾坤之戒
        容量：12/60格
        ━━━━━━━━━━━━━━━
        【材料】
          · 灵草×5
          · 精铁
        存入：... 取出：... 搜索：... 升级：...
    """
    lines = [ln.strip() for ln in text.splitlines()]
    title = ""
    info = {"ring": "", "rank": "", "desc": "", "used": "", "total": "",
            "cats": [], "notes": []}
    cur_cat = None
    for ln in lines:
        if not ln:
            continue
        m = _TITLE_EQ_RE.match(ln)
        if m and not title:
            title = m.group(1).strip()
            continue
        if not title:
            title = ln
            continue
        if _SEP_RE.match(ln):
            continue
        if not info["ring"]:
            mm = _STORAGE_RING_RE.match(ln)
            if mm:
                info["ring"], info["rank"] = mm.group(1).strip(), mm.group(2).strip()
                continue
        if not info["total"]:
            mm = _STORAGE_CAP_RE.match(ln)
            if mm:
                info["used"], info["total"] = mm.group(1), mm.group(2)
                continue
        me = _STORAGE_EMPTY_RE.match(ln)     # 【存储物品】空
        if me:
            info["cats"].append({"name": me.group(1).strip(), "items": []})
            cur_cat = None
            continue
        mc = _STORAGE_CAT_RE.match(ln)
        if mc:
            cur_cat = {"name": mc.group(1).strip(), "items": []}
            info["cats"].append(cur_cat)
            continue
        mi = _STORAGE_ITEM_RE.match(ln)
        if mi and cur_cat is not None:
            cur_cat["items"].append((mi.group(1).strip(), mi.group(2) or ""))
            continue
        # 其余：戒子描述（第一个）→ desc；用法/警告 → notes
        if not info["desc"] and not info["cats"] and not info["total"]:
            info["desc"] = ln
        else:
            info["notes"].append(ln)
    return title, info


def _is_storage(title: str, info) -> bool:
    """判定是否为储物戒**主面板**。

    ⚠️ 必须匹配「XX 的储物戒」：「储物戒列表」（升级用）虽然也含「储物戒」，
    但它的条目是「容量：N格 | 需求：境界」且列出多枚戒子，按主面板渲染会错位，
    故用「的储物戒」把它排除在外。
    """
    if "的储物戒" not in title:
        return False
    return bool(info.get("total")) or bool(info.get("cats"))


# ============================================================
# 布局一：我的信息（角色卡）
# ============================================================
def _render_player(title, sections, theme: str = DEFAULT_THEME) -> str:
    tm = re.search(r"道友\s*(.+?)\s*的信息", title)
    name = tm.group(1) if tm else title

    realm = _sec_get(sections, "基本信息", "境界", "") or ""
    root = _sec_get(sections, "基本信息", "灵根", "") or ""
    style = (_sec_get(sections, "修炼属性", "修炼方式", "")
             or _sec_get(sections, "基本信息", "修炼方式", "") or "")
    power = (_sec_get(sections, "基本信息", "战力", "")
             or _sec_get(sections, "修炼属性", "战力", "") or "")
    exp = _sec_get(sections, "基本信息", "修为", "") or ""
    gold = _sec_get(sections, "基本信息", "灵石", "") or ""
    atkpractice = _sec_get(sections, "修炼属性", "攻击修炼")
    blood = _sec_get(sections, "修炼属性", "气血")
    qi = _sec_get(sections, "修炼属性", "灵气")
    lifespan = _sec_get(sections, "修炼属性", "寿命") or _sec_get(sections, "基本信息", "寿命")
    brate = (_sec_get(sections, "基本信息", "突破加成")
             or _sec_get(sections, "修炼属性", "突破加成"))

    weapon = _sec_get(sections, "装备信息", "法器")
    armor = _sec_get(sections, "装备信息", "防具")
    technique = _sec_get(sections, "装备信息", "主修功法")
    sect = _sec_get(sections, "宗门信息", "所在宗门")
    position = _sec_get(sections, "宗门信息", "宗门职位")

    # 未被专用布局消费的字段 → 杂项区（零丢失）
    consumed = {"道号", "境界", "灵根", "修炼方式", "战力", "修为", "灵石", "气血", "灵气",
                "寿命", "突破加成", "法器", "防具", "主修功法", "所在宗门", "宗门职位",
                "物伤", "法伤", "物防", "法防", "精神力", "状态", "攻击修炼"}
    misc = []
    for s in sections:
        if s["name"] in ("基本信息", "修炼属性"):
            for k, v in s["kvs"]:
                if k not in consumed:
                    misc.append((k, v))
        elif s["name"] in ("宗门信息", "装备信息"):
            continue
        elif s["name"] not in ("贷款信息",):
            for k, v in s["kvs"]:
                misc.append((k, v))
            misc.extend((None, raw) for raw in s["raws"])

    h = []
    # ① 主视觉
    h.append('<div class="hero"><div class="h-deco">✦ ✦ ✦</div>'
             f'<div class="dname gold-t">{_esc(name)}</div>')
    badges = [b for b in (realm, root, style) if b]
    if badges:
        cells = "".join(f'<span class="bd">{_esc(b)}</span>' for b in badges)
        h.append(f'<div class="badges">{cells}</div>')
    h.append("</div>")

    # ② 战力
    if power:
        h.append('<div class="power"><div class="pw-label">— 战 力 —</div>'
                 f'<div class="pw-num gold-t">{_esc(power)}</div></div>')

    # ③ 修为 / 气血 / 灵气 进度
    m = _NUMV_RE.match(exp.replace(" ", "")) if exp else None
    if m:
        h.append(_progress("修为", m.group(1), m.group(2)))
    m = _NUMV_RE.match(blood.replace(" ", "")) if blood else None
    if m:
        h.append(_progress("气血", m.group(1), m.group(2), hp=True))
    m = _NUMV_RE.match(qi.replace(" ", "")) if qi else None
    if m:
        h.append(_progress("灵气", m.group(1), m.group(2)))

    # ④ 属性卡（四维 + 精神力 + 灵石）
    stats = []
    for k in ("物伤", "法伤", "物防", "法防", "精神力"):
        v = _sec_get(sections, "修炼属性", k)
        if v is not None:
            stats.append(_stat(STAT_ICONS[k], k, v))
    if atkpractice:
        stats.append(_stat("🗡", "攻击修炼", atkpractice))
    if gold:
        stats.append(_stat("💰", "灵石", gold))
    if stats:
        h.append(f'<div class="stat-grid">{"".join(stats)}</div>')

    # ⑤ 装备
    gear = []
    if weapon:
        gear.append(f'<div class="g-row"><span class="g-icon">🗡️</span><span class="g-slot">法器</span>'
                    f'<span class="g-name">{_esc(weapon)}</span></div>')
    if armor:
        gear.append(f'<div class="g-row"><span class="g-icon">🛡️</span><span class="g-slot">防具</span>'
                    f'<span class="g-name">{_esc(armor)}</span></div>')
    if technique:
        gear.append(f'<div class="g-row"><span class="g-icon">📜</span><span class="g-slot">心法</span>'
                    f'<span class="g-name">{_esc(technique)}</span></div>')
    if gear:
        h.append('<div class="sec"><span class="emo">🗡️</span>随身装备<i></i></div>'
                 + "".join(gear))

    # ⑥ 杂项（含突破加成等）
    if brate:
        misc.insert(0, ("突破加成", brate))
    if misc:
        rows = "".join(
            f'<div class="row"><span class="k">{_esc(k)}</span>'
            f'<span class="{_vc(v)}">{_emph(_esc(v))}</span></div>' if k else
            (_div_html() if _is_sep(v) else f'<div class="li">{_emph(_esc(v))}</div>')
            for k, v in misc)
        h.append(f'<div class="misc">{rows}</div>')

    # ⑦ 脚注
    if sect or lifespan:
        bits = []
        if sect and sect != "无宗门":
            bits.append(_esc(sect) + (f" · {_esc(position)}" if position and position != "散修" else ""))
        elif position and position != "散修":
            bits.append(_esc(position))
        if lifespan:
            bits.append(f"寿元 {_esc(lifespan)}")
        if bits:
            h.append(f'<div class="foot">{"".join(f"<span>{b}</span>" for b in bits)}</div>')

    return _frame("", "".join(h), theme)


def _vc(v: str) -> str:
    if v in ("无", "未装备", "无宗门", "散修"):
        return "v dim"
    if re.match(r"^[+＋]\d", v) or v.endswith("%") or v.endswith("％"):
        return "v up"
    return "v"


# ============================================================
# 布局二：我的装备
# ============================================================
def _render_equip(title, sections, theme: str = DEFAULT_THEME) -> str:
    owner = re.sub(r"\s*的装备\s*$", "", title).strip()
    h = ['<div class="hero"><div class="dname gold-t">⚔ 装备一览</div>'
         f'<div class="p-sub">{_esc(owner)} · EQUIPMENT</div></div>']
    stats = []
    gear_rows = []
    misc = []

    for s in sections:
        n = s["name"]
        if n == "装备属性加成":
            for k, v in s["kvs"]:
                k2 = k.replace("⚔️", "").replace("✨", "").replace("🪨", "") \
                      .replace("🛡️", "").replace("🧠", "").replace("📈", "").strip()
                icon = STAT_ICONS.get(k2, "✦")
                if _NUMV_RE.match(v.replace(" ", "")):
                    mm = _NUMV_RE.match(v.replace(" ", ""))
                    h.append(_progress(k2, mm.group(1), mm.group(2)))
                else:
                    stats.append(_stat(icon, k2, v))
            for raw in s["raws"]:
                m = _PCT_STAT_RE.match(raw)
                if m:
                    k2 = m.group(1).split()[-1]  # 去掉 emoji 前缀取字段名
                    stats.append(_stat(STAT_ICONS.get(k2, "✦"), k2, m.group(2)))
                else:
                    misc.append((None, raw))
            continue
        # 槽位 kv（【武器】紫霄皇剑 → kv (武器, 紫霄皇剑)）
        for k, v in list(s["kvs"]):
            if k in ("武器", "防具", "主修心法"):
                icon = {"武器": "🗡️", "防具": "🛡️", "主修心法": "📜"}[k]
                gear_rows.append(f'<div class="g-row"><span class="g-icon">{icon}</span>'
                                 f'<span class="g-slot">{k}</span>'
                                 f'<span class="g-name">{_esc(v)}</span></div>')
            elif k == "功法":
                chips = [re.sub(r"^\d+\.\s*", "", raw) for raw in s["raws"]
                         if re.match(r"^\d+\.", raw)]
                if chips:
                    cells = "".join(f'<span class="chip">{_esc(c)}</span>' for c in chips)
                    gear_rows.append(f'<div class="g-row"><span class="g-icon">📜</span>'
                                     f'<span class="g-slot">功法</span><span class="chips">{cells}</span></div>')
            else:
                misc.append((k, v))
        # 非 chips 的 raws → misc
        chip_raws = any(k == "功法" for k, _ in s["kvs"])
        if not chip_raws:
            misc.extend((None, raw) for raw in s["raws"])

    if gear_rows:
        h.append("".join(gear_rows))
    if stats:
        h.append('<div class="sec"><span class="emo">✦</span>属性加成（含精炼）<i></i></div>'
                 f'<div class="stat-grid">{"".join(stats)}</div>')
    if misc:
        rows = "".join(
            f'<div class="row"><span class="k">{_esc(k)}</span>'
            f'<span class="{_vc(v)}">{_emph(_esc(v))}</span></div>' if k else
            (_div_html() if _is_sep(v) else f'<div class="li">{_emph(_esc(v))}</div>')
            for k, v in misc)
        h.append(f'<div class="misc">{rows}</div>')

    return _frame("", "".join(h), theme)


# ============================================================
# 布局三：修仙帮助
# ============================================================
def _render_help(title, sections, theme: str = DEFAULT_THEME) -> str:
    h = ['<div class="hero"><div class="dname gold-t">📖 修仙指令大全</div>'
         '<div class="p-sub">COMMANDS</div></div>']
    for s in sections:
        if not s["name"] and not s["kvs"] and not s["raws"]:
            continue
        if s["name"]:
            icon = SEC_ICONS.get(s["name"], "✧")
            h.append(f'<div class="h-sec"><span class="emo">{icon}</span>{_esc(s["name"])}</div>')
        elif any(r for r in s["raws"]) or s["kvs"]:
            h.append('<div class="h-sec">✦ 须知</div>')
        rows = []
        for k, v in s["kvs"]:
            rows.append(f'<div class="cmdrow"><span class="cmd">{_esc(k)}</span>'
                        f'<span class="desc">{_esc(v)}</span></div>')
        for raw in s["raws"]:
            m = _SUB_RE.match(raw)
            if m:
                txt = _esc(m.group(1))
                cls = "sub warn" if ("⚠" in txt or "逾期" in txt or "死亡" in txt or "清除" in txt) else "sub"
                rows.append(f'<div class="{cls}">└─ {txt}</div>')
                continue
            if _is_sep(raw):
                rows.append(_div_html())
                continue
            m = _ARROW_RE.match(raw)
            if m and len(m.group(1)) <= 30:
                rows.append(f'<div class="cmdrow"><span class="cmd">{_esc(m.group(1))}</span>'
                            f'<span class="desc">{_esc(m.group(2))}</span></div>')
                continue
            cls = "li warn" if ("⚠" in raw or "逾期" in raw or "致死" in raw) else "li"
            rows.append(f'<div class="{cls}">{_emph(_esc(raw))}</div>')
        h.append("".join(rows))
    return _frame("", "".join(h), theme)


# ============================================================
# 布局四：商店（阁楼货架 · 商品卡网格）
# ============================================================
def _render_shop(title: str, items, notes, theme: str = DEFAULT_THEME) -> str:
    sub = PAVILION_SUB.get(title, "PAVILION")
    h = [f'<div class="shop-head"><div class="dname gold-t">🏪 {_esc(title)}</div>'
         f'<div class="p-sub">{sub}</div></div>']

    cells = []
    for it in items:
        tier = RANK_TIER.get(it["rank"], 0)
        rank_html = f'<span class="s-rank rk{tier}">{_esc(it["rank"])}</span>' if it["rank"] else ""
        off_html = ""
        if it["off"]:
            up = it["off"].startswith("+")
            off_html = f'<span class="s-off{" up" if up else ""}">{_esc(it["off"])}</span>'
        price_html = ""
        if it["price"]:
            price_html = (f'<span class="s-price">{_esc(it["price"])}'
                          f'<i>灵石</i></span>')
        stock_html = ""
        if it["stock"]:
            label = "库存紧张" if it["tight"] else "库存"
            cls = "s-stock low" if it["tight"] else "s-stock"
            stock_html = f'<span class="{cls}">{label} {it["stock"]}</span>'
        eff_html = ""
        if it["effect"]:
            eff_html = f'<div class="s-eff">{_emph(_esc(it["effect"]))}</div>'

        cells.append(
            '<div class="s-item">'
            '<div class="s-top">'
            f'<span class="s-no">{_esc(it["no"])}</span>'
            f'<span class="s-name">{_esc(it["name"])}</span>'
            f'{price_html}</div>'
            '<div class="s-meta">'
            f'{rank_html}'
            f'<span class="s-type">{_esc(it["type"])}</span>'
            f'{off_html}'
            f'{stock_html}</div>'
            f'{eff_html}'
            '</div>'
        )
    h.append(f'<div class="shop-grid">{"".join(cells)}</div>')

    # 提示区（下次刷新 / 购买提示）
    note_rows = []
    for n in notes:
        txt = _esc(n)
        # 「下次刷新: 5小时30分钟后」→ 高亮时长
        txt = re.sub(r"(下次刷新\s*[:：]\s*)(.+)", r'\1<b>\2</b>', txt)
        note_rows.append(f'<span>{txt}</span>')
    if note_rows:
        h.append(f'<div class="shop-note">{"".join(note_rows)}</div>')

    return _frame("", "".join(h), theme)


# ============================================================
# 布局六：丹药配方（⚗ 单列卡片）
# ============================================================
def _render_recipe(title: str, recipes, notes, theme: str = DEFAULT_THEME) -> str:
    """丹药配方面板：每个配方一张卡（名称+ID+成功率 / 境界+突破目标 / 材料 / 效果）。

    配方字段行多（材料串可能很长），用**单列**卡片而非商店那种双列网格，避免挤压换行。
    """
    h = ['<div class="st-head">'
         f'<div class="dname gold-t">{_esc(title)}</div>'
         '<div class="p-sub">ALCHEMY RECIPES</div></div>']

    cells = []
    for r in recipes:
        id_html = f'<span class="r-id">#{_esc(r["id"])}</span>' if r["id"] else ""
        rate_html = ""
        if r["rate"]:
            rate_html = f'<span class="r-rate">{_emph(_esc(r["rate"]))}<i>成功率</i></span>'

        meta = []
        if r["lv"]:
            meta.append(f'<span class="r-lv">需求 {_esc(r["lv"])}</span>')
        if r["target"]:
            cls = "r-tg ok" if r["ok"] else "r-tg lock"
            mark = "✅ 可炼" if r["ok"] else "🔒 未达境界"
            meta.append(f'<span class="{cls}">{_esc(r["target"])} · {mark}</span>')
        meta_html = f'<div class="r-meta">{"".join(meta)}</div>' if meta else ""

        mat_html = ""
        if r["mats"]:
            parts = [p.strip() for p in re.split(r"[,，、]", r["mats"]) if p.strip()]
            inner = " · ".join(f"<b>{_esc(p)}</b>" for p in parts)
            mat_html = f'<div class="r-mat">🧪 材料 {inner}</div>'

        eff_html = f'<div class="r-eff">{_emph(_esc(r["desc"]))}</div>' if r["desc"] else ""

        cells.append('<div class="r-item">'
                     f'<div class="r-top">{id_html}'
                     f'<span class="r-name">{_esc(r["name"])}</span>'
                     f'{rate_html}</div>'
                     f'{meta_html}{mat_html}{eff_html}</div>')
    h.append(f'<div class="r-list">{"".join(cells)}</div>')

    if notes:
        rows = "".join(f'<div>{_emph(_esc(n))}</div>' for n in notes)
        h.append(f'<div class="st-note">{rows}</div>')

    return _frame("", "".join(h), theme)


# ============================================================
# 布局七：储物戒（💍 戒子信息 + 容量条 + 分类物品格）
# ============================================================
def _render_storage(title: str, info, theme: str = DEFAULT_THEME) -> str:
    """储物戒面板：戒名/品级 → 容量进度条 → 按分类的 2 列物品格 → 用法提示。"""
    rank_html = (f'<span class="st-rank">{_esc(info["rank"])}</span>'
                 if info["rank"] else "")
    h = ['<div class="st-head">'
         f'<div class="dname gold-t">💍 {_esc(info["ring"] or "储物戒")}</div>'
         f'{rank_html}</div>'
         f'<div class="p-sub">{_esc(title)}</div>']

    if info["desc"]:
        h.append(f'<div class="st-desc">{_esc(info["desc"])}</div>')
    if info["total"]:
        h.append(_progress("容量", info["used"] or "0", info["total"]))

    for cat in info["cats"]:
        chips = []
        for nm, ct in cat["items"]:
            ct_html = f'<span class="ct">×{_esc(ct)}</span>' if ct else ""
            chips.append(f'<div class="st-chip"><span class="nm">{_esc(nm)}</span>{ct_html}</div>')
        body = (f'<div class="st-grid">{"".join(chips)}</div>' if chips
                else '<div class="st-empty">（空）</div>')
        h.append(f'<div class="st-sec"><div class="st-sec-h">【{_esc(cat["name"])}】</div>{body}</div>')

    if info["notes"]:
        rows = "".join(f'<div>{_emph(_esc(n))}</div>' for n in info["notes"])
        h.append(f'<div class="st-note">{rows}</div>')

    return _frame("", "".join(h), theme)


# ============================================================
# 布局五：物品详情（单件商品详解）
# ============================================================
def _render_item_detail(title: str, sections, theme: str = DEFAULT_THEME) -> str:
    """物品信息面板：名称/品级/价格/描述/属性/获取途径。"""
    m = _ITEM_NAME_RE.match(title)
    name = m.group(1).strip() if m else title
    # 名称后面可能粘着别的内容
    if m and len(name) > 20:
        name = name[:20]

    rank = ""
    price = ""
    desc = ""
    rows = []
    for s in sections:
        for k, v in s["kvs"]:
            if k == "名称":
                continue
            if k == "品级" and not rank:
                rank = v
                continue
            if k == "价格" and not price:
                price = v
                continue
            if k == "描述" and not desc:
                desc = v
                continue
            rows.append((k, v))
        for raw in s["raws"]:
            rows.append((None, raw))

    h = ['<div class="hero"><div class="dname gold-t">'
         f'{_esc(name)}</div><div class="p-sub">ITEM DETAIL</div></div>']

    badges = []
    if rank:
        tier = RANK_TIER.get(rank, 0)
        badges.append(f'<span class="bd rk{tier}">{_esc(rank)}</span>')
    if price:
        badges.append(f'<span class="bd">💰 {_esc(price)}</span>')
    if badges:
        h.append(f'<div class="badges">{"".join(badges)}</div>')

    if desc:
        h.append(f'<div class="li" style="text-align:center;padding:8px 4px 2px">'
                 f'{_esc(desc)}</div>')

    body = []
    for k, v in rows:
        if k:
            body.append(f'<div class="row"><span class="k">{_esc(k)}</span>'
                        f'<span class="{_vc(v)}">{_emph(_esc(v))}</span></div>')
        else:
            cls = "li warn" if ("⚠" in v or "致死" in v) else "li"
            body.append(f'<div class="{cls}">{_emph(_esc(v))}</div>')
    if body:
        h.append('<div class="misc">' + "".join(body) + "</div>")

    return _frame("", "".join(h), theme)


# ============================================================
# 布局六：通用（玄金条目式）
# ============================================================
def _render_generic(title, sections, theme: str = DEFAULT_THEME) -> str:
    tm = re.match(r"^([^\w\s【】]{1,3})\s*(.*)$", title)
    emo, name = (tm.group(1), tm.group(2)) if tm and tm.group(2) else ("", title)
    emo_html = f'<span class="emo">{_esc(emo)}</span>' if emo else ""
    h = [f'<div class="p-title">{emo_html}{_esc(name)}</div>'
         '<div class="p-sub">PANEL</div>']

    r_buf: list = []
    stat_buf: list = []

    def flush_stats():
        if stat_buf:
            r_buf.append(f'<div class="stat-grid">{"".join(stat_buf)}</div>')
            stat_buf.clear()

    for s in sections:
        if s["name"]:
            flush_stats()
            icon = SEC_ICONS.get(s["name"], "✧")
            r_buf.append(f'<div class="sec"><span class="emo">{icon}</span>{_esc(s["name"])}<i></i></div>')
        for k, v in s["kvs"]:
            if k in ("战力", "总战力"):
                flush_stats()
                r_buf.append('<div class="power"><div class="pw-label">— 战 力 —</div>'
                             f'<div class="pw-num gold-t">{_esc(v)}</div></div>')
            elif k in STAT_ICONS:
                stat_buf.append(_stat(STAT_ICONS[k], k, v))
            elif k in ("修为", "气血", "灵气") and _NUMV_RE.match(v.replace(" ", "")):
                flush_stats()
                mm = _NUMV_RE.match(v.replace(" ", ""))
                r_buf.append(_progress(k, mm.group(1), mm.group(2), hp=(k == "气血")))
            else:
                flush_stats()
                r_buf.append(f'<div class="row"><span class="k">{_esc(k)}</span>'
                             f'<span class="{_vc(v)}">{_emph(_esc(v))}</span></div>')
        for raw in s["raws"]:
            flush_stats()
            m = _SUB_RE.match(raw)
            if m:
                txt = _esc(m.group(1))
                cls = "sub warn" if ("⚠" in txt or "逾期" in txt or "死亡" in txt) else "sub"
                r_buf.append(f'<div class="{cls}">└─ {txt}</div>')
                continue
            if _is_sep(raw):
                r_buf.append(_div_html())
                continue
            cls = "li warn" if ("⚠" in raw or "逾期" in raw or "致死" in raw) else "li"
            r_buf.append(f'<div class="{cls}">{_emph(_esc(raw))}</div>')
    flush_stats()
    return _frame("", "".join(h) + "".join(r_buf), theme)


# ============================================================
# 入口
# ============================================================
def render_panel_html(text: str, theme: str = DEFAULT_THEME) -> Optional[str]:
    """把长文本面板渲染为 HTML。

    :param theme: `paper`（宣纸金，默认）/ `gold`（玄金暗色）；未知值回退默认主题。
    """
    if not text or not text.strip():
        return None
    if theme not in THEMES:
        theme = DEFAULT_THEME

    # ① 商店货架（专用解析器：按商品头行重新聚合）
    shop_title, shop_items, shop_notes = _parse_shop_items(text)
    if _is_shop(shop_title, shop_items):
        return _render_shop(shop_title, shop_items, shop_notes, theme)

    # ② 丹药配方（专用解析器：按配方头行重新聚合）
    r_title, recipes, r_notes = _parse_recipes(text)
    if _is_recipe(r_title, recipes):
        return _render_recipe(r_title, recipes, r_notes, theme)

    # ③ 储物戒主面板（容量进度条 + 分类物品格）
    s_title, s_info = _parse_storage(text)
    if _is_storage(s_title, s_info):
        return _render_storage(s_title, s_info, theme)

    title, sections = _parse_sections(text)
    if _is_player(title, sections):
        return _render_player(title, sections, theme)
    if _is_equip(title, sections):
        return _render_equip(title, sections, theme)
    if _is_help(title, sections):
        return _render_help(title, sections, theme)
    # ② 物品详情
    if _ITEM_NAME_RE.match(title):
        return _render_item_detail(title, sections, theme)
    return _render_generic(title, sections, theme)
