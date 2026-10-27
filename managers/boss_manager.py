# managers/boss_manager.py
"""
Boss系统管理器 - 处理Boss生成、战斗、奖励等逻辑
参照NoneBot2插件的xiuxian_boss实现
"""

import random
import time
from typing import Tuple, Dict, Optional, List, TYPE_CHECKING
from ..data.data_manager import DataBase
from ..models_extended import Boss

from ..models import Player
from .combat_manager import CombatManager, CombatStats

if TYPE_CHECKING:
    from ..core import StorageRingManager

# ===== v3.2.8 世界Boss挑战限制 =====
# 每只 Boss 每个玩家最多可挑战次数（Boss 刷新后自动重置；0 = 不限制）
DEFAULT_MAX_CHALLENGES = 1
# 两次挑战之间的冷却秒数（0 = 不限制）
DEFAULT_CHALLENGE_COOLDOWN = 600  # 10 分钟


class BossManager:
    """Boss系统管理器"""
    
    # Boss境界配置
    BOSS_LEVELS = [
        {"name": "练气", "level_index": 0, "hp_mult": 1.0, "atk_mult": 1.0, "reward_mult": 1.0},
        {"name": "筑基", "level_index": 3, "hp_mult": 1.5, "atk_mult": 1.2, "reward_mult": 1.5},
        {"name": "金丹", "level_index": 6, "hp_mult": 2.0, "atk_mult": 1.5, "reward_mult": 2.0},
        {"name": "元婴", "level_index": 9, "hp_mult": 2.5, "atk_mult": 1.8, "reward_mult": 2.5},
        {"name": "化神", "level_index": 12, "hp_mult": 3.0, "atk_mult": 2.0, "reward_mult": 3.0},
        {"name": "炼虚", "level_index": 15, "hp_mult": 4.0, "atk_mult": 2.5, "reward_mult": 4.0},
        {"name": "合体", "level_index": 18, "hp_mult": 5.0, "atk_mult": 3.0, "reward_mult": 5.0},
        {"name": "大乘", "level_index": 21, "hp_mult": 6.0, "atk_mult": 3.5, "reward_mult": 6.0},
    ]
    
    # Boss名称池
    BOSS_NAMES = [
        "血魔", "邪修", "魔头", "妖王", "魔君",
        "异兽", "凶兽", "妖尊", "魔尊", "邪帝",
        "天魔", "地魔", "魔神", "妖神", "邪神"
    ]
    
    # Boss物品掉落表
    BOSS_DROP_TABLE = {
        "low": [  # 低级Boss (练气-金丹)
            {"name": "灵兽内丹", "weight": 40, "min": 1, "max": 2},
            {"name": "妖兽精血", "weight": 30, "min": 1, "max": 3},
            {"name": "精铁", "weight": 30, "min": 3, "max": 6},
        ],
        "mid": [  # 中级Boss (元婴-化神)
            {"name": "灵兽内丹", "weight": 30, "min": 2, "max": 4},
            {"name": "星辰石", "weight": 25, "min": 2, "max": 4},
            {"name": "天材地宝", "weight": 20, "min": 1, "max": 2},
            {"name": "功法残页", "weight": 25, "min": 1, "max": 2},
        ],
        "high": [  # 高级Boss (炼虚及以上)
            {"name": "天材地宝", "weight": 30, "min": 2, "max": 4},
            {"name": "混沌精华", "weight": 25, "min": 1, "max": 2},
            {"name": "神兽之骨", "weight": 20, "min": 1, "max": 1},
            {"name": "远古秘籍", "weight": 15, "min": 1, "max": 1},
            {"name": "仙器碎片", "weight": 10, "min": 1, "max": 1},
        ],
    }
    
    def __init__(self, db: DataBase, combat_mgr: CombatManager, config_manager=None, storage_ring_manager: "StorageRingManager" = None):
        self.db = db
        self.combat_mgr = combat_mgr
        self.config_manager = config_manager
        self.storage_ring_manager = storage_ring_manager
        self.config = config_manager.boss_config if config_manager else {}
        self.levels = self.config.get("levels", self.BOSS_LEVELS)
        # v3.2.8：每只 Boss 每人的挑战次数上限（0 = 不限制）
        self.max_challenges = int(self.config.get("max_challenges", DEFAULT_MAX_CHALLENGES))
        # v3.2.8：两次挑战之间的冷却秒数（0 = 不限制）
        self.challenge_cooldown = int(self.config.get("challenge_cooldown", DEFAULT_CHALLENGE_COOLDOWN))
    
    async def spawn_boss(
        self,
        base_exp: int = 100000,
        level_config: Optional[Dict] = None
    ) -> Tuple[bool, str, Optional[Boss]]:
        """
        生成Boss
        
        Args:
            base_exp: 基础修为（用于计算属性）
            level_config: Boss等级配置，如果为None则随机选择
            
        Returns:
            (成功标志, 消息, Boss对象)
        """
        # 检查是否已有存活的Boss
        existing_boss = await self.db.ext.get_active_boss()
        if existing_boss:
            return False, f"❌ 当前已有Boss『{existing_boss.boss_name}』存在！", None
        
        # 选择Boss等级
        if not level_config:
            level_config = random.choice(self.levels)
        
        # 生成Boss名称
        boss_name = random.choice(self.BOSS_NAMES) + f"·{level_config['name']}境"
        
        # 计算Boss属性
        hp_mult = level_config["hp_mult"]
        atk_mult = level_config["atk_mult"]
        reward_mult = level_config["reward_mult"]
        
        # Boss的HP和ATK基于修为计算
        max_hp = int(base_exp * hp_mult // 2)
        atk = int(base_exp * atk_mult // 10)
        
        # 灵石奖励
        stone_reward = int(base_exp * reward_mult // 10)
        
        # Boss防御力（高境界Boss有减伤）
        defense = 0
        if level_config["level_index"] >= 15:  # 炼虚及以上
            defense = random.randint(40, 90)  # 40%-90%减伤
        
        # 创建Boss
        boss = Boss(
            boss_id=0,  # 自动生成
            boss_name=boss_name,
            boss_level=level_config["name"],
            hp=max_hp,
            max_hp=max_hp,
            atk=atk,
            defense=defense,
            stone_reward=stone_reward,
            create_time=int(time.time()),
            status=1  # 1=存活
        )
        
        boss_id = await self.db.ext.create_boss(boss)
        boss.boss_id = boss_id

        # v3.2.8：新 Boss 生成后清理上一只 Boss 的挑战记录
        # （次数本就按 boss_id 计数，新 Boss 自然重置；此处只做数据瘦身）
        try:
            await self.db.ext.cleanup_boss_challenges(boss_id)
        except Exception:
            pass
        
        msg = f"""
👹 Boss降临
━━━━━━━━━━━━━━━

{boss_name}降临世间！

境界：{level_config["name"]}
HP：{max_hp}
ATK：{atk}
防御：{defense}%减伤
奖励：{stone_reward}灵石

快来挑战吧！
        """.strip()
        
        return True, msg, boss
    
    async def challenge_boss(
        self,
        user_id: str
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        挑战Boss

        Args:
            user_id: 挑战者ID

        Returns:
            (成功标志, 消息, 战斗结果)
        """
        # 1. 检查玩家
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", None

        # 2. 检查Boss是否存在
        boss = await self.db.ext.get_active_boss()
        if not boss:
            return False, "❌ 当前没有Boss！", None

        # 3. 挑战 Boss 为瞬时操作，不受闭关/历练/秘境影响

        # 3.5 境界门槛：避免低境界玩家挑战远超自身的 Boss（既送死又无收益）
        boss_level_index = 0
        for lvl in self.levels:
            if lvl["name"] == boss.boss_level:
                boss_level_index = lvl["level_index"]
                break
        if boss_level_index and (boss_level_index - player.level_index) > 6:
            return False, (
                f"❌ 你的境界远低于 Boss『{boss.boss_name}』（{boss.boss_level}境），暂无法挑战！\n"
                f"💡 先提升境界再来吧。"
            ), None

        # 3.6 v3.2.8 挑战次数 + 冷却闸门（防止无限连发刷奖励 / 磨血抢人头）
        gate_msg = await self._check_challenge_gate(user_id, boss)
        if gate_msg:
            return False, gate_msg, None

        # 3.7 v3.2.8 原子占位一次挑战机会（并发安全：同一玩家并发请求
        #     最多只有一条能占位成功，杜绝双挑战重复领奖）
        now = int(time.time())
        reserved = await self.db.ext.reserve_boss_challenge(
            boss.boss_id, user_id, now, self.max_challenges
        )
        if not reserved:
            used = await self.db.ext.get_boss_challenge_count(boss.boss_id, user_id)
            return False, (
                f"❌ 你对『{boss.boss_name}』的挑战次数已用尽（{used}/{self.max_challenges} 次）\n"
                f"💡 每只 Boss 每位道友只能出手有限次，等待下一只 Boss 现世吧。"
            ), None

        try:
            return await self._run_boss_battle(user_id, player, boss)
        except Exception:
            # 战斗异常：回滚已占位的次数，避免玩家白白损失挑战机会
            await self.db.ext.release_boss_challenge(boss.boss_id, user_id)
            raise

    async def _run_boss_battle(
        self, user_id: str, player: Player, boss: Boss
    ) -> Tuple[bool, str, Optional[Dict]]:
        """执行 Boss 战斗并结算（调用方需已完成次数占位）"""
        # 4. 计算玩家战斗属性（每次挑战都重新计算，使用最新修为/传承/装备，避免陈旧属性）
        impart_info = await self.db.ext.get_impart_info(user_id)
        hp_buff = impart_info.impart_hp_per if impart_info else 0.0
        mp_buff = impart_info.impart_mp_per if impart_info else 0.0
        atk_buff = impart_info.impart_atk_per if impart_info else 0.0
        crit_rate_buff = impart_info.impart_know_per if impart_info else 0.0

        equip = CombatManager.calculate_equipment_bonus(
            self.config_manager, player, await self.db.get_refine_map(player.user_id)
        )
        player_stats = CombatManager.calculate_combat_stats(
            player, impart_info, equip["atk"], equip["defense"]
        )
        player_stats.crit_rate = int(crit_rate_buff * 100)  # 转换为百分比

        # 将刷新后的属性写回玩家，保证结算一致（修复此前沿用旧 HP/ATK 的问题）
        # 注：气血在此仍按满值入场——Boss 战在本插件中是「独立副本」式战斗
        # （气血不是核心资源模型，任何一次决斗/切磋都会重算满血）。
        # 防止「无限挑战」不靠扣气血，而靠次数上限 + 冷却 + 安慰奖封顶三重闸门，
        # 避免引入「血量卡死无法再战」的新问题。
        player.hp = player_stats.hp
        player.mp = player_stats.mp
        player.atk = player_stats.atk
        await self.db.update_player(player)
        
        # 创建Boss战斗属性
        boss_stats = CombatStats(
            user_id=str(boss.boss_id),
            name=boss.boss_name,
            hp=boss.hp,
            max_hp=boss.max_hp,
            mp=boss.max_hp,  # Boss的MP等于HP
            max_mp=boss.max_hp,
            atk=boss.atk,
            defense=boss.defense,
            crit_rate=30,  # Boss固定30%会心率
            exp=boss.stone_reward  # 奖励存在exp字段
        )
        
        # 5. 开始战斗
        battle_result = self.combat_mgr.player_vs_boss(player_stats, boss_stats)

        # 注：挑战次数已在进入战斗前通过 reserve_boss_challenge 原子占位，
        #     此处无需再记录（避免重复计数）。

        # 6. 处理战斗结果
        winner = battle_result["winner"]
        reward = battle_result["reward"]

        if winner == user_id:
            # 玩家在战斗模拟中获胜。
            # ⚠️ v3.2.8：Boss 死亡是**条件 UPDATE**（`status = 1` 才置 0），
            #    并发挑战时可能两人同时算出「胜利」，但只有**首个真正完成击杀**
            #    的玩家（rowcount > 0）能拿完整奖励并发击杀广播；
            #    其余人视为「打在尸体上」，按安慰奖结算，避免双领奖。
            actually_killed = await self.db.ext.defeat_boss(boss.boss_id)

            if not actually_killed:
                # Boss 已被他人抢先击杀 → 降级为安慰奖
                consolation = self._cap_consolation(reward, boss)
                result_msg = f"""
⚔️ 讨伐完成（BOSS已被他人斩杀）

你的最后一击赶在他人之前落下，
但『{boss.boss_name}』已被其他道友先行击杀。

战斗回合数：{battle_result['rounds']}
安慰奖：{consolation}灵石
                """.strip()
                if consolation > 0:
                    player.gold += consolation
                reward = consolation
                player.hp = battle_result["player_final_hp"]
                player.mp = battle_result["player_final_mp"]
                await self.db.update_player(player)
                combat_log = "\n".join(battle_result["combat_log"])
                # ⚠️ 标记「非击杀者」：调用方据此避免重复广播击杀消息
                battle_result["actually_killed"] = False
                return True, combat_log + "\n\n" + result_msg, battle_result

            # 玩家胜利（且确为击杀者）
            boss.status = 0  # 标记Boss为已击败
            battle_result["actually_killed"] = True

            # 发放奖励
            player.gold += reward

            # 物品掉落
            item_msg = ""
            roll_msg = ""
            dropped_items = []
            if self.storage_ring_manager:
                dropped_items = await self._roll_boss_drops(player, boss)
                roll_msg = self._get_boss_roll_msg()
                if dropped_items:
                    item_lines = []
                    for item_name, count in dropped_items:
                        success, _ = await self.storage_ring_manager.store_item(player, item_name, count, silent=True)
                        if success:
                            item_lines.append(f"  · {item_name} x{count}")
                        else:
                            item_lines.append(f"  · {item_name} x{count}（储物戒已满，丢失）")
                    if item_lines:
                        item_msg = "\n\n📦 获得物品：\n" + "\n".join(item_lines)

            roll_block = f"\n🎰 命数判定：\n{roll_msg}" if roll_msg else ""
            result_msg = f"""
🎉 挑战成功！
━━━━━━━━━━━━━━━

你成功击败了『{boss.boss_name}』！

战斗回合数：{battle_result['rounds']}
获得灵石：{reward}{item_msg}{roll_block}

{player_stats.name}
HP：{battle_result['player_final_hp']}/{player_stats.max_hp}
            """.strip()
        else:
            # 玩家失败
            boss.hp = battle_result["boss_final_hp"]
            await self.db.ext.update_boss(boss)

            # ⚠️ v3.2.8 安慰奖收敛：按「造成伤害占 Boss 初始血量」给奖励，
            #    但封顶为完整奖励的 50%——失败最多算半个成功。
            #    原因：次数上限限制了单玩家刷奖，但「每个玩家都拿一份安慰奖」
            #    在人多的服务器仍会造成灵石通胀（人数 × 完整奖励）。
            consolation = self._cap_consolation(reward, boss)

            result_msg = f"""
💀 挑战失败
━━━━━━━━━━━━━━━

你被『{boss.boss_name}』击败了！

战斗回合数：{battle_result['rounds']}
安慰奖：{consolation}灵石

{boss.boss_name} 剩余HP：{boss.hp}/{boss.max_hp}
            """.strip()

            # 即使失败也给予部分奖励（封顶后）
            if consolation > 0:
                player.gold += consolation
            reward = consolation

        # 更新玩家HP/MP
        player.hp = battle_result["player_final_hp"]
        player.mp = battle_result["player_final_mp"]
        await self.db.update_player(player)

        # 返回完整战斗日志
        combat_log = "\n".join(battle_result["combat_log"])
        full_msg = combat_log + "\n\n" + result_msg

        return True, full_msg, battle_result

    # ===== v3.2.8 挑战次数 / 冷却闸门 =====

    @staticmethod
    def _cap_consolation(reward: int, boss: Boss) -> int:
        """v3.2.8 安慰奖封顶：失败奖励最多为完整奖励的 50%

        抽成独立方法便于单独测试与复用。封顶依据是 Boss 的完整奖励
        （`stone_reward`），而非玩家造成的伤害比例。
        """
        consolation_cap = int(boss.stone_reward * 0.5)
        return min(int(reward), consolation_cap)

    async def _check_challenge_gate(self, user_id: str, boss: Boss) -> str:
        """检查挑战次数与冷却限制

        Returns:
            空字符串 = 允许挑战；非空 = 拒绝原因（可直接展示给玩家）
        """
        now = int(time.time())

        # 冷却检查（先判冷却，让玩家的提示更贴近「等一会儿再来」）
        if self.challenge_cooldown > 0:
            record = await self.db.ext.get_boss_challenge(boss.boss_id, user_id)
            last_time = record["last_challenge_time"] if record else 0
            if last_time and (now - last_time) < self.challenge_cooldown:
                remain = self.challenge_cooldown - (now - last_time)
                return (
                    f"❌ 挑战冷却中，还需 {remain // 60} 分 {remain % 60} 秒\n"
                    f"💡 世界Boss每场激战需休整片刻，稍后再来。"
                )

        # 次数检查
        if self.max_challenges > 0:
            used = await self.db.ext.get_boss_challenge_count(boss.boss_id, user_id)
            if used >= self.max_challenges:
                return (
                    f"❌ 你对『{boss.boss_name}』的挑战次数已用尽（{used}/{self.max_challenges} 次）\n"
                    f"💡 每只 Boss 每位道友只能出手有限次，等待下一只 Boss 现世吧。"
                )

        return ""
    
    async def get_boss_info(self) -> Tuple[bool, str, Optional[Boss]]:
        """
        获取当前Boss信息

        Returns:
            (成功标志, 消息, Boss对象)
        """
        boss = await self.db.ext.get_active_boss()
        if not boss:
            return False, "❌ 当前没有Boss！", None

        hp_percent = (boss.hp / boss.max_hp) * 100

        msg = f"""
👹 当前Boss
━━━━━━━━━━━━━━━

名称：{boss.boss_name}
境界：{boss.boss_level}

HP：{boss.hp}/{boss.max_hp} ({hp_percent:.1f}%)
ATK：{boss.atk}
防御：{boss.defense}%减伤

奖励：{boss.stone_reward}灵石

使用 /挑战Boss 来挑战！
        """.strip()

        return True, msg, boss

    async def get_boss_info_for_user(self, user_id: str) -> Tuple[bool, str, Optional[Boss]]:
        """获取当前 Boss 信息（附带玩家本人的挑战额度）

        与 `get_boss_info` 的区别：额外显示该玩家对当前这只 Boss 的
        已用次数与剩余次数，让「挑战限制」对玩家可见、可预期。
        """
        success, msg, boss = await self.get_boss_info()
        if not success or boss is None:
            return success, msg, boss

        extra_lines = []
        if self.max_challenges > 0:
            used = await self.db.ext.get_boss_challenge_count(boss.boss_id, user_id)
            remain = max(0, self.max_challenges - used)
            extra_lines.append(
                f"🎯 你的挑战次数：{used}/{self.max_challenges}（剩余 {remain} 次）"
            )
        if self.challenge_cooldown > 0:
            record = await self.db.ext.get_boss_challenge(boss.boss_id, user_id)
            last_time = record["last_challenge_time"] if record else 0
            if last_time:
                remain_cd = self.challenge_cooldown - (int(time.time()) - last_time)
                if remain_cd > 0:
                    extra_lines.append(
                        f"⏳ 挑战冷却：还需 {remain_cd // 60} 分 {remain_cd % 60} 秒"
                    )

        if extra_lines:
            msg = msg + "\n━━━━━━━━━━━━━━━\n" + "\n".join(extra_lines)

        return True, msg, boss
    
    async def auto_spawn_boss(self, player_count: int = 0) -> Tuple[bool, str, Optional[Boss]]:
        """
        自动生成Boss（定时任务使用）
        根据服务器玩家数量和平均等级自动调整Boss难度
        
        Args:
            player_count: 玩家数量（用于调整难度）
            
        Returns:
            (成功标志, 消息, Boss对象)
        """
        # 检查是否已有Boss
        existing_boss = await self.db.ext.get_active_boss()
        if existing_boss:
            return False, "当前已有Boss存在", None
        
        # 获取所有玩家的平均等级
        all_players = await self.db.get_all_players()
        if not all_players:
            # 没有玩家，生成低级Boss
            level_config = self.levels[0]
            base_exp = 50000
        else:
            # 计算平均修为
            total_exp = sum(p.experience for p in all_players)
            avg_exp = total_exp // len(all_players) if all_players else 50000
            
            # 根据平均修为选择Boss等级
            for config in reversed(self.levels):
                if avg_exp >= config.get("level_index", 0) * 10000:
                    level_config = config
                    break
            else:
                level_config = self.levels[0]
            
            # Boss修为比平均稍高
            base_exp = int(avg_exp * 1.2)
        
        # 生成Boss
        return await self.spawn_boss(base_exp, level_config)
    
    async def _roll_boss_drops(self, player: Player, boss: Boss) -> List[Tuple[str, int]]:
        """
        根据Boss等级随机掉落物品
        
        Args:
            player: 玩家对象
            boss: Boss对象
            
        Returns:
            掉落物品列表 [(物品名, 数量), ...]
        """
        dropped_items = []
        
        # 根据Boss等级确定掉落表
        boss_level_index = 0
        for level in self.levels:
            if level["name"] == boss.boss_level:
                boss_level_index = level["level_index"]
                break
        
        if boss_level_index <= 6:  # 练气-金丹
            drop_table = self.BOSS_DROP_TABLE["low"]
        elif boss_level_index <= 12:  # 元婴-化神
            drop_table = self.BOSS_DROP_TABLE["mid"]
        else:  # 炼虚及以上
            drop_table = self.BOSS_DROP_TABLE["high"]
        
        # Boss击杀100%掉落至少1件物品
        total_weight = sum(item["weight"] for item in drop_table)
        roll = random.randint(1, total_weight)
        
        current_weight = 0
        for item in drop_table:
            current_weight += item["weight"]
            if roll <= current_weight:
                count = random.randint(item["min"], item["max"])
                dropped_items.append((item["name"], count))
                break
        
        # 高级Boss有额外掉落概率
        if boss_level_index >= 9:  # 元婴及以上
            extra_chance = 50 if boss_level_index < 15 else 70
            if random.randint(1, 100) <= extra_chance:
                roll = random.randint(1, total_weight)
                current_weight = 0
                for item in drop_table:
                    current_weight += item["weight"]
                    if roll <= current_weight:
                        count = random.randint(item["min"], item["max"])
                        dropped_items.append((item["name"], count))
                        break
                self._last_extra_chance = extra_chance
                self._last_extra_hit = True
            else:
                self._last_extra_chance = extra_chance
                self._last_extra_hit = False
        else:
            self._last_extra_chance = 0
            self._last_extra_hit = False
        
        return dropped_items

    def _get_boss_roll_msg(self) -> str:
        """生成 Boss 掉落概率判定说明"""
        from ..utils.probability import describe_roll

        lines = [describe_roll("必落物品", 100, True)]
        extra_chance = getattr(self, "_last_extra_chance", 0)
        if extra_chance:
            lines.append(
                describe_roll(
                    "额外掉落", extra_chance, getattr(self, "_last_extra_hit", False)
                )
            )
        return "\n".join(lines)
