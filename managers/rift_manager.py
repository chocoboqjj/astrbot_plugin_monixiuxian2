# managers/rift_manager.py
"""
秘境系统管理器 - 处理秘境探索、奖励等逻辑
"""

import random
import time
from typing import Tuple, List, Optional, Dict, TYPE_CHECKING
from ..data.data_manager import DataBase
from ..models_extended import Rift, UserStatus
from ..models import Player

if TYPE_CHECKING:
    from ..core import StorageRingManager


class RiftManager:
    """秘境系统管理器"""
    
    # 默认秘境探索时长（秒）
    DEFAULT_DURATION = 1800
    
    # 秘境物品掉落表（按秘境等级分组）
    RIFT_DROP_TABLE = {
        1: [  # 低级秘境
            {"name": "灵草", "weight": 40, "min": 2, "max": 5},
            {"name": "精铁", "weight": 30, "min": 1, "max": 3},
            {"name": "灵石碎片", "weight": 30, "min": 3, "max": 8},
        ],
        2: [  # 中级秘境
            {"name": "灵草", "weight": 30, "min": 3, "max": 7},
            {"name": "精铁", "weight": 25, "min": 2, "max": 4},
            {"name": "灵兽毛皮", "weight": 20, "min": 1, "max": 3},
            {"name": "功法残页", "weight": 15, "min": 1, "max": 1},
            {"name": "秘境精华", "weight": 10, "min": 1, "max": 2},
        ],
        3: [  # 高级秘境
            {"name": "精铁", "weight": 25, "min": 3, "max": 6},
            {"name": "星辰石", "weight": 20, "min": 2, "max": 4},
            {"name": "灵兽内丹", "weight": 20, "min": 1, "max": 2},
            {"name": "功法残页", "weight": 20, "min": 1, "max": 2},
            {"name": "天材地宝", "weight": 15, "min": 1, "max": 1},
        ],
    }
    
    # 秘境稀有丹药掉落表（按秘境等级分组，低概率掉落通用增益丹）
    RIFT_PILL_DROP_TABLE = {
        1: [  # 低级秘境 - 3%概率掉落
            {"name": "三品凝神增益丹", "weight": 100, "min": 1, "max": 1},
        ],
        2: [  # 中级秘境 - 5%概率掉落
            {"name": "三品凝神增益丹", "weight": 50, "min": 1, "max": 1},
            {"name": "四品破境增益丹", "weight": 40, "min": 1, "max": 1},
            {"name": "五品渡劫增益丹", "weight": 10, "min": 1, "max": 1},
        ],
        3: [  # 高级秘境 - 10%概率掉落
            {"name": "四品破境增益丹", "weight": 40, "min": 1, "max": 1},
            {"name": "五品渡劫增益丹", "weight": 30, "min": 1, "max": 1},
            {"name": "六品破境增益丹", "weight": 20, "min": 1, "max": 1},
            {"name": "七品化神增益丹", "weight": 10, "min": 1, "max": 1},
        ],
    }
    
    # 秘境丹药掉落概率（百分比）
    RIFT_PILL_DROP_CHANCE = {
        1: 3,   # 低级秘境 3%
        2: 5,   # 中级秘境 5%
        3: 10,  # 高级秘境 10%
    }
    
    def __init__(self, db: DataBase, config_manager=None, storage_ring_manager: "StorageRingManager" = None):
        self.db = db
        self.config_manager = config_manager
        self.storage_ring_manager = storage_ring_manager
        self.config = config_manager.rift_config if config_manager else {}
        self.explore_duration = self.config.get("default_duration", self.DEFAULT_DURATION)
    
    def _get_level_name(self, level_index: int) -> str:
        """获取境界名称"""
        if self.config_manager and hasattr(self.config_manager, 'level_data'):
            if 0 <= level_index < len(self.config_manager.level_data):
                return self.config_manager.level_data[level_index].get("level_name", f"境界{level_index}")
        # 默认境界名称
        level_names = ["炼气期一层", "炼气期二层", "炼气期三层", "炼气期四层", "炼气期五层",
                       "炼气期六层", "炼气期七层", "炼气期八层", "炼气期九层", "炼气期十层",
                       "筑基期初期", "筑基期中期", "筑基期后期", "金丹期初期", "金丹期中期", "金丹期后期"]
        if 0 <= level_index < len(level_names):
            return level_names[level_index]
        return f"境界{level_index}"
    
    async def list_rifts(self) -> Tuple[bool, str]:
        """
        列出所有秘境
        
        Returns:
            (成功标志, 消息)
        """
        rifts = await self.db.ext.get_all_rifts()
        
        if not rifts:
            return False, "❌ 当前没有开放的秘境！"
        
        msg = "🌀 秘境列表\n"
        msg += "━━━━━━━━━━━━━━━\n"
        
        for rift in rifts:
            rewards_dict = rift.get_rewards()
            exp_range = rewards_dict.get("exp", [0, 0])
            gold_range = rewards_dict.get("gold", [0, 0])
            level_name = self._get_level_name(rift.required_level)
            
            msg += f"【{rift.rift_name}】(ID:{rift.rift_id})\n"
            if rift.required_level == 0:
                msg += f"  等级要求：无限制\n"
            else:
                msg += f"  等级要求：{level_name} 及以上\n"
            msg += f"  修为奖励：{exp_range[0]:,}-{exp_range[1]:,}\n"
            msg += f"  灵石奖励：{gold_range[0]:,}-{gold_range[1]:,}\n\n"
        
        msg += "💡 使用 /探索秘境 <ID> 进入（如：/探索秘境 1）"
        
        return True, msg
    
    async def enter_rift(
        self,
        user_id: str,
        rift_id: int
    ) -> Tuple[bool, str]:
        """
        进入秘境
        
        Args:
            user_id: 用户ID
            rift_id: 秘境ID
            
        Returns:
            (成功标志, 消息)
        """
        # 1. 检查用户
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        
        # 2. 只检查「同类活动」是否已在进行；闭关/历练可与秘境并存
        if await self._is_exploring(user_id):
            return False, "❌ 你已在探索秘境中，请勿重复开始！"
        
        # 3. 检查秘境
        rift = await self.db.ext.get_rift_by_id(rift_id)
        if not rift:
            return False, "❌ 秘境不存在！使用 /秘境列表 查看可用秘境"
        
        # 4. 检查境界要求
        if player.level_index < rift.required_level:
            level_name = self._get_level_name(rift.required_level)
            return False, f"❌ 探索【{rift.rift_name}】需要达到【{level_name}】！"
        
        # 5. 设置探索状态，存储秘境ID
        scheduled_time = int(time.time()) + self.explore_duration
        extra_data = {"rift_id": rift_id, "rift_level": rift.rift_level}
        # 写入独立活动槽位（与闭关/历练互不覆盖）
        await self._set_activity(user_id, "rift", scheduled_time, extra_data)
        
        return True, f"✨ 你进入了『{rift.rift_name}』！探索需要 {self.explore_duration//60} 分钟。\n使用 /完成探索 领取奖励"
    
    async def finish_exploration(
        self,
        user_id: str
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        完成秘境探索
        
        Args:
            user_id: 用户ID
            
        Returns:
            (成功标志, 消息, 奖励数据)
        """
        # 1. 检查用户
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", None
        
        # 2. 检查秘境活动状态
        activity = await self._get_activity(user_id, "rift")
        if not activity:
            return False, "❌ 你当前不在探索秘境！", None
        
        # 3. 检查时间
        current_time = int(time.time())
        if current_time < activity["scheduled_time"]:
            remaining = activity["scheduled_time"] - current_time
            minutes = remaining // 60
            return False, f"❌ 探索尚未完成！还需要 {minutes} 分钟。", None
        
        # 4. 获取秘境信息（从extra_data中读取）
        extra_data = activity.get("extra_data") or {}
        rift_id = extra_data.get("rift_id", 0)
        rift_level = extra_data.get("rift_level", 1)
        
        # 获取秘境配置
        rift = await self.db.ext.get_rift_by_id(rift_id) if rift_id else None
        rift_name = rift.rift_name if rift else "未知秘境"
        
        # 5. 根据秘境配置计算奖励
        if rift:
            rewards_config = rift.get_rewards()
            exp_range = rewards_config.get("exp", [1000, 5000])
            gold_range = rewards_config.get("gold", [500, 2000])
            exp_reward = random.randint(exp_range[0], exp_range[1])
            gold_reward = random.randint(gold_range[0], gold_range[1])
            rift_level = rift.rift_level
        else:
            # 兼容旧数据，使用默认奖励
            exp_reward = random.randint(1000, 5000)
            gold_reward = random.randint(500, 2000)
        
        # 随机事件
        events = [
            {"desc": "你发现了一处灵泉，修为大增！", "item_chance": 70},
            {"desc": "你在秘境中击败了一只妖兽！", "item_chance": 80},
            {"desc": "你找到了一个隐藏的宝箱！", "item_chance": 100},
            {"desc": "你领悟了一些修炼心得。", "item_chance": 40},
            {"desc": "你在秘境中遇到了前辈留下的传承！", "item_chance": 90}
        ]
        event = random.choice(events)
        
        # 6. 物品掉落（根据秘境等级）
        dropped_items = []
        item_msg = ""
        roll_msg = ""
        dropped_items, roll_msg = await self._roll_rift_drops(
            player, rift_level, event["item_chance"]
        )
        if dropped_items:
            item_lines = []
            for item_name, count in dropped_items:
                # 检查是否为丹药，丹药存入丹药背包，其他存入储物戒
                is_pill = self._is_pill_item(item_name)
                if is_pill:
                    # 存入丹药背包
                    inventory = player.get_pills_inventory()
                    inventory[item_name] = inventory.get(item_name, 0) + count
                    player.set_pills_inventory(inventory)
                    item_lines.append(f"  · {item_name} x{count}（丹药背包）")
                elif self.storage_ring_manager:
                    success, _ = await self.storage_ring_manager.store_item(player, item_name, count, silent=True)
                    if success:
                        item_lines.append(f"  · {item_name} x{count}")
                    else:
                        item_lines.append(f"  · {item_name} x{count}（储物戒已满，丢失）")
                else:
                    item_lines.append(f"  · {item_name} x{count}（无法存储）")
            if item_lines:
                item_msg = "\n\n📦 获得物品：\n" + "\n".join(item_lines)
        
        # 7. 应用奖励
        player.experience += exp_reward
        player.gold += gold_reward
        await self.db.update_player(player)
        
        # 8. 清除秘境活动槽位（不影响并行中的闭关/历练）
        await self._clear_activity(user_id, "rift")
        
        # 概率判定说明块（概率透明）
        roll_block = ""
        if roll_msg:
            roll_block = f"\n\n🎰 命数判定：\n{roll_msg}"
        
        msg = f"""
🌀 探索完成 - {rift_name}
━━━━━━━━━━━━━━━

{event["desc"]}

获得修为：+{exp_reward:,}
获得灵石：+{gold_reward:,}{item_msg}
{roll_block}        """.strip()
        
        reward_data = {
            "exp": exp_reward,
            "gold": gold_reward,
            "event": event["desc"],
            "items": dropped_items,
            "rift_name": rift_name
        }
        
        return True, msg, reward_data
    
    async def exit_rift(self, user_id: str) -> Tuple[bool, str]:
        """
        退出秘境（放弃探索）
        
        Args:
            user_id: 用户ID
            
        Returns:
            (成功标志, 消息)
        """
        # 1. 检查用户
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        
        # 2. 检查秘境活动状态
        activity = await self._get_activity(user_id, "rift")
        if not activity:
            return False, "❌ 你当前不在探索秘境！"
        
        # 3. 清除秘境活动槽位（不影响并行中的闭关/历练）
        await self._clear_activity(user_id, "rift")
        
        return True, "✅ 你已退出秘境，本次探索未获得任何奖励。"
    
    # ===== 活动槽位（与闭关/历练独立并存）=====

    def _activity_mgr(self):
        """获取多活动管理器（未注入时返回 None）"""
        return getattr(self.db, "activity_mgr", None)

    async def _is_exploring(self, user_id: str) -> bool:
        """是否正在探索秘境"""
        mgr = self._activity_mgr()
        if mgr is None:
            cd = await self.db.ext.get_user_cd(user_id)
            return bool(cd and cd.type == UserStatus.EXPLORING)
        return await mgr.is_active(user_id, "rift")

    async def _get_activity(self, user_id: str, activity_type: str) -> Optional[dict]:
        """读取活动槽位（降级到旧 user_cd）"""
        mgr = self._activity_mgr()
        if mgr is not None:
            return await mgr.get(user_id, activity_type)
        cd = await self.db.ext.get_user_cd(user_id)
        legacy_map = {"cultivation": 1, "adventure": 2, "rift": 3}
        if not cd or cd.type != legacy_map.get(activity_type):
            return None
        extra = {}
        if hasattr(cd, "get_extra_data"):
            extra = cd.get_extra_data()
        return {
            "create_time": cd.create_time,
            "scheduled_time": cd.scheduled_time,
            "extra_data": extra,
        }

    async def _set_activity(self, user_id: str, activity_type: str,
                            scheduled_time: int, extra: dict):
        """写入活动槽位（降级到旧 user_cd）"""
        mgr = self._activity_mgr()
        if mgr is not None:
            await mgr.start(user_id, activity_type, scheduled_time, extra)
            return
        legacy_map = {"cultivation": 1, "adventure": 2, "rift": 3}
        await self.db.ext.set_user_busy(
            user_id, legacy_map.get(activity_type, 3), scheduled_time, extra_data=extra
        )

    async def _clear_activity(self, user_id: str, activity_type: str):
        """清除活动槽位（降级到旧 user_cd）"""
        mgr = self._activity_mgr()
        if mgr is not None:
            await mgr.finish(user_id, activity_type)
            return
        await self.db.ext.set_user_free(user_id)

    def _is_pill_item(self, item_name: str) -> bool:
        """检查物品是否为丹药"""
        if self.config_manager and hasattr(self.config_manager, 'is_pill'):
            return self.config_manager.is_pill(item_name)
        return False
    
    def _get_rift_level_by_player(self, player: Player) -> int:
        """根据玩家境界确定秘境等级"""
        level_index = player.level_index
        if level_index <= 5:
            return 1  # 低级秘境
        elif level_index <= 12:
            return 2  # 中级秘境
        else:
            return 3  # 高级秘境
    
    async def _roll_rift_drops(
        self, player: Player, rift_level: int, item_chance: int
    ) -> Tuple[List[Tuple[str, int]], str]:
        """
        根据秘境等级随机掉落物品

        Args:
            player: 玩家对象
            rift_level: 秘境等级 (1-3)
            item_chance: 掉落概率

        Returns:
            (掉落物品列表 [(物品名, 数量), ...], 概率判定说明文本)
        """
        from ..utils.probability import describe_roll

        dropped_items = []
        roll_lines = []
        
        # 检查是否触发物品掉落
        hit_item = random.randint(1, 100) <= item_chance
        if not hit_item:
            roll_lines.append(describe_roll("物品掉落", item_chance, False))
            # 稀有丹药判定仍需进行（低概率）
            pill_drops, pill_roll = self._roll_pill_drops(rift_level)
            if pill_drops:
                dropped_items.extend(pill_drops)
            if pill_roll:
                roll_lines.append(pill_roll)
            return dropped_items, "\n".join(roll_lines)
        
        # 获取对应等级的掉落表
        drop_table = self.RIFT_DROP_TABLE.get(rift_level, self.RIFT_DROP_TABLE[1])
        
        # 加权随机选择物品（秘境保证至少掉落1件）
        total_weight = sum(item["weight"] for item in drop_table)
        roll = random.randint(1, total_weight)
        
        current_weight = 0
        for item in drop_table:
            current_weight += item["weight"]
            if roll <= current_weight:
                count = random.randint(item["min"], item["max"])
                dropped_items.append((item["name"], count))
                break
        
        # 高级秘境有50%概率额外掉落一件
        extra_chance = 50 if rift_level >= 2 else 0
        extra_hit = False
        if extra_chance and random.randint(1, 100) <= extra_chance:
            extra_hit = True
            roll = random.randint(1, total_weight)
            current_weight = 0
            for item in drop_table:
                current_weight += item["weight"]
                if roll <= current_weight:
                    count = random.randint(item["min"], item["max"])
                    dropped_items.append((item["name"], count))
                    break
            roll_lines.append(describe_roll("额外掉落", extra_chance, True))
        elif extra_chance:
            roll_lines.append(describe_roll("额外掉落", extra_chance, False))
        
        # 稀有丹药掉落检测
        pill_drops, pill_roll = self._roll_pill_drops(rift_level)
        if pill_drops:
            dropped_items.extend(pill_drops)
        if pill_roll:
            roll_lines.append(pill_roll)
        
        result_text = ""
        if dropped_items:
            result_text = f"{dropped_items[0][0]} x{dropped_items[0][1]}"
        roll_lines.insert(
            0, describe_roll("物品掉落", item_chance, True, result_text=result_text)
        )
        return dropped_items, "\n".join(roll_lines)
    
    def _roll_pill_drops(self, rift_level: int) -> Tuple[List[Tuple[str, int]], str]:
        """
        根据秘境等级随机掉落稀有丹药
        
        Args:
            rift_level: 秘境等级 (1-3)
            
        Returns:
            (掉落丹药列表 [(物品名, 数量), ...], 概率判定说明文本)
        """
        from ..utils.probability import describe_roll

        dropped_pills = []
        
        # 获取丹药掉落概率
        pill_chance = self.RIFT_PILL_DROP_CHANCE.get(rift_level, 3)
        
        # 检查是否触发丹药掉落
        if random.randint(1, 100) > pill_chance:
            return dropped_pills, describe_roll("稀有丹药", pill_chance, False)
        
        # 获取对应等级的丹药掉落表
        pill_table = self.RIFT_PILL_DROP_TABLE.get(rift_level, self.RIFT_PILL_DROP_TABLE[1])
        
        # 加权随机选择丹药
        total_weight = sum(item["weight"] for item in pill_table)
        roll = random.randint(1, total_weight)
        
        current_weight = 0
        for item in pill_table:
            current_weight += item["weight"]
            if roll <= current_weight:
                count = random.randint(item["min"], item["max"])
                dropped_pills.append((item["name"], count))
                break
        
        result_text = ""
        if dropped_pills:
            result_text = f"{dropped_pills[0][0]} x{dropped_pills[0][1]}"
        return dropped_pills, describe_roll("稀有丹药", pill_chance, True, result_text=result_text)
    