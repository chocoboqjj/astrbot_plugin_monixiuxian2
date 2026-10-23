# core/pill_manager.py

import time
from typing import Dict, List, Optional, Tuple
from astrbot.api import logger

from ..models import Player
from ..data import DataBase
from ..config_manager import ConfigManager


class PillManager:
    """丹药管理器 - 处理丹药效果、属性加成和限制机制"""

    # 丹药效果类型 → 中文名（错误提示统一取用，避免透出英文配置键）
    EFFECT_TYPE_NAMES = {
        "instant": "即时",
        "temporary": "临时",
        "permanent": "永久",
    }

    # 百分比增益键 → (玩家当前属性名, 折算后的固定增益键)
    # 用于表达「上限 +5%」「全部属性 +2%」这类按玩家当前属性比例生效的永久增益。
    # 折算后的数值仍会走每境界 30% 上限逻辑，避免百分比丹药绕开上限无限叠属性。
    PERCENT_GAIN_KEYS = {
        "physical_damage_gain_percent": ("physical_damage", "physical_damage_gain"),
        "magic_damage_gain_percent": ("magic_damage", "magic_damage_gain"),
        "physical_defense_gain_percent": ("physical_defense", "physical_defense_gain"),
        "magic_defense_gain_percent": ("magic_defense", "magic_defense_gain"),
        "mental_power_gain_percent": ("mental_power", "mental_power_gain"),
        "lifespan_gain_percent": ("lifespan", "lifespan_gain"),
        "max_spiritual_qi_gain_percent": ("max_spiritual_qi", "max_spiritual_qi_gain"),
        "max_blood_qi_gain_percent": ("max_blood_qi", "max_blood_qi_gain"),
    }

    # 永久属性丹药的每境界增益上限比例（默认 30%）
    DEFAULT_BASE_LIMIT_RATIO = 0.3

    # 「基础属性上限提升」的存放键。
    # ⚠️ 必须放在 permanent_pill_gains 的**顶层**（与 level_X 分桶平级），
    # 因为它是对「上限本身」的全局倍率提升，不属于任何单一境界的增益分桶。
    BASE_LIMIT_KEY = "_base_attribute_limit_bonus"

    # 全局上限倍率的封顶（防止多颗洗髓丹把 30% 叠成不合理的数值）
    MAX_BASE_LIMIT_BONUS = 2.0

    def __init__(self, db: DataBase, config_manager: ConfigManager, plugin_config=None):
        self.db = db
        self.config_manager = config_manager
        self.plugin_config = plugin_config

    def _get_daily_pill_limit(self) -> int:
        """读取每日服用丹药上限配置（0 表示不限制）。"""
        if not self.plugin_config:
            return 20
        try:
            values = self.plugin_config["VALUES"]
        except Exception:
            try:
                values = self.plugin_config.get("VALUES", {})
            except Exception:
                values = {}
        try:
            return int(values.get("DAILY_PILL_LIMIT", 20))
        except Exception:
            return 20

    def _ensure_non_negative_attributes(self, player: Player):
        """保证属性不为负，并同步能量上限约束"""
        attrs = [
            "lifespan",
            "experience",
            "physical_damage",
            "magic_damage",
            "physical_defense",
            "magic_defense",
            "mental_power",
            "spiritual_qi",
            "max_spiritual_qi",
            "blood_qi",
            "max_blood_qi",
        ]
        for attr in attrs:
            value = getattr(player, attr, 0)
            if value < 0:
                setattr(player, attr, 0)

        # 保证当前能量不超过上限
        if player.spiritual_qi > player.max_spiritual_qi:
            player.spiritual_qi = player.max_spiritual_qi
        if player.blood_qi > player.max_blood_qi:
            player.blood_qi = player.max_blood_qi

    def get_pill_by_name(self, pill_name: str) -> Optional[dict]:
        """根据名称获取丹药配置

        Args:
            pill_name: 丹药名称

        Returns:
            丹药配置字典，如果找不到返回None
        """
        # 尝试从破境丹中查找
        pill = self.config_manager.pills_data.get(pill_name)
        if pill:
            return pill

        # 尝试从修为丹中查找
        pill = self.config_manager.exp_pills_data.get(pill_name)
        if pill:
            return pill

        # 尝试从功能丹中查找
        pill = self.config_manager.utility_pills_data.get(pill_name)
        if pill:
            return pill

        return None

    async def update_temporary_effects(self, player: Player):
        """更新临时丹药效果，移除过期效果

        Args:
            player: 玩家对象
        """
        effects = player.get_active_pill_effects()
        current_time = int(time.time())
        updated_effects = []
        has_changes = False

        for effect in effects:
            if self._apply_periodic_effects(player, effect, current_time):
                has_changes = True

            expiry_time = effect.get("expiry_time", 0)
            if expiry_time <= 0 or current_time < expiry_time:
                updated_effects.append(effect)
            else:
                has_changes = True
                logger.info(f"玩家 {player.user_id} 的丹药效果 {effect.get('pill_name')} 已过期")

        if has_changes or len(updated_effects) != len(effects):
            player.set_active_pill_effects(updated_effects)
            await self.db.update_player(player)

    async def use_pill(
        self,
        player: Player,
        pill_name: str
    ) -> Tuple[bool, str]:
        """使用丹药

        Args:
            player: 玩家对象
            pill_name: 丹药名称

        Returns:
            (是否成功, 消息)
        """
        # 检查背包是否有该丹药
        inventory = player.get_pills_inventory()
        if pill_name not in inventory or inventory[pill_name] <= 0:
            return False, f"你的背包中没有【{pill_name}】！"

        # 获取丹药配置
        pill_data = self.get_pill_by_name(pill_name)
        if not pill_data:
            return False, f"丹药【{pill_name}】配置不存在！"

        # 检查境界需求
        required_level = pill_data.get("required_level_index", 0)
        if player.level_index < required_level:
            # 根据玩家修炼类型获取对应境界名称
            level_data = self.config_manager.get_level_data(player.cultivation_type)
            level_name = f"境界{required_level}"
            if 0 <= required_level < len(level_data):
                level_name = level_data[required_level]["level_name"]
            return False, (
                f"境界不足！使用【{pill_name}】需要达到【{level_name}】"
            )

        # 根据丹药类型处理
        # 每日丹药使用上限（防止丹药无限刷属性，daily_pill_usage 此前从未被使用）
        today = time.strftime("%Y-%m-%d")
        if player.last_daily_reset != today:
            player.set_daily_pill_usage({})
            player.last_daily_reset = today
        daily_usage = player.get_daily_pill_usage()
        daily_limit = self._get_daily_pill_limit()
        if daily_limit and sum(daily_usage.values()) >= daily_limit:
            return False, (
                f"今日服用丹药已达上限（{daily_limit} 次）！\n"
                f"当前已用：{sum(daily_usage.values())} 次\n"
                f"💡 明日 0 点自动重置，请合理规划丹药使用。"
            )
        daily_usage[pill_name] = daily_usage.get(pill_name, 0) + 1
        player.set_daily_pill_usage(daily_usage)

        effect_type = pill_data.get("effect_type", "instant")
        subtype = pill_data.get("subtype", "")
        if subtype == "exp":
            # 修为丹
            return await self._use_exp_pill(player, pill_name, pill_data)
        elif subtype == "resurrection":
            # 回生丹
            return await self._use_resurrection_pill(player, pill_name, pill_data)
        elif effect_type == "temporary":
            # 临时效果丹药
            return await self._use_temporary_pill(player, pill_name, pill_data)
        elif effect_type == "permanent":
            # 永久属性丹药
            return await self._use_permanent_pill(player, pill_name, pill_data)
        elif effect_type == "instant":
            # 瞬间效果丹药
            return await self._use_instant_pill(player, pill_name, pill_data)
        else:
            # 不回显原始英文配置键
            return False, f"未知的丹药类型：{self.EFFECT_TYPE_NAMES.get(effect_type, '未知类型')}"

    async def _use_exp_pill(self, player: Player, pill_name: str, pill_data: dict) -> Tuple[bool, str]:
        """使用修为丹"""
        exp_gain = pill_data.get("exp_gain", 0)
        player.experience += exp_gain

        # 扣除丹药
        inventory = player.get_pills_inventory()
        inventory[pill_name] -= 1
        if inventory[pill_name] <= 0:
            del inventory[pill_name]
        player.set_pills_inventory(inventory)

        await self.db.update_player(player)

        return True, (
            f"✨ 服用【{pill_name}】成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📈 获得修为：{exp_gain}\n"
            f"💫 当前修为：{player.experience}\n"
            f"━━━━━━━━━━━━━━━"
        )

    async def _use_resurrection_pill(self, player: Player, pill_name: str, pill_data: dict) -> Tuple[bool, str]:
        """使用回生丹"""
        if player.has_resurrection_pill:
            return False, "你已经拥有回生丹效果，无需重复使用！"

        player.has_resurrection_pill = True

        # 扣除丹药
        inventory = player.get_pills_inventory()
        inventory[pill_name] -= 1
        if inventory[pill_name] <= 0:
            del inventory[pill_name]
        player.set_pills_inventory(inventory)

        await self.db.update_player(player)

        return True, (
            f"✨ 服用【{pill_name}】成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🛡️ 你获得了起死回生的能力\n"
            f"下次死亡时将自动复活\n"
            f"（复活后所有属性减半）\n"
            f"━━━━━━━━━━━━━━━"
        )

    async def _use_temporary_pill(self, player: Player, pill_name: str, pill_data: dict) -> Tuple[bool, str]:
        """使用临时效果丹药"""
        duration_minutes = pill_data.get("duration_minutes", 60)
        current_time = int(time.time())
        expiry_time = current_time + duration_minutes * 60

        # 创建效果记录
        effect = {
            "pill_name": pill_name,
            "pill_id": pill_data.get("id", ""),
            "subtype": pill_data.get("subtype", ""),
            "start_time": current_time,
            "expiry_time": expiry_time,
            "duration_minutes": duration_minutes,
            "last_tick_time": current_time,
        }

        # 添加具体效果数据
        effect_keys = [
            "cultivation_multiplier", "physical_damage_multiplier", "magic_damage_multiplier",
            "physical_defense_multiplier", "magic_defense_multiplier",
            "lifespan_cost_per_minute", "lifespan_regen_per_minute",
            "spiritual_qi_regen_per_minute", "blood_qi_regen_per_minute", "blood_qi_cost_per_minute",
            "breakthrough_bonus", "temp_bonus_cap"
        ]
        for key in effect_keys:
            if key in pill_data:
                effect[key] = pill_data[key]

        # 添加到活跃效果
        effects = player.get_active_pill_effects()
        effects.append(effect)
        player.set_active_pill_effects(effects)

        # 扣除丹药
        inventory = player.get_pills_inventory()
        inventory[pill_name] -= 1
        if inventory[pill_name] <= 0:
            del inventory[pill_name]
        player.set_pills_inventory(inventory)

        await self.db.update_player(player)

        # 构建效果描述
        effect_desc = []
        if "cultivation_multiplier" in pill_data:
            mult = pill_data["cultivation_multiplier"]
            if mult > 0:
                effect_desc.append(f"修炼速度+{mult:.0%}")
            else:
                effect_desc.append(f"修炼速度{mult:.0%}")

        if "physical_damage_multiplier" in pill_data:
            mult = pill_data["physical_damage_multiplier"]
            if mult > 0:
                effect_desc.append(f"物伤+{mult:.0%}")
            else:
                effect_desc.append(f"物伤{mult:.0%}")

        if "magic_damage_multiplier" in pill_data:
            mult = pill_data["magic_damage_multiplier"]
            if mult > 0:
                effect_desc.append(f"法伤+{mult:.0%}")
            else:
                effect_desc.append(f"法伤{mult:.0%}")

        if "physical_defense_multiplier" in pill_data:
            mult = pill_data["physical_defense_multiplier"]
            if mult > 0:
                effect_desc.append(f"物防+{mult:.0%}")
            else:
                effect_desc.append(f"物防{mult:.0%}")

        if "magic_defense_multiplier" in pill_data:
            mult = pill_data["magic_defense_multiplier"]
            if mult > 0:
                effect_desc.append(f"法防+{mult:.0%}")
            else:
                effect_desc.append(f"法防{mult:.0%}")

        if "lifespan_cost_per_minute" in pill_data:
            cost = pill_data["lifespan_cost_per_minute"]
            effect_desc.append(f"每分钟扣除寿命-{cost}")

        if "lifespan_regen_per_minute" in pill_data:
            regen = pill_data["lifespan_regen_per_minute"]
            effect_desc.append(f"每分钟恢复寿命+{regen}")

        if "spiritual_qi_regen_per_minute" in pill_data:
            regen = pill_data["spiritual_qi_regen_per_minute"]
            effect_desc.append(f"每分钟恢复灵气+{regen}")

        if "blood_qi_regen_per_minute" in pill_data:
            regen = pill_data["blood_qi_regen_per_minute"]
            effect_desc.append(f"每分钟恢复气血+{regen}")

        if "blood_qi_cost_per_minute" in pill_data:
            cost = pill_data["blood_qi_cost_per_minute"]
            effect_desc.append(f"每分钟扣除气血-{cost}")

        if "breakthrough_bonus" in pill_data:
            bonus = pill_data["breakthrough_bonus"]
            if bonus > 0:
                effect_desc.append(f"突破成功率+{bonus:.0%}")
            else:
                effect_desc.append(f"突破成功率{bonus:.0%}")

        effects_str = "、".join(effect_desc) if effect_desc else "特殊效果"

        return True, (
            f"✨ 服用【{pill_name}】成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⏱️ 持续时间：{duration_minutes}分钟\n"
            f"🎯 效果：{effects_str}\n"
            f"━━━━━━━━━━━━━━━"
        )

    def _get_base_limit_ratio(self, permanent_gains: dict) -> float:
        """获取当前生效的「每境界永久增益上限比例」

        默认 30%（DEFAULT_BASE_LIMIT_RATIO）。洗髓丹/易筋丹的
        `base_attribute_limit_increase` 会以**倍率**形式提升该上限：
        例如洗髓丹 +0.05 表示上限从 30% 提升到 30% × 1.05。

        该加成存放在 permanent_pill_gains 顶层（BASE_LIMIT_KEY），
        因为它是对「上限」本身的全局提升，与具体境界分桶无关。
        """
        try:
            bonus = float(permanent_gains.get(self.BASE_LIMIT_KEY, 0) or 0)
        except (TypeError, ValueError):
            bonus = 0.0
        bonus = max(0.0, min(bonus, self.MAX_BASE_LIMIT_BONUS))
        return self.DEFAULT_BASE_LIMIT_RATIO * (1.0 + bonus)

    async def _use_permanent_pill(self, player: Player, pill_name: str, pill_data: dict) -> Tuple[bool, str]:
        """使用永久属性丹药"""
        # 检查境界限制（30%上限）
        permanent_gains = player.get_permanent_pill_gains()
        level_key = f"level_{player.level_index}"

        if level_key not in permanent_gains:
            permanent_gains[level_key] = {
                "physical_damage": 0,
                "magic_damage": 0,
                "physical_defense": 0,
                "magic_defense": 0,
                "mental_power": 0,
                "lifespan": 0,
                "max_spiritual_qi": 0,
                "max_blood_qi": 0,
            }

        # 计算基础属性（当前境界突破时获得的属性）
        base_attrs = self._get_base_attributes_for_level(player, player.level_index)

        # 当前生效的上限比例（洗髓丹/易筋丹可提升）
        limit_ratio = self._get_base_limit_ratio(permanent_gains)

        # 检查各项属性是否已达上限
        attr_mapping = {
            "physical_damage_gain": ("physical_damage", "物伤"),
            "magic_damage_gain": ("magic_damage", "法伤"),
            "physical_defense_gain": ("physical_defense", "物防"),
            "magic_defense_gain": ("magic_defense", "法防"),
            "mental_power_gain": ("mental_power", "精神力"),
            "lifespan_gain": ("lifespan", "寿命"),
            "max_spiritual_qi_gain": ("max_spiritual_qi", "最大灵气"),
            "max_blood_qi_gain": ("max_blood_qi", "最大气血"),
        }

        gains_applied = {}
        gains_blocked = {}

        # 百分比增益先按玩家当前属性折算成固定数值，再统一走下面的上限逻辑
        resolved_pill_data = self._resolve_percentage_gains(player, pill_data)

        for gain_key, (attr_key, attr_name) in attr_mapping.items():
            if gain_key not in resolved_pill_data:
                continue

            gain = resolved_pill_data[gain_key]
            try:
                gain = int(gain)
            except (TypeError, ValueError):
                continue
            if gain == 0:
                continue

            # 只有正向增益才受上限限制
            if gain > 0:
                current_gain = permanent_gains[level_key].get(attr_key, 0)
                base_value = base_attrs.get(attr_key, 100)  # 默认基础值100
                limit = base_value * limit_ratio  # 每境界上限（默认 30%，可被洗髓丹提升）

                if current_gain >= limit:
                    gains_blocked[attr_name] = f"已达上限({limit:.0f})"
                    continue

                # 计算实际可以增加的值
                actual_gain = min(gain, limit - current_gain)
                if int(actual_gain) <= 0:
                    # 剩余额度不足 1 点：不应用，避免展示「物伤 +0」这类无意义增益
                    gains_blocked[attr_name] = "本境界增益额度已不足"
                    continue
                if actual_gain < gain:
                    gains_blocked[attr_name] = f"部分受限(+{int(actual_gain)}/{gain})"

                # 应用增益
                permanent_gains[level_key][attr_key] += actual_gain
                setattr(player, attr_key, getattr(player, attr_key) + int(actual_gain))
                gains_applied[attr_name] = int(actual_gain)
            else:
                # 负向效果直接应用
                permanent_gains[level_key][attr_key] += gain
                setattr(player, attr_key, getattr(player, attr_key) + int(gain))
                gains_applied[attr_name] = int(gain)

        # 处理修炼倍率（永久）
        if "cultivation_multiplier" in pill_data:
            cult_mult = pill_data["cultivation_multiplier"]
            if "cultivation_multiplier" not in permanent_gains[level_key]:
                permanent_gains[level_key]["cultivation_multiplier"] = 0
            permanent_gains[level_key]["cultivation_multiplier"] += cult_mult
            gains_applied["修炼速度"] = f"{cult_mult:+.0%}"

        # 处理突破死亡概率降低
        if "death_protection_multiplier" in pill_data:
            death_mult = pill_data["death_protection_multiplier"]
            if "death_protection_multiplier" not in permanent_gains[level_key]:
                permanent_gains[level_key]["death_protection_multiplier"] = 1.0
            permanent_gains[level_key]["death_protection_multiplier"] *= death_mult
            gains_applied["突破死亡概率"] = f"降低{(1 - death_mult) * 100:.0f}%"

        # 处理「基础属性上限提升」（洗髓丹 / 易筋丹）
        # ⚠️ 这类丹药本身不提供任何属性增益，只提升「每境界永久增益的上限比例」，
        # 因此必须走独立分支：否则会被下面的 `if not gains_applied` 判定为
        # 「所有属性增益都已达到上限」而永远无法使用（此前即为此问题）。
        if "base_attribute_limit_increase" in pill_data:
            try:
                inc = float(pill_data.get("base_attribute_limit_increase") or 0)
            except (TypeError, ValueError):
                inc = 0.0
            if inc > 0:
                cur_bonus = float(permanent_gains.get(self.BASE_LIMIT_KEY, 0) or 0)
                new_bonus = min(cur_bonus + inc, self.MAX_BASE_LIMIT_BONUS)
                if new_bonus <= cur_bonus:
                    gains_blocked["基础属性上限"] = "已达上限"
                else:
                    permanent_gains[self.BASE_LIMIT_KEY] = new_bonus
                    new_ratio = self.DEFAULT_BASE_LIMIT_RATIO * (1.0 + new_bonus)
                    gains_applied["基础属性上限"] = (
                        f"{self.DEFAULT_BASE_LIMIT_RATIO:.0%} → {new_ratio:.1%}"
                    )

        if not gains_applied:
            return False, "该丹药的所有属性增益都已达到上限，无法使用！"

        # 修正属性下限与能量上限
        self._ensure_non_negative_attributes(player)

        # 更新玩家数据
        player.set_permanent_pill_gains(permanent_gains)

        # 扣除丹药
        inventory = player.get_pills_inventory()
        inventory[pill_name] -= 1
        if inventory[pill_name] <= 0:
            del inventory[pill_name]
        player.set_pills_inventory(inventory)

        await self.db.update_player(player)

        # 构建消息
        msg_parts = [
            f"✨ 服用【{pill_name}】成功！",
            "━━━━━━━━━━━━━━━",
            "💪 永久增益："
        ]
        for attr_name, value in gains_applied.items():
            if isinstance(value, int):
                msg_parts.append(f"  {attr_name} +{value}")
            else:
                msg_parts.append(f"  {attr_name} {value}")

        if gains_blocked:
            msg_parts.append("\n⚠️ 受限提示：")
            for attr_name, reason in gains_blocked.items():
                msg_parts.append(f"  {attr_name} {reason}")

        msg_parts.append("━━━━━━━━━━━━━━━")
        # 上限比例取「本次服用后」的实际值：洗髓丹/易筋丹会提升它
        msg_parts.append(
            f"注：每个境界的永久属性丹药\n"
            f"增益最多为基础属性的{limit_ratio:.0%}"
        )

        return True, "\n".join(msg_parts)

    async def _use_instant_pill(self, player: Player, pill_name: str, pill_data: dict) -> Tuple[bool, str]:
        """使用瞬间效果丹药"""
        msg_parts = [
            f"✨ 服用【{pill_name}】成功！",
            "━━━━━━━━━━━━━━━"
        ]

        # 恢复能量（灵气/气血）
        energy_restore = None
        energy_label = "灵气"
        current_energy = player.spiritual_qi
        max_energy = player.max_spiritual_qi

        # 体修优先使用专属气血恢复键；若无则复用灵气恢复作为气血恢复
        if player.cultivation_type == "体修" and "blood_qi_restore" in pill_data:
            energy_restore = pill_data["blood_qi_restore"]
            energy_label = "气血"
            current_energy = player.blood_qi
            max_energy = player.max_blood_qi
        elif "spiritual_qi_restore" in pill_data:
            energy_restore = pill_data["spiritual_qi_restore"]
            if player.cultivation_type == "体修":
                energy_label = "气血"
                current_energy = player.blood_qi
                max_energy = player.max_blood_qi

        if energy_restore is not None:
            if energy_restore == -1:
                # 恢复至满
                current_energy = max_energy
                actual_restore = max_energy
            else:
                old_energy = current_energy
                current_energy = min(current_energy + energy_restore, max_energy)
                actual_restore = current_energy - old_energy

            if energy_label == "气血":
                player.blood_qi = current_energy
                msg_parts.append(f"🌟 恢复气血：+{actual_restore}")
                msg_parts.append(f"🩸 当前气血：{player.blood_qi}/{player.max_blood_qi}")
            else:
                player.spiritual_qi = current_energy
                msg_parts.append(f"🌟 恢复灵气：+{actual_restore}")
                msg_parts.append(f"💫 当前灵气：{player.spiritual_qi}/{player.max_spiritual_qi}")

        # 重置永久丹药增益
        if pill_data.get("resets_permanent_pills"):
            reset_applied = self._reset_permanent_pill_effects(player)
            if reset_applied:
                msg_parts.append("🔄 已重置所有永久属性丹药增益")
                refund_ratio = pill_data.get("reset_refund_ratio", 0.5)
                refund = int(pill_data.get("price", 0) * refund_ratio)
                if refund > 0:
                    player.gold += refund
                    msg_parts.append(f"💰 返还灵石：{refund}")
            else:
                msg_parts.append("ℹ️ 当前没有可重置的永久增益")

        # 定魂丹 - 下一次负面效果免疫
        if pill_data.get("blocks_next_debuff"):
            if player.has_debuff_shield:
                msg_parts.append("🛡️ 定魂护盾已存在，无需重复使用")
            else:
                player.has_debuff_shield = True
                msg_parts.append("🛡️ 获得定魂护盾：下一次负面效果将被抵消")

        # 扣除丹药
        inventory = player.get_pills_inventory()
        inventory[pill_name] -= 1
        if inventory[pill_name] <= 0:
            del inventory[pill_name]
        player.set_pills_inventory(inventory)

        await self.db.update_player(player)

        msg_parts.append("━━━━━━━━━━━━━━━")
        return True, "\n".join(msg_parts)

    def _resolve_percentage_gains(self, player: Player, pill_data: dict) -> dict:
        """把「按玩家当前属性百分比生效」的增益折算为固定数值增益

        例：回元丹配置 max_spiritual_qi_gain_percent = 0.05，玩家当前最大灵气 2000
        → 折算为 max_spiritual_qi_gain = 100，随后仍受每境界 30% 上限约束。

        若同时配置了同名的固定增益键，两者相加（先百分比后叠加固定值）。
        """
        resolved = dict(pill_data)
        for pct_key, (attr_key, flat_key) in self.PERCENT_GAIN_KEYS.items():
            if pct_key not in resolved:
                continue
            try:
                ratio = float(resolved.get(pct_key) or 0)
            except (TypeError, ValueError):
                logger.warning(
                    f"丹药【{pill_data.get('name', '')}】的 {pct_key} 配置非法：{resolved.get(pct_key)}，已忽略"
                )
                continue

            current_value = getattr(player, attr_key, 0) or 0
            try:
                flat_value = int(resolved.get(flat_key, 0) or 0)
            except (TypeError, ValueError):
                flat_value = 0

            resolved[flat_key] = int(current_value * ratio) + flat_value
        return resolved

    def _get_base_attributes_for_level(self, player: Player, level_index: int) -> dict:
        """获取当前境界的基础属性（用于计算每境界永久增益上限）

        上限公式：`limit = 基础属性 × 上限比例`（比例默认 30%，可被洗髓丹提升）。
        「基础属性」= 该境界突破时各项属性的成长量。

        ⚠️ 两张境界表各自只带本系字段，导致跨系基准缺失、曾经回退到硬编码默认 100：
          - `level_config.json`（灵修）没有 `breakthrough_blood_qi_gain`
          - `body_level_config.json`（体修）没有 `breakthrough_spiritual_qi_gain`
          ⇒ 跨系那一路的上限只有 100×30% = 30 点，回元丹承诺的「+5% 气血/灵气」
            实际只给 +30（缩水约 98.5%）。
          - `body_level_config.json`（体修）的 `breakthrough_magic_damage_gain` 恒为 0
            ⇒ 体修法伤的上限为 0，宗门洗髓丹的法伤增益被完全阻断。

        下面按「本系主属性成长量」与「玩家当前属性值」做兜底，
        **不修改任何境界表配置**，因此突破收益完全不受影响。

        Args:
            player: 玩家对象，用于确定修炼类型
            level_index: 境界索引

        Returns:
            基础属性字典
        """
        level_data = self.config_manager.get_level_data(player.cultivation_type)
        # 兜底：如果数据为空，使用灵修配置避免索引错误
        if not level_data:
            level_data = self.config_manager.level_data

        # 越界保护
        if level_data:
            level_index = min(level_index, len(level_data) - 1)
            level_config = level_data[level_index]
        else:
            level_config = {}

        def _growth(key: str, default: int) -> int:
            """读取突破成长量；配置缺失时返回 0（区别于「显式为 0」）"""
            value = level_config.get(key)
            if value is None:
                return 0
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0

        spirit_growth = _growth("breakthrough_spiritual_qi_gain", 0)
        blood_growth = _growth("breakthrough_blood_qi_gain", 0)
        magic_damage_growth = _growth("breakthrough_magic_damage_gain", 0)

        # 跨系能量基准：本系若没有对方能量字段，则以本系主能量成长量作为基准
        # （灵修无 blood_qi 字段 → 用灵气成长量；体修无 spiritual_qi 字段 → 用气血成长量）
        max_spiritual_qi_base = spirit_growth or blood_growth
        max_blood_qi_base = blood_growth or spirit_growth

        # 某属性在本系「不随境界成长」时（成长量为 0 且已过境界 0），
        # 以玩家当前属性值作为上限基准，避免该属性的丹药增益被完全阻断。
        # 境界 0 保持基准为 0：此时突破成长量全为 0，永久丹药本就无额度可分配。
        def _fallback_to_current(attr_key: str, growth: int) -> int:
            if growth > 0 or level_index <= 0:
                return growth
            try:
                return int(getattr(player, attr_key, 0) or 0)
            except (TypeError, ValueError):
                return 0

        return {
            "physical_damage": _growth("breakthrough_physical_damage_gain", 10),
            "magic_damage": _fallback_to_current("magic_damage", magic_damage_growth),
            "physical_defense": _growth("breakthrough_physical_defense_gain", 5),
            "magic_defense": _growth("breakthrough_magic_defense_gain", 5),
            "mental_power": _growth("breakthrough_mental_power_gain", 100),
            "lifespan": _growth("breakthrough_lifespan_gain", 100),
            "max_spiritual_qi": max_spiritual_qi_base,
            "max_blood_qi": max_blood_qi_base,
        }

    async def handle_resurrection(self, player: Player) -> bool:
        """处理玩家死亡时的回生丹效果

        Args:
            player: 玩家对象

        Returns:
            是否成功复活
        """
        if not player.has_resurrection_pill:
            return False

        logger.info(f"玩家 {player.user_id} 触发回生丹效果")

        # 消耗回生丹效果
        player.has_resurrection_pill = False

        # 所有属性减半
        player.lifespan = player.lifespan // 2
        player.experience = player.experience // 2
        player.physical_damage = player.physical_damage // 2
        player.magic_damage = player.magic_damage // 2
        player.physical_defense = player.physical_defense // 2
        player.magic_defense = player.magic_defense // 2
        player.mental_power = player.mental_power // 2
        player.max_spiritual_qi = player.max_spiritual_qi // 2
        player.spiritual_qi = player.max_spiritual_qi // 2
        player.max_blood_qi = player.max_blood_qi // 2
        player.blood_qi = player.max_blood_qi // 2

        self._ensure_non_negative_attributes(player)

        await self.db.update_player(player)
        return True

    def calculate_pill_attribute_effects(self, player: Player) -> dict:
        """计算丹药对属性的影响（乘法加成）

        Args:
            player: 玩家对象

        Returns:
            属性乘法倍率字典
        """
        effects = player.get_active_pill_effects()
        current_time = int(time.time())
        multipliers = {
            "physical_damage": 1.0,
            "magic_damage": 1.0,
            "physical_defense": 1.0,
            "magic_defense": 1.0,
            "cultivation_speed": 1.0,
        }

        # 累加临时效果
        for effect in effects:
            expiry_time = effect.get("expiry_time", 0)
            if expiry_time > 0 and current_time >= expiry_time:
                continue
            if "physical_damage_multiplier" in effect:
                multipliers["physical_damage"] += effect["physical_damage_multiplier"]
            if "magic_damage_multiplier" in effect:
                multipliers["magic_damage"] += effect["magic_damage_multiplier"]
            if "physical_defense_multiplier" in effect:
                multipliers["physical_defense"] += effect["physical_defense_multiplier"]
            if "magic_defense_multiplier" in effect:
                multipliers["magic_defense"] += effect["magic_defense_multiplier"]
            if "cultivation_multiplier" in effect:
                multipliers["cultivation_speed"] += effect["cultivation_multiplier"]

        # 累加永久效果
        permanent_gains = player.get_permanent_pill_gains()
        level_key = f"level_{player.level_index}"
        if level_key in permanent_gains:
            level_gains = permanent_gains[level_key]
            if "cultivation_multiplier" in level_gains:
                multipliers["cultivation_speed"] += level_gains["cultivation_multiplier"]

        # 确保倍率不为负
        for key in multipliers:
            multipliers[key] = max(0.0, multipliers[key])

        return multipliers

    def get_breakthrough_modifiers(self, player: Player) -> dict:
        """获取突破时的临时与永久加成信息"""
        effects = player.get_active_pill_effects()
        current_time = int(time.time())
        temp_bonus = 0.0
        # 带上限的增益（如宗门破障丹）单独累计，避免"每日免费领 + 24h 持续"导致无限叠加，
        # 把突破这一核心风险闸门直接抹平。不带 temp_bonus_cap 的丹药（幸运丹/天命幸运丹等）
        # 完全走原累加逻辑，行为零变化。
        capped_bonus = 0.0
        capped_cap: Optional[float] = None
        has_temp_effects = False

        for effect in effects:
            expiry_time = effect.get("expiry_time", 0)
            if expiry_time > 0 and current_time >= expiry_time:
                continue

            subtype = effect.get("subtype", "")
            if subtype in {"breakthrough_boost", "breakthrough_debuff"}:
                bonus = effect.get("breakthrough_bonus", 0) or 0.0
                cap = effect.get("temp_bonus_cap") if subtype == "breakthrough_boost" else None
                if cap is not None:
                    try:
                        capped_bonus += float(bonus)
                        cap = float(cap)
                        capped_cap = cap if capped_cap is None else min(capped_cap, cap)
                    except (TypeError, ValueError):
                        temp_bonus += bonus
                else:
                    temp_bonus += bonus
                has_temp_effects = True

        # 带 cap 的增益夹紧到上限内（多颗叠加最多仍只到 cap）
        if capped_cap is not None:
            temp_bonus += min(capped_bonus, capped_cap)

        permanent_multiplier = 1.0
        permanent_gains = player.get_permanent_pill_gains()
        for level_gain in permanent_gains.values():
            # ⚠️ 顶层可能存在标量键（如 BASE_LIMIT_KEY 存 float），需跳过
            if not isinstance(level_gain, dict):
                continue
            permanent_multiplier *= level_gain.get("death_protection_multiplier", 1.0)

        return {
            "temp_bonus": temp_bonus,
            "has_temp_effects": has_temp_effects,
            "permanent_death_multiplier": max(0.0, min(1.0, permanent_multiplier)),
        }

    async def consume_breakthrough_effects(self, player: Player):
        """突破完成后移除相关临时丹药效果"""
        effects = player.get_active_pill_effects()
        remaining_effects = [
            effect for effect in effects
            if effect.get("subtype", "") not in {"breakthrough_boost", "breakthrough_debuff"}
        ]

        if len(remaining_effects) != len(effects):
            player.set_active_pill_effects(remaining_effects)
            await self.db.update_player(player)

    async def add_pill_to_inventory(self, player: Player, pill_name: str, count: int = 1):
        """添加丹药到背包

        Args:
            player: 玩家对象
            pill_name: 丹药名称
            count: 数量
        """
        inventory = player.get_pills_inventory()
        if pill_name in inventory:
            inventory[pill_name] += count
        else:
            inventory[pill_name] = count
        player.set_pills_inventory(inventory)
        await self.db.update_player(player)

    def get_pill_inventory_display(self, player: Player) -> str:
        """获取丹药背包显示文本

        Args:
            player: 玩家对象

        Returns:
            丹药背包的格式化文本
        """
        inventory = player.get_pills_inventory()
        if not inventory:
            return "你的丹药背包是空的！"

        lines = ["--- 丹药背包 ---"]
        for pill_name, count in inventory.items():
            pill_data = self.get_pill_by_name(pill_name)
            if pill_data:
                rank = pill_data.get("rank", "未知")
                lines.append(f"[{rank}] {pill_name} × {count}")
            else:
                lines.append(f"{pill_name} × {count}")

        lines.append("-" * 20)
        return "\n".join(lines)

    def _apply_periodic_effects(self, player: Player, effect: dict, current_time: int) -> bool:
        """根据时间自动结算持续恢复/扣减"""
        expiry_time = effect.get("expiry_time", 0)
        tick_limit = min(current_time, expiry_time) if expiry_time > 0 else current_time
        last_tick = effect.get("last_tick_time", effect.get("start_time", current_time))

        if tick_limit <= last_tick:
            return False

        elapsed_seconds = tick_limit - last_tick
        minutes = elapsed_seconds // 60
        if minutes <= 0:
            return False

        effect["last_tick_time"] = last_tick + minutes * 60
        changed = False

        if "lifespan_cost_per_minute" in effect:
            total_cost = effect["lifespan_cost_per_minute"] * minutes
            player.lifespan = max(0, player.lifespan - total_cost)
            changed = True

        if "lifespan_regen_per_minute" in effect:
            total_regen = effect["lifespan_regen_per_minute"] * minutes
            player.lifespan += total_regen
            changed = True

        if "spiritual_qi_regen_per_minute" in effect:
            total_qi = effect["spiritual_qi_regen_per_minute"] * minutes
            player.spiritual_qi = min(player.max_spiritual_qi, player.spiritual_qi + total_qi)
            changed = True

        if "blood_qi_regen_per_minute" in effect:
            total_blood = effect["blood_qi_regen_per_minute"] * minutes
            player.blood_qi = min(player.max_blood_qi, player.blood_qi + total_blood)
            changed = True

        if "blood_qi_cost_per_minute" in effect:
            total_cost = effect["blood_qi_cost_per_minute"] * minutes
            player.blood_qi = max(0, player.blood_qi - total_cost)
            changed = True

        if changed:
            self._ensure_non_negative_attributes(player)

        return changed

    def _reset_permanent_pill_effects(self, player: Player) -> bool:
        """清空永久丹药增益并回退属性"""
        permanent_gains = player.get_permanent_pill_gains()
        if not permanent_gains:
            return False

        attr_keys = [
            "physical_damage",
            "magic_damage",
            "physical_defense",
            "magic_defense",
            "mental_power",
            "lifespan",
            "max_spiritual_qi",
            "max_blood_qi",
        ]

        changed = False
        for gain_key, gain in permanent_gains.items():
            # ⚠️ 顶层可能存在非分桶的标量键（如 BASE_LIMIT_KEY 存的是 float），
            # 这里只处理 dict 类型的境界分桶，避免对 float 调用 .get() 抛异常。
            if not isinstance(gain, dict):
                continue
            for attr_key in attr_keys:
                value = gain.get(attr_key, 0)
                if value:
                    delta = int(value)
                    setattr(player, attr_key, getattr(player, attr_key) - delta)
                    changed = True

            if "cultivation_multiplier" in gain:
                gain["cultivation_multiplier"] = 0
            if "death_protection_multiplier" in gain:
                gain["death_protection_multiplier"] = 1.0

        # set_permanent_pill_gains({}) 会一并清掉基础属性上限提升，
        # 这符合「重置所有永久属性丹药效果」的语义（洗髓丹/易筋丹也属永久丹药）。
        player.set_permanent_pill_gains({})
        return changed
