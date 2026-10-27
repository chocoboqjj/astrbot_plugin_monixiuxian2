# managers/technique_manager.py
"""
功法合成系统管理器（v3.3.8）

设计要点（对应用户诉求「若干个功法残页合成随机功法」）：
- **残页合成**：消耗 N 枚「功法残页」随机合成一门功法。
- **品质概率**：普通功法（凡品/灵品/地品）概率高，高阶功法（天品/皇品/圣品/帝品/道品/仙品）
  概率低；消耗数量越多，品质下限越高、稀有机率越大。
- **保底**：无论怎么摇，产出品质**不会低于「保底品级」**（随消耗量提升），
  避免玩家花大价钱合成出垃圾。
- **少量可出高品质**：消耗 10+ 枚残页时，有概率摇出皇品及以上。

⚠️ 合成结果必须是 items.json 中真实存在的功法名（不得凭空造名），
   否则会产出「幽灵功法」——面板显示但装备链不认识。
"""

import random
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from ..models import Player

if TYPE_CHECKING:
    from ..data.data_manager import DataBase
    from ..config_manager import ConfigManager
    from ..core import StorageRingManager

__all__ = ["TechniqueManager"]


class TechniqueManager:
    """功法残页合成管理器"""

    # 合成消耗表：残页数量 → (保底品级, 品质权重, 灵石额外消耗)
    # 权重顺序：凡品 / 珍品 / 灵品 / 地品 / 天品 / 皇品 / 圣品 / 帝品 / 道品 / 仙品 / 混元先天
    # ⚠️ 品级顺序必须与项目既有「品级阶梯」一致（RANK_TIER）：
    #    珍品与灵品同级（tier=1），但命名不同 ⇒ 两者都保留在序列里，
    #    避免「珍品」功法（如不动明王经、北冥神功、九阳神功）被排除在合成池外。
    TIER_ORDER = ["凡品", "珍品", "灵品", "地品", "天品", "皇品", "圣品", "帝品", "道品", "仙品", "混元先天"]

    RECIPES = {
        1: {"pages": 1,  "floor": "凡品", "weights": [60, 20, 8, 4, 2, 0, 0, 0, 0, 0, 0], "gold": 0},
        2: {"pages": 2,  "floor": "凡品", "weights": [50, 22, 12, 8, 4, 0, 0, 0, 0, 0, 0], "gold": 500},
        3: {"pages": 3,  "floor": "珍品", "weights": [30, 32, 18, 12, 6, 2, 0, 0, 0, 0, 0], "gold": 2000},
        5: {"pages": 5,  "floor": "珍品", "weights": [15, 30, 25, 16, 9, 4, 1, 0, 0, 0, 0], "gold": 8000},
        8: {"pages": 8,  "floor": "灵品", "weights": [0, 15, 28, 27, 17, 9, 3, 1, 0, 0, 0], "gold": 30000},
        12: {"pages": 12, "floor": "地品", "weights": [0, 5, 20, 30, 24, 13, 5, 2, 1, 0, 0], "gold": 100000},
        18: {"pages": 18, "floor": "天品", "weights": [0, 0, 10, 25, 28, 20, 10, 5, 2, 0, 0], "gold": 300000},
        25: {"pages": 25, "floor": "皇品", "weights": [0, 0, 0, 12, 28, 30, 18, 8, 3, 1, 0], "gold": 800000},
        40: {"pages": 40, "floor": "圣品", "weights": [0, 0, 0, 0, 15, 30, 28, 17, 7, 2, 1], "gold": 2000000},
    }

    def __init__(self, db: "DataBase", config_manager: "ConfigManager" = None,
                 storage_ring_manager: "StorageRingManager" = None):
        self.db = db
        self.config_manager = config_manager
        self.storage_ring_manager = storage_ring_manager

    # ------------------------------------------------------------------
    # 功法池
    # ------------------------------------------------------------------
    def _technique_pool(self) -> Dict[str, List[dict]]:
        """按品级分组收集可合成的功法（items.json 里 type=功法）。

        ⚠️ 排除「混元先天」这一终局款（价格 5000 万）——
        它保留给终局档，不参与残页合成，避免低阶消耗就摇出至宝。
        """
        pool: Dict[str, List[dict]] = {t: [] for t in self.TIER_ORDER}
        if not self.config_manager:
            return pool

        items = self.config_manager.items_data
        for item in items.values():
            if not isinstance(item, dict):
                continue
            if item.get("type") != "功法":
                continue
            rank = item.get("rank", "凡品")
            if rank not in pool:
                continue
            if rank == "混元先天":
                continue
            pool[rank].append(item)
        return pool

    async def get_available_recipes(self, user_id: str) -> Tuple[bool, str]:
        """展示可用的合成配方"""
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"

        lines = [
            "📜 功法合成配方",
            "━━━━━━━━━━━━━━━",
            "",
            "消耗「功法残页」随机合成一门功法。",
            "残页越多，品质保底越高、稀有功法概率越大。",
            "",
        ]
        for pages, cfg in self.RECIPES.items():
            floor = cfg["floor"]
            top = self.TIER_ORDER[-1]
            lines.append(f"【{pages} 枚残页】保底 {floor} 品")
            mats = f"功法残页×{pages}"
            if cfg["gold"]:
                mats += f"、灵石 {cfg['gold']:,}"
            lines.append(f"  材料：{mats}")
            lines.append(f"  品质范围：{floor} ~ {top}")
            lines.append("")
        lines.append("使用 /合成功法 <残页数量> 开始合成")
        return True, "\n".join(lines)

    def _roll_tier(self, weights: List[int], floor: str) -> str:
        """按权重摇品质，并施加保底下限"""
        floor_idx = self.TIER_ORDER.index(floor) if floor in self.TIER_ORDER else 0
        # 保底：低于 floor 的权重清零
        eff = list(weights)
        for i in range(floor_idx):
            eff[i] = 0
        total = sum(eff)
        if total <= 0:
            return floor
        pick = random.randint(1, total)
        acc = 0
        for idx, w in enumerate(eff):
            acc += w
            if pick <= acc:
                return self.TIER_ORDER[idx]
        return floor

    async def craft_technique(
        self,
        user_id: str,
        pages: int = 1
    ) -> Tuple[bool, str, Optional[Dict]]:
        """合成功法。

        Args:
            user_id: 玩家 ID
            pages: 消耗的残页数量（自动向下取到合法档位）

        Returns:
            (是否成功, 消息, 结果数据)
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", None

        try:
            pages = int(pages)
        except (TypeError, ValueError):
            pages = 1
        if pages <= 0:
            pages = 1

        # 向下取到合法档位（不静默向上）
        valid_pages = sorted(self.RECIPES.keys())
        chosen = valid_pages[0]
        for p in valid_pages:
            if p <= pages:
                chosen = p
        cfg = self.RECIPES[chosen]
        actual_pages = cfg["pages"]
        required_gold = cfg["gold"]

        # 检查材料
        missing = []
        have_pages = 0
        if self.storage_ring_manager:
            have_pages = self.storage_ring_manager.get_item_count(player, "功法残页")
        else:
            have_pages = player.get_storage_ring_items().get("功法残页", 0)

        if have_pages < actual_pages:
            missing.append(f"功法残页（需要{actual_pages}，拥有{have_pages}）")
        if player.gold < required_gold:
            missing.append(f"灵石（需要{required_gold:,}，拥有{player.gold:,}）")

        if missing:
            return False, "❌ 材料不足！\n" + "\n".join(f"  · {m}" for m in missing), None

        # 扣除材料
        if self.storage_ring_manager:
            ok, _ = await self.storage_ring_manager.retrieve_item(player, "功法残页", actual_pages)
            if not ok:
                return False, "❌ 扣除功法残页失败！", None
        else:
            items = player.get_storage_ring_items()
            items["功法残页"] = items.get("功法残页", 0) - actual_pages
            if items["功法残页"] <= 0:
                del items["功法残页"]
            player.set_storage_ring_items(items)

        player.gold -= required_gold

        # 摇品质 → 摇具体功法
        tier = self._roll_tier(cfg["weights"], cfg["floor"])
        pool = self._technique_pool().get(tier, [])
        if not pool:
            # 该品质暂无可合成功法 ⇒ 退到该品质下有货的最高档
            for t in reversed(self.TIER_ORDER[: self.TIER_ORDER.index(tier) + 1]):
                if self._technique_pool().get(t):
                    tier = t
                    pool = self._technique_pool()[t]
                    break
        if not pool:
            await self.db.update_player(player)
            return False, "❌ 当前没有可用于合成的功法，请联系管理员！", None

        chosen_item = random.choice(pool)
        technique_name = chosen_item["name"]

        # 产出存入储物戒
        stored = False
        store_msg = ""
        if self.storage_ring_manager:
            ok, store_msg = await self.storage_ring_manager.store_item(player, technique_name, 1)
            stored = ok
        await self.db.update_player(player)

        cost_parts = [f"功法残页 -{actual_pages}"]
        if required_gold:
            cost_parts.append(f"灵石 -{required_gold:,}")

        if not stored:
            return True, (
                f"🎲 合成完成！但储物戒已满，无法放入【{technique_name}】。\n"
                f"{store_msg}\n消耗：{'、'.join(cost_parts)}"
            ), {"success": True, "name": technique_name, "rank": tier, "stored": False}

        return True, (
            f"🎲 合成成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"你合成出【{technique_name}】（{tier}）！\n"
            f"已存入储物戒\n\n"
            f"消耗：{'、'.join(cost_parts)}\n"
            f"保底品级：{cfg['floor']}"
        ), {"success": True, "name": technique_name, "rank": tier, "stored": True}
