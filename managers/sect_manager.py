# managers/sect_manager.py
"""
宗门系统管理器 - 处理宗门创建、管理、捐献、任务等逻辑
参照NoneBot2插件的xiuxian_sect实现
"""

import random
import time
from typing import Tuple, List, Optional, Dict
from astrbot.api import logger

from ..data.data_manager import DataBase
from ..models_extended import Sect

from ..models import Player

SECT_NAME_MIN_LENGTH = 2
SECT_NAME_MAX_LENGTH = 12
SECT_NAME_FORBIDDEN = ["管理员", "系统", "官方", "GM", "admin"]

# 宗门丹房建设配置
# 每一级丹房需要消耗的资材与灵石，等级越高每日可领丹药越好
SECT_ELIXIR_ROOMS = {
    0: {"name": "无丹房", "materials": 0, "stone": 0, "pills": [], "desc": "尚未建造丹房"},
    1: {"name": "一阶丹房", "materials": 200, "stone": 5000, "pills": ["聚气丹"], "desc": "可每日领取 1 颗聚气丹"},
    2: {"name": "二阶丹房", "materials": 500, "stone": 15000, "pills": ["聚气丹", "回元丹"], "desc": "可每日领取聚气丹 + 回元丹"},
    3: {"name": "三阶丹房", "materials": 1200, "stone": 40000, "pills": ["聚气丹", "回元丹", "宗门凝神丹"], "desc": "可每日领取聚气丹 + 回元丹 + 宗门凝神丹"},
    4: {"name": "四阶丹房", "materials": 3000, "stone": 100000, "pills": ["聚气丹", "回元丹", "宗门凝神丹", "破障丹"], "desc": "可每日领取聚气丹 + 回元丹 + 宗门凝神丹 + 破障丹"},
    5: {"name": "五阶丹房", "materials": 8000, "stone": 250000, "pills": ["聚气丹", "回元丹", "宗门凝神丹", "破障丹", "宗门洗髓丹"], "desc": "丹房大成，弟子可领五味宗门丹药"},
}
MAX_ELIXIR_ROOM_LEVEL = 5

# 宗门任务每日次数上限（配合每日 0 点重置 sect_task 字段）
SECT_TASK_DAILY_LIMIT = 3

# 宗门丹药效果（与丹药系统一致，用于展示说明）
# ⚠️ 本表是对玩家的对外承诺，必须与 config/utility_pills.json 中的真实效果严格一致。
# 注：「凝神丹」原文案为「会心率 +3%」，但当前版本无「丹药 → 会心率」的实现链路，
#     故改用宗门专属变体「宗门凝神丹」（精神力 +5%），文案同步调整，详见
#     docs/design/sect_elixir_pills.md 的 BLOCKED 项。
SECT_ELIXIR_EFFECTS = {
    "聚气丹": "闭关修炼速度 +10%",
    "回元丹": "气血与灵气上限 +5%",
    "宗门凝神丹": "精神力 +5%",
    "破障丹": "突破成功率 +5%",
    "宗门洗髓丹": "全部属性 +2%",
}


