# managers/forge_manager.py
"""
炼器系统管理器 - 处理装备打造、精炼升星（v3.3.3）

设计要点：
- 打造：照搬炼丹流程（查配方 → 查境界 → 查材料 → 扣材料 → 成功率判定 → 产出入储物戒）。
  产出是装备/法器，直接存入储物戒供玩家装备。
- 精炼升星：消耗灵石 + 精铁（高阶额外消耗紫金沙）提升已有装备的精炼星数，
  每星按 forge_config.refine.per_star_bonus 提升装备攻防，是孤儿材料的核心消耗出口。
"""

import random
from typing import Tuple, Dict, Optional, List, TYPE_CHECKING
from ..models import Player

if TYPE_CHECKING:
    from ..data.data_manager import DataBase
    from ..config_manager import ConfigManager
    from ..core import StorageRingManager


class ForgeManager:
    """炼器系统管理器（打造 + 精炼）"""

    def __init__(self, db: "DataBase", config_manager: "ConfigManager" = None, storage_ring_manager: "StorageRingManager" = None):
        self.db = db
        self.config_manager = config_manager
        self.storage_ring_manager = storage_ring_manager
        self.config = config_manager.forge_config if config_manager else {}
        self.refine_config = self.config.get("refine", {}) if self.config else {}

        raw_recipes = {}
        if config_manager and hasattr(config_manager, "forge_recipes") and config_manager.forge_recipes:
            raw_recipes = config_manager.forge_recipes

        self.recipes = {}
        for recipe in raw_recipes.values():
            if isinstance(recipe, dict) and recipe.get("id"):
                recipe_id = int(recipe["id"])
                self.recipes[recipe_id] = self._normalize_recipe(recipe_id, recipe)

    # ------------------------------------------------------------------
    # 配方
    # ------------------------------------------------------------------
    def _normalize_recipe(self, recipe_id: int, recipe: Dict) -> Dict:
        """标准化配方字段"""
        name = recipe.get("name", f"装备{recipe_id}")
        desc = recipe.get("desc", "")
        if not desc:
            desc = f"消耗材料打造【{name}】"
        return {
            "id": recipe.get("id", recipe_id),
            "name": name,
            "level_required": recipe.get("level_required", 0),
            "materials": recipe.get("materials", {}),
            "success_rate": recipe.get("success_rate", 50),
            "desc": desc,
        }

    def _get_equipment_config(self, name: str) -> Optional[Dict]:
        """从武器/物品配置中获取装备信息（用于校验产出真实存在）"""
        if not self.config_manager:
            return None
        if name in self.config_manager.weapons_data:
            return self.config_manager.weapons_data[name]
        if name in self.config_manager.items_data:
            return self.config_manager.items_data[name]
        return None

    async def get_available_recipes(self, user_id: str) -> Tuple[bool, str]:
        """获取可打造的配方列表"""
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"

        available = [r for r in self.recipes.values() if player.level_index >= r["level_required"]]
        if not available:
            return False, "❌ 你当前境界无法打造任何装备！"

        msg = "⚒️ 炼器配方\n"
        msg += "━━━━━━━━━━━━━━━\n\n"
        for r in available:
            mats = ", ".join(f"{k}×{v}" for k, v in r["materials"].items())
            msg += f"【{r['name']}】(ID:{r['id']})\n"
            msg += f"  需求境界：Lv.{r['level_required']}\n"
            msg += f"  材料：{mats}\n"
            msg += f"  成功率：{r['success_rate']}%\n\n"
        msg += "使用 /炼器 <配方ID> 开始打造"
        return True, msg

    # ------------------------------------------------------------------
    # 打造
    # ------------------------------------------------------------------
    async def forge_equipment(
        self, user_id: str, recipe_id: int
    ) -> Tuple[bool, str, Optional[Dict]]:
        """打造装备"""
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", None

        # 打造为瞬时操作，不受闭关/历练/秘境影响

        if recipe_id not in self.recipes:
            return False, "❌ 无效的配方ID！", None

        recipe = self.recipes[recipe_id]

        if player.level_index < recipe["level_required"]:
            return False, f"❌ 打造【{recipe['name']}】需要达到境界等级 {recipe['level_required']}！", None

        # 校验产出装备真实存在
        equip_cfg = self._get_equipment_config(recipe["name"])
        if not equip_cfg:
            return False, f"❌ 配方产出【{recipe['name']}】在装备库中不存在，请联系管理员！", None

        # 检查材料（灵石 + 储物戒材料）
        materials = recipe["materials"]
        missing = []

        required_gold = materials.get("灵石", 0)
        if player.gold < required_gold:
            missing.append(f"灵石（需要{required_gold}，拥有{player.gold}）")

        if self.storage_ring_manager:
            for mat_name, cnt in materials.items():
                if mat_name == "灵石":
                    continue
                have = self.storage_ring_manager.get_item_count(player, mat_name)
                if have < cnt:
                    missing.append(f"{mat_name}（需要{cnt}，拥有{have}）")
        else:
            pass  # 兼容旧逻辑

        if missing:
            return False, "❌ 材料不足！\n" + "\n".join(f"  · {m}" for m in missing), None

        # 扣除灵石与材料
        player.gold -= required_gold
        consumed = []
        if self.storage_ring_manager:
            for mat_name, cnt in materials.items():
                if mat_name == "灵石":
                    continue
                success, _ = await self.storage_ring_manager.retrieve_item(player, mat_name, cnt)
                if success:
                    consumed.append(f"{mat_name}×{cnt}")

        # 成功率判定（每高一级境界 +2%，上限 95%）
        base_rate = recipe["success_rate"]
        level_bonus = (player.level_index - recipe["level_required"]) * 2
        final_rate = min(95, base_rate + level_bonus)
        is_success = random.randint(1, 100) <= final_rate

        cost_lines = []
        if required_gold > 0:
            cost_lines.append(f"灵石 -{required_gold}")
        cost_lines.extend(consumed)
        cost_str = "、".join(cost_lines) if cost_lines else "无"

        if is_success:
            # 产出存入储物戒
            success_store, store_msg = await self.storage_ring_manager.store_item(player, recipe["name"], 1)
            await self.db.update_player(player)
            if not success_store:
                # 储物戒满：材料已扣，装备退回为提示（不重复扣）
                return True, (
                    f"🎉 打造成功！但储物戒已满，无法放入【{recipe['name']}】。\n"
                    f"{store_msg}\n消耗：{cost_str}"
                ), {"success": True, "name": recipe["name"], "stored": False}

            rank = equip_cfg.get("rank", "")
            return True, (
                f"🎉 打造成功！\n━━━━━━━━━━━━━━━\n"
                f"你成功打造了【{recipe['name']}】（{rank}）！\n"
                f"已存入储物戒\n\n消耗：{cost_str}\n成功率：{final_rate}%"
            ), {"success": True, "name": recipe["name"], "stored": True}
        else:
            await self.db.update_player(player)
            return True, (
                f"💔 打造失败\n━━━━━━━━━━━━━━━\n"
                f"打造【{recipe['name']}】失败了...\n材料已消耗\n消耗：{cost_str}\n成功率：{final_rate}%\n再接再厉！"
            ), {"success": False, "name": recipe["name"]}

    # ------------------------------------------------------------------
    # 精炼升星
    # ------------------------------------------------------------------
    def _calc_refine_cost(self, current_star: int) -> Dict[str, int]:
        """计算精炼到第 current_star+1 星的消耗（灵石 + 精铁 + 高阶紫金沙）"""
        gold_base = self.refine_config.get("gold_base", 500)
        gold_step = self.refine_config.get("gold_step", 500)
        gold = gold_base + gold_step * current_star

        cost: Dict[str, int] = {}
        for mat, base in self.refine_config.get("material_base", {"精铁": 1}).items():
            step = self.refine_config.get("material_step", {}).get(mat, 0)
            cost[mat] = base + step * current_star

        # 高阶精炼额外消耗紫金沙
        premium = self.refine_config.get("premium_material", "紫金沙")
        premium_from = self.refine_config.get("premium_from_star", 6)
        premium_step = self.refine_config.get("premium_step", 1)
        new_star = current_star + 1
        if new_star >= premium_from:
            cost[premium] = premium_step * (new_star - premium_from + 1)

        cost["灵石"] = gold
        return cost

    def _refine_success_rate(self, current_star: int) -> int:
        """精炼成功率（随星数递减，有下限）"""
        base = self.refine_config.get("base_success_rate", 85)
        penalty = self.refine_config.get("star_penalty", 5)
        floor = self.refine_config.get("min_success_rate", 20)
        return max(floor, base - penalty * current_star)

    def _owns_item(self, player: Player, item_name: str) -> bool:
        """玩家是否拥有该装备（已装备 或 在储物戒中）"""
        if player.weapon == item_name or player.armor == item_name or player.main_technique == item_name:
            return True
        if item_name in player.get_techniques_list():
            return True
        if self.storage_ring_manager and self.storage_ring_manager.has_item(player, item_name, 1):
            return True
        return False

    async def refine_equipment(
        self, user_id: str, item_name: str
    ) -> Tuple[bool, str, Optional[Dict]]:
        """精炼升星某装备"""
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", None

        item_name = (item_name or "").strip()
        if not item_name:
            return False, "❌ 请输入要精炼的装备名称。\n💡 使用 /精炼 <装备名>", None

        # 校验装备真实存在
        equip_cfg = self._get_equipment_config(item_name)
        if not equip_cfg:
            return False, f"❌ 未找到装备【{item_name}】，无法精炼！", None

        # 必须拥有
        if not self._owns_item(player, item_name):
            return False, f"❌ 你并未拥有【{item_name}】，无法精炼！", None

        max_level = self.refine_config.get("max_level", 10)
        current_star = await self.db.get_refine_level(user_id, item_name)
        if current_star >= max_level:
            return False, f"❌ 【{item_name}】已达精炼上限（{max_level}★）！", None

        # 计算消耗并检查
        cost = self._calc_refine_cost(current_star)
        missing = []
        required_gold = cost.get("灵石", 0)
        if player.gold < required_gold:
            missing.append(f"灵石（需要{required_gold}，拥有{player.gold}）")
        if self.storage_ring_manager:
            for mat_name, cnt in cost.items():
                if mat_name == "灵石":
                    continue
                have = self.storage_ring_manager.get_item_count(player, mat_name)
                if have < cnt:
                    missing.append(f"{mat_name}（需要{cnt}，拥有{have}）")
        if missing:
            return False, "❌ 精炼材料不足！\n" + "\n".join(f"  · {m}" for m in missing), None

        # 扣除
        player.gold -= required_gold
        consumed = []
        if self.storage_ring_manager:
            for mat_name, cnt in cost.items():
                if mat_name == "灵石":
                    continue
                success, _ = await self.storage_ring_manager.retrieve_item(player, mat_name, cnt)
                if success:
                    consumed.append(f"{mat_name}×{cnt}")

        rate = self._refine_success_rate(current_star)
        is_success = random.randint(1, 100) <= rate

        cost_lines = []
        if required_gold > 0:
            cost_lines.append(f"灵石 -{required_gold}")
        cost_lines.extend(consumed)
        cost_str = "、".join(cost_lines) if cost_lines else "无"

        if is_success:
            new_star = current_star + 1
            await self.db.set_refine_level(user_id, item_name, new_star)
            await self.db.update_player(player)
            bonus_pct = int(new_star * self.refine_config.get("per_star_bonus", 0.10) * 100)
            return True, (
                f"✨ 精炼成功！\n━━━━━━━━━━━━━━━\n"
                f"【{item_name}】精炼至 {new_star}★\n"
                f"攻防提升约 {bonus_pct}%\n\n消耗：{cost_str}\n成功率：{rate}%"
            ), {"success": True, "name": item_name, "star": new_star}
        else:
            await self.db.update_player(player)
            return True, (
                f"💔 精炼失败\n━━━━━━━━━━━━━━━\n"
                f"【{item_name}】精炼失败，星数不变（当前 {current_star}★）。\n材料已消耗\n消耗：{cost_str}\n成功率：{rate}%\n再接再厉！"
            ), {"success": False, "name": item_name, "star": current_star}
