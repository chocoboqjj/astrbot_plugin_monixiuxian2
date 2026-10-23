# managers/calamity_manager.py
"""天灾人祸系统管理器（v3.2.9）

设计要点（与用户确认的方案一一对应）：

1. **定时随机触发**：每 `interval` 秒（默认 3600 = 1 小时）触发一次天灾人祸。
2. **按资产比例扣**：惩罚按被罚者**当前**灵石/修为的百分比计算，
   天然适配不同境界的玩家——新玩家不会被打爆，大佬才会真正感到痛。
3. **惩罚数量最少为 0**：命中「无事发生」概率时不扣任何东西，但仍会播报，
   制造「今天差点遭殃」的戏剧感。
4. **绝不致死**：只做资源定向扣除，**不调用** `PenaltyManager.punish()`，
   不触发走火入魔、不删号。与已有的走火入魔 / 银行追杀明确区分。
5. **定魂护盾可免疫**：`player.has_debuff_shield`（定魂丹）此前是「只设不消」的
   悬空特性，本系统作为它的**首个消费点**——有护盾则完全免疫本次天灾。
6. **境界地板**：修为不会被扣到当前境界门槛以下，避免玩家被卡境界。
"""

import random
import time
from typing import Dict, List, Optional, Tuple

from ..data import DataBase
from ..models import Player
from ..utils.probability import describe_roll

__all__ = ["CalamityManager"]

# ===== 默认参数（配置文件缺失时的兜底）=====
DEFAULT_INTERVAL = 3600           # 触发间隔（秒）
DEFAULT_NO_EVENT_CHANCE = 30      # 无事发生概率（百分比）
DEFAULT_MIN_GOLD_LOSS = 0         # 灵石起罚门槛（低于此值视为无事发生）
DEFAULT_MIN_EXP_LOSS = 0          # 修为起罚门槛
DEFAULT_RATE_JITTER = 0.2         # 扣减比例抖动幅度（±20%）
DEFAULT_SHIELD_CONSUMED = True    # 护盾抵挡后是否消耗

# 分类名（用于播报与查询）
CATEGORY_TIANZAI = "天灾"
CATEGORY_RENHUO = "人祸"


class CalamityManager:
    """天灾人祸管理器"""

    def __init__(self, db: DataBase, config_manager=None, plugin_config: Optional[Dict] = None):
        self.db = db
        self.config_manager = config_manager
        # 插件主配置（`_conf_schema.json` 的 CALAMITY 段）——可选的覆盖层
        self.plugin_config = plugin_config or {}
        self.config: Dict = {}
        self.reload_config()

    # ===== 配置 =====

    def reload_config(self) -> Dict:
        """重新读取天灾配置

        配置来源有两层（后者覆盖前者）：
          1. `config/calamity_config.json` —— 天灾**种类表**（10 种天灾）
             与默认值，来源为 `ConfigManager.calamity_config`。
          2. 插件主配置的 `CALAMITY` 段（`_conf_schema.json`）—— 供服主
             在 AstrBot 面板上调参（间隔、无事发生概率、抖动、护盾消耗）。
        """
        cfg = {}
        if self.config_manager is not None:
            cfg = dict(getattr(self.config_manager, "calamity_config", None) or {})

        # 覆盖层：插件主配置 CALAMITY 段
        override = self.plugin_config.get("CALAMITY") or {}
        if isinstance(override, dict):
            mapping = {
                "ENABLED": "enabled",
                "INTERVAL": "interval",
                "NO_EVENT_CHANCE": "no_event_chance",
                "RATE_JITTER": "rate_jitter",
                "SHIELD_CONSUMED_ON_BLOCK": "shield_consumed_on_block",
            }
            for src_key, dst_key in mapping.items():
                if src_key in override and override[src_key] is not None:
                    cfg[dst_key] = override[src_key]

        self.config = cfg
        return cfg

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", True))

    @property
    def interval(self) -> int:
        return max(60, int(self.config.get("interval", DEFAULT_INTERVAL)))

    @property
    def no_event_chance(self) -> int:
        return max(0, min(100, int(self.config.get("no_event_chance", DEFAULT_NO_EVENT_CHANCE))))

    @property
    def min_gold_loss(self) -> int:
        return max(0, int(self.config.get("min_gold_loss", DEFAULT_MIN_GOLD_LOSS)))

    @property
    def min_exp_loss(self) -> int:
        return max(0, int(self.config.get("min_exp_loss", DEFAULT_MIN_EXP_LOSS)))

    @property
    def rate_jitter(self) -> float:
        return max(0.0, min(1.0, float(self.config.get("rate_jitter", DEFAULT_RATE_JITTER))))

    @property
    def shield_consumed_on_block(self) -> bool:
        return bool(self.config.get("shield_consumed_on_block", DEFAULT_SHIELD_CONSUMED))

    def get_calamities(self) -> List[Dict]:
        """返回天灾列表（配置缺失时为空）"""
        items = self.config.get("calamities") or []
        return [c for c in items if isinstance(c, dict) and c.get("id")]

    # ===== 选取 =====

    def pick_calamity(self) -> Optional[Dict]:
        """按权重随机抽一种天灾"""
        items = self.get_calamities()
        if not items:
            return None
        weights = []
        for c in items:
            try:
                w = float(c.get("weight", 0))
            except (TypeError, ValueError):
                w = 0.0
            weights.append(max(0.0, w))
        total = sum(weights)
        if total <= 0:
            # 权重全为 0 / 缺失 → 等概率
            return random.choice(items)
        # random.choices 的 cum_weights 需与 weights 同长，这里做一次安全裁剪
        picked = random.choices(items, weights=weights, k=1)[0]
        return picked

    async def pick_target(self) -> Optional[Player]:
        """从全体玩家中等概率抽取一名被罚者

        方案已确认「全体玩家等概率」——不按财富加权，避免富者恒被盯上。
        抽到的玩家若身无分文，扣减自然为 0（等价于「无事发生」）。
        """
        players = await self.db.get_all_players()
        if not players:
            return None
        return random.choice(players)

    # ===== 惩罚计算 =====

    def get_exp_floor(self, player: Player) -> int:
        """当前境界的修为地板

        `level_config.json` 的 `exp_needed[i]` 是「成为第 i 境界所需的累计修为」，
        而 `player.experience` 是**累计值**（突破不清零）。因此扣修为时不能
        低于 `exp_needed[level_index]`，否则玩家会因修为不足而卡在当前境界。
        """
        if self.config_manager is None:
            return 0
        try:
            level_data = self.config_manager.get_level_data(player.cultivation_type)
        except Exception:
            level_data = []
        if not level_data:
            level_data = getattr(self.config_manager, "level_data", []) or []
        idx = max(0, min(int(player.level_index or 0), len(level_data) - 1))
        if 0 <= idx < len(level_data):
            try:
                return int(level_data[idx].get("exp_needed", 0) or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    def _jittered_rate(self, rate: float) -> float:
        """给扣减比例加一点抖动，避免同一天灾每次都是同一个数字"""
        jitter = self.rate_jitter
        if jitter <= 0:
            return max(0.0, float(rate))
        factor = random.uniform(1.0 - jitter, 1.0 + jitter)
        return max(0.0, float(rate) * factor)

    def calculate_losses(self, player: Player, calamity: Dict) -> Tuple[int, int]:
        """计算本次天灾的灵石/修为扣减量

        Args:
            player: 被罚玩家
            calamity: 天灾配置

        Returns:
            (灵石扣减, 修为扣减)
        """
        gold_rate = self._jittered_rate(float(calamity.get("gold_rate", 0) or 0))
        exp_rate = self._jittered_rate(float(calamity.get("exp_rate", 0) or 0))

        gold_lost = int(max(0, player.gold or 0) * gold_rate)
        exp_lost = int(max(0, player.experience or 0) * exp_rate)

        # 灵石不能扣成负数
        gold_lost = min(gold_lost, max(0, int(player.gold or 0)))

        # 修为不能跌破当前境界门槛
        floor = self.get_exp_floor(player)
        exp_lost = max(0, min(exp_lost, max(0, int(player.experience or 0) - floor)))

        # 起罚门槛：扣得太少的那部分视同「无事发生」（默认 0 = 不设门槛）
        if gold_lost < self.min_gold_loss:
            gold_lost = 0
        if exp_lost < self.min_exp_loss:
            exp_lost = 0

        return gold_lost, exp_lost

    # ===== 触发 =====

    async def trigger_calamity(self) -> Optional[Dict]:
        """触发一次天灾人祸

        Returns:
            事件结果字典（供群播报与落库）；系统禁用 / 无玩家时返回 None
        """
        if not self.enabled:
            return None

        calamity = self.pick_calamity()
        if not calamity:
            return None

        player = await self.pick_target()
        if not player:
            return None

        now = int(time.time())
        cal_id = str(calamity.get("id", "unknown"))
        cal_name = str(calamity.get("name", "无名天灾"))
        category = str(calamity.get("category", CATEGORY_TIANZAI))
        desc = str(calamity.get("desc", ""))
        target_name = player.user_name or f"道友{str(player.user_id)[:6]}"

        # --- 第一层：无事发生（虚惊一场） ---
        # ⚠️ 必须排在护盾判定之前：既然「无事发生」，就不该消耗玩家的定魂护盾。
        no_event_chance = self.no_event_chance
        no_event_hit = random.randint(1, 100) <= no_event_chance
        if no_event_hit:
            result = {
                "calamity_id": cal_id,
                "calamity_name": cal_name,
                "category": category,
                "desc": desc,
                "target_user_id": player.user_id,
                "target_name": target_name,
                "gold_lost": 0,
                "exp_lost": 0,
                "no_event": True,
                "shielded": False,
                "shield_consumed": False,
                "gold_rate": float(calamity.get("gold_rate", 0) or 0),
                "exp_rate": float(calamity.get("exp_rate", 0) or 0),
                "create_time": now,
                "reason": "no_event",
                "roll_line": describe_roll("天灾落空", no_event_chance, True,
                                           result_text="虚惊一场，未伤分毫"),
            }
            await self._record(result)
            return result

        # --- 第二层：计算扣减量 ---
        gold_lost, exp_lost = self.calculate_losses(player, calamity)

        # 起罚门槛：扣得太少视同无事发生（保留「惩罚最少为 0」的语义）
        if gold_lost <= 0 and exp_lost <= 0:
            result = {
                "calamity_id": cal_id,
                "calamity_name": cal_name,
                "category": category,
                "desc": desc,
                "target_user_id": player.user_id,
                "target_name": target_name,
                "gold_lost": 0,
                "exp_lost": 0,
                "no_event": True,
                "shielded": False,
                "shield_consumed": False,
                "gold_rate": float(calamity.get("gold_rate", 0) or 0),
                "exp_rate": float(calamity.get("exp_rate", 0) or 0),
                "create_time": now,
                "reason": "below_threshold",
            }
            await self._record(result)
            return result

        # --- 第三层：原子落库（护盾判定在同一次条件 UPDATE 内完成） ---
        applied = await self.db.ext.apply_calamity_penalty(
            player.user_id,
            gold_lost=gold_lost,
            exp_lost=exp_lost,
            exp_floor=self.get_exp_floor(player),
            consume_shield=self.shield_consumed_on_block,
        )
        if not applied.get("success"):
            return None

        result = {
            "calamity_id": cal_id,
            "calamity_name": cal_name,
            "category": category,
            "desc": desc,
            "target_user_id": player.user_id,
            "target_name": target_name,
            "gold_lost": int(applied.get("gold_lost", 0)),
            "exp_lost": int(applied.get("exp_lost", 0)),
            "no_event": False,
            "shielded": bool(applied.get("shielded")),
            "shield_consumed": bool(applied.get("shield_consumed")),
            "gold_rate": float(calamity.get("gold_rate", 0) or 0),
            "exp_rate": float(calamity.get("exp_rate", 0) or 0),
            "create_time": now,
            "reason": "shield" if applied.get("shielded") else "penalty",
        }
        await self._record(result)
        return result

    async def _record(self, result: Dict):
        """落库一条天灾记录"""
        try:
            await self.db.ext.create_calamity_record(
                calamity_id=result.get("calamity_id", ""),
                calamity_name=result.get("calamity_name", ""),
                category=result.get("category", CATEGORY_TIANZAI),
                target_user_id=result.get("target_user_id", ""),
                target_name=result.get("target_name", ""),
                gold_lost=int(result.get("gold_lost", 0)),
                exp_lost=int(result.get("exp_lost", 0)),
                no_event=bool(result.get("no_event")),
                shielded=bool(result.get("shielded")),
                create_time=int(result.get("create_time", 0)),
            )
        except Exception:
            # 记录失败不影响天灾本身生效
            pass

    # ===== 查询 =====

    async def get_recent(self, limit: int = 10) -> List[Dict]:
        return await self.db.ext.get_recent_calamities(limit)

    async def get_user_history(self, user_id: str, limit: int = 5) -> List[Dict]:
        return await self.db.ext.get_user_calamities(user_id, limit)

    async def get_user_stats(self, user_id: str) -> Dict:
        return await self.db.ext.get_calamity_stats(user_id)

    async def cleanup(self, keep: int = 200) -> int:
        return await self.db.ext.cleanup_calamity_records(keep)

    # ===== 文案 =====

    @staticmethod
    def format_broadcast(result: Dict) -> str:
        """生成群播报文案"""
        if not result:
            return ""
        name = result.get("calamity_name", "无名天灾")
        category = result.get("category", CATEGORY_TIANZAI)
        target = result.get("target_name", "某位道友")
        desc = result.get("desc", "")

        icon = "⛈️" if category == CATEGORY_TIANZAI else "🗡️"
        head = f"{icon} 【{category}】{name}"

        if result.get("shielded"):
            body = (
                f"{head}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"{desc}\n"
                f"受难者：{target}\n"
                f"🛡️ 定魂护盾自行运转，灾害尽数消弭\n"
                f"此次天灾未造成任何损失。"
            )
            return body

        if result.get("no_event"):
            body = (
                f"{head}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"{desc}\n"
                f"受难者：{target}\n"
                f"🍃 虚惊一场——今日命数稳固，未伤分毫。"
            )
            # 概率透明化：随机玩法的判定一律展示概率（项目统一约定）
            roll_line = result.get("roll_line")
            if roll_line:
                body = f"{body}\n{roll_line}"
            return body

        gold_lost = int(result.get("gold_lost", 0))
        exp_lost = int(result.get("exp_lost", 0))
        gold_rate = float(result.get("gold_rate", 0) or 0)
        exp_rate = float(result.get("exp_rate", 0) or 0)
        lines = [
            head,
            "━━━━━━━━━━━━━━━",
            desc,
            f"受难者：{target}",
        ]
        if gold_lost > 0:
            lines.append(f"💔 损失灵石：{gold_lost}（约 {gold_rate:.0%}）")
        if exp_lost > 0:
            lines.append(f"💔 损失修为：{exp_lost}（约 {exp_rate:.0%}）")
        if gold_lost <= 0 and exp_lost <= 0:
            lines.append("🍃 此次未造成实质损失。")
        lines.append("━━━━━━━━━━━━━━━")
        lines.append("⚠️ 天灾只夺资源，绝不夺命——道友切莫忧心。")
        return "\n".join(lines)

    async def format_history_text(self, user_id: str, player_name: str, limit: int = 5) -> str:
        """生成「我的天灾受害史」文案"""
        stats = await self.get_user_stats(user_id)
        history = await self.get_user_history(user_id, limit)

        lines = [
            "☠️ 天灾人祸·受害档案",
            "━━━━━━━━━━━━━━━",
            f"道号：{player_name}",
            f"累计遭灾：{stats.get('count', 0)} 次",
            f"累计损失灵石：{stats.get('gold_lost', 0)}",
            f"累计损失修为：{stats.get('exp_lost', 0)}",
            "━━━━━━━━━━━━━━━",
        ]
        if not history:
            lines.append("📜 尚无受害记录——道友命数稳固，尚未被天灾盯上。")
            return "\n".join(lines)

        lines.append("📜 最近受害记录：")
        for rec in history:
            ts = rec.get("create_time", 0)
            time_str = time.strftime("%m-%d %H:%M", time.localtime(ts)) if ts else "时间未知"
            name = rec.get("calamity_name", "无名天灾")
            category = rec.get("category", CATEGORY_TIANZAI)
            if rec.get("shielded"):
                lines.append(f"  · [{time_str}] {category}·{name} → 🛡️ 护盾挡下，未伤分毫")
            elif rec.get("no_event"):
                lines.append(f"  · [{time_str}] {category}·{name} → 🍃 虚惊一场")
            else:
                g = int(rec.get("gold_lost", 0))
                e = int(rec.get("exp_lost", 0))
                loss = []
                if g > 0:
                    loss.append(f"灵石 {g}")
                if e > 0:
                    loss.append(f"修为 {e}")
                loss_str = "、".join(loss) if loss else "无损失"
                lines.append(f"  · [{time_str}] {category}·{name} → 损失 {loss_str}")
        return "\n".join(lines)

    async def format_recent_text(self, limit: int = 10) -> str:
        """生成「近期天灾纪事」文案"""
        records = await self.get_recent(limit)
        lines = [
            "📜 天灾人祸·近期纪事",
            "━━━━━━━━━━━━━━━",
        ]
        if not records:
            lines.append("近期风调雨顺，尚无天灾降临。")
            return "\n".join(lines)
        for rec in records:
            ts = rec.get("create_time", 0)
            time_str = time.strftime("%m-%d %H:%M", time.localtime(ts)) if ts else "时间未知"
            name = rec.get("calamity_name", "无名天灾")
            category = rec.get("category", CATEGORY_TIANZAI)
            target = rec.get("target_name", "某位道友")
            if rec.get("shielded"):
                outcome = "🛡️ 护盾挡下"
            elif rec.get("no_event"):
                outcome = "🍃 虚惊一场"
            else:
                g = int(rec.get("gold_lost", 0))
                e = int(rec.get("exp_lost", 0))
                loss = []
                if g > 0:
                    loss.append(f"灵石 {g}")
                if e > 0:
                    loss.append(f"修为 {e}")
                outcome = "损失 " + ("、".join(loss) if loss else "无")
            lines.append(f"  · [{time_str}] {category}·{name} → {target}：{outcome}")
        return "\n".join(lines)
