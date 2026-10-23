# managers/spirit_eye_manager.py
"""天地灵眼系统管理器

v3.2.6 改造要点：
  1. **灵眼有时效**：每档灵眼都有独立寿命（越高级时效越短），到期自动消散；
     消散前先把持有者未收取的修为结算给他，不吞收益。
  2. **被占灵眼依然可见**：`get_all_spirit_eyes()` 返回所有未过期灵眼（含已被
     占据的），玩家能看到别人的灵眼并据此发起争夺。
  3. **支持 @人 争夺**：对他人灵眼发起切磋式 PVP，胜者夺得灵眼；发起方有冷却，
     胜方有守护期，避免骚扰。
"""
import time
import random
from typing import Tuple, Optional, Dict, List
from ..data import DataBase
from ..models import Player
from .combat_manager import CombatManager

__all__ = ["SpiritEyeManager"]

# 灵眼配置
# lifetime_hours：灵眼自刷新起存在的时长（时效）。每提升一档时效减半——
# 高阶灵眼产出更高但窗口更短，形成「高收益 = 短窗口」的争夺节奏。
SPIRIT_EYE_TYPES = {
    1: {"name": "下品灵眼", "exp_per_hour": 500, "spawn_rate": 50, "lifetime_hours": 24},
    2: {"name": "中品灵眼", "exp_per_hour": 2000, "spawn_rate": 30, "lifetime_hours": 12},
    3: {"name": "上品灵眼", "exp_per_hour": 8000, "spawn_rate": 15, "lifetime_hours": 6},
    4: {"name": "极品灵眼", "exp_per_hour": 30000, "spawn_rate": 5, "lifetime_hours": 3},
}

# 发起争夺的冷却（秒）：限制发起频率，杜绝骚扰
EYE_CLAIM_COOLDOWN = 300
# 守护窗口（秒）：守住/夺得灵眼后的一段时间内不可再被争夺
EYE_PROTECT_DURATION = 300
# 单个灵眼最多累积的收益小时数（与原有收取上限保持一致）
MAX_ACCUMULATE_HOURS = 24


def format_remaining(seconds: int) -> str:
    """把剩余秒数格式化成「X 天 Y 小时」/「X 小时 Y 分」/「X 分」。"""
    seconds = max(0, int(seconds))
    if seconds >= 86400:
        return f"{seconds // 86400} 天 {(seconds % 86400) // 3600} 小时"
    if seconds >= 3600:
        return f"{seconds // 3600} 小时 {(seconds % 3600) // 60} 分"
    return f"{seconds // 60} 分"