class SectManager:
    """宗门系统管理器"""
    
    # 宗门职位定义
    POSITIONS = {
        0: "宗主",
        1: "长老",
        2: "亲传弟子",
        3: "内门弟子",
        4: "外门弟子"
    }
    
    # 宗门职位权限
    POSITION_PERMISSIONS = {
        0: ["manage_all", "kick", "position_change", "build", "search_skill"],
        1: ["kick_outer", "build"],
        2: ["learn_skill"],
        3: ["learn_skill"],
        4: []  # 外门弟子无特殊权限
    }
    
    def __init__(self, db: DataBase, config_manager=None):
        self.db = db
        self.config = config_manager.sect_config if config_manager else {}
        self.config_manager = config_manager

    def _is_pill_defined(self, pill_name: str) -> bool:
        """校验丹药在丹药系统中确实存在（存在才发放，避免发出「用不了」的幽灵丹药）

        只认 PillManager.get_pill_by_name 会查询的三个配置源：
        pills.json（破境丹）/ exp_pills.json（修为丹）/ utility_pills.json（功能丹）。
        """
        config_manager = self.config_manager
        if config_manager is None:
            logger.warning(
                f"[宗门丹房] 无配置管理器，无法校验丹药【{pill_name}】是否存在，按已定义处理"
            )
            return True
        return (
            pill_name in getattr(config_manager, "pills_data", {})
            or pill_name in getattr(config_manager, "exp_pills_data", {})
            or pill_name in getattr(config_manager, "utility_pills_data", {})
        )
    
    def _get_pill_level_requirement(self, pill_name: str) -> int:
        """取丹药的境界门槛（与 PillManager.use_pill 的校验同源），取不到按 0 处理

        join_sect 没有境界门槛，若发放时不校验，境界不足的弟子会领到丹药
        却在服用时被判「境界不足」——即本次要根除的「领了用不了」问题。
        """
        config_manager = self.config_manager
        if config_manager is None:
            return 0
        for attr in ("pills_data", "exp_pills_data", "utility_pills_data"):
            data = getattr(config_manager, attr, None) or {}
            if pill_name in data:
                try:
                    return int(data[pill_name].get("required_level_index", 0) or 0)
                except (TypeError, ValueError, AttributeError):
                    return 0
        return 0

    def _validate_sect_name(self, name: str) -> Tuple[bool, str]:
        """验证宗门名称"""
        if len(name) < SECT_NAME_MIN_LENGTH or len(name) > SECT_NAME_MAX_LENGTH:
            return False, f"❌ 宗门名称长度需在{SECT_NAME_MIN_LENGTH}-{SECT_NAME_MAX_LENGTH}字之间！"
        for forbidden in SECT_NAME_FORBIDDEN:
            if forbidden.lower() in name.lower():
                return False, f"❌ 宗门名称包含禁用词汇！"
        return True, ""
    
    async def create_sect(
        self,
        user_id: str,
        sect_name: str,
        required_stone: int = None,
        required_level: int = None
    ) -> Tuple[bool, str]:
        """
        创建宗门
        
        Args:
            user_id: 用户ID
            sect_name: 宗门名称
            required_stone: 需求灵石（默认为配置值或10000）
            required_level: 需求境界等级（默认为配置值或3）
            
        Returns:
            (成功标志, 消息)
        """
        # 加载配置
        if required_stone is None:
            required_stone = self.config.get("create_cost", 10000)
        if required_level is None:
            required_level = self.config.get("create_level_required", 3)
        # 1. 检查用户是否存在
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        
        # 2. 检查是否已有宗门
        if player.sect_id != 0:
            return False, "❌ 你已经加入了宗门，无法创建新宗门！"
        
        # 3. 检查境界
        if player.level_index < required_level:
            return False, f"❌ 创建宗门需要达到境界等级 {required_level}！"
        
        # 4. 检查灵石
        if player.gold < required_stone:
            return False, f"❌ 创建宗门需要 {required_stone} 灵石！"
        
        # 验证宗门名称
        valid, error = self._validate_sect_name(sect_name)
        if not valid:
            return False, error
        
        # 5. 检查宗门名称是否重复
        existing_sect = await self.db.ext.get_sect_by_name(sect_name)
        if existing_sect:
            return False, f"❌ 宗门名称『{sect_name}』已被使用！"
        
        # 6. 扣除灵石
        player.gold -= required_stone
        await self.db.update_player(player)
        
        # 7. 创建宗门
        new_sect = Sect(
            sect_id=0,  # 自动生成
            sect_name=sect_name,
            sect_owner=user_id,
            sect_scale=100,  # 初始建设度
            sect_used_stone=0,
            sect_fairyland=0,
            sect_materials=100,  # 初始资材
            mainbuff="0",
            secbuff="0",
            elixir_room_level=0
        )
        
        sect_id = await self.db.ext.create_sect(new_sect)
        
        # 8. 更新玩家宗门信息（设为宗主）
        await self.db.ext.update_player_sect_info(user_id, sect_id, 0)
        
        # 9. 初始化用户buff信息（如果没有）
        buff_info = await self.db.ext.get_buff_info(user_id)
        if not buff_info:
            await self.db.ext.create_buff_info(user_id)
        
        return True, f"✨ 恭喜！你成功创建了宗门『{sect_name}』，成为一代宗主！"
    
    async def join_sect(self, user_id: str, sect_name: str) -> Tuple[bool, str]:
        """
        加入宗门
        
        Args:
            user_id: 用户ID
            sect_name: 宗门名称
            
        Returns:
            (成功标志, 消息)
        """
        # 1. 检查用户
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        
        if player.sect_id != 0:
            return False, "❌ 你已经加入了宗门！请先退出当前宗门。"
        
        # 2. 查找宗门
        sect = await self.db.ext.get_sect_by_name(sect_name)
        if not sect:
            return False, f"❌ 未找到宗门『{sect_name}』！"
        
        # 3. 加入宗门（默认为外门弟子）
        await self.db.ext.update_player_sect_info(user_id, sect.sect_id, 4)
        
        # 4. 初始化buff信息
        buff_info = await self.db.ext.get_buff_info(user_id)
        if not buff_info:
            await self.db.ext.create_buff_info(user_id)
        
        return True, f"✨ 你成功加入了宗门『{sect_name}』，成为外门弟子！"
    
    async def leave_sect(self, user_id: str) -> Tuple[bool, str]:
        """
        退出宗门
        
        Args:
            user_id: 用户ID
            
        Returns:
            (成功标志, 消息)
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        
        if player.sect_id == 0:
            return False, "❌ 你还未加入任何宗门！"
        
        # 检查是否为宗主
        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if sect and sect.sect_owner == user_id:
            return False, "❌ 宗主无法直接退出宗门！请先传位或解散宗门。"
        
        sect_name = sect.sect_name if sect else "未知宗门"
        
        # 清除宗门信息
        await self.db.ext.update_player_sect_info(user_id, 0, 4)
        player.sect_contribution = 0
        await self.db.update_player(player)
        
        return True, f"✨ 你已退出宗门『{sect_name}』！"
    
    async def donate_to_sect(
        self,
        user_id: str,
        stone_amount: int
    ) -> Tuple[bool, str]:
        """
        宗门捐献（1灵石 = 10建设度）
        
        Args:
            user_id: 用户ID
            stone_amount: 捐献灵石数量
            
        Returns:
            (成功标志, 消息)
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        
        if player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
        
        if stone_amount <= 0:
            return False, "❌ 捐献数量必须大于0！"
        
        if player.gold < stone_amount:
            return False, f"❌ 你的灵石不足！当前拥有 {player.gold} 灵石。"
        
        # 扣除灵石
        player.gold -= stone_amount
        
        # 增加宗门贡献度（1灵石 = 1贡献）
        player.sect_contribution += stone_amount
        await self.db.update_player(player)
        
        # 增加宗门建设度和灵石（1灵石 = 10建设度）
        await self.db.ext.donate_to_sect(player.sect_id, stone_amount)
        
        scale_gained = stone_amount * 10
        
        return True, f"✨ 捐献成功！消耗 {stone_amount} 灵石，宗门获得 {scale_gained} 建设度！\n你的宗门贡献度：{player.sect_contribution}"
    
    async def get_sect_info(self, user_id: str) -> Tuple[bool, str, Optional[Dict]]:
        """
        获取宗门信息
        
        Args:
            user_id: 用户ID
            
        Returns:
            (成功标志, 消息, 宗门数据)
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", None
        
        if player.sect_id == 0:
            return False, "❌ 你还未加入宗门！", None
        
        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if not sect:
            return False, "❌ 宗门信息异常！", None
        
        # 获取宗主信息
        owner = await self.db.get_player_by_id(sect.sect_owner)
        owner_name = owner.user_name if owner and owner.user_name else sect.sect_owner
        
        # 获取成员数量
        members = await self.db.ext.get_sect_members(sect.sect_id)
        member_count = len(members)
        
        # 构建信息
        position_name = self.POSITIONS.get(player.sect_position, "未知")
        
        info_msg = f"""
