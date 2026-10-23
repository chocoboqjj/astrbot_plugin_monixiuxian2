# data/database_extended.py
"""
扩展数据库操作类，包含宗门、Boss、秘境等新系统的CRUD方法
"""

import aiosqlite
import json
import time
from typing import List, Optional
from ..models_extended import (
    Sect, BuffInfo, Boss, Rift, ImpartInfo, UserCd
)


class DatabaseExtended:
    """数据库扩展操作类"""
    
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn
    
    # ===== 宗门系统 CRUD =====
    
    async def create_sect(self, sect: Sect):
        """创建宗门"""
        await self.conn.execute(
            """
            INSERT INTO sects (
                sect_name, sect_owner, sect_scale, sect_used_stone,
                sect_fairyland, sect_materials, mainbuff, secbuff, elixir_room_level
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sect.sect_name, sect.sect_owner, sect.sect_scale,
                sect.sect_used_stone, sect.sect_fairyland, sect.sect_materials,
                sect.mainbuff, sect.secbuff, sect.elixir_room_level
            )
        )
        await self.conn.commit()
        
        # 获取刚插入的sect_id
        async with self.conn.execute("SELECT last_insert_rowid()") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None
    
    async def get_sect_by_id(self, sect_id: int) -> Optional[Sect]:
        """根据ID获取宗门信息"""
        async with self.conn.execute(
            "SELECT * FROM sects WHERE sect_id = ?",
            (sect_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Sect(**dict(row))
            return None
    
    async def get_sect_by_owner(self, owner_id: str) -> Optional[Sect]:
        """根据宗主ID获取宗门信息"""
        async with self.conn.execute(
            "SELECT * FROM sects WHERE sect_owner = ?",
            (owner_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Sect(**dict(row))
            return None
    
    async def get_sect_by_name(self, sect_name: str) -> Optional[Sect]:
        """根据宗门名称获取宗门信息"""
        async with self.conn.execute(
            "SELECT * FROM sects WHERE sect_name = ?",
            (sect_name,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Sect(**dict(row))
            return None
    
    async def update_sect(self, sect: Sect):
        """更新宗门信息"""
        await self.conn.execute(
            """
            UPDATE sects SET
                sect_name = ?, sect_owner = ?, sect_scale = ?, sect_used_stone = ?,
                sect_fairyland = ?, sect_materials = ?, mainbuff = ?, secbuff = ?,
                elixir_room_level = ?
            WHERE sect_id = ?
            """,
            (
                sect.sect_name, sect.sect_owner, sect.sect_scale,
                sect.sect_used_stone, sect.sect_fairyland, sect.sect_materials,
                sect.mainbuff, sect.secbuff, sect.elixir_room_level,
                sect.sect_id
            )
        )
        await self.conn.commit()
    
    async def delete_sect(self, sect_id: int):
        """删除宗门"""
        await self.conn.execute("DELETE FROM sects WHERE sect_id = ?", (sect_id,))
        await self.conn.commit()
    
    async def get_all_sects(self) -> List[Sect]:
        """获取所有宗门"""
        async with self.conn.execute("SELECT * FROM sects ORDER BY sect_scale DESC") as cursor:
            rows = await cursor.fetchall()
            return [Sect(**dict(row)) for row in rows]
    
    async def update_sect_materials(self, sect_id: int, materials: int, operation: int = 1):
        """更新宗门资材
        
        Args:
            sect_id: 宗门ID
            materials: 资材数量
            operation: 1=增加, 2=减少
        """
        if operation == 1:
            await self.conn.execute(
                "UPDATE sects SET sect_materials = sect_materials + ? WHERE sect_id = ?",
                (materials, sect_id)
            )
        else:
            await self.conn.execute(
                "UPDATE sects SET sect_materials = sect_materials - ? WHERE sect_id = ?",
                (materials, sect_id)
            )
        await self.conn.commit()
    
    async def donate_to_sect(self, sect_id: int, stone_num: int):
        """宗门捐献（增加灵石和建设度）"""
        await self.conn.execute(
            """
            UPDATE sects SET 
                sect_used_stone = sect_used_stone + ?,
                sect_scale = sect_scale + ?
            WHERE sect_id = ?
            """,
            (stone_num, stone_num * 10, sect_id)  # 1灵石 = 10建设度
        )
        await self.conn.commit()
    
    # ===== BuffInfo 系统 CRUD =====
    
    async def create_buff_info(self, user_id: str):
        """初始化用户的buff信息（幂等：已存在则跳过）"""
        await self.conn.execute(
            """
            INSERT OR IGNORE INTO buff_info (
                user_id, main_buff, sec_buff, faqi_buff, fabao_weapon,
                armor_buff, atk_buff, blessed_spot, sub_buff
            ) VALUES (?, 0, 0, 0, 0, 0, 0, 0, 0)
            """,
            (user_id,)
        )
        await self.conn.commit()
    
    async def get_buff_info(self, user_id: str) -> Optional[BuffInfo]:
        """获取用户buff信息"""
        async with self.conn.execute(
            "SELECT * FROM buff_info WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return BuffInfo(**dict(row))
            return None
    
    async def update_buff_info(self, buff_info: BuffInfo):
        """更新用户buff信息"""
        await self.conn.execute(
            """
            UPDATE buff_info SET
                main_buff = ?, sec_buff = ?, faqi_buff = ?, fabao_weapon = ?,
                armor_buff = ?, atk_buff = ?, blessed_spot = ?, sub_buff = ?
            WHERE user_id = ?
            """,
            (
                buff_info.main_buff, buff_info.sec_buff, buff_info.faqi_buff,
                buff_info.fabao_weapon, buff_info.armor_buff, buff_info.atk_buff,
                buff_info.blessed_spot, buff_info.sub_buff, buff_info.user_id
            )
        )
        await self.conn.commit()
    
    async def update_user_main_buff(self, user_id: str, buff_id: int):
        """更新用户主修功法"""
        await self.conn.execute(
            "UPDATE buff_info SET main_buff = ? WHERE user_id = ?",
            (buff_id, user_id)
        )
        await self.conn.commit()
    
    async def update_user_sec_buff(self, user_id: str, buff_id: int):
        """更新用户辅修功法"""
        await self.conn.execute(
            "UPDATE buff_info SET sec_buff = ? WHERE user_id = ?",
            (buff_id, user_id)
        )
        await self.conn.commit()
    
    # ===== Boss 系统 CRUD =====
    
    async def create_boss(self, boss: Boss) -> int:
        """创建Boss"""
        await self.conn.execute(
            """
            INSERT INTO boss (
                boss_name, boss_level, hp, max_hp, atk, defense,
                stone_reward, create_time, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                boss.boss_name, boss.boss_level, boss.hp, boss.max_hp,
                boss.atk, boss.defense, boss.stone_reward,
                boss.create_time, boss.status
            )
        )
        await self.conn.commit()
        
        async with self.conn.execute("SELECT last_insert_rowid()") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None
    
    async def get_active_boss(self) -> Optional[Boss]:
        """获取当前存活的Boss"""
        async with self.conn.execute(
            "SELECT * FROM boss WHERE status = 1 ORDER BY create_time DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Boss(**dict(row))
            return None
    
    async def get_boss_by_id(self, boss_id: int) -> Optional[Boss]:
        """根据ID获取Boss信息"""
        async with self.conn.execute(
            "SELECT * FROM boss WHERE boss_id = ?",
            (boss_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Boss(**dict(row))
            return None
    
    async def update_boss(self, boss: Boss):
        """更新Boss信息"""
        await self.conn.execute(
            """
            UPDATE boss SET
                boss_name = ?, boss_level = ?, hp = ?, max_hp = ?, atk = ?,
                defense = ?, stone_reward = ?, status = ?
            WHERE boss_id = ?
            """,
            (
                boss.boss_name, boss.boss_level, boss.hp, boss.max_hp,
                boss.atk, boss.defense, boss.stone_reward, boss.status,
                boss.boss_id
            )
        )
        await self.conn.commit()
    
    async def defeat_boss(self, boss_id: int) -> bool:
        """标记Boss为已击败

        v3.2.8：改为**条件 UPDATE**（仅当 status = 1 时才置 0），靠 rowcount
        判定「本次是否由我真正击杀」。

        背景：此前是无条件 `UPDATE boss SET status = 0 WHERE boss_id = ?`，
        并发挑战时两名玩家可以同时「获胜」（各自基于同一份旧血量计算出胜利），
        双双领走完整奖励并双发击杀广播。

        Returns:
            True = 本次调用真正完成了击杀（首个击杀者）
            False = Boss 已被他人抢先击杀（本次只是打在了尸体上）
        """
        cursor = await self.conn.execute(
            "UPDATE boss SET status = 0 WHERE boss_id = ? AND status = 1",
            (boss_id,)
        )
        # ⚠️ 先判 rowcount 再 commit（commit 后 rollback 无效）
        killed = cursor.rowcount > 0
        await self.conn.commit()
        return killed

    # ===== 世界Boss挑战次数限制（v24）=====

    async def get_boss_challenge(self, boss_id: int, user_id: str) -> Optional[dict]:
        """获取某玩家对某只 Boss 的挑战记录

        Returns:
            None 或 {"boss_id", "user_id", "challenge_count", "last_challenge_time"}
        """
        async with self.conn.execute(
            """SELECT boss_id, user_id, challenge_count, last_challenge_time
               FROM boss_challenges WHERE boss_id = ? AND user_id = ?""",
            (boss_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "boss_id": row[0],
                    "user_id": row[1],
                    "challenge_count": row[2],
                    "last_challenge_time": row[3]
                }
            return None

    async def record_boss_challenge(self, boss_id: int, user_id: str, challenge_time: int):
        """记录一次 Boss 挑战（次数 +1，并刷新上次挑战时间）

        使用 UPSERT，天然幂等——同一 (boss_id, user_id) 只有一行。
        """
        await self.conn.execute(
            """INSERT INTO boss_challenges
                   (boss_id, user_id, challenge_count, last_challenge_time)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(boss_id, user_id) DO UPDATE SET
                   challenge_count = challenge_count + 1,
                   last_challenge_time = excluded.last_challenge_time""",
            (boss_id, user_id, challenge_time)
        )
        await self.conn.commit()

    async def reserve_boss_challenge(
        self, boss_id: int, user_id: str, challenge_time: int, max_count: int
    ) -> bool:
        """原子地占位一次挑战机会（并发安全）

        与 `record_boss_challenge` 的区别：本方法在**同一条 SQL** 里完成
        「检查次数上限 + 次数 +1」，用条件 UPDATE 的 rowcount 判定成败，
        因此同一玩家的并发请求**最多只有一条能占位成功**（避免双挑战）。

        Args:
            boss_id: Boss 实例 ID
            user_id: 挑战者 ID
            challenge_time: 本次挑战时间戳（同时写入冷却起点）
            max_count: 次数上限；<= 0 表示不限次数

        Returns:
            True = 占位成功；False = 次数已用尽
        """
        if max_count <= 0:
            # 不限次数：直接 UPSERT
            await self.conn.execute(
                """INSERT INTO boss_challenges
                       (boss_id, user_id, challenge_count, last_challenge_time)
                   VALUES (?, ?, 1, ?)
                   ON CONFLICT(boss_id, user_id) DO UPDATE SET
                       challenge_count = challenge_count + 1,
                       last_challenge_time = excluded.last_challenge_time""",
                (boss_id, user_id, challenge_time)
            )
            await self.conn.commit()
            return True

        # 有上限：条件 UPDATE —— 仅当 count < max 时才递增
        # ⚠️ 先判 rowcount 再 commit（commit 后 rollback 无效）
        cursor = await self.conn.execute(
            """INSERT INTO boss_challenges
                   (boss_id, user_id, challenge_count, last_challenge_time)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(boss_id, user_id) DO UPDATE SET
                   challenge_count = challenge_count + 1,
                   last_challenge_time = excluded.last_challenge_time
               WHERE challenge_count < ?""",
            (boss_id, user_id, challenge_time, max_count)
        )
        reserved = cursor.rowcount > 0
        await self.conn.commit()
        return reserved

    async def release_boss_challenge(self, boss_id: int, user_id: str):
        """释放一次已占位的挑战机会（战斗异常时回滚，避免白白消耗次数）"""
        await self.conn.execute(
            """UPDATE boss_challenges
               SET challenge_count = MAX(0, challenge_count - 1)
               WHERE boss_id = ? AND user_id = ?""",
            (boss_id, user_id)
        )
        await self.conn.commit()

    async def cleanup_boss_challenges(self, keep_boss_id: int = 0):
        """清理历史 Boss 的挑战记录

        只保留当前这只 Boss（keep_boss_id）的记录，避免表无限膨胀。
        新 Boss 生成时调用即可（计数本就随 boss_id 自然重置）。
        """
        await self.conn.execute(
            "DELETE FROM boss_challenges WHERE boss_id != ?",
            (keep_boss_id,)
        )
        await self.conn.commit()

    async def get_boss_challenge_count(self, boss_id: int, user_id: str) -> int:
        """获取某玩家对某只 Boss 的已挑战次数（无记录返回 0）"""
        async with self.conn.execute(
            "SELECT challenge_count FROM boss_challenges WHERE boss_id = ? AND user_id = ?",
            (boss_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    # ===== 天灾人祸记录（v25）=====

    async def create_calamity_record(
        self,
        calamity_id: str,
        calamity_name: str,
        category: str,
        target_user_id: str,
        target_name: str,
        gold_lost: int,
        exp_lost: int,
        no_event: bool = False,
        shielded: bool = False,
        create_time: int = 0,
    ) -> int:
        """写入一条天灾人祸记录，返回记录 ID"""
        cursor = await self.conn.execute(
            """INSERT INTO calamity_records (
                   calamity_id, calamity_name, category, target_user_id,
                   target_name, gold_lost, exp_lost, no_event, shielded, create_time
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                calamity_id, calamity_name, category, target_user_id,
                target_name, int(gold_lost), int(exp_lost),
                int(bool(no_event)), int(bool(shielded)), int(create_time),
            ),
        )
        await self.conn.commit()
        return cursor.lastrowid

    async def apply_calamity_penalty(
        self,
        user_id: str,
        gold_lost: int = 0,
        exp_lost: int = 0,
        exp_floor: int = 0,
        consume_shield: bool = True,
    ) -> dict:
        """天灾人祸：原子扣除灵石/修为（绝不致死）

        v3.2.9 设计要点：
          1. **绝不致死**：只做 `gold` / `experience` 的定向扣减，
             **不触碰** `state` / `lifespan` 等生死字段，也**不删号**。
             与走火入魔（`PenaltyManager.punish`）、银行追杀明确区分。
          2. **定魂护盾**：`has_debuff_shield` 为真时完全免疫本次天灾；
             `consume_shield=True` 时抵挡后消耗掉护盾。
             这是该字段（全库此前只设不消）的**首个消费点**。
          3. **单条 SQL 原子完成**：整段扣减（含护盾判定、余额裁剪、
             境界地板裁剪）都在**一条** `UPDATE ... RETURNING` 里做完。

             ⚠️ 为什么不用「先 SELECT 再写回绝对值」：
             本插件所有 manager **共享同一个 aiosqlite 连接**，多个协程
             并发时事务边界是连接级的——一个协程读到的旧值可能已经过期，
             写回绝对值就会**丢更新**（别人刚加的灵石被覆盖掉）。
             改成「原地加减」后不会丢更新。

             ⚠️ 为什么用 `WITH old AS MATERIALIZED`：
             为了**准确上报实际扣减量**，需要拿到「本次扣减前的值」。
             `RETURNING` 默认只能看到**更新后**的值；
             而把 CTE 引用到 `SET` 表达式里，可以强制它在写入前求值，
             从而在同一语句内得到旧值 ⇒ 扣减量精确、无并发误差。
             （实测：CTE 只在 `RETURNING` 里引用会拿到新值，**不可用**。）

        Args:
            user_id: 被罚玩家
            gold_lost: 计划扣除的灵石（SQL 内按实际余额裁剪）
            exp_lost: 计划扣除的修为（SQL 内按境界地板裁剪）
            exp_floor: 修为地板（当前境界的累计门槛），修为不会被扣到它以下
            consume_shield: 护盾抵挡后是否消耗

        Returns:
            {
              "success": bool,        # 是否成功落库
              "shielded": bool,       # 是否被定魂护盾挡下
              "shield_consumed": bool,# 护盾是否被消耗
              "gold_lost": int,       # 实际扣除的灵石
              "exp_lost": int,        # 实际扣除的修为
              "gold_after": int,
              "exp_after": int,
            }
        """
        gold_lost = max(0, int(gold_lost or 0))
        exp_lost = max(0, int(exp_lost or 0))
        exp_floor = max(0, int(exp_floor or 0))
        consume = 1 if consume_shield else 0

        # 单条原子语句：原地加减 + 护盾免疫（护盾存在时完全不动资源）
        # ⚠️ CTE 被引用在 SET 表达式里 ⇒ 强制在写入前求值 ⇒ 拿到的是「旧值」
        cursor = await self.conn.execute(
            """WITH old AS MATERIALIZED (
                   SELECT gold AS og, experience AS oe, has_debuff_shield AS osh
                   FROM players WHERE user_id = ?
               )
               UPDATE players SET
                   gold = CASE WHEN (SELECT osh FROM old) = 1
                               THEN gold
                               ELSE MAX(0, (SELECT og FROM old) - ?) END,
                   experience = CASE WHEN (SELECT osh FROM old) = 1
                                     THEN experience
                                     ELSE MAX(?, (SELECT oe FROM old) - ?) END,
                   has_debuff_shield = CASE
                       WHEN has_debuff_shield = 1 AND ? = 1 THEN 0
                       ELSE has_debuff_shield END
               WHERE user_id = ?
               RETURNING
                   gold, experience, has_debuff_shield,
                   (SELECT og FROM old) AS snap_gold,
                   (SELECT oe FROM old) AS snap_exp,
                   (SELECT osh FROM old) AS snap_shield""",
            (user_id, gold_lost, exp_floor, exp_lost, consume, user_id),
        )
        new_row = await cursor.fetchone()
        # ⚠️ 先取 rowcount / 结果再 commit（commit 后无法回滚判定）
        await self.conn.commit()
        if not new_row:
            return {
                "success": False, "shielded": False, "shield_consumed": False,
                "gold_lost": 0, "exp_lost": 0, "gold_after": 0, "exp_after": 0,
            }

        new_gold = int(new_row[0] or 0)
        new_exp = int(new_row[1] or 0)
        new_shield = bool(new_row[2])
        # ⚠️ 以语句内 CTE 快照的旧值为准（并发下比「外面读到的旧值」更准）
        snap_gold = int(new_row[3] or 0)
        snap_exp = int(new_row[4] or 0)
        snap_shield = bool(new_row[5])

        # 护盾挡下：资源分毫未动
        if snap_shield:
            actual_gold = 0
            actual_exp = 0
        else:
            actual_gold = max(0, snap_gold - new_gold)
            actual_exp = max(0, snap_exp - new_exp)

        return {
            "success": True,
            "shielded": snap_shield,
            "shield_consumed": snap_shield and (not new_shield),
            "gold_lost": actual_gold,
            "exp_lost": actual_exp,
            "gold_after": new_gold,
            "exp_after": new_exp,
        }

    async def get_recent_calamities(self, limit: int = 10) -> List[dict]:
        """获取最近的天灾人祸记录（按时间倒序）"""
        async with self.conn.execute(
            "SELECT * FROM calamity_records ORDER BY id DESC LIMIT ?",
            (int(limit),)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_user_calamities(self, user_id: str, limit: int = 5) -> List[dict]:
        """获取某玩家被天灾人祸惩罚的历史（按时间倒序）"""
        async with self.conn.execute(
            """SELECT * FROM calamity_records
               WHERE target_user_id = ? ORDER BY id DESC LIMIT ?""",
            (user_id, int(limit))
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_calamity_stats(self, user_id: str) -> dict:
        """统计某玩家因天灾累计损失"""
        async with self.conn.execute(
            """SELECT COUNT(*),
                      COALESCE(SUM(gold_lost), 0),
                      COALESCE(SUM(exp_lost), 0)
               FROM calamity_records WHERE target_user_id = ?""",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return {"count": 0, "gold_lost": 0, "exp_lost": 0}
            return {
                "count": int(row[0]),
                "gold_lost": int(row[1]),
                "exp_lost": int(row[2]),
            }

    async def cleanup_calamity_records(self, keep: int = 200) -> int:
        """清理过老的天灾记录（只保留最近 keep 条），返回删除条数"""
        async with self.conn.execute(
            """DELETE FROM calamity_records WHERE id NOT IN (
                   SELECT id FROM calamity_records ORDER BY id DESC LIMIT ?
               )""",
            (int(keep),)
        ) as cursor:
            deleted = cursor.rowcount
        await self.conn.commit()
        return max(0, deleted)

    # ===== 秘境系统 CRUD =====
    
    async def create_rift(self, rift: Rift) -> int:
        """创建秘境"""
        await self.conn.execute(
            """
            INSERT INTO rifts (
                rift_name, rift_level, required_level, rewards
            ) VALUES (?, ?, ?, ?)
            """,
            (rift.rift_name, rift.rift_level, rift.required_level, rift.rewards)
        )
        await self.conn.commit()
        
        async with self.conn.execute("SELECT last_insert_rowid()") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None
    
    async def get_rift_by_id(self, rift_id: int) -> Optional[Rift]:
        """根据ID获取秘境信息"""
        async with self.conn.execute(
            "SELECT * FROM rifts WHERE rift_id = ?",
            (rift_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Rift(**dict(row))
            return None
    
    async def get_all_rifts(self) -> List[Rift]:
        """获取所有秘境"""
        async with self.conn.execute(
            "SELECT * FROM rifts ORDER BY rift_level ASC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [Rift(**dict(row)) for row in rows]
    
    # ===== 传承系统 CRUD =====
    
    async def create_impart_info(self, user_id: str):
        """初始化用户传承信息（幂等：已存在则跳过）"""
        await self.conn.execute(
            """
            INSERT OR IGNORE INTO impart_info (
                user_id, impart_hp_per, impart_mp_per, impart_atk_per,
                impart_know_per, impart_burst_per
            ) VALUES (?, 0.0, 0.0, 0.0, 0.0, 0.0)
            """,
            (user_id,)
        )
        await self.conn.commit()
    
    async def get_impart_info(self, user_id: str) -> Optional[ImpartInfo]:
        """获取用户传承信息（记录缺失时自动补建，兼容存量玩家）"""
        async with self.conn.execute(
            "SELECT * FROM impart_info WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return ImpartInfo(**dict(row))
            # 自愈：老玩家可能没有这条记录，补建一条全零记录
            try:
                await self.create_impart_info(user_id)
                async with self.conn.execute(
                    "SELECT * FROM impart_info WHERE user_id = ?",
                    (user_id,)
                ) as cursor2:
                    row2 = await cursor2.fetchone()
                    if row2:
                        return ImpartInfo(**dict(row2))
            except Exception:
                pass
            return None
    
    async def update_impart_info(self, impart: ImpartInfo):
        """更新用户传承信息"""
        await self.conn.execute(
            """
            UPDATE impart_info SET
                impart_hp_per = ?, impart_mp_per = ?, impart_atk_per = ?,
                impart_know_per = ?, impart_burst_per = ?
            WHERE user_id = ?
            """,
            (
                impart.impart_hp_per, impart.impart_mp_per, impart.impart_atk_per,
                impart.impart_know_per, impart.impart_burst_per, impart.user_id
            )
        )
        await self.conn.commit()
    
    # ===== 用户CD系统 CRUD =====
    
    async def create_user_cd(self, user_id: str):
        """初始化用户CD信息"""
        await self.conn.execute(
            """
            INSERT INTO user_cd (user_id, type, create_time, scheduled_time)
            VALUES (?, 0, 0, 0)
            """,
            (user_id,)
        )
        await self.conn.commit()
    
    async def get_user_cd(self, user_id: str) -> Optional[UserCd]:
        """获取用户CD信息"""
        async with self.conn.execute(
            "SELECT * FROM user_cd WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return UserCd(**dict(row))
            return None
    
    async def update_user_cd(self, user_cd: UserCd):
        """更新用户CD信息"""
        await self.conn.execute(
            """
            UPDATE user_cd SET
                type = ?, create_time = ?, scheduled_time = ?, extra_data = ?
            WHERE user_id = ?
            """,
            (user_cd.type, user_cd.create_time, user_cd.scheduled_time, user_cd.extra_data, user_cd.user_id)
        )
        await self.conn.commit()
    
    async def set_user_busy(self, user_id: str, busy_type: int, scheduled_time: int = 0, extra_data: dict = None):
        """设置用户忙碌状态
        
        Args:
            user_id: 用户ID
            busy_type: 0=空闲, 1=闭关, 2=历练, 3=探索秘境
            scheduled_time: 计划完成时间戳
            extra_data: 额外数据（如秘境ID等）
        """
        import time
        import json
        extra_json = json.dumps(extra_data or {}, ensure_ascii=False)
        # 使用 UPSERT：记录不存在时自动插入（此前纯 UPDATE 会静默失效，
        # 导致新玩家没有 user_cd 记录、状态判断一直走"无记录"分支）
        await self.conn.execute(
            """
            INSERT OR REPLACE INTO user_cd (user_id, type, create_time, scheduled_time, extra_data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, busy_type, int(time.time()), scheduled_time, extra_json)
        )
        await self.conn.commit()
    
    async def set_user_free(self, user_id: str):
        """设置用户为空闲状态"""
        await self.set_user_busy(user_id, 0, 0)
    
    # ===== Player扩展字段更新方法 =====
    
    async def update_player_hp_mp(self, user_id: str, hp: int, mp: int):
        """更新玩家HP和MP"""
        await self.conn.execute(
            "UPDATE players SET hp = ?, mp = ? WHERE user_id = ?",
            (hp, mp, user_id)
        )
        await self.conn.commit()
    
    async def update_player_sect_info(self, user_id: str, sect_id: int, sect_position: int):
        """更新玩家宗门信息"""
        await self.conn.execute(
            "UPDATE players SET sect_id = ?, sect_position = ? WHERE user_id = ?",
            (sect_id, sect_position, user_id)
        )
        await self.conn.commit()
    
    async def update_player_sect_contribution(self, user_id: str, contribution: int):
        """更新玩家宗门贡献度"""
        await self.conn.execute(
            "UPDATE players SET sect_contribution = ? WHERE user_id = ?",
            (contribution, user_id)
        )
        await self.conn.commit()
    
    async def increment_sect_task_count(self, user_id: str, count: int = 1):
        """增加宗门任务完成次数"""
        await self.conn.execute(
            "UPDATE players SET sect_task = sect_task + ? WHERE user_id = ?",
            (count, user_id)
        )
        await self.conn.commit()
    
    async def reset_sect_tasks(self):
        """重置所有用户的宗门任务次数（定时任务）"""
        await self.conn.execute("UPDATE players SET sect_task = 0")
        await self.conn.commit()
    
    async def reset_sect_elixir_get(self):
        """重置所有用户的宗门丹药领取标记（定时任务）"""
        await self.conn.execute("UPDATE players SET sect_elixir_get = 0")
        await self.conn.commit()
    
    async def get_sect_members(self, sect_id: int) -> List:
        """获取宗门所有成员"""
        from ..models import Player
        async with self.conn.execute(
            "SELECT * FROM players WHERE sect_id = ? ORDER BY sect_position ASC, level_index DESC",
            (sect_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            # 简化返回，只返回部分字段
            from dataclasses import fields
            PLAYER_FIELDS = {f.name for f in fields(Player)}
            return [Player(**{k: v for k, v in dict(row).items() if k in PLAYER_FIELDS}) for row in rows]
    
    # ===== Phase 2: 灵石银行 CRUD =====
    
    async def get_bank_account(self, user_id: str) -> Optional[dict]:
        """获取银行账户信息"""
        async with self.conn.execute(
            "SELECT balance, last_interest_time FROM bank_accounts WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"balance": row[0], "last_interest_time": row[1]}
            return None
    
    async def update_bank_account(self, user_id: str, balance: int, last_interest_time: int):
        """更新或创建银行账户"""
        await self.conn.execute(
            """
            INSERT INTO bank_accounts (user_id, balance, last_interest_time)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET 
                balance = excluded.balance,
                last_interest_time = excluded.last_interest_time
            """,
            (user_id, balance, last_interest_time)
        )
        await self.conn.commit()
    
    # ===== Phase 2: 悬赏令系统 CRUD =====
    
    async def ensure_bounty_tables(self):
        """确保悬赏系统表存在（运行时检查）"""
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS bounty_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                bounty_id INTEGER NOT NULL,
                bounty_name TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_count INTEGER NOT NULL,
                current_progress INTEGER NOT NULL DEFAULT 0,
                rewards TEXT NOT NULL DEFAULT '{}',
                start_time INTEGER NOT NULL,
                expire_time INTEGER NOT NULL,
                status INTEGER NOT NULL DEFAULT 1
            )
        """)
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_bounty_user ON bounty_tasks(user_id)")
        await self.conn.commit()
    
    async def get_active_bounty(self, user_id: str) -> Optional[dict]:
        """获取用户当前进行中的悬赏任务"""
        await self.ensure_bounty_tables()  # 确保表存在
        async with self.conn.execute(
            "SELECT * FROM bounty_tasks WHERE user_id = ? AND status = 1",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    async def create_bounty(self, user_id: str, bounty_id: int, bounty_name: str, 
                           target_type: str, target_count: int, rewards: str, 
                           expire_time: int):
        """创建悬赏任务"""
        import time
        await self.conn.execute(
            """
            INSERT INTO bounty_tasks (
                user_id, bounty_id, bounty_name, target_type, 
                target_count, current_progress, rewards, 
                start_time, expire_time, status
            ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 1)
            """,
            (user_id, bounty_id, bounty_name, target_type, 
             target_count, rewards, int(time.time()), expire_time)
        )
        await self.conn.commit()
    
    async def update_bounty_progress(self, user_id: str, progress: int):
        """更新悬赏任务进度"""
        await self.conn.execute(
            "UPDATE bounty_tasks SET current_progress = ? WHERE user_id = ? AND status = 1",
            (progress, user_id)
        )
        await self.conn.commit()
    
    async def complete_bounty(self, user_id: str) -> bool:
        """完成悬赏任务

        返回是否真的完成了任务（此前恒返回 True，调用方无法感知失败）。
        仅当存在进行中（status=1）且进度已达标的悬赏才会被标记完成。
        """
        import time
        async with self.conn.execute(
            "SELECT current_progress, target_count, expire_time FROM bounty_tasks "
            "WHERE user_id = ? AND status = 1",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return False
            progress, target, expire_time = row
            if int(progress) < int(target):
                return False
            if expire_time and int(time.time()) > int(expire_time):
                return False

        await self.conn.execute(
            "UPDATE bounty_tasks SET status = 2 WHERE user_id = ? AND status = 1",
            (user_id,)
        )
        await self.conn.commit()
        return True
    
    async def cancel_bounty(self, user_id: str):
        """取消悬赏任务"""
        await self.conn.execute(
            "UPDATE bounty_tasks SET status = 0 WHERE user_id = ? AND status = 1",
            (user_id,)
        )
        await self.conn.commit()
    
    # ===== 系统配置 CRUD =====
    
    async def ensure_system_config_table(self):
        """确保系统配置表存在"""
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER DEFAULT 0
            )
        """)
        await self.conn.commit()
    
    async def get_system_config(self, key: str) -> Optional[str]:
        """获取系统配置"""
        await self.ensure_system_config_table()
        async with self.conn.execute(
            "SELECT value FROM system_config WHERE key = ?",
            (key,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None
    
    async def set_system_config(self, key: str, value: str):
        """设置系统配置"""
        import time
        await self.ensure_system_config_table()
        await self.conn.execute(
            """
            INSERT INTO system_config (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?
            """,
            (key, value, int(time.time()), value, int(time.time()))
        )
        await self.conn.commit()
    
    # ===== 赠予请求系统 CRUD =====
    
    async def create_pending_gift(self, receiver_id: str, sender_id: str, sender_name: str,
                                   item_name: str, count: int, expires_hours: int = 24) -> int:
        """创建赠予请求
        
        Args:
            receiver_id: 接收者ID
            sender_id: 发送者ID
            sender_name: 发送者名称
            item_name: 物品名称
            count: 物品数量
            expires_hours: 过期时间（小时），默认24小时
            
        Returns:
            新创建的赠予请求ID
        """
        import time
        now = int(time.time())
        expires_at = now + expires_hours * 3600
        
        await self.conn.execute(
            """
            INSERT INTO pending_gifts (
                receiver_id, sender_id, sender_name, item_name, count, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (receiver_id, sender_id, sender_name, item_name, count, now, expires_at)
        )
        await self.conn.commit()
        
        async with self.conn.execute("SELECT last_insert_rowid()") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None
    
    async def get_pending_gift(self, receiver_id: str) -> Optional[dict]:
        """获取接收者的待处理赠予请求（最新的一个）"""
        import time
        now = int(time.time())
        
        # 先清理过期的请求
        await self.cleanup_expired_gifts()
        
        async with self.conn.execute(
            """
            SELECT id, receiver_id, sender_id, sender_name, item_name, count, created_at, expires_at
            FROM pending_gifts 
            WHERE receiver_id = ? AND expires_at > ?
            ORDER BY created_at DESC 
            LIMIT 1
            """,
            (receiver_id, now)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "receiver_id": row[1],
                    "sender_id": row[2],
                    "sender_name": row[3],
                    "item_name": row[4],
                    "count": row[5],
                    "created_at": row[6],
                    "expires_at": row[7]
                }
            return None
    
    async def get_all_pending_gifts(self, receiver_id: str) -> List[dict]:
        """获取接收者的所有待处理赠予请求"""
        import time
        now = int(time.time())
        
        async with self.conn.execute(
            """
            SELECT id, receiver_id, sender_id, sender_name, item_name, count, created_at, expires_at
            FROM pending_gifts 
            WHERE receiver_id = ? AND expires_at > ?
            ORDER BY created_at DESC
            """,
            (receiver_id, now)
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "receiver_id": row[1],
                    "sender_id": row[2],
                    "sender_name": row[3],
                    "item_name": row[4],
                    "count": row[5],
                    "created_at": row[6],
                    "expires_at": row[7]
                }
                for row in rows
            ]
    
    async def delete_pending_gift(self, gift_id: int):
        """删除赠予请求"""
        await self.conn.execute(
            "DELETE FROM pending_gifts WHERE id = ?",
            (gift_id,)
        )
        await self.conn.commit()
    
    async def delete_pending_gift_by_receiver(self, receiver_id: str):
        """删除接收者的所有赠予请求"""
        await self.conn.execute(
            "DELETE FROM pending_gifts WHERE receiver_id = ?",
            (receiver_id,)
        )
        await self.conn.commit()
    
    async def cleanup_expired_gifts(self):
        """清理过期的赠予请求"""
        import time
        now = int(time.time())
        await self.conn.execute(
            "DELETE FROM pending_gifts WHERE expires_at < ?",
            (now,)
        )
        await self.conn.commit()
    
    # ===== Phase 3: 银行贷款系统 CRUD =====
    
    async def get_active_loan(self, user_id: str) -> Optional[dict]:
        """获取用户当前活跃的贷款"""
        async with self.conn.execute(
            """SELECT id, user_id, principal, interest_rate, borrowed_at, due_at, status, loan_type,
                      inherit_count, settled_amount
               FROM bank_loans WHERE user_id = ? AND status = 'active'""",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "user_id": row[1],
                    "principal": row[2],
                    "interest_rate": row[3],
                    "borrowed_at": row[4],
                    "due_at": row[5],
                    "status": row[6],
                    "loan_type": row[7],
                    "inherit_count": row[8],
                    "settled_amount": row[9]
                }
            return None

    async def get_carried_loan(self, user_id: str) -> Optional[dict]:
        """获取玩家待继承（延续）的贷款

        玩家死亡且贷款未还清时，该贷款会被置为 'carried' 状态并保留在库中，
        等待玩家重开（我要修仙）后恢复为正常贷款。
        """
        async with self.conn.execute(
            """SELECT id, user_id, principal, interest_rate, borrowed_at, due_at, status, loan_type,
                      inherit_count, settled_amount, inherit_at
               FROM bank_loans WHERE user_id = ? AND status = 'carried'""",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "user_id": row[1],
                    "principal": row[2],
                    "interest_rate": row[3],
                    "borrowed_at": row[4],
                    "due_at": row[5],
                    "status": row[6],
                    "loan_type": row[7],
                    "inherit_count": row[8],
                    "settled_amount": row[9],
                    "inherit_at": row[10]
                }
            return None

    async def restore_carried_loan(self, user_id: str, grace_days: int = 7) -> Optional[dict]:
        """玩家重开时把延续债务恢复为正常贷款

        恢复后的贷款：
          - 本金 = 死亡时锁定的应还总额（本金 + 已产生利息），之后固定免息不再增长
          - 利率置 0（固定免息）
          - 到期时间 = now + 宽限期
          - 银行账户一并重建（级联删除时已被清空）

        Returns:
            恢复后的贷款信息；无延续债务时返回 None
        """
        loan = await self.get_carried_loan(user_id)
        if not loan:
            return None

        now = int(time.time())
        due_at = now + max(1, int(grace_days)) * 86400
        total = loan["settled_amount"] or loan["principal"]

        await self.conn.execute(
            """UPDATE bank_loans
               SET status = 'active',
                   principal = ?,
                   interest_rate = 0.0,
                   borrowed_at = ?,
                   due_at = ?,
                   grace_until = ?
               WHERE id = ?""",
            (total, now, due_at, due_at, loan["id"])
        )
        # 重建银行账户（玩家死亡时账户已被级联删除）
        await self.conn.execute(
            """INSERT INTO bank_accounts (user_id, balance, last_interest_time)
               VALUES (?, 0, ?)
               ON CONFLICT(user_id) DO NOTHING""",
            (user_id, now)
        )
        await self.conn.commit()

        return {
            **loan,
            "principal": total,
            "interest_rate": 0.0,
            "borrowed_at": now,
            "due_at": due_at,
            "grace_until": due_at,
            "status": "active"
        }
    
    async def create_loan(self, user_id: str, principal: int, interest_rate: float, 
                          borrowed_at: int, due_at: int, loan_type: str = "normal") -> int:
        """创建贷款记录"""
        await self.conn.execute(
            """INSERT INTO bank_loans (user_id, principal, interest_rate, borrowed_at, due_at, status, loan_type)
               VALUES (?, ?, ?, ?, ?, 'active', ?)""",
            (user_id, principal, interest_rate, borrowed_at, due_at, loan_type)
        )
        await self.conn.commit()
        async with self.conn.execute("SELECT last_insert_rowid()") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0
    
    async def close_loan(self, loan_id: int):
        """关闭贷款（标记为已还清）"""
        await self.conn.execute(
            "UPDATE bank_loans SET status = 'closed' WHERE id = ?",
            (loan_id,)
        )
        await self.conn.commit()

    async def mark_loan_carried(self, loan_id: int, settled_amount: int, inherit_count: int):
        """把贷款标记为「继承待偿」（玩家死亡时未还清的债务）

        Args:
            loan_id: 贷款 ID
            settled_amount: 锁定的应还总额（本金 + 死亡时已产生的利息），固定免息
            inherit_count: 累计继承次数（用于「3 次后豁免」上限判定）
        """
        await self.conn.execute(
            """UPDATE bank_loans
               SET status = 'carried',
                   settled_amount = ?,
                   inherit_count = ?,
                   inherit_at = ?,
                   grace_until = 0
               WHERE id = ?""",
            (settled_amount, inherit_count, int(time.time()), loan_id)
        )
        await self.conn.commit()

    async def mark_loan_overdue(self, loan_id: int):
        """标记贷款逾期

        只处理仍处于 active 的贷款：
        银行逾期追杀流程中，级联删除已把该贷款置为 bad_debt（债务免除），
        此时不应再被改写为 overdue，否则会覆盖掉「已免除」的最终状态。
        """
        await self.conn.execute(
            "UPDATE bank_loans SET status = 'overdue' WHERE id = ? AND status = 'active'",
            (loan_id,)
        )
        await self.conn.commit()

    async def get_overdue_loans(self, current_time: int) -> List[dict]:
        """获取所有逾期贷款"""
        loans = []
        async with self.conn.execute(
            """SELECT id, user_id, principal, interest_rate, borrowed_at, due_at, loan_type
               FROM bank_loans WHERE status = 'active' AND due_at < ?""",
            (current_time,)
        ) as cursor:
            async for row in cursor:
                loans.append({
                    "id": row[0],
                    "user_id": row[1],
                    "principal": row[2],
                    "interest_rate": row[3],
                    "borrowed_at": row[4],
                    "due_at": row[5],
                    "loan_type": row[6]
                })
        return loans
    
    # ===== Phase 3: 银行交易流水 CRUD =====
    
    async def add_bank_transaction(self, user_id: str, trans_type: str, amount: int, 
                                    balance_after: int, description: str, created_at: int):
        """添加银行交易流水"""
        await self.conn.execute(
            """INSERT INTO bank_transactions (user_id, trans_type, amount, balance_after, description, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, trans_type, amount, balance_after, description, created_at)
        )
        await self.conn.commit()
    
    async def get_bank_transactions(self, user_id: str, limit: int = 20) -> List[dict]:
        """获取用户银行交易流水"""
        transactions = []
        async with self.conn.execute(
            """SELECT id, trans_type, amount, balance_after, description, created_at
               FROM bank_transactions WHERE user_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit)
        ) as cursor:
            async for row in cursor:
                transactions.append({
                    "id": row[0],
                    "trans_type": row[1],
                    "amount": row[2],
                    "balance_after": row[3],
                    "description": row[4],
                    "created_at": row[5]
                })
        return transactions
    
    async def get_deposit_ranking(self, limit: int = 10) -> List[dict]:
        """获取存款排行榜"""
        rankings = []
        async with self.conn.execute(
            """SELECT user_id, balance FROM bank_accounts
               WHERE balance > 0
               ORDER BY balance DESC LIMIT ?""",
            (limit,)
        ) as cursor:
            async for row in cursor:
                rankings.append({
                    "user_id": row[0],
                    "balance": row[1]
                })
        return rankings