class SpiritEyeManager:
    """天地灵眼管理器"""

    def __init__(self, db: DataBase, combat_mgr: CombatManager = None, config_manager=None):
        self.db = db
        self.combat_mgr = combat_mgr
        self.config_manager = config_manager

    # ===== 基础查询 =====

    async def get_user_spirit_eye(self, user_id: str) -> Optional[Dict]:
        """获取用户占据的灵眼（已失效的灵眼返回 None）。"""
        eye = await self._get_user_eye_raw(user_id)
        if eye and not self._is_expired(eye):
            return eye
        return None

    async def _get_user_eye_raw(self, user_id: str) -> Optional[Dict]:
        """获取用户占据的灵眼原始记录（不做过期过滤）。"""
        async with self.db.conn.execute(
            "SELECT * FROM spirit_eyes WHERE owner_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

    async def get_available_spirit_eyes(self) -> List[Dict]:
        """获取所有无主且未过期的灵眼。"""
        async with self.db.conn.execute(
            "SELECT * FROM spirit_eyes WHERE owner_id IS NULL OR owner_id = ''"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows if not self._is_expired(dict(row))]

    async def get_all_spirit_eyes(self) -> List[Dict]:
        """获取所有未过期的灵眼（无论是否有主）——用于展示被占据的灵眼。"""
        async with self.db.conn.execute(
            "SELECT * FROM spirit_eyes ORDER BY eye_id ASC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows if not self._is_expired(dict(row))]

    # ===== 时效处理 =====

    @staticmethod
    def _is_expired(eye: Dict) -> bool:
        """灵眼是否已过时效（expire_time 为 0 表示旧数据无时效，视为未过期）。"""
        expire_time = int(eye.get("expire_time") or 0)
        if expire_time <= 0:
            return False
        return expire_time <= int(time.time())

    @staticmethod
    def _lifetime_seconds(eye_type: int) -> int:
        config = SPIRIT_EYE_TYPES.get(eye_type, SPIRIT_EYE_TYPES[1])
        return int(config["lifetime_hours"]) * 3600

    async def _settle_pending_exp(self, eye: Dict, end_time: int) -> int:
        """结算灵眼已累积但尚未收取的修为（时效到期 / 灵眼易主时调用）。

        end_time：结算截止时间（到期用 expire_time，易主用当前时间）。
        返回结算出的修为数（0 表示无可结算）。
        """
        owner_id = eye.get("owner_id")
        if not owner_id:
            return 0
        last = int(eye.get("last_collect_time") or eye.get("claim_time") or 0)
        if last <= 0 or end_time <= last:
            return 0
        hours = min(MAX_ACCUMULATE_HOURS, (end_time - last) // 3600)
        if hours <= 0:
            return 0
        exp_income = int(eye.get("exp_per_hour") or 0) * hours
        if exp_income <= 0:
            return 0
        owner = await self.db.get_player_by_id(owner_id)
        if owner:
            owner.experience += exp_income
            await self.db.update_player(owner)
        return exp_income

    async def _cleanup_expired_eyes(self) -> List[Dict]:
        """清理已过时效的灵眼：先给持有者结算未收取修为，再删除该灵眼。

        返回被清理的灵眼记录列表（每项含 eye 与 settled 字段），便于向玩家
        提示「灵眼消散，未收修为已自动结算」。
        """
        now = int(time.time())
        async with self.db.conn.execute(
            "SELECT * FROM spirit_eyes WHERE expire_time > 0 AND expire_time <= ?",
            (now,)
        ) as cursor:
            rows = await cursor.fetchall()

        if not rows:
            return []

        cleaned = []
        for row in rows:
            eye = dict(row)
            # 先结算持有者已累积的修为（不吞收益）
            settled = await self._settle_pending_exp(eye, int(eye.get("expire_time") or now))
            await self.db.conn.execute(
                "DELETE FROM spirit_eyes WHERE eye_id = ?",
                (eye["eye_id"],)
            )
            cleaned.append({"eye": eye, "settled": settled})
        await self.db.conn.commit()
        return cleaned

    async def cleanup_expired_eyes(self) -> int:
        """清理已过时效的灵眼，返回被清理的数量。"""
        cleaned = await self._cleanup_expired_eyes()
        return len(cleaned)

    # ===== 刷新与抢占 =====

    async def spawn_spirit_eye(self) -> Tuple[bool, str]:
        """生成新灵眼（定时调用）"""
        # 先清理过期灵眼，避免表里堆积失效数据
        await self._cleanup_expired_eyes()

        # 随机生成灵眼类型
        roll = random.randint(1, 100)
        eye_type = 1
        cumulative = 0
        for etype, config in SPIRIT_EYE_TYPES.items():
            cumulative += config["spawn_rate"]
            if roll <= cumulative:
                eye_type = etype
                break

        config = SPIRIT_EYE_TYPES[eye_type]
        now = int(time.time())
        expire_time = now + self._lifetime_seconds(eye_type)

        await self.db.conn.execute(
            """
            INSERT INTO spirit_eyes (eye_type, eye_name, exp_per_hour, spawn_time, expire_time)
            VALUES (?, ?, ?, ?, ?)
            """,
            (eye_type, config["name"], config["exp_per_hour"], now, expire_time)
        )
        await self.db.conn.commit()

        return True, (
            f"天地间出现了一处【{config['name']}】！\n"
            f"⏳ 仅存 {config['lifetime_hours']} 小时，速来抢占！"
        )

    async def claim_spirit_eye(self, player: Player, eye_id: int) -> Tuple[bool, str]:
        """抢占无主灵眼（按编号）"""
        await self._cleanup_expired_eyes()

        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            # 检查是否已有灵眼
            existing = await self.get_user_spirit_eye(player.user_id)
            if existing:
                await self.db.conn.rollback()
                return False, (
                    f"❌ 你已占据【{existing['eye_name']}】，无法再抢占。\n"
                    f"💡 可先 /释放灵眼 释放后再来。"
                )

            # 获取目标灵眼（带锁）
            async with self.db.conn.execute(
                "SELECT * FROM spirit_eyes WHERE eye_id = ?",
                (eye_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    await self.db.conn.rollback()
                    return False, "❌ 灵眼不存在（或已消散）。"
                eye = dict(row)

            if self._is_expired(eye):
                await self.db.conn.rollback()
                return False, "❌ 此灵眼已过时效、已然消散。"

            # 检查是否有主
            if eye["owner_id"]:
                owner_name = eye["owner_name"] or "某人"
                await self.db.conn.rollback()
                return False, (
                    f"❌ 此灵眼已被【{owner_name}】占据。\n"
                    f"💡 可用 /抢占灵眼 @对方 发起争夺（切磋定胜负）。"
                )

            # 抢占
            now = int(time.time())
            cursor = await self.db.conn.execute(
                """UPDATE spirit_eyes SET owner_id = ?, owner_name = ?, claim_time = ?, last_collect_time = ?
                   WHERE eye_id = ? AND (owner_id IS NULL OR owner_id = '')""",
                (player.user_id, player.user_name or player.user_id[:8], now, now, eye_id)
            )

            # 先看影响行数再提交：rowcount 为 0 说明被他人抢先（并发）
            if cursor.rowcount == 0:
                await self.db.conn.rollback()
                return False, "❌ 抢占失败，灵眼已被他人占据。"
            await self.db.conn.commit()

            remain = format_remaining(int(eye.get("expire_time") or 0) - now)
            return True, (
                f"✨ 成功抢占【{eye['eye_name']}】！\n"
                f"━━━━━━━━━━━━━━━\n"
                f"每小时可获得 {eye['exp_per_hour']:,} 修为\n"
                f"剩余时效：{remain}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"使用 /灵眼收取 领取收益"
            )
        except Exception as e:
            await self.db.conn.rollback()
            raise

    # ===== 争夺（@人抢占） =====

    async def _get_eye_cooldown(self, user_id: str) -> int:
        """获取玩家上次发起灵眼争夺的时间（0 表示从未发起过）。"""
        try:
            async with self.db.conn.execute(
                "SELECT last_eye_time FROM combat_cooldowns WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return int(row[0] or 0)
        except Exception:
            pass
        return 0

    async def _update_eye_cooldown(self, user_id: str):
        """记录玩家本次发起灵眼争夺的时间。"""
        now = int(time.time())
        try:
            await self.db.conn.execute(
                """
                INSERT INTO combat_cooldowns (user_id, last_duel_time, last_spar_time, last_eye_time)
                VALUES (?, 0, 0, ?)
                ON CONFLICT(user_id) DO UPDATE SET last_eye_time = ?
                """,
                (user_id, now, now)
            )
            await self.db.conn.commit()
        except Exception:
            pass

    async def challenge_spirit_eye(self, attacker: Player, defender_id: str) -> Tuple[bool, str]:
        """挑战他人灵眼：切磋定胜负，胜者夺得该灵眼。

        Args:
            attacker: 挑战者
            defender_id: 被挑战者（灵眼占主）user_id

        Returns:
            (是否成功发起争夺, 提示文案)
        """
        if attacker.user_id == defender_id:
            return False, "❌ 不能争夺自己的灵眼。"

        defender = await self.db.get_player_by_id(defender_id)
        if not defender:
            return False, "❌ 对方还未踏入修仙之路。"

        await self._cleanup_expired_eyes()

        # 挑战者不能已占据灵眼
        mine = await self.get_user_spirit_eye(attacker.user_id)
        if mine:
            return False, (
                f"❌ 你已占据【{mine['eye_name']}】，无法再抢占。\n"
                f"💡 可先 /释放灵眼 释放后再来。"
            )

        # 目标必须确实占据灵眼
        eye = await self.get_user_spirit_eye(defender_id)
        if not eye:
            return False, "❌ 对方当前并未占据任何灵眼。"

        now = int(time.time())

        # 守护窗口：刚守住（或刚夺得）灵眼的一段时间内不可再被争夺
        protect_until = int(eye.get("protect_until") or 0)
        if protect_until > now:
            remain = format_remaining(protect_until - now)
            return False, (
                f"🛡️ 【{eye['eye_name']}】刚被守住，暂时无法争夺。\n"
                f"⏳ 守护剩余：{remain}"
            )

        # 发起方冷却
        last = await self._get_eye_cooldown(attacker.user_id)
        if last and (now - last) < EYE_CLAIM_COOLDOWN:
            remain = EYE_CLAIM_COOLDOWN - (now - last)
            return False, f"❌ 抢占冷却中，还需 {remain // 60} 分 {remain % 60} 秒。"

        # 战斗属性（与决斗 / 传承挑战共用唯一权威入口）
        atk_impart = await self.db.ext.get_impart_info(attacker.user_id)
        def_impart = await self.db.ext.get_impart_info(defender_id)
        atk_equip = CombatManager.calculate_equipment_bonus(self.config_manager, attacker)
        def_equip = CombatManager.calculate_equipment_bonus(self.config_manager, defender)
        atk_stats = CombatManager.calculate_combat_stats(
            attacker, atk_impart, atk_equip["atk"], atk_equip["defense"]
        )
        def_stats = CombatManager.calculate_combat_stats(
            defender, def_impart, def_equip["atk"], def_equip["defense"]
        )

        # 切磋式战斗（combat_type=1）：不消耗气血
        result = CombatManager.player_vs_player(atk_stats, def_stats, combat_type=1)
        log = "\n".join(result["combat_log"])
        await self._update_eye_cooldown(attacker.user_id)

        winner = result["winner"]
        if winner == "平局":
            await self.db.conn.execute(
                "UPDATE spirit_eyes SET protect_until = ? WHERE eye_id = ?",
                (now + EYE_PROTECT_DURATION, eye["eye_id"])
            )
            await self.db.conn.commit()
            return False, (
                f"{log}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"❌ 势均力敌，未能分出胜负，灵眼归属不变。"
            )

        if winner != attacker.user_id:
            # 挑战失败：守方保留灵眼并获得守护期
            await self.db.conn.execute(
                "UPDATE spirit_eyes SET protect_until = ? WHERE eye_id = ?",
                (now + EYE_PROTECT_DURATION, eye["eye_id"])
            )
            await self.db.conn.commit()
            return False, (
                f"{log}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"❌ 争夺失败，你技不如人。\n"
                f"🛡️ 对方灵眼获得 {EYE_PROTECT_DURATION // 60} 分钟守护期。"
            )

        # 挑战成功：结算原占主未收取的修为，然后易主
        await self._settle_pending_exp(eye, now)
        cursor = await self.db.conn.execute(
            """UPDATE spirit_eyes SET owner_id = ?, owner_name = ?, claim_time = ?,
                   last_collect_time = ?, protect_until = ?
               WHERE eye_id = ? AND owner_id = ?""",
            (
                attacker.user_id, attacker.user_name or attacker.user_id[:8],
                now, now, now + EYE_PROTECT_DURATION,
                eye["eye_id"], defender_id
            )
        )
        if cursor.rowcount == 0:
            await self.db.conn.rollback()
            return False, "❌ 争夺失败，灵眼归属已变更（可能已被他人夺走或消散）。"
        await self.db.conn.commit()

        remain = format_remaining(int(eye.get("expire_time") or 0) - now)
        return True, (
            f"{log}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"✨ 争夺成功！你夺得【{eye['eye_name']}】！\n"
            f"每小时可获得 {eye['exp_per_hour']:,} 修为\n"
            f"剩余时效：{remain}\n"
            f"🛡️ 守护期 {EYE_PROTECT_DURATION // 60} 分钟"
        )

    # ===== 收取与释放 =====

    async def collect_spirit_eye(self, player: Player) -> Tuple[bool, str]:
        """收取灵眼收益"""
        cleaned = await self._cleanup_expired_eyes()

        eye = await self.get_user_spirit_eye(player.user_id)
        if not eye:
            # 灵眼可能刚好到期消散——结算已自动完成，这里补一句提示
            settled = 0
            for item in cleaned:
                if item["eye"].get("owner_id") == player.user_id:
                    settled = max(settled, int(item["settled"] or 0))
            if settled > 0:
                return False, (
                    f"⌛ 你占据的灵眼已到时效、消散无踪。\n"
                    f"💰 未收取修为已自动结算：+{settled:,}"
                )
            return False, "❌ 你还没有占据灵眼（或灵眼已消散）。"

        # 使用last_collect_time计算收益，如果没有则使用claim_time
        last_collect = eye.get("last_collect_time") or eye.get("claim_time", 0)
        now = int(time.time())
        hours_passed = (now - last_collect) / 3600

        if hours_passed < 1:
            remaining = int(3600 - (now - last_collect))
            return False, f"❌ 收取冷却中，还需 {remaining // 60} 分钟。"

        # 计算收益（最多 MAX_ACCUMULATE_HOURS 小时，且不超过灵眼剩余时效）
        hours = min(MAX_ACCUMULATE_HOURS, int(hours_passed))
        expire_time = int(eye.get("expire_time") or 0)
        if expire_time > 0:
            hours = min(hours, max(0, (expire_time - last_collect) // 3600))
        if hours <= 0:
            return False, "❌ 收取冷却中，还需 60 分钟。"

        exp_income = eye["exp_per_hour"] * hours

        player.experience += exp_income
        await self.db.update_player(player)

        # 更新last_collect_time
        await self.db.conn.execute(
            "UPDATE spirit_eyes SET last_collect_time = ? WHERE owner_id = ?",
            (now, player.user_id)
        )
        await self.db.conn.commit()

        remain_text = ""
        if expire_time > 0:
            remain_text = f"\n剩余时效：{format_remaining(expire_time - now)}"

        return True, (
            f"✅ 灵眼收取成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"【{eye['eye_name']}】\n"
            f"累计时长：{hours} 小时\n"
            f"获得修为：+{exp_income:,}{remain_text}"
        )

    async def release_spirit_eye(self, user_id: str) -> Tuple[bool, str]:
        """释放灵眼"""
        cleaned = await self._cleanup_expired_eyes()

        eye = await self.get_user_spirit_eye(user_id)
        if not eye:
            settled = 0
            for item in cleaned:
                if item["eye"].get("owner_id") == user_id:
                    settled = max(settled, int(item["settled"] or 0))
            if settled > 0:
                return False, (
                    f"⌛ 你占据的灵眼已到时效、消散无踪。\n"
                    f"💰 未收取修为已自动结算：+{settled:,}"
                )
            return False, "❌ 你没有占据灵眼。"

        # 释放前结算已累积但未收取的修为（不吞收益）
        now = int(time.time())
        settled = await self._settle_pending_exp(eye, now)

        await self.db.conn.execute(
            """
            UPDATE spirit_eyes SET owner_id = NULL, owner_name = NULL, claim_time = NULL,
                   last_collect_time = NULL, protect_until = 0
            WHERE owner_id = ?
            """,
            (user_id,)
        )
        await self.db.conn.commit()

        settle_text = f"\n已结算未收取修为：+{settled:,}" if settled > 0 else ""
        return True, f"已释放【{eye['eye_name']}】。{settle_text}"

    # ===== 信息展示 =====

    async def get_spirit_eye_info(self, user_id: str) -> str:
        """获取灵眼信息"""
        await self._cleanup_expired_eyes()

        my_eye = await self.get_user_spirit_eye(user_id)
        all_eyes = await self.get_all_spirit_eyes()
        now = int(time.time())

        lines = ["👁️ 天地灵眼", "━━━━━━━━━━━━━━━"]

        if my_eye:
            last = my_eye.get("last_collect_time") or my_eye.get("claim_time") or now
            hours = (now - last) / 3600
            pending = int(min(MAX_ACCUMULATE_HOURS, hours) * my_eye["exp_per_hour"])
            lines.append(f"【我的灵眼】{my_eye['eye_name']}")
            lines.append(f"每小时：+{my_eye['exp_per_hour']:,} 修为")
            lines.append(f"待收取：约 +{pending:,} 修为")
            expire_time = int(my_eye.get("expire_time") or 0)
            if expire_time > 0:
                lines.append(f"剩余时效：{format_remaining(expire_time - now)}")
            lines.append("")

        free_eyes = [e for e in all_eyes if not e.get("owner_id")]
        owned_eyes = [e for e in all_eyes if e.get("owner_id")]

        if free_eyes:
            lines.append("【无主灵眼】")
            for eye in free_eyes[:5]:
                expire_time = int(eye.get("expire_time") or 0)
                remain = format_remaining(expire_time - now) if expire_time > 0 else "—"
                lines.append(
                    f"  [{eye['eye_id']}] {eye['eye_name']} "
                    f"(+{eye['exp_per_hour']:,}/时) ⏳{remain}"
                )
            lines.append("")

        if owned_eyes:
            lines.append("【已被占据的灵眼】")
            for eye in owned_eyes[:5]:
                expire_time = int(eye.get("expire_time") or 0)
                remain = format_remaining(expire_time - now) if expire_time > 0 else "—"
                owner_name = eye.get("owner_name") or "某人"
                lines.append(
                    f"  [{eye['eye_id']}] {eye['eye_name']} "
                    f"(+{eye['exp_per_hour']:,}/时) — {owner_name} ⏳{remain}"
                )
            lines.append("")

        if not free_eyes and not owned_eyes:
            lines.append("天地间暂时没有灵眼显现。")
            lines.append("")

        lines.append("💡 /抢占灵眼 <编号> 抢占无主灵眼")
        lines.append("💡 /抢占灵眼 @对方 争夺他人灵眼（切磋定胜负）")
        lines.append("⏳ 灵眼均有时效，越高级存在越短，到期消散（未收修为自动结算）")
        return "\n".join(lines)