🏛️ 宗门信息
━━━━━━━━━━━━━━━

宗门名称：{sect.sect_name}
宗主：{owner_name}
建设度：{sect.sect_scale}
宗门灵石：{sect.sect_used_stone}
宗门资材：{sect.sect_materials}
丹房等级：{sect.elixir_room_level}
成员数量：{member_count}人

你的职位：{position_name}
你的贡献：{player.sect_contribution}
        """.strip()
        
        sect_data = {
            "sect": sect,
            "player_position": player.sect_position,
            "player_contribution": player.sect_contribution,
            "member_count": member_count
        }
        
        return True, info_msg, sect_data
    
    async def list_all_sects(self) -> Tuple[bool, str]:
        """
        获取所有宗门列表
        
        Returns:
            (成功标志, 消息)
        """
        sects = await self.db.ext.get_all_sects()
        
        if not sects:
            return False, "❌ 当前还没有任何宗门！"
        
        msg = "🏛️ 宗门列表\n"
        msg += "━━━━━━━━━━━━━━━\n"
        
        for idx, sect in enumerate(sects[:10], 1):  # 只显示前10个
            owner = await self.db.get_player_by_id(sect.sect_owner)
            owner_name = owner.user_name if owner and owner.user_name else "未知"
            members = await self.db.ext.get_sect_members(sect.sect_id)
            
            msg += f"{idx}. 【{sect.sect_name}】\n"
            msg += f"   宗主：{owner_name}\n"
            msg += f"   建设度：{sect.sect_scale} | 成员：{len(members)}人\n\n"
        
        return True, msg
    
    async def change_position(
        self,
        operator_id: str,
        target_id: str,
        new_position: int
    ) -> Tuple[bool, str]:
        """
        变更宗门职位
        
        Args:
            operator_id: 操作者ID（必须是宗主）
            target_id: 目标用户ID
            new_position: 新职位（0-4）
            
        Returns:
            (成功标志, 消息)
        """
        # 检查操作者
        operator = await self.db.get_player_by_id(operator_id)
        if not operator or operator.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
        
        if operator.sect_position != 0:
            return False, "❌ 只有宗主才能变更职位！"
        
        # 检查目标用户
        target = await self.db.get_player_by_id(target_id)
        if not target:
            return False, "❌ 目标用户不存在！"
        
        if target.sect_id != operator.sect_id:
            return False, "❌ 目标用户不在你的宗门！"
        
        if target_id == operator_id:
            return False, "❌ 无法变更自己的职位！"
        
        if new_position not in self.POSITIONS:
            return False, "❌ 无效的职位！职位范围：0（宗主）- 4（外门弟子）"
        
        if new_position == 0:
            return False, "❌ 无法直接任命宗主！请使用传位功能。"
        
        # 变更职位
        await self.db.ext.update_player_sect_info(target_id, target.sect_id, new_position)
        
        target_name = target.user_name if target.user_name else target_id
        position_name = self.POSITIONS[new_position]
        
        return True, f"✨ 已将 {target_name} 的职位变更为：{position_name}"
    
    async def transfer_ownership(
        self,
        current_owner_id: str,
        new_owner_id: str
    ) -> Tuple[bool, str]:
        """
        宗主传位
        
        Args:
            current_owner_id: 当前宗主ID
            new_owner_id: 新宗主ID
            
        Returns:
            (成功标志, 消息)
        """
        # 检查当前宗主
        current_owner = await self.db.get_player_by_id(current_owner_id)
        if not current_owner or current_owner.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
        
        sect = await self.db.ext.get_sect_by_id(current_owner.sect_id)
        if not sect or sect.sect_owner != current_owner_id:
            return False, "❌ 你不是宗主！"
        
        # 检查新宗主
        new_owner = await self.db.get_player_by_id(new_owner_id)
        if not new_owner:
            return False, "❌ 目标用户不存在！"
        
        if new_owner.sect_id != current_owner.sect_id:
            return False, "❌ 目标用户不在你的宗门！"
        
        if new_owner_id == current_owner_id:
            return False, "❌ 无法传位给自己！"
        
        # 执行传位
        sect.sect_owner = new_owner_id
        await self.db.ext.update_sect(sect)
        
        # 更新职位：新宗主->宗主，旧宗主->长老
        await self.db.ext.update_player_sect_info(new_owner_id, sect.sect_id, 0)
        await self.db.ext.update_player_sect_info(current_owner_id, sect.sect_id, 1)
        
        new_owner_name = new_owner.user_name if new_owner.user_name else new_owner_id
        
        return True, f"✨ 宗主之位已传给 {new_owner_name}！你现在是长老。"
    
    async def kick_member(
        self,
        operator_id: str,
        target_id: str
    ) -> Tuple[bool, str]:
        """
        踢出宗门成员
        
        Args:
            operator_id: 操作者ID
            target_id: 目标用户ID
            
        Returns:
            (成功标志, 消息)
        """
        # 检查操作者权限
        operator = await self.db.get_player_by_id(operator_id)
        if not operator or operator.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
        
        # 宗主和长老可以踢人
        if operator.sect_position not in [0, 1]:
            return False, "❌ 只有宗主和长老才能踢出成员！"
        
        # 检查目标
        target = await self.db.get_player_by_id(target_id)
        if not target:
            return False, "❌ 目标用户不存在！"
        
        if target.sect_id != operator.sect_id:
            return False, "❌ 目标用户不在你的宗门！"
        
        if target_id == operator_id:
            return False, "❌ 无法踢出自己！"
        
        # 长老只能踢外门弟子
        if operator.sect_position == 1 and target.sect_position <= 3:
            return False, "❌ 长老只能踢出外门弟子！"
        
        # 无法踢出宗主
        if target.sect_position == 0:
            return False, "❌ 无法踢出宗主！"
        
        # 踢出
        target_name = target.user_name if target.user_name else target_id
        await self.db.ext.update_player_sect_info(target_id, 0, 4)
        target.sect_contribution = 0
        await self.db.update_player(target)
        
        return True, f"✨ 已将 {target_name} 踢出宗门！"

    async def perform_sect_task(self, user_id: str) -> Tuple[bool, str]:
        """
        执行宗门任务
        
        Args:
            user_id: 用户ID
            
        Returns:
            (成功标志, 消息)
        """
        player = await self.db.get_player_by_id(user_id)
        if not player or player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
            
        current_time = int(time.time())

        # 冷却检查：宗门任务是瞬时操作，用独立冷却存储，
        # 不占用 user_cd 忙碌状态（否则玩家会被锁住 1 小时，无法进行其他操作）
        cd_key = f"sect_task_cd_{user_id}"
        cd_value = await self.db.ext.get_system_config(cd_key)
        if cd_value:
            try:
                next_time = int(cd_value)
                if current_time < next_time:
                    remaining = next_time - current_time
                    return False, f"❌ 宗门任务冷却中！还需 {remaining//60} 分钟。"
            except (TypeError, ValueError):
                pass

        # 每日次数上限（用 sect_task 字段记录，配合每日定时重置）
        if player.sect_task >= SECT_TASK_DAILY_LIMIT:
            return False, (
                f"❌ 今日宗门任务次数已用尽（{SECT_TASK_DAILY_LIMIT} 次）！\n"
                f"💡 明日 0 点重置"
            )

        # 执行任务
        contribution_gain = random.randint(10, 30)
        stone_gain = contribution_gain * 10
        
        player.sect_contribution += contribution_gain
        player.sect_task += 1
        await self.db.update_player(player)
        
        # 宗门增加资源（任务产出的资材直接入账）
        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if sect:
            sect.sect_materials += stone_gain
            await self.db.ext.update_sect(sect)

        # 设置独立冷却（1小时），不动忙碌状态
        await self.db.ext.set_system_config(cd_key, str(current_time + 3600))
        
        return True, (
            f"✨ 完成宗门任务！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"获得贡献：+{contribution_gain}\n"
            f"宗门资材：+{stone_gain}\n"
            f"今日剩余次数：{SECT_TASK_DAILY_LIMIT - player.sect_task}/{SECT_TASK_DAILY_LIMIT}\n"
            f"💡 资材可用于「宗门建设」升级丹房"
        )

    # ===== 宗门建设（丹房）=====

    async def upgrade_elixir_room(self, user_id: str) -> Tuple[bool, str]:
        """宗主消耗宗门资材 + 灵石升级丹房等级

        宗门资材（sect_materials）此前只增不消费，丹房等级恒为 0，
        此处为其补上真实消费途径，让「宗门建设」成为可玩的升级系统。
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        if player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"

        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if not sect:
            return False, "❌ 宗门信息异常！"

        # 建设权限：宗主或长老
        if player.sect_position not in (0, 1):
            return False, "❌ 只有宗主或长老可以主持宗门建设！"

        current_level = sect.elixir_room_level
        if current_level >= MAX_ELIXIR_ROOM_LEVEL:
            return False, f"❌ {SECT_ELIXIR_ROOMS[current_level]['name']}已是最高等级！"

        target = SECT_ELIXIR_ROOMS[current_level + 1]
        need_materials = target["materials"]
        need_stone = target["stone"]

        if sect.sect_materials < need_materials:
            return False, (
                f"❌ 宗门资材不足！\n"
                f"需要：{need_materials} 资材\n"
                f"当前：{sect.sect_materials} 资材\n"
                f"💡 完成宗门任务可获得资材"
            )
        if player.gold < need_stone:
            return False, (
                f"❌ 灵石不足！\n"
                f"需要：{need_stone:,} 灵石\n"
                f"当前：{player.gold:,} 灵石"
            )

        # 扣资材（宗门公共资源）+ 扣灵石（建设者个人承担）
        sect.sect_materials -= need_materials
        sect.elixir_room_level = current_level + 1
        await self.db.ext.update_sect(sect)

        player.gold -= need_stone
        await self.db.update_player(player)

        new_pills = target["pills"]
        return True, (
            f"🎉 丹房升级成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{target['name']} 已建成\n"
            f"消耗：{need_materials} 资材 + {need_stone:,} 灵石\n"
            f"━━━━━━━━━━━━━━━\n"
            f"宗门弟子每日可领取：{'、'.join(new_pills)}\n"
            f"💡 使用 /宗门丹药 领取"
        )

    async def get_elixir_room_status(self, user_id: str) -> Tuple[bool, str]:
        """查看宗门丹房建设状态与效果说明"""
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        if player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"

        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if not sect:
            return False, "❌ 宗门信息异常！"

        level = sect.elixir_room_level
        current = SECT_ELIXIR_ROOMS[level]
        lines = [
            f"🏛️ 宗门丹房 · {sect.sect_name}",
            "━━━━━━━━━━━━━━━",
            f"当前等级：{current['name']}（Lv.{level}）",
            f"宗门资材：{sect.sect_materials}",
        ]

        if level == 0:
            lines.append("\n尚未建造丹房，宗门弟子暂无可领丹药。")
        else:
            lines.append("\n每日可领丹药：")
            for pill in current["pills"]:
                lines.append(f"  · {pill} —— {SECT_ELIXIR_EFFECTS.get(pill, '')}")

        if level < MAX_ELIXIR_ROOM_LEVEL:
            nxt = SECT_ELIXIR_ROOMS[level + 1]
            lines.append("\n━━━━━━━━━━━━━━━")
            lines.append(f"下一级：{nxt['name']}")
            lines.append(f"  需要：{nxt['materials']} 资材 + {nxt['stone']:,} 灵石")
            lines.append(f"  效果：{nxt['desc']}")
            lines.append("💡 宗主/长老可使用「宗门建设」升级")

        return True, "\n".join(lines)

    async def claim_sect_elixir(self, user_id: str) -> Tuple[bool, str]:
        """领取宗门每日丹药"""
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        if player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"

        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if not sect:
            return False, "❌ 宗门信息异常！"

        level = sect.elixir_room_level
        if level == 0:
            return False, "❌ 宗门尚未建造丹房，无丹药可领。\n💡 宗主可使用「宗门建设」升级丹房"

        # 每日只能领一次
        if player.sect_elixir_get == 1:
            return False, "❌ 你今日已领取过宗门丹药了，明日再来。"

        pills = SECT_ELIXIR_ROOMS[level]["pills"]
        inventory = player.get_pills_inventory()
        gained = []
        skipped = []
        level_blocked = []
        for pill in pills:
            # 防御性校验一：丹药必须在丹药系统中有定义，否则跳过并记日志，
            # 避免再次出现「领到了但服用时提示配置不存在」的幽灵丹药
            if not self._is_pill_defined(pill):
                logger.warning(
                    f"[宗门丹房] 玩家 {user_id} 领取丹药失败："
                    f"【{pill}】在丹药系统中无配置（宗门 {player.sect_id} 丹房 {level} 阶），已跳过发放"
                )
                skipped.append(pill)
                continue
            # 防御性校验二：境界不足的丹药不发放。
            # join_sect 无境界门槛，若不过滤，低境界弟子会领到却用不了。
            required_level = self._get_pill_level_requirement(pill)
            if player.level_index < required_level:
                level_blocked.append((pill, required_level))
                continue
            inventory[pill] = inventory.get(pill, 0) + 1
            gained.append(pill)

        if not gained and level_blocked:
            # 全因境界不足发不出去：不消耗每日领取机会，让弟子到境界后还能领
            blocked_lines = "\n".join(f"  · {p}" for p, _ in level_blocked)
            return False, (
                "❌ 你当前的境界还不足以领取宗门丹药。\n"
                f"━━━━━━━━━━━━━━━\n"
                f"{blocked_lines}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💡 提升境界后再来领取（本次不消耗每日领取机会）"
            )

        if not gained:
            # 一枚都发不出去时不置位每日标记，玩家修复配置后可重新领取
            return False, (
                "❌ 宗门丹房配置的丹药当前均不可用（配置缺失），本次未发放。\n"
                f"💡 缺失丹药：{'、'.join(skipped) if skipped else '未知'}\n"
                "💡 请联系服务器管理员检查丹药配置。"
            )

        player.set_pills_inventory(inventory)

        player.sect_elixir_get = 1
        await self.db.update_player(player)

        effect_lines = "\n".join(
            f"  · {p} —— {SECT_ELIXIR_EFFECTS.get(p, '')}" for p in gained
        )
        message = (
            f"🎁 领取宗门丹药成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{effect_lines}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 使用「服用丹药 <名称>」生效"
        )
        if skipped:
            message += f"\n⚠️ 以下丹药配置缺失已跳过：{'、'.join(skipped)}"
        if level_blocked:
            blocked_lines = "\n".join(f"  · {p}（需更高境界）" for p, _ in level_blocked)
            message += (
                f"\n⚠️ 以下丹药境界不足，暂未发放：\n"
                f"{blocked_lines}\n"
                f"💡 提升境界后再来服用"
            )
        return True, message

    async def handle_owner_death(self, sect_id: int, dead_owner_id: str) -> Tuple[bool, str]:
        """处理玩家因死亡/重修离开宗门时的宗门善后

        - 若该玩家**不是**宗主：仅脱离宗门（sect_id 归零，职位回退外门）
        - 若该玩家**是**宗主：
            - 有其他成员 → 按「职位优先、贡献次之」自动传位
            - 无其他成员 → 解散宗门
        """
        sect = await self.db.ext.get_sect_by_id(sect_id)
        if not sect:
            # 宗门已不存在，仅确保玩家自身关系干净
            await self.db.ext.update_player_sect_info(dead_owner_id, 0, 4)
            return True, "宗门已不存在，你已自动脱离。"

        members = await self.db.ext.get_sect_members(sect_id)
        # 过滤掉已死/离开的玩家
        remaining = [m for m in members if m.user_id != dead_owner_id]

        # 情形一：玩家并非宗主，只是普通成员
        if sect.sect_owner != dead_owner_id:
            await self.db.ext.update_player_sect_info(dead_owner_id, 0, 4)
            return True, "你已脱离宗门。"

        # 情形二：玩家是宗主
        if not remaining:
            # 无其他成员，解散宗门（成员列表此时只含死者，无需额外释放）
            await self.db.ext.delete_sect(sect_id)
            return True, "宗门已解散"

        # 按职位和贡献排序，选择新宗主
        remaining.sort(key=lambda m: (m.sect_position, -m.sect_contribution))
        new_owner = remaining[0]

        # 更新宗门宗主
        sect.sect_owner = new_owner.user_id
        await self.db.ext.update_sect(sect)
        await self.db.ext.update_player_sect_info(new_owner.user_id, sect_id, 0)

        # 原宗主的残留关系（此时玩家即将被级联删除，这里兜底清理）
        await self.db.ext.update_player_sect_info(dead_owner_id, 0, 4)

        return True, f"宗主之位已传给{new_owner.user_name or new_owner.user_id}"
