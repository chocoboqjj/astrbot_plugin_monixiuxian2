# managers/blessed_land_manager.py
"""洞天福地系统管理器"""
import time
import json
from typing import Tuple, Optional, Dict
from ..data import DataBase
from ..models import Player

__all__ = ["BlessedLandManager"]

# 洞天配置
# 经济平衡（v3.2.5）：gold_per_hour 按「价格 ÷ 7 天 ÷ 24 小时」标定，
# 即各档洞天均约 7 天回本（约 14.3%/天），洞天回归「优质长期资产」定位。
# 存储说明：gold_per_hour 会落库到 blessed_lands 表（升级时按 1+level*0.15 重算），
# 故改常量只影响新购；存量洞天由 data/migration.py 的 v21 迁移重算。
BLESSED_LANDS = {
    1: {"name": "小洞天", "price": 10000, "exp_bonus": 0.05, "gold_per_hour": 60, "max_level": 5, "max_exp_per_hour": 5000},
    2: {"name": "中洞天", "price": 50000, "exp_bonus": 0.10, "gold_per_hour": 300, "max_level": 10, "max_exp_per_hour": 15000},
    3: {"name": "大洞天", "price": 200000, "exp_bonus": 0.20, "gold_per_hour": 1200, "max_level": 15, "max_exp_per_hour": 30000},
    4: {"name": "福地", "price": 500000, "exp_bonus": 0.30, "gold_per_hour": 3000, "max_level": 20, "max_exp_per_hour": 50000},
    5: {"name": "洞天福地", "price": 1000000, "exp_bonus": 0.50, "gold_per_hour": 6000, "max_level": 30, "max_exp_per_hour": 100000},
}


