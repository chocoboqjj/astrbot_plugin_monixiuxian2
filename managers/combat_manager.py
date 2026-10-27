# managers/combat_manager.py
"""
战斗系统管理器 - 处理HP/MP/ATK系统和战斗逻辑
参照NoneBot2插件的player_fight.py实现
"""

import random
from typing import Tuple, Dict, Optional, List, TYPE_CHECKING
from dataclasses import dataclass

from ..models import resolve_equipment_attributes

if TYPE_CHECKING:
    from ..models import Player

@dataclass
class CombatStats:
    """战斗属性"""
    user_id: str
    name: str  # 道号
    hp: int  # 当前气血
    max_hp: int  # 最大气血
    mp: int  # 当前真元
    max_mp: int  # 最大真元
    atk: int  # 攻击力
    defense: int = 0  # 防御力
    crit_rate: int = 0  # 会心率（百分比）
    exp: int = 0  # 修为（用于计算攻击力）


class CombatManager:
    """战斗系统管理器"""
    
    @staticmethod
    def calculate_hp_mp(experience: int, hp_buff: float = 0.0, mp_buff: float = 0.0) -> Tuple[int, int]:
        """
        根据修为计算HP和MP
        
        Args:
            experience: 修为
            hp_buff: HP加成百分比
            mp_buff: MP加成百分比
            
        Returns:
            (hp, mp) 元组
        """
        base_hp = experience // 2
        base_mp = experience
        
        hp = int(base_hp * (1 + hp_buff))
        mp = int(base_mp * (1 + mp_buff))
        
        return hp, mp
    
    @classmethod
    def calculate_combat_stats(
        cls,
        player: "Player",
        impart_info=None,
        equipment_atk: int = 0,
        equipment_defense: int = 0,
    ) -> "CombatStats":
        """根据玩家修为、传承加成与装备加成构建战斗属性。

        这是战斗属性计算的唯一权威入口，供决斗 / 传承挑战 / Boss 战等统一调用，
        避免各模块重复实现导致数值不一致（例如此前传承挑战直接调用一个不存在的方法）。

        Args:
            player: 玩家对象
            impart_info: 传承加成信息（可为 None）
            equipment_atk: 装备提供的攻击加成
            equipment_defense: 装备提供的防御加成

        Returns:
            CombatStats 战斗属性
        """
        hp_buff = impart_info.impart_hp_per if impart_info else 0.0
        mp_buff = impart_info.impart_mp_per if impart_info else 0.0
        atk_buff = impart_info.impart_atk_per if impart_info else 0.0

        hp, mp = cls.calculate_hp_mp(player.experience, hp_buff, mp_buff)
        base_atk = cls.calculate_atk(player.experience, player.atkpractice, atk_buff)
        final_atk = base_atk + equipment_atk

        return CombatStats(
            user_id=player.user_id,
            name=player.user_name if player.user_name else f"道友{player.user_id}",
            hp=hp,
            max_hp=hp,
            mp=mp,
            max_mp=mp,
            atk=final_atk,
            defense=equipment_defense,
            exp=player.experience,
        )

    @staticmethod
    def calculate_equipment_bonus(config_manager, player, refine_map: Optional[Dict[str, int]] = None) -> Dict[str, int]:
        """计算装备提供的攻防加成（武器加攻击，防具加防御）。

        同时供决斗与传承挑战复用，避免逻辑分散。
        refine_map: {item_name: 精炼星数}，提供则按星数放大装备攻防。
        """
        bonus: Dict[str, int] = {"atk": 0, "defense": 0}
        if not config_manager:
            return bonus

        # 精炼加成倍率（每星提升装备攻防）
        per_star = 0.10
        forge_cfg = getattr(config_manager, "forge_config", None)
        if forge_cfg:
            per_star = forge_cfg.get("refine", {}).get("per_star_bonus", 0.10)

        def _mult(item_name: str) -> float:
            if not refine_map:
                return 1.0
            star = refine_map.get(item_name, 0)
            return 1.0 + star * per_star

        # 统一查找顺序（与 EquipmentManager.parse_item_from_name 一致：先 items 后 weapons）
        items_data = getattr(config_manager, "items_data", None) or {}
        weapons_data = getattr(config_manager, "weapons_data", None) or {}

        if player.weapon:
            data = items_data.get(player.weapon) or weapons_data.get(player.weapon)
            if data:
                # v3.3.4：与面板共用 resolve_equipment_attributes，
                # 修复旧格式（equip_effects.attack）与 items 侧武器不生效的缺陷
                attrs = resolve_equipment_attributes(data)
                atk = attrs["physical_damage"] + attrs["magic_damage"]
                bonus["atk"] += int(round(atk * _mult(player.weapon)))

        if player.armor:
            data = items_data.get(player.armor) or weapons_data.get(player.armor)
            if data:
                # v3.3.4：修复旧格式（equip_effects.defense）防具防御不生效的缺陷
                attrs = resolve_equipment_attributes(data)
                defense = attrs["physical_defense"] + attrs["magic_defense"]
                bonus["defense"] += int(round(defense * _mult(player.armor)))

        return bonus

    @staticmethod
    def calculate_atk(experience: int, atkpractice: int = 0, atk_buff: float = 0.0) -> int:
        """
        根据修为和攻击修炼等级计算攻击力
        
        Args:
            experience: 修为
            atkpractice: 攻击修炼等级（每级提升4%攻击力）
            atk_buff: 额外攻击加成百分比
            
        Returns:
            攻击力
        """
        base_atk = experience // 10
        practice_bonus = atkpractice * 0.04  # 每级4%加成
        total_atk = int(base_atk * (1 + practice_bonus + atk_buff))
        
        return max(total_atk, 1)  # 至少为1
    
    @staticmethod
    def calculate_turn_attack(
        base_atk: int,
        crit_rate: int = 0,
        atk_buff: float = 0.0
    ) -> Tuple[bool, int]:
        """
        计算单回合攻击伤害
        
        Args:
            base_atk: 基础攻击力
            crit_rate: 会心率（百分比，0-100）
            atk_buff: 攻击加成（技能buff等）
            
        Returns:
            (是否暴击, 伤害值) 元组
        """
        # 攻击波动 95%-105%
        damage = int(round(random.uniform(0.95, 1.05), 2) * base_atk * (1 + atk_buff))
        
        # 会心判定
        is_crit = random.randint(0, 100) <= crit_rate
        if is_crit:
            damage = int(damage * 1.5)  # 会心伤害1.5倍
        
        return is_crit, damage
    
    @staticmethod
    def calculate_combat_power(
        physical_damage: int,
        magic_damage: int,
        physical_defense: int,
        magic_defense: int,
        mental_power: int,
        hp: int = 0,
        crit_rate: int = 0,
    ) -> int:
        """统一的战力计算公式（玩家面板与排行榜共用，避免数值不一致）。

        构成：
          - 攻防主体：物伤 + 法伤 + (物防 + 法防) * 0.8
          - 精神力：每 5 点贡献 1 战力（兼作“敏捷/速度”维度）
          - 暴击：每 1% 暴击率贡献 2 战力
          - 生存：HP 封顶 10 万后每 100 点贡献 1 战力（防止高修为 HP 淹没攻防）

        Args:
            physical_damage / magic_damage: 物伤 / 法伤
            physical_defense / magic_defense: 物防 / 法防
            mental_power: 精神力
            hp: 当前/估算气血（可选）
            crit_rate: 暴击率百分比（可选）
        """
        offense = int(physical_damage) + int(magic_damage)
        defense = (int(physical_defense) + int(magic_defense)) * 0.8
        hp_contrib = min(int(hp), 100000) // 100
        return int(offense + defense + int(mental_power) // 5 + int(crit_rate) * 2 + hp_contrib)

    @staticmethod
    def apply_damage_reduction(damage: int, defense: int = 0) -> int:
        """
        应用伤害减免（使用递减公式）
        
        Args:
            damage: 原始伤害
            defense: 防御力
            
        Returns:
            减免后的伤害
        """
        if defense <= 0:
            return damage
        reduction_rate = defense / (defense + 100)
        final_damage = int(damage * (1 - reduction_rate))
        return max(1, final_damage)
    
    @classmethod
    def player_vs_player(
        cls,
        player1: CombatStats,
        player2: CombatStats,
        combat_type: int = 1
    ) -> Dict:
        """
        玩家vs玩家战斗
        
        Args:
            player1: 玩家1战斗属性
            player2: 玩家2战斗属性
            combat_type: 战斗类型（1=切磋不消耗HP/MP，2=决斗消耗HP/MP）
            
        Returns:
            战斗结果字典，包含：
            - winner: 获胜者user_id
            - combat_log: 战斗日志列表
            - player1_final_hp: 玩家1最终HP
            - player1_final_mp: 玩家1最终MP
            - player2_final_hp: 玩家2最终HP
            - player2_final_mp: 玩家2最终MP
        """
        combat_log = []
        combat_log.append(f"☆━━━━ 战斗开始 ━━━━☆")
        combat_log.append(f"{player1.name} VS {player2.name}")
        combat_log.append(f"{player1.name}：HP {player1.hp}/{player1.max_hp}，ATK {player1.atk}")
        combat_log.append(f"{player2.name}：HP {player2.hp}/{player2.max_hp}，ATK {player2.atk}")
        combat_log.append("")
        
        round_num = 0
        max_rounds = 100  # 最大回合数，防止无限循环
        
        while player1.hp > 0 and player2.hp > 0 and round_num < max_rounds:
            round_num += 1
            combat_log.append(f"-- 第 {round_num} 回合 --")
            
            # 玩家1攻击
            is_crit1, damage1 = cls.calculate_turn_attack(player1.atk, player1.crit_rate)
            damage1 = cls.apply_damage_reduction(damage1, player2.defense)
            player2.hp -= damage1
            
            if is_crit1:
                combat_log.append(f"{player1.name} 发起会心一击，造成 {damage1} 点伤害！")
            else:
                combat_log.append(f"{player1.name} 发起攻击，造成 {damage1} 点伤害")
            combat_log.append(f"{player2.name} 剩余 HP: {max(0, player2.hp)}")
            
            if player2.hp <= 0:
                break
            
            # 玩家2攻击
            is_crit2, damage2 = cls.calculate_turn_attack(player2.atk, player2.crit_rate)
            damage2 = cls.apply_damage_reduction(damage2, player1.defense)
            player1.hp -= damage2
            
            if is_crit2:
                combat_log.append(f"{player2.name} 发起会心一击，造成 {damage2} 点伤害！")
            else:
                combat_log.append(f"{player2.name} 发起攻击，造成 {damage2} 点伤害")
            combat_log.append(f"{player1.name} 剩余 HP: {max(0, player1.hp)}")
            combat_log.append("")
        
        # 判断胜负
        if player1.hp > 0:
            winner = player1.user_id
            combat_log.append(f"☆━━━━ {player1.name} 胜利！━━━━☆")
        elif player2.hp > 0:
            winner = player2.user_id
            combat_log.append(f"☆━━━━ {player2.name} 胜利！━━━━☆")
        else:
            winner = "平局"
            combat_log.append(f"☆━━━━ 平局！━━━━☆")
        
        # 如果是切磋，不消耗HP/MP
        if combat_type == 1:
            player1_final_hp = player1.max_hp
            player1_final_mp = player1.max_mp
            player2_final_hp = player2.max_hp
            player2_final_mp = player2.max_mp
        else:
            # 决斗消耗HP/MP，战败者HP降为1
            player1_final_hp = max(1, player1.hp) if player1.hp > 0 else 1
            player1_final_mp = player1.mp
            player2_final_hp = max(1, player2.hp) if player2.hp > 0 else 1
            player2_final_mp = player2.mp
        
        return {
            "winner": winner,
            "combat_log": combat_log,
            "player1_final_hp": player1_final_hp,
            "player1_final_mp": player1_final_mp,
            "player2_final_hp": player2_final_hp,
            "player2_final_mp": player2_final_mp,
            "rounds": round_num
        }
    
    @classmethod
    def player_vs_boss(
        cls,
        player: CombatStats,
        boss: CombatStats
    ) -> Dict:
        """
        玩家vs Boss战斗
        
        Args:
            player: 玩家战斗属性
            boss: Boss战斗属性
            
        Returns:
            战斗结果字典
        """
        combat_log = []
        combat_log.append(f"☆━━━━ Boss战开始 ━━━━☆")
        combat_log.append(f"{player.name} 挑战 {boss.name}")
        combat_log.append(f"{player.name}：HP {player.hp}/{player.max_hp}，ATK {player.atk}")
        combat_log.append(f"{boss.name}：HP {boss.hp}/{boss.max_hp}，ATK {boss.atk}")
        combat_log.append("")
        
        round_num = 0
        max_rounds = 100
        total_damage_dealt = 0  # 玩家造成的总伤害（用于失败时计算奖励）
        
        while player.hp > 0 and boss.hp > 0 and round_num < max_rounds:
            round_num += 1
            combat_log.append(f"-- 第 {round_num} 回合 --")
            
            # 玩家攻击
            is_crit, damage = cls.calculate_turn_attack(player.atk, player.crit_rate)
            # Boss可能有减伤
            damage = cls.apply_damage_reduction(damage, boss.defense)
            boss.hp -= damage
            total_damage_dealt += damage
            
            if is_crit:
                combat_log.append(f"{player.name} 发起会心一击，造成 {damage} 点伤害！")
            else:
                combat_log.append(f"{player.name} 发起攻击，造成 {damage} 点伤害")
            combat_log.append(f"{boss.name} 剩余 HP: {max(0, boss.hp)}")
            
            if boss.hp <= 0:
                break
            
            # Boss攻击
            is_boss_crit, boss_damage = cls.calculate_turn_attack(boss.atk, 30)  # Boss固定30会心率
            boss_damage = cls.apply_damage_reduction(boss_damage, player.defense)
            player.hp -= boss_damage
            
            if is_boss_crit:
                combat_log.append(f"{boss.name} 发起会心一击，造成 {boss_damage} 点伤害！")
            else:
                combat_log.append(f"{boss.name} 发起攻击，造成 {boss_damage} 点伤害")
            combat_log.append(f"{player.name} 剩余 HP: {max(0, player.hp)}")
            combat_log.append("")
        
        # 判断胜负和奖励
        if boss.hp <= 0:
            winner = player.user_id
            combat_log.append(f"☆━━━━ {player.name} 击败了 {boss.name}！━━━━☆")
            reward = boss.exp  # 完整奖励
        elif player.hp <= 0:
            winner = boss.user_id
            combat_log.append(f"☆━━━━ {player.name} 被 {boss.name} 击败！━━━━☆")
            # 失败时根据造成的伤害比例获得部分奖励
            damage_ratio = total_damage_dealt / boss.max_hp
            reward = int(boss.exp * damage_ratio)
            combat_log.append(f"虽败犹荣，获得 {reward} 灵石作为奖励")
        else:
            winner = "平局"
            reward = 0
            combat_log.append(f"☆━━━━ 战斗超时，平局！━━━━☆")
        
        return {
            "winner": winner,
            "combat_log": combat_log,
            "player_final_hp": max(1, player.hp),  # 战败者HP降为1
            "player_final_mp": player.mp,
            "boss_final_hp": max(0, boss.hp),
            "reward": reward,
            "rounds": round_num
        }