class BlessedLandManager:
    """洞天福地管理器"""
    
    def __init__(self, db: DataBase):
        self.db = db
    
    async def _get_active_loan_notice(self, player: Player) -> str:
        """返回贷款存续期间的洞天产出托管提示（无贷款则返回空串）。

        设计说明（v3.2.5 借贷套利防护）：
          洞天福地为生息资产，历史漏洞是玩家可用「贷款 → 买洞天 → 用洞天
          被动收益还贷」的闭环净赚并白得生息资产（杠杆套利）。
          根因是洞天收益率远高于贷款利率，且还贷后玩家仍保留生息资产，
          单纯调利率无法根除。
          现改为「**允许**在贷款存续期购置/升级洞天，但**洞天产出被银行托管**，
          还清贷款后方可收取」：
            · 套利路径被切断——洞天收益无法用于还贷，玩家必须用其他途径
              自筹本息，纯亏利息，无法净赚；
            · 玩家仍可在资金周转困难时先用洞天顶一顶，还清贷款后立即恢复
              收取，玩法自由度不受影响。
        """
        loan = await self.db.ext.get_active_loan(player.user_id)
        if not loan:
            return ""
        return (
            "\n⚠️ 你当前有未结清的贷款，洞天产出将被银行托管，"
            "还清贷款（/还款）后方可收取。"
        )

    async def get_user_blessed_land(self, user_id: str) -> Optional[Dict]:
        """获取用户洞天信息"""
        async with self.db.conn.execute(
            "SELECT * FROM blessed_lands WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    async def purchase_blessed_land(self, player: Player, land_type: int) -> Tuple[bool, str]:
        """购买洞天"""
        if land_type not in BLESSED_LANDS:
            return False, "❌ 无效的洞天类型。可选：1-小洞天 2-中洞天 3-大洞天 4-福地 5-洞天福地"

        # 借贷套利防护：允许在贷款存续期购置，但产出将被托管至还清贷款
        loan_notice = await self._get_active_loan_notice(player)

        # 检查是否已有洞天
        existing = await self.get_user_blessed_land(player.user_id)
        if existing:
            return False, f"❌ 你已拥有【{existing['land_name']}】，请先升级而非重新购买。"
        
        land_config = BLESSED_LANDS[land_type]
        price = land_config["price"]
        
        if player.gold < price:
            return False, f"❌ 灵石不足！购买{land_config['name']}需要 {price:,} 灵石。"
        
        # 扣除灵石
        player.gold -= price
        await self.db.update_player(player)
        
        # 创建洞天
        await self.db.conn.execute(
            """
            INSERT INTO blessed_lands (user_id, land_type, land_name, level, exp_bonus, 
                                       gold_per_hour, last_collect_time)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            """,
            (player.user_id, land_type, land_config["name"], land_config["exp_bonus"],
             land_config["gold_per_hour"], int(time.time()))
        )
        await self.db.conn.commit()
        
        return True, (
            f"✨ 恭喜获得【{land_config['name']}】！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"闭关修炼加成：+{land_config['exp_bonus']:.0%}\n"
            f"挂机产出：{land_config['gold_per_hour']} 灵石 + "
            f"{land_config.get('max_exp_per_hour', 5000)} 修为 /小时\n"
            f"━━━━━━━━━━━━━━━\n"
            f"使用 /洞天收取 领取产出"
            f"{loan_notice}"
        )

    async def upgrade_blessed_land(self, player: Player) -> Tuple[bool, str]:
        """升级洞天"""
        land = await self.get_user_blessed_land(player.user_id)
        if not land:
            return False, "❌ 你还没有洞天！使用 /购买洞天 <类型> 获取。"

        # 借贷套利防护：允许在贷款存续期升级，但产出将被托管至还清贷款
        loan_notice = await self._get_active_loan_notice(player)

        land_type = land["land_type"]
        current_level = land["level"]
        config = BLESSED_LANDS.get(land_type, BLESSED_LANDS[1])
        
        if current_level >= config["max_level"]:
            return False, f"❌ 你的{land['land_name']}已达最高等级 {config['max_level']}！"
        
        # 升级费用：基础价格 × 当前等级 × 0.5
        upgrade_cost = int(config["price"] * current_level * 0.5)
        
        if player.gold < upgrade_cost:
            return False, f"❌ 灵石不足！升级需要 {upgrade_cost:,} 灵石。"
        
        # 升级加成
        new_level = current_level + 1
        new_exp_bonus = config["exp_bonus"] * (1 + new_level * 0.1)
        new_gold_per_hour = int(config["gold_per_hour"] * (1 + new_level * 0.15))
        
        player.gold -= upgrade_cost
        await self.db.update_player(player)
        
        await self.db.conn.execute(
            """
            UPDATE blessed_lands SET level = ?, exp_bonus = ?, gold_per_hour = ?
            WHERE user_id = ?
            """,
            (new_level, new_exp_bonus, new_gold_per_hour, player.user_id)
        )
        await self.db.conn.commit()
        
        return True, (
            f"🎉 {land['land_name']}升级到 Lv.{new_level}！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"闭关修炼加成：+{new_exp_bonus:.1%}\n"
            f"挂机产出：{new_gold_per_hour} 灵石 + "
            f"{config.get('max_exp_per_hour', 5000)} 修为 /小时\n"
            f"花费：{upgrade_cost:,} 灵石"
            f"{loan_notice}"
        )

    async def collect_income(self, player: Player) -> Tuple[bool, str]:
        """收取洞天产出"""
        land = await self.get_user_blessed_land(player.user_id)
        if not land:
            return False, "❌ 你还没有洞天！"

        # 借贷套利防护：贷款未结清时冻结洞天收取（产出被银行托管）。
        # 防止已用贷款购置洞天的玩家，把洞天被动收益装进口袋去还贷、
        # 从而白得生息资产。玩家须先用其他途径还清贷款，之后洞天照常收取。
        # （无活跃贷款者不受影响；收取上限 24h 使冻结期最多只损失溢出部分。）
        if await self.db.ext.get_active_loan(player.user_id):
            return False, (
                "⚠️ 你当前有未结清的贷款，洞天产出已被银行托管，无法收取。\n"
                "━━━━━━━━━━━━━━━\n"
                "请先还清贷款（/还款），再收取洞天产出。\n"
                "📌 防止「借贷款买洞天、用洞天收益还贷」的套利行为。"
            )
        
        last_collect = land["last_collect_time"]
        now = int(time.time())
        hours_passed = (now - last_collect) / 3600
        
        if hours_passed < 1:
            remaining = int(3600 - (now - last_collect))
            minutes = remaining // 60
            return False, f"❌ 收取冷却中，还需 {minutes} 分钟。"
        
        # 计算产出（最多24小时）
        hours = min(24, int(hours_passed))
        gold_income = land["gold_per_hour"] * hours
        
        # 计算修为收益
        # 设计说明：
        #   - exp_bonus 是「修炼加成」百分比，直接作用于闭关修炼速度（见 player_handler 闭关结算）
        #   - 洞天的**挂机修为产出**按配置项 max_exp_per_hour 固定发放，
        #     不再以 player.experience 为基数（那会造成「越强收益越多」的复利膨胀）
        land_type = land["land_type"]
        config = BLESSED_LANDS.get(land_type, BLESSED_LANDS[1])
        max_exp_per_hour = config.get("max_exp_per_hour", 5000)
        exp_income = max_exp_per_hour * hours
        
        player.gold += gold_income
        player.experience += exp_income
        await self.db.update_player(player)
        
        await self.db.conn.execute(
            "UPDATE blessed_lands SET last_collect_time = ? WHERE user_id = ?",
            (now, player.user_id)
        )
        await self.db.conn.commit()
        
        return True, (
            f"✅ 洞天收取成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"累计时长：{hours} 小时\n"
            f"获得灵石：+{gold_income:,}\n"
            f"获得修为：+{exp_income:,}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"当前灵石：{player.gold:,}"
        )
    
    async def get_blessed_land_info(self, user_id: str) -> str:
        """获取洞天信息展示"""
        land = await self.get_user_blessed_land(user_id)
        if not land:
            return (
                "🏔️ 洞天福地\n"
                "━━━━━━━━━━━━━━━\n"
                "你还没有洞天！\n\n"
                "可购买的洞天：\n"
                "  1. 小洞天 - 10,000灵石 (60灵石/时)\n"
                "  2. 中洞天 - 50,000灵石 (300灵石/时)\n"
                "  3. 大洞天 - 200,000灵石 (1,200灵石/时)\n"
                "  4. 福地 - 500,000灵石 (3,000灵石/时)\n"
                "  5. 洞天福地 - 1,000,000灵石 (6,000灵石/时)\n\n"
                "各档约 7 天回本，产出最多累积 24 小时\n\n"
                "💡 使用 /购买洞天 <编号>"
            )

        now = int(time.time())
        hours_since = (now - land["last_collect_time"]) / 3600
        pending_gold = int(min(24, hours_since) * land["gold_per_hour"])

        # 贷款存续期提示：产出被托管，暂不可收取
        escrow_hint = ""
        if await self.db.ext.get_active_loan(user_id):
            escrow_hint = (
                f"⚠️ 你有未结清贷款，产出被银行托管暂不可收取"
                f"（还清贷款后累计上限 24 小时）\n"
            )

        return (
            f"🏔️ {land['land_name']} (Lv.{land['level']})\n"
            f"━━━━━━━━━━━━━━━\n"
            f"闭关修炼加成：+{land['exp_bonus']:.1%}\n"
            f"挂机产出：{land['gold_per_hour']} 灵石 + "
            f"{BLESSED_LANDS.get(land['land_type'], BLESSED_LANDS[1]).get('max_exp_per_hour', 5000)} 修为 /小时\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{escrow_hint}"
            f"待收取：约 {pending_gold:,} 灵石\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 /升级洞天 | /洞天收取"
        )
