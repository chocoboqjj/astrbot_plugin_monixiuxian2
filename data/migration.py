# data/migration.py

import aiosqlite
from typing import Dict, Callable, Awaitable
from astrbot.api import logger
from ..config_manager import ConfigManager

LATEST_DB_VERSION = 25  # v25: 天灾人祸记录（calamity_records 表）

# 灵眼时效（小时）：与 managers/spirit_eye_manager.py::SPIRIT_EYE_TYPES 保持一致。
# 迁移函数内不能 import managers.*（会引发循环依赖），故在此复制一份并由测试断言一致性。
SPIRIT_EYE_LIFETIME_HOURS = {
    1: 24,   # 下品灵眼
    2: 12,   # 中品灵眼
    3: 6,    # 上品灵眼
    4: 3,    # 极品灵眼
}

MIGRATION_TASKS: Dict[int, Callable[[aiosqlite.Connection, ConfigManager], Awaitable[None]]] = {}

def migration(version: int):
    """注册数据库迁移任务的装饰器"""
    def decorator(func: Callable[[aiosqlite.Connection, ConfigManager], Awaitable[None]]):
        MIGRATION_TASKS[version] = func
        return func
    return decorator

class MigrationManager:
    """数据库迁移管理器"""

    def __init__(self, conn: aiosqlite.Connection, config_manager: ConfigManager):
        self.conn = conn
        self.config_manager = config_manager

    async def migrate(self):
        await self.conn.execute("PRAGMA foreign_keys = ON")
        async with self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='db_info'") as cursor:
            if await cursor.fetchone() is None:
                logger.info("未检测到数据库版本，将进行全新安装...")
                await self.conn.execute("BEGIN")
                # 使用最新的建表函数
                await _create_all_tables_v2(self.conn)
                await self.conn.execute("INSERT INTO db_info (version) VALUES (?)", (LATEST_DB_VERSION,))
                await self.conn.commit()
                logger.info(f"数据库已初始化到最新版本: v{LATEST_DB_VERSION}")
                return

        async with self.conn.execute("SELECT version FROM db_info") as cursor:
            row = await cursor.fetchone()
            current_version = row[0] if row else 0

        logger.info(f"当前数据库版本: v{current_version}, 最新版本: v{LATEST_DB_VERSION}")
        if current_version < LATEST_DB_VERSION:
            logger.info("检测到数据库需要升级...")
            for version in sorted(MIGRATION_TASKS.keys()):
                if current_version < version:
                    logger.info(f"正在执行数据库升级: v{current_version} -> v{version} ...")
                    await self.conn.execute("BEGIN")
                    try:
                        await MIGRATION_TASKS[version](self.conn, self.config_manager)
                        await self.conn.execute("UPDATE db_info SET version = ?", (version,))
                        await self.conn.commit()
                        current_version = version
                        logger.info(f"数据库升级成功: v{version}")
                    except Exception as e:
                        await self.conn.rollback()
                        logger.error(f"数据库升级失败: v{version}. 错误: {str(e)}")
                        raise
            logger.info(f"数据库已升级到最新版本: v{LATEST_DB_VERSION}")
        else:
            logger.info("数据库已是最新版本，无需升级。")

async def _create_all_tables_v1(conn: aiosqlite.Connection):
    """创建所有表 - v1，只保留玩家基础信息"""

    # 数据库版本信息表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS db_info (
            version INTEGER NOT NULL
        )
    """)

    # 玩家表 - 只保留基础属性
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id TEXT PRIMARY KEY,
            level_index INTEGER NOT NULL DEFAULT 0,
            spiritual_root TEXT NOT NULL DEFAULT '未知',
            experience INTEGER NOT NULL DEFAULT 0,
            gold INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL DEFAULT '空闲',
            hp INTEGER NOT NULL DEFAULT 100,
            max_hp INTEGER NOT NULL DEFAULT 100,
            attack INTEGER NOT NULL DEFAULT 10,
            defense INTEGER NOT NULL DEFAULT 5,
            spiritual_power INTEGER NOT NULL DEFAULT 50,
            mental_power INTEGER NOT NULL DEFAULT 50
        )
    """)

    # 创建索引
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_player_level ON players(level_index)")

    logger.info("数据库表已创建完成（v1）")

@migration(2)
async def _migrate_to_v2(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v2 - 新属性系统（灵修/体修）"""
    logger.info("开始迁移到v2：新属性系统")

    # 删除旧表并创建新表
    await conn.execute("DROP TABLE IF EXISTS players")
    await _create_all_tables_v2(conn)

    logger.info("v2迁移完成：新属性系统")

@migration(3)
async def _migrate_to_v3(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v3 - 添加闭关系统"""
    logger.info("开始迁移到v3：添加闭关系统")

    # 添加 cultivation_start_time 字段
    await conn.execute("ALTER TABLE players ADD COLUMN cultivation_start_time INTEGER NOT NULL DEFAULT 0")

    logger.info("v3迁移完成：闭关系统")

@migration(4)
async def _migrate_to_v4(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v4 - 添加签到系统"""
    logger.info("开始迁移到v4：添加签到系统")

    # 添加 last_check_in_date 字段
    await conn.execute("ALTER TABLE players ADD COLUMN last_check_in_date TEXT NOT NULL DEFAULT ''")

    logger.info("v4迁移完成：签到系统")

@migration(5)
async def _migrate_to_v5(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v5 - 添加装备系统"""
    logger.info("开始迁移到v5：添加装备系统")

    # 添加装备栏字段
    await conn.execute("ALTER TABLE players ADD COLUMN weapon TEXT NOT NULL DEFAULT ''")
    await conn.execute("ALTER TABLE players ADD COLUMN armor TEXT NOT NULL DEFAULT ''")
    await conn.execute("ALTER TABLE players ADD COLUMN main_technique TEXT NOT NULL DEFAULT ''")
    await conn.execute("ALTER TABLE players ADD COLUMN techniques TEXT NOT NULL DEFAULT '[]'")

    # 添加灵气容量字段
    await conn.execute("ALTER TABLE players ADD COLUMN max_spiritual_qi INTEGER NOT NULL DEFAULT 1000")

    logger.info("v5迁移完成：装备系统")

@migration(6)
async def _migrate_to_v6(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v6 - 添加丹药系统"""
    logger.info("开始迁移到v6：添加丹药系统")

    # 添加丹药系统相关字段
    await conn.execute("ALTER TABLE players ADD COLUMN active_pill_effects TEXT NOT NULL DEFAULT '[]'")
    await conn.execute("ALTER TABLE players ADD COLUMN permanent_pill_gains TEXT NOT NULL DEFAULT '{}'")
    await conn.execute("ALTER TABLE players ADD COLUMN has_resurrection_pill INTEGER NOT NULL DEFAULT 0")
    await conn.execute("ALTER TABLE players ADD COLUMN pills_inventory TEXT NOT NULL DEFAULT '{}'")

    logger.info("v6迁移完成：丹药系统")

@migration(7)
async def _migrate_to_v7(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v7 - 丹药系统扩展字段"""
    logger.info("开始迁移到v7：丹药系统扩展字段")

    await conn.execute("ALTER TABLE players ADD COLUMN has_debuff_shield INTEGER NOT NULL DEFAULT 0")

    logger.info("v7迁移完成：新增定魂丹护盾字段")

@migration(8)
async def _migrate_to_v8(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v8 - 添加商店系统"""
    logger.info("开始迁移到v8：添加商店系统")

    # 创建商店表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS shop (
            shop_id TEXT PRIMARY KEY,
            last_refresh_time INTEGER NOT NULL DEFAULT 0,
            current_items TEXT NOT NULL DEFAULT '[]'
        )
    """)

    # 插入全局商店数据
    await conn.execute("""
        INSERT OR IGNORE INTO shop (shop_id, last_refresh_time, current_items)
        VALUES ('global', 0, '[]')
    """)

    logger.info("v8迁移完成：商店系统")

@migration(9)
async def _migrate_to_v9(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v9 - 添加体修气血系统"""
    logger.info("开始迁移到v9：添加体修气血系统")

    # 添加气血字段
    await conn.execute("ALTER TABLE players ADD COLUMN blood_qi INTEGER NOT NULL DEFAULT 0")
    await conn.execute("ALTER TABLE players ADD COLUMN max_blood_qi INTEGER NOT NULL DEFAULT 0")

    logger.info("v9迁移完成：体修气血系统")

@migration(10)
async def _migrate_to_v10(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v10 - 清理废弃字段（equipment_inventory等）"""
    logger.info("开始迁移到v10：清理废弃字段")

    # 获取当前表结构
    async with conn.execute("PRAGMA table_info(players)") as cursor:
        columns = {row[1] for row in await cursor.fetchall()}

    # 定义需要保留的字段（与 Player 模型一致）
    valid_columns = {
        'user_id', 'level_index', 'spiritual_root', 'cultivation_type', 'lifespan',
        'experience', 'gold', 'state', 'cultivation_start_time', 'last_check_in_date',
        'spiritual_qi', 'max_spiritual_qi', 'blood_qi', 'max_blood_qi',
        'magic_damage', 'physical_damage', 'magic_defense', 'physical_defense', 'mental_power',
        'weapon', 'armor', 'main_technique', 'techniques',
        'active_pill_effects', 'permanent_pill_gains', 'has_resurrection_pill', 'has_debuff_shield', 'pills_inventory'
    }

    # 找出需要删除的废弃字段
    deprecated_columns = columns - valid_columns
    if deprecated_columns:
        logger.info(f"发现废弃字段: {deprecated_columns}，将进行清理...")

        # 使用正确的表重建方式（保留约束）
        columns_to_keep = columns & valid_columns
        columns_str = ', '.join(columns_to_keep)

        # 1. 创建新表（带完整约束）
        await conn.execute("""
            CREATE TABLE players_new (
                user_id TEXT PRIMARY KEY,
                level_index INTEGER NOT NULL DEFAULT 0,
                spiritual_root TEXT NOT NULL DEFAULT '未知',
                cultivation_type TEXT NOT NULL DEFAULT '灵修',
                lifespan INTEGER NOT NULL DEFAULT 100,
                experience INTEGER NOT NULL DEFAULT 0,
                gold INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT '空闲',
                cultivation_start_time INTEGER NOT NULL DEFAULT 0,
                last_check_in_date TEXT NOT NULL DEFAULT '',
                spiritual_qi INTEGER NOT NULL DEFAULT 100,
                max_spiritual_qi INTEGER NOT NULL DEFAULT 1000,
                blood_qi INTEGER NOT NULL DEFAULT 0,
                max_blood_qi INTEGER NOT NULL DEFAULT 0,
                magic_damage INTEGER NOT NULL DEFAULT 10,
                physical_damage INTEGER NOT NULL DEFAULT 10,
                magic_defense INTEGER NOT NULL DEFAULT 5,
                physical_defense INTEGER NOT NULL DEFAULT 5,
                mental_power INTEGER NOT NULL DEFAULT 100,
                weapon TEXT NOT NULL DEFAULT '',
                armor TEXT NOT NULL DEFAULT '',
                main_technique TEXT NOT NULL DEFAULT '',
                techniques TEXT NOT NULL DEFAULT '[]',
                active_pill_effects TEXT NOT NULL DEFAULT '[]',
                permanent_pill_gains TEXT NOT NULL DEFAULT '{}',
                has_resurrection_pill INTEGER NOT NULL DEFAULT 0,
                has_debuff_shield INTEGER NOT NULL DEFAULT 0,
                pills_inventory TEXT NOT NULL DEFAULT '{}',
                storage_ring TEXT NOT NULL DEFAULT '基础储物戒',
                storage_ring_items TEXT NOT NULL DEFAULT '{}'
            )
        """)

        # 2. 复制数据
        await conn.execute(f"""
            INSERT INTO players_new ({columns_str})
            SELECT {columns_str} FROM players
        """)

        # 3. 删除旧表
        await conn.execute("DROP TABLE players")

        # 4. 重命名新表
        await conn.execute("ALTER TABLE players_new RENAME TO players")

        # 5. 重建索引
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_player_level ON players(level_index)")

        logger.info(f"已清理废弃字段: {deprecated_columns}")
    else:
        logger.info("没有发现废弃字段，跳过清理")

    logger.info("v10迁移完成：清理废弃字段")


@migration(11)
async def _migrate_to_v11(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v11 - 添加储物戒系统"""
    logger.info("开始迁移到v11：添加储物戒系统")

    # 添加储物戒字段
    await conn.execute("ALTER TABLE players ADD COLUMN storage_ring TEXT NOT NULL DEFAULT '基础储物戒'")
    await conn.execute("ALTER TABLE players ADD COLUMN storage_ring_items TEXT NOT NULL DEFAULT '{}'")

    logger.info("v11迁移完成：储物戒系统 - 所有玩家已配备基础储物戒")


async def _create_all_tables_v2(conn: aiosqlite.Connection):
    """创建所有表 - v2版本，完整修仙系统"""

    # 数据库版本信息表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS db_info (
            version INTEGER NOT NULL
        )
    """)

    # 玩家表 - 完整字段
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id TEXT PRIMARY KEY,
            user_name TEXT NOT NULL DEFAULT '',
            level_index INTEGER NOT NULL DEFAULT 0,
            cultivation_type TEXT NOT NULL DEFAULT '灵修',
            experience INTEGER NOT NULL DEFAULT 0,
            gold INTEGER NOT NULL DEFAULT 0,
            hp INTEGER NOT NULL DEFAULT 0,
            mp INTEGER NOT NULL DEFAULT 0,
            atk INTEGER NOT NULL DEFAULT 0,
            atkpractice INTEGER NOT NULL DEFAULT 0,
            sect_id INTEGER NOT NULL DEFAULT 0,
            sect_position INTEGER NOT NULL DEFAULT 4,
            sect_contribution INTEGER NOT NULL DEFAULT 0,
            sect_task INTEGER NOT NULL DEFAULT 0,
            sect_elixir_get INTEGER NOT NULL DEFAULT 0,
            blessed_spot_flag INTEGER NOT NULL DEFAULT 0,
            blessed_spot_name TEXT NOT NULL DEFAULT '',
            level_up_rate INTEGER NOT NULL DEFAULT 0,
            
            spiritual_root TEXT NOT NULL DEFAULT '未知',
            lifespan INTEGER NOT NULL DEFAULT 100,
            state TEXT NOT NULL DEFAULT '空闲',
            cultivation_start_time INTEGER NOT NULL DEFAULT 0,
            last_check_in_date TEXT NOT NULL DEFAULT '',
            spiritual_qi INTEGER NOT NULL DEFAULT 100,
            max_spiritual_qi INTEGER NOT NULL DEFAULT 1000,
            blood_qi INTEGER NOT NULL DEFAULT 0,
            max_blood_qi INTEGER NOT NULL DEFAULT 0,
            magic_damage INTEGER NOT NULL DEFAULT 10,
            physical_damage INTEGER NOT NULL DEFAULT 10,
            magic_defense INTEGER NOT NULL DEFAULT 5,
            physical_defense INTEGER NOT NULL DEFAULT 5,
            mental_power INTEGER NOT NULL DEFAULT 100,
            
            weapon TEXT NOT NULL DEFAULT '',
            armor TEXT NOT NULL DEFAULT '',
            main_technique TEXT NOT NULL DEFAULT '',
            techniques TEXT NOT NULL DEFAULT '[]',
            
            active_pill_effects TEXT NOT NULL DEFAULT '[]',
            permanent_pill_gains TEXT NOT NULL DEFAULT '{}',
            has_resurrection_pill INTEGER NOT NULL DEFAULT 0,
            has_debuff_shield INTEGER NOT NULL DEFAULT 0,
            pills_inventory TEXT NOT NULL DEFAULT '{}',
            storage_ring TEXT NOT NULL DEFAULT '基础储物戒',
            storage_ring_items TEXT NOT NULL DEFAULT '{}',
            
            daily_pill_usage TEXT NOT NULL DEFAULT '{}',
            last_daily_reset TEXT NOT NULL DEFAULT ''
        )
    """)

    # 创建索引
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_player_level ON players(level_index)")

    # 创建商店表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS shop (
            shop_id TEXT PRIMARY KEY,
            last_refresh_time INTEGER NOT NULL DEFAULT 0,
            current_items TEXT NOT NULL DEFAULT '[]'
        )
    """)
    # 插入全局商店数据
    await conn.execute("""
        INSERT OR IGNORE INTO shop (shop_id, last_refresh_time, current_items)
        VALUES ('global', 0, '[]')
    """)
    
    # 创建宗门表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS sects (
            sect_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sect_name TEXT NOT NULL UNIQUE,
            sect_owner TEXT NOT NULL,
            sect_scale INTEGER NOT NULL DEFAULT 0,
            sect_used_stone INTEGER NOT NULL DEFAULT 0,
            sect_fairyland INTEGER NOT NULL DEFAULT 0,
            sect_materials INTEGER NOT NULL DEFAULT 0,
            mainbuff TEXT NOT NULL DEFAULT '0',
            secbuff TEXT NOT NULL DEFAULT '0',
            elixir_room_level INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_sect_owner ON sects(sect_owner)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_sect_scale ON sects(sect_scale DESC)")
    
    # 创建Buff信息表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS buff_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            main_buff INTEGER NOT NULL DEFAULT 0,
            sec_buff INTEGER NOT NULL DEFAULT 0,
            faqi_buff INTEGER NOT NULL DEFAULT 0,
            fabao_weapon INTEGER NOT NULL DEFAULT 0,
            armor_buff INTEGER NOT NULL DEFAULT 0,
            atk_buff INTEGER NOT NULL DEFAULT 0,
            blessed_spot INTEGER NOT NULL DEFAULT 0,
            sub_buff INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_buff_user ON buff_info(user_id)")
    
    # 创建Boss表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS boss (
            boss_id INTEGER PRIMARY KEY AUTOINCREMENT,
            boss_name TEXT NOT NULL,
            boss_level TEXT NOT NULL,
            hp INTEGER NOT NULL,
            max_hp INTEGER NOT NULL,
            atk INTEGER NOT NULL,
            defense INTEGER NOT NULL DEFAULT 0,
            stone_reward INTEGER NOT NULL DEFAULT 0,
            create_time INTEGER NOT NULL DEFAULT 0,
            status INTEGER NOT NULL DEFAULT 1
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_boss_status ON boss(status, create_time DESC)")
    
    # 创建秘境表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS rifts (
            rift_id INTEGER PRIMARY KEY AUTOINCREMENT,
            rift_name TEXT NOT NULL,
            rift_level INTEGER NOT NULL,
            required_level INTEGER NOT NULL,
            rewards TEXT NOT NULL DEFAULT '{}'
        )
    """)
    
    # 创建传承信息表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS impart_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            impart_hp_per REAL NOT NULL DEFAULT 0.0,
            impart_mp_per REAL NOT NULL DEFAULT 0.0,
            impart_atk_per REAL NOT NULL DEFAULT 0.0,
            impart_know_per REAL NOT NULL DEFAULT 0.0,
            impart_burst_per REAL NOT NULL DEFAULT 0.0
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_impart_user ON impart_info(user_id)")
    
    # 创建用户CD表
    # 注意：extra_data 列由 v20 迁移添加，但秘境/历练的 set_user_busy 写入与
    # get_extra_data 读取都依赖它，全新安装时必须直接建出来，否则一进秘境就崩。
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_cd (
            user_id TEXT PRIMARY KEY,
            type INTEGER NOT NULL DEFAULT 0,
            create_time INTEGER NOT NULL DEFAULT 0,
            scheduled_time INTEGER NOT NULL DEFAULT 0,
            extra_data TEXT NOT NULL DEFAULT '{}'
        )
    """)
    
    # 创建赠予请求表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_gifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receiver_id TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            sender_name TEXT NOT NULL DEFAULT '',
            item_name TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_gifts_receiver ON pending_gifts(receiver_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_gifts_expires ON pending_gifts(expires_at)")
    
    # 创建银行账户表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bank_accounts (
            user_id TEXT PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0,
            last_interest_time INTEGER NOT NULL DEFAULT 0
        )
    """)
    
    # 创建银行贷款表
    # v23 起：移除表级 UNIQUE(user_id, status)，改为「部分唯一索引」保证同一用户
    # 最多一条 active 贷款 + 一条 carried 继承债务（详见 _migrate_to_v23）。
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bank_loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            principal INTEGER NOT NULL DEFAULT 0,
            interest_rate REAL NOT NULL DEFAULT 0.005,
            borrowed_at INTEGER NOT NULL,
            due_at INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            loan_type TEXT NOT NULL DEFAULT 'normal',
            inherit_count INTEGER NOT NULL DEFAULT 0,
            settled_amount INTEGER NOT NULL DEFAULT 0,
            inherit_at INTEGER NOT NULL DEFAULT 0,
            grace_until INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_loans_user ON bank_loans(user_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_loans_status ON bank_loans(status)")
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_bank_loans_user_active "
        "ON bank_loans(user_id) WHERE status = 'active'"
    )
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_bank_loans_user_carried "
        "ON bank_loans(user_id) WHERE status = 'carried'"
    )
    
    # 创建银行交易流水表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bank_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            trans_type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            balance_after INTEGER NOT NULL DEFAULT 0,
            description TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_trans_user ON bank_transactions(user_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_trans_time ON bank_transactions(created_at)")

    # ===== Phase 2/3/4 补充表（v14/v16/v20 的建表在此补齐）=====
    # 说明：全新安装路径不会执行 MIGRATION_TASKS，若此处缺失，
    # 洞天福地 / 灵田 / 双修 / 灵眼 / 悬赏 / 决斗 将直接抛 no such table。

    # 悬赏任务表（v14）
    await conn.execute("""
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
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_bounty_user ON bounty_tasks(user_id)")

    # 洞天福地表（v16）
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS blessed_lands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            land_type INTEGER NOT NULL DEFAULT 1,
            land_name TEXT NOT NULL DEFAULT '小洞天',
            level INTEGER NOT NULL DEFAULT 1,
            exp_bonus REAL NOT NULL DEFAULT 0.05,
            gold_per_hour INTEGER NOT NULL DEFAULT 60,
            last_collect_time INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_blessed_lands_user ON blessed_lands(user_id)")

    # 灵田表（v16）
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS spirit_farms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            level INTEGER NOT NULL DEFAULT 1,
            crops TEXT NOT NULL DEFAULT '[]'
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_spirit_farms_user ON spirit_farms(user_id)")

    # 双修记录表（v16）
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS dual_cultivation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            last_dual_time INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_dual_user ON dual_cultivation(user_id)")

    # 天地灵眼表（v16 + v20 增补 last_collect_time 列 + v22 增补时效/守护字段）
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS spirit_eyes (
            eye_id INTEGER PRIMARY KEY AUTOINCREMENT,
            eye_type INTEGER NOT NULL DEFAULT 1,
            eye_name TEXT NOT NULL DEFAULT '下品灵眼',
            exp_per_hour INTEGER NOT NULL DEFAULT 500,
            spawn_time INTEGER NOT NULL,
            owner_id TEXT,
            owner_name TEXT,
            claim_time INTEGER,
            last_collect_time INTEGER,
            expire_time INTEGER NOT NULL DEFAULT 0,
            protect_until INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_spirit_eyes_owner ON spirit_eyes(owner_id)")

    # 双修请求持久化表（v20）
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS dual_cultivation_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_id TEXT NOT NULL,
            from_name TEXT NOT NULL,
            target_id TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_dual_req_target ON dual_cultivation_requests(target_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_dual_req_expires ON dual_cultivation_requests(expires_at)")

    # 战斗冷却表（v20 + v22 增补 last_eye_time 灵眼争夺冷却）
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS combat_cooldowns (
            user_id TEXT PRIMARY KEY,
            last_duel_time INTEGER NOT NULL DEFAULT 0,
            last_spar_time INTEGER NOT NULL DEFAULT 0,
            last_eye_time INTEGER NOT NULL DEFAULT 0
        )
    """)

    # 世界Boss挑战记录表（v24）：按「玩家 × Boss 实例」计次数，Boss 刷新后自动重置
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS boss_challenges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            boss_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            challenge_count INTEGER NOT NULL DEFAULT 0,
            last_challenge_time INTEGER NOT NULL DEFAULT 0,
            UNIQUE(boss_id, user_id)
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_boss_challenges_user ON boss_challenges(user_id)"
    )

    # 天灾人祸记录表（v25）：记录每次天灾的类型、被罚者与实际损失
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS calamity_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            calamity_id TEXT NOT NULL DEFAULT '',
            calamity_name TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '天灾',
            target_user_id TEXT NOT NULL,
            target_name TEXT NOT NULL DEFAULT '',
            gold_lost INTEGER NOT NULL DEFAULT 0,
            exp_lost INTEGER NOT NULL DEFAULT 0,
            no_event INTEGER NOT NULL DEFAULT 0,
            shielded INTEGER NOT NULL DEFAULT 0,
            create_time INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_calamity_records_time ON calamity_records(create_time)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_calamity_records_user ON calamity_records(target_user_id)"
    )

    # ===== 种子数据 =====
    # 默认秘境（v15 的种子数据；缺失会导致 /秘境列表 永远为空）
    import json as _json
    import time as _time
    default_rifts = [
        (1, "青云秘境", 1, 0, _json.dumps({"exp": [500, 1500], "gold": [200, 800]})),
        (2, "落日峡谷", 2, 3, _json.dumps({"exp": [1500, 4000], "gold": [500, 2000]})),
        (3, "万妖洞", 3, 6, _json.dumps({"exp": [3000, 8000], "gold": [1000, 5000]})),
        (4, "玄冰地宫", 4, 10, _json.dumps({"exp": [5000, 15000], "gold": [2000, 10000]})),
        (5, "上古遗迹", 5, 15, _json.dumps({"exp": [10000, 30000], "gold": [5000, 20000]})),
    ]
    for rift in default_rifts:
        try:
            await conn.execute(
                "INSERT OR IGNORE INTO rifts (rift_id, rift_name, rift_level, required_level, rewards) VALUES (?, ?, ?, ?, ?)",
                rift
            )
        except Exception:
            pass

    # 初始灵眼（v16 的种子数据；v22 起带时效，到期自动消散）
    now = int(_time.time())
    initial_eyes = [
        (1, "下品灵眼", 500, now, now + SPIRIT_EYE_LIFETIME_HOURS[1] * 3600),
        (1, "下品灵眼", 500, now, now + SPIRIT_EYE_LIFETIME_HOURS[1] * 3600),
        (2, "中品灵眼", 2000, now, now + SPIRIT_EYE_LIFETIME_HOURS[2] * 3600),
    ]
    for eye in initial_eyes:
        try:
            await conn.execute(
                "INSERT INTO spirit_eyes (eye_type, eye_name, exp_per_hour, spawn_time, expire_time) "
                "VALUES (?, ?, ?, ?, ?)",
                eye
            )
        except Exception:
            pass

    logger.info("数据库表已创建完成（v2 - 完整修仙系统，含 Phase 2/3/4 补充表与种子数据）")


@migration(12)
async def _migrate_to_v12(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v12 - 添加完整修仙系统（宗门、Boss、秘境、战斗系统等）"""
    logger.info("开始迁移到v12：添加完整修仙系统")
    
    # 1. 添加Player新字段（战斗属性和宗门）
    logger.info("添加战斗属性字段...")
    await conn.execute("ALTER TABLE players ADD COLUMN user_name TEXT NOT NULL DEFAULT ''")
    await conn.execute("ALTER TABLE players ADD COLUMN level_up_rate INTEGER NOT NULL DEFAULT 0")
    await conn.execute("ALTER TABLE players ADD COLUMN hp INTEGER NOT NULL DEFAULT 0")
    await conn.execute("ALTER TABLE players ADD COLUMN mp INTEGER NOT NULL DEFAULT 0")
    await conn.execute("ALTER TABLE players ADD COLUMN atk INTEGER NOT NULL DEFAULT 0")
    await conn.execute("ALTER TABLE players ADD COLUMN atkpractice INTEGER NOT NULL DEFAULT 0")
    
    logger.info("添加宗门相关字段...")
    await conn.execute("ALTER TABLE players ADD COLUMN sect_id INTEGER NOT NULL DEFAULT 0")
    await conn.execute("ALTER TABLE players ADD COLUMN sect_position INTEGER NOT NULL DEFAULT 4")
    await conn.execute("ALTER TABLE players ADD COLUMN sect_contribution INTEGER NOT NULL DEFAULT 0")
    await conn.execute("ALTER TABLE players ADD COLUMN sect_task INTEGER NOT NULL DEFAULT 0")
    await conn.execute("ALTER TABLE players ADD COLUMN sect_elixir_get INTEGER NOT NULL DEFAULT 0")
    
    logger.info("添加洞天福地字段...")
    await conn.execute("ALTER TABLE players ADD COLUMN blessed_spot_flag INTEGER NOT NULL DEFAULT 0")
    await conn.execute("ALTER TABLE players ADD COLUMN blessed_spot_name TEXT NOT NULL DEFAULT ''")
    
    # 2. 创建新表
    logger.info("创建宗门表...")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS sects (
            sect_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sect_name TEXT NOT NULL UNIQUE,
            sect_owner TEXT NOT NULL,
            sect_scale INTEGER NOT NULL DEFAULT 0,
            sect_used_stone INTEGER NOT NULL DEFAULT 0,
            sect_fairyland INTEGER NOT NULL DEFAULT 0,
            sect_materials INTEGER NOT NULL DEFAULT 0,
            mainbuff TEXT NOT NULL DEFAULT '0',
            secbuff TEXT NOT NULL DEFAULT '0',
            elixir_room_level INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_sect_owner ON sects(sect_owner)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_sect_scale ON sects(sect_scale DESC)")
    
    logger.info("创建Buff信息表...")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS buff_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            main_buff INTEGER NOT NULL DEFAULT 0,
            sec_buff INTEGER NOT NULL DEFAULT 0,
            faqi_buff INTEGER NOT NULL DEFAULT 0,
            fabao_weapon INTEGER NOT NULL DEFAULT 0,
            armor_buff INTEGER NOT NULL DEFAULT 0,
            atk_buff INTEGER NOT NULL DEFAULT 0,
            blessed_spot INTEGER NOT NULL DEFAULT 0,
            sub_buff INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_buff_user ON buff_info(user_id)")
    
    logger.info("创建Boss表...")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS boss (
            boss_id INTEGER PRIMARY KEY AUTOINCREMENT,
            boss_name TEXT NOT NULL,
            boss_level TEXT NOT NULL,
            hp INTEGER NOT NULL,
            max_hp INTEGER NOT NULL,
            atk INTEGER NOT NULL,
            defense INTEGER NOT NULL DEFAULT 0,
            stone_reward INTEGER NOT NULL DEFAULT 0,
            create_time INTEGER NOT NULL DEFAULT 0,
            status INTEGER NOT NULL DEFAULT 1
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_boss_status ON boss(status, create_time DESC)")
    
    logger.info("创建秘境表...")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS rifts (
            rift_id INTEGER PRIMARY KEY AUTOINCREMENT,
            rift_name TEXT NOT NULL,
            rift_level INTEGER NOT NULL,
            required_level INTEGER NOT NULL,
            rewards TEXT NOT NULL DEFAULT '{}'
        )
    """)
    
    logger.info("创建传承信息表...")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS impart_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            impart_hp_per REAL NOT NULL DEFAULT 0.0,
            impart_mp_per REAL NOT NULL DEFAULT 0.0,
            impart_atk_per REAL NOT NULL DEFAULT 0.0,
            impart_know_per REAL NOT NULL DEFAULT 0.0,
            impart_burst_per REAL NOT NULL DEFAULT 0.0
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_impart_user ON impart_info(user_id)")
    
    logger.info("创建用户CD表...")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_cd (
            user_id TEXT PRIMARY KEY,
            type INTEGER NOT NULL DEFAULT 0,
            create_time INTEGER NOT NULL DEFAULT 0,
            scheduled_time INTEGER NOT NULL DEFAULT 0
        )
    """)
    
    # 3. 初始化现有用户的扩展数据
    logger.info("为现有用户初始化扩展数据...")
    async with conn.execute("SELECT user_id FROM players") as cursor:
        users = await cursor.fetchall()
        for user in users:
            user_id = user[0]
            # 初始化BuffInfo
            await conn.execute("""
                INSERT OR IGNORE INTO buff_info (user_id) VALUES (?)
            """, (user_id,))
            # 初始化UserCd
            await conn.execute("""
                INSERT OR IGNORE INTO user_cd (user_id) VALUES (?)
            """, (user_id,))
            # 初始化ImpartInfo
            await conn.execute("""
                INSERT OR IGNORE INTO impart_info (user_id) VALUES (?)
            """, (user_id,))
    
    logger.info(f"v12迁移完成：完整修仙系统 - 已为 {len(users)} 个用户初始化扩展数据")


@migration(13)
async def _migrate_to_v13(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v13 - Phase 1: 道号系统、每日限制、物品绑定"""
    logger.info("开始迁移到v13：Phase 1 功能增强")
    
    # 1. 添加每日限制字段
    logger.info("添加每日限制字段...")
    try:
        await conn.execute("ALTER TABLE players ADD COLUMN daily_pill_usage TEXT NOT NULL DEFAULT '{}'")
    except:
        pass  # 字段可能已存在
    try:
        await conn.execute("ALTER TABLE players ADD COLUMN last_daily_reset TEXT NOT NULL DEFAULT ''")
    except:
        pass
    
    logger.info("v13迁移完成：Phase 1 功能增强")


@migration(14)
async def _migrate_to_v14(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v14 - Phase 2: 灵石银行、悬赏令系统"""
    logger.info("开始迁移到v14：Phase 2 经济与任务系统")
    
    # 1. 创建银行账户表
    logger.info("创建银行账户表...")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bank_accounts (
            user_id TEXT PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0,
            last_interest_time INTEGER NOT NULL DEFAULT 0
        )
    """)
    
    # 2. 创建悬赏任务表
    logger.info("创建悬赏任务表...")
    await conn.execute("""
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
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_bounty_user ON bounty_tasks(user_id)")
    
    logger.info("v14迁移完成：Phase 2 经济与任务系统")


@migration(15)
async def _migrate_to_v15(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v15 - 添加默认秘境数据"""
    logger.info("开始迁移到v15：添加默认秘境数据")
    
    # 插入默认秘境数据
    import json
    default_rifts = [
        (1, "青云秘境", 1, 0, json.dumps({"exp": [500, 1500], "gold": [200, 800]})),
        (2, "落日峡谷", 2, 3, json.dumps({"exp": [1500, 4000], "gold": [500, 2000]})),
        (3, "万妖洞", 3, 6, json.dumps({"exp": [3000, 8000], "gold": [1000, 5000]})),
        (4, "玄冰地宫", 4, 10, json.dumps({"exp": [5000, 15000], "gold": [2000, 10000]})),
        (5, "上古遗迹", 5, 15, json.dumps({"exp": [10000, 30000], "gold": [5000, 20000]})),
    ]
    
    for rift in default_rifts:
        try:
            await conn.execute(
                "INSERT OR IGNORE INTO rifts (rift_id, rift_name, rift_level, required_level, rewards) VALUES (?, ?, ?, ?, ?)",
                rift
            )
        except:
            pass
    
    await conn.commit()
    logger.info("v15迁移完成：已添加5个默认秘境")


@migration(16)
async def _migrate_to_v16(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v16 - Phase 4 扩展功能"""
    logger.info("开始迁移到v16：Phase 4 扩展功能")
    
    # 洞天福地表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS blessed_lands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            land_type INTEGER NOT NULL DEFAULT 1,
            land_name TEXT NOT NULL DEFAULT '小洞天',
            level INTEGER NOT NULL DEFAULT 1,
            exp_bonus REAL NOT NULL DEFAULT 0.05,
            gold_per_hour INTEGER NOT NULL DEFAULT 60,
            last_collect_time INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_blessed_lands_user ON blessed_lands(user_id)")
    
    # 灵田表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS spirit_farms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            level INTEGER NOT NULL DEFAULT 1,
            crops TEXT NOT NULL DEFAULT '[]'
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_spirit_farms_user ON spirit_farms(user_id)")
    
    # 双修记录表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS dual_cultivation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            last_dual_time INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_dual_user ON dual_cultivation(user_id)")
    
    # 天地灵眼表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS spirit_eyes (
            eye_id INTEGER PRIMARY KEY AUTOINCREMENT,
            eye_type INTEGER NOT NULL DEFAULT 1,
            eye_name TEXT NOT NULL DEFAULT '下品灵眼',
            exp_per_hour INTEGER NOT NULL DEFAULT 500,
            spawn_time INTEGER NOT NULL,
            owner_id TEXT,
            owner_name TEXT,
            claim_time INTEGER
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_spirit_eyes_owner ON spirit_eyes(owner_id)")
    
    # 插入初始灵眼
    import time
    now = int(time.time())
    initial_eyes = [
        (1, "下品灵眼", 500, now),
        (1, "下品灵眼", 500, now),
        (2, "中品灵眼", 2000, now),
    ]
    for eye in initial_eyes:
        await conn.execute(
            "INSERT INTO spirit_eyes (eye_type, eye_name, exp_per_hour, spawn_time) VALUES (?, ?, ?, ?)",
            eye
        )
    
    await conn.commit()
    logger.info("v16迁移完成：Phase 4 扩展功能（洞天福地、灵田、双修、灵眼）")


@migration(17)
async def _migrate_to_v17(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v17 - 赠予请求持久化"""
    logger.info("开始迁移到v17：赠予请求持久化")
    
    # 创建赠予请求表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_gifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receiver_id TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            sender_name TEXT NOT NULL DEFAULT '',
            item_name TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_gifts_receiver ON pending_gifts(receiver_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_gifts_expires ON pending_gifts(expires_at)")
    
    await conn.commit()
    logger.info("v17迁移完成：赠予请求持久化")


@migration(18)
async def _migrate_to_v18(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v18 - 银行贷款与交易流水系统"""
    logger.info("开始迁移到v18：银行贷款与交易流水系统")
    
    # 0. 确保 bank_accounts 表存在（v14可能未正确创建）
    logger.info("确保银行账户表存在...")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bank_accounts (
            user_id TEXT PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0,
            last_interest_time INTEGER NOT NULL DEFAULT 0
        )
    """)
    
    # 1. 创建银行贷款表
    logger.info("创建银行贷款表...")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bank_loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            principal INTEGER NOT NULL DEFAULT 0,
            interest_rate REAL NOT NULL DEFAULT 0.005,
            borrowed_at INTEGER NOT NULL,
            due_at INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            loan_type TEXT NOT NULL DEFAULT 'normal',
            UNIQUE(user_id, status)
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_loans_user ON bank_loans(user_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_loans_status ON bank_loans(status)")
    
    # 2. 创建银行交易流水表
    logger.info("创建银行交易流水表...")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bank_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            trans_type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            balance_after INTEGER NOT NULL DEFAULT 0,
            description TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_trans_user ON bank_transactions(user_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_trans_time ON bank_transactions(created_at)")
    
    await conn.commit()
    logger.info("v18迁移完成：银行贷款与交易流水系统")


@migration(19)
async def _migrate_to_v19(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v19 - 银行系统表完整性修复"""
    logger.info("开始迁移到v19：银行系统表完整性修复")
    
    # 确保 bank_accounts 表存在（修复v14迁移可能跳过的情况）
    logger.info("确保银行账户表存在...")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bank_accounts (
            user_id TEXT PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0,
            last_interest_time INTEGER NOT NULL DEFAULT 0
        )
    """)
    
    # 确保 bank_loans 表存在
    logger.info("确保银行贷款表存在...")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bank_loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            principal INTEGER NOT NULL DEFAULT 0,
            interest_rate REAL NOT NULL DEFAULT 0.005,
            borrowed_at INTEGER NOT NULL,
            due_at INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            loan_type TEXT NOT NULL DEFAULT 'normal'
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_loans_user ON bank_loans(user_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_loans_status ON bank_loans(status)")
    
    # 确保 bank_transactions 表存在
    logger.info("确保银行交易流水表存在...")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bank_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            trans_type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            balance_after INTEGER NOT NULL DEFAULT 0,
            description TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_trans_user ON bank_transactions(user_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_trans_time ON bank_transactions(created_at)")
    
    await conn.commit()
    logger.info("v19迁移完成：银行系统表完整性修复")


@migration(20)
async def _migrate_to_v20(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v20 - 用户CD表添加额外数据字段"""
    logger.info("开始迁移到v20：用户CD表添加额外数据字段")
    
    # 添加extra_data字段用于存储额外信息（如秘境ID、战斗冷却等）
    try:
        await conn.execute("ALTER TABLE user_cd ADD COLUMN extra_data TEXT NOT NULL DEFAULT '{}'")
    except Exception as e:
        logger.warning(f"添加extra_data字段失败（可能已存在）: {e}")
    
    # 添加last_collect_time字段到spirit_eyes表（修复灵眼收取时间计算）
    try:
        await conn.execute("ALTER TABLE spirit_eyes ADD COLUMN last_collect_time INTEGER")
    except Exception as e:
        logger.warning(f"添加last_collect_time字段失败（可能已存在）: {e}")
    
    # 添加双修请求持久化表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS dual_cultivation_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_id TEXT NOT NULL,
            from_name TEXT NOT NULL,
            target_id TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_dual_req_target ON dual_cultivation_requests(target_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_dual_req_expires ON dual_cultivation_requests(expires_at)")
    
    # 添加战斗冷却表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS combat_cooldowns (
            user_id TEXT PRIMARY KEY,
            last_duel_time INTEGER NOT NULL DEFAULT 0,
            last_spar_time INTEGER NOT NULL DEFAULT 0
        )
    """)
    
    await conn.commit()
    logger.info("v20迁移完成：用户CD表添加额外数据字段")


@migration(21)
async def _migrate_to_v21(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v21 - 洞天福地挂机产出重标定（约7天回本）

    背景：
      洞天收益原先约 4 天回本（24%/天），玩家可用「贷款 → 买洞天 → 用洞天
      被动收益还贷」闭环净赚并白得生息资产（杠杆套利）。v3.2.5 将各档洞天
      重标定为约 7 天回本（约 14.3%/天），并改为「贷款存续期洞天产出被
      银行托管」来切断套利路径。

    为何需要迁移：
      blessed_lands.gold_per_hour 是**入库快照**——购置时写入当时的配置值，
      升级时按 int(base * (1 + level*0.15)) 重算。直接改 managers 中的
      BLESSED_LANDS 常量只对**新购/新升级**生效，存量玩家的洞天仍是旧
      收益率，必须回填才能让经济口径一致。

    做法：
      按 land_type + level 用新基准值重算存量洞天的 gold_per_hour
      （level=1 取基准值；level>=2 沿用升级公式 int(base*(1+level*0.15))）。
    """
    logger.info("开始迁移到v21：洞天福地挂机产出重标定（约7天回本）")

    # 新基准：与 managers/blessed_land_manager.py::BLESSED_LANDS 保持一致
    new_base = {
        1: 60,     # 小洞天   10,000 灵石
        2: 300,    # 中洞天   50,000 灵石
        3: 1200,   # 大洞天  200,000 灵石
        4: 3000,   # 福地    500,000 灵石
        5: 6000,   # 洞天福地 1,000,000 灵石
    }

    try:
        async with conn.execute("SELECT user_id, land_type, level FROM blessed_lands") as cursor:
            rows = await cursor.fetchall()

        updated = 0
        for row in rows:
            user_id = row[0]
            land_type = int(row[1] or 1)
            level = int(row[2] or 1)
            base = new_base.get(land_type)
            if not base:
                continue
            if level <= 1:
                new_gph = base
            else:
                new_gph = int(base * (1 + level * 0.15))
            await conn.execute(
                "UPDATE blessed_lands SET gold_per_hour = ? WHERE user_id = ?",
                (new_gph, user_id)
            )
            updated += 1

        logger.info(f"v21迁移完成：已重算 {updated} 位玩家的洞天挂机产出")
    except Exception as e:
        logger.error(f"v21迁移失败（洞天产出重标定）: {e}")
        raise

    await conn.commit()


@migration(22)
async def _migrate_to_v22(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v22 - 天地灵眼时效化 + PVP 争夺支持

    背景：
      此前灵眼一旦被抢占就从列表消失（get_available_spirit_eyes 只查无主），
      导致玩家既看不到别人的灵眼、也无法发起争夺；同时灵眼永不过期，
      高阶灵眼可被长期垄断。新版将灵眼改为「有时效」资源：越高级时效越短，
      到期自动消散（结算未收修为后删除），并支持 @人 发起 PVP 争夺。

    新增字段：
      spirit_eyes.expire_time    —— 消散时间戳（0 表示旧数据/无时效）
      spirit_eyes.protect_until —— 守护期截止时间戳（防守成功后生效，冷却骚扰）
      combat_cooldowns.last_eye_time —— 玩家上次发起灵眼争夺的时间（发起冷却）

    存量数据处理：
      旧灵眼的 expire_time 一律回填为「当前时间 + 该档时效」，让存量灵眼
      获得完整的一个时效窗口，而不是上线即全灭（避免玩家资产瞬间蒸发）。
    """
    logger.info("开始迁移到v22：天地灵眼时效化 + PVP 争夺支持")

    import time as _time
    now = int(_time.time())

    # 1) spirit_eyes 新增两列
    for ddl in (
        "ALTER TABLE spirit_eyes ADD COLUMN expire_time INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE spirit_eyes ADD COLUMN protect_until INTEGER NOT NULL DEFAULT 0",
    ):
        try:
            await conn.execute(ddl)
        except Exception as e:
            logger.warning(f"添加灵眼字段失败（可能已存在）: {e}")

    # 2) combat_cooldowns 新增灵眼争夺冷却列
    try:
        await conn.execute(
            "ALTER TABLE combat_cooldowns ADD COLUMN last_eye_time INTEGER NOT NULL DEFAULT 0"
        )
    except Exception as e:
        logger.warning(f"添加 last_eye_time 字段失败（可能已存在）: {e}")

    # 3) 存量灵眼回填时效：从当前时间起算，给足一个完整窗口
    try:
        async with conn.execute("SELECT eye_id, eye_type FROM spirit_eyes") as cursor:
            rows = await cursor.fetchall()

        updated = 0
        for row in rows:
            eye_id = row[0]
            eye_type = int(row[1] or 1)
            hours = SPIRIT_EYE_LIFETIME_HOURS.get(eye_type, SPIRIT_EYE_LIFETIME_HOURS[1])
            await conn.execute(
                "UPDATE spirit_eyes SET expire_time = ?, protect_until = 0 WHERE eye_id = ?",
                (now + hours * 3600, eye_id)
            )
            updated += 1

        logger.info(f"v22迁移完成：已为 {updated} 处灵眼设置时效")
    except Exception as e:
        logger.error(f"v22迁移失败（灵眼时效化）: {e}")
        raise

    await conn.commit()


@migration(23)
async def _migrate_to_v23(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v23 - 贷款死亡债务继承（Death Debt Carry-over）

    背景：
      此前玩家死亡时 `delete_player_cascade` 会把 active 贷款直接置为 bad_debt（免除），
      玩家重开（我要修仙）后债务静默消失，形成「借钱 → 死亡 → 重开白嫖」的漏洞。

    变更：
      1) 重建 bank_loans 表：
         - 移除表级 UNIQUE(user_id, status) 约束。
           该约束让同一用户每种 status 只能存在一行，导致：
             * 第二次还款（active → closed）触发 IntegrityError（玩家一生只能成功还清一次贷款）
             * 无法同时保留「历史已结清记录」与「当前活跃贷款」
           改为使用「部分唯一索引」：同一用户最多一条 active + 一条 carried。
         - 新增列：
             inherit_count   —— 该债务已被继承追溯的次数（用于「3 次后豁免」上限）
             settled_amount  —— 继承时锁定的应还总额（本金 + 死亡时已产生利息），固定免息
             inherit_at      —— 最近一次继承的时间戳
             grace_until     —— 重开后恢复债务的宽限期截止时间戳
      2) 存量数据处理：
         - 原有 active 贷款原样保留（inheritable 语义在运行时生效，无需改写本金）
         - 已存在的 closed / bad_debt / overdue 行一并迁移，历史不清空
    """
    logger.info("开始迁移到v23：贷款死亡债务继承")

    # 1) 确认旧表结构（兼容 bank_loans 不存在的极端情况）
    async with conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='bank_loans'"
    ) as cursor:
        table_exists = await cursor.fetchone() is not None

    if not table_exists:
        # 极端场景：旧库根本没有 bank_loans，直接建新表
        logger.warning("v23迁移：未找到 bank_loans 表，将直接创建新结构")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bank_loans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                principal INTEGER NOT NULL DEFAULT 0,
                interest_rate REAL NOT NULL DEFAULT 0.005,
                borrowed_at INTEGER NOT NULL,
                due_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                loan_type TEXT NOT NULL DEFAULT 'normal',
                inherit_count INTEGER NOT NULL DEFAULT 0,
                settled_amount INTEGER NOT NULL DEFAULT 0,
                inherit_at INTEGER NOT NULL DEFAULT 0,
                grace_until INTEGER NOT NULL DEFAULT 0
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_loans_user ON bank_loans(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_loans_status ON bank_loans(status)")
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_bank_loans_user_active "
            "ON bank_loans(user_id) WHERE status = 'active'"
        )
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_bank_loans_user_carried "
            "ON bank_loans(user_id) WHERE status = 'carried'"
        )
        await conn.commit()
        logger.info("v23迁移完成：已创建 bank_loans（新结构）")
        return

    # 2) 重建表：去掉表级 UNIQUE(user_id, status)，补齐新列
    await conn.execute("ALTER TABLE bank_loans RENAME TO bank_loans_old_v22")

    await conn.execute("""
        CREATE TABLE bank_loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            principal INTEGER NOT NULL DEFAULT 0,
            interest_rate REAL NOT NULL DEFAULT 0.005,
            borrowed_at INTEGER NOT NULL,
            due_at INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            loan_type TEXT NOT NULL DEFAULT 'normal',
            inherit_count INTEGER NOT NULL DEFAULT 0,
            settled_amount INTEGER NOT NULL DEFAULT 0,
            inherit_at INTEGER NOT NULL DEFAULT 0,
            grace_until INTEGER NOT NULL DEFAULT 0
        )
    """)

    # 3) 搬运存量数据（保留 id，保证外部引用不失效）
    await conn.execute("""
        INSERT INTO bank_loans (
            id, user_id, principal, interest_rate, borrowed_at, due_at,
            status, loan_type, inherit_count, settled_amount, inherit_at, grace_until
        )
        SELECT id, user_id, principal, interest_rate, borrowed_at, due_at,
               status, loan_type, 0, 0, 0, 0
        FROM bank_loans_old_v22
    """)

    await conn.execute("DROP TABLE bank_loans_old_v22")

    # 3.5) 去重：v19 建表时没有 UNIQUE(user_id,status) 约束，
    #      极端情况下同一用户可能存在多条 active / carried 记录，
    #      会导致下方部分唯一索引创建失败。此处按 id 倒序保留最新一条。
    await conn.execute("""
        DELETE FROM bank_loans
        WHERE id NOT IN (
            SELECT MAX(id) FROM bank_loans
            WHERE status IN ('active', 'carried')
            GROUP BY user_id, status
        )
        AND status IN ('active', 'carried')
    """)

    # 4) 重建索引（含两条部分唯一索引）
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_loans_user ON bank_loans(user_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_loans_status ON bank_loans(status)")
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_bank_loans_user_active "
        "ON bank_loans(user_id) WHERE status = 'active'"
    )
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_bank_loans_user_carried "
        "ON bank_loans(user_id) WHERE status = 'carried'"
    )

    await conn.commit()
    logger.info("v23迁移完成：贷款债务继承机制已启用")


@migration(24)
async def _migrate_to_v24(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v24 - 世界Boss挑战次数限制

    背景：
      此前 `challenge_boss` 没有任何次数/冷却限制，且每次挑战前会把玩家
      气血重算为满值（`player.hp = player_stats.hp`），失败还按伤害比例
      发「安慰奖」⇒ 玩家可以连发无限次「挑战Boss」：
        1. 无限刷安慰奖（每次失败都按伤害比例给灵石）；
        2. 把 Boss 血量磨到濒死，让后续玩家轻松收割（抢人头）；
        3. 无视自身战力差距反复送死。

    变更：
      新增 `boss_challenges` 表，记录「玩家 × 某只 Boss」的挑战次数与
      上次挑战时间。次数按 Boss 实例（boss_id）计数，Boss 刷新后自然是
      新 boss_id ⇒ 次数自动重置，无需额外的每日重置任务。
    """
    logger.info("开始迁移到v24：世界Boss挑战次数限制")

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS boss_challenges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            boss_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            challenge_count INTEGER NOT NULL DEFAULT 0,
            last_challenge_time INTEGER NOT NULL DEFAULT 0,
            UNIQUE(boss_id, user_id)
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_boss_challenges_user ON boss_challenges(user_id)"
    )

    await conn.commit()
    logger.info("v24迁移完成：世界Boss挑战次数限制已启用")


@migration(25)
async def _migrate_to_v25(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """迁移到v25 - 天灾人祸记录

    背景：
      每小时触发的「天灾人祸」需要留下可查询的历史，让玩家能回顾
      「最近发生过哪些天灾、被谁连累」，也让 `/天灾` 指令有数据可查。

    变更：
      新增 `calamity_records` 表，记录每次天灾的：
        - 天灾类型与分类（天灾 / 人祸）
        - 被罚玩家 ID 与道号
        - 实际扣除的灵石与修为
        - 是否为「虚惊一场」（无事发生）与是否被定魂护盾挡下
        - 触发时间
    """
    logger.info("开始迁移到v25：天灾人祸记录")

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS calamity_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            calamity_id TEXT NOT NULL DEFAULT '',
            calamity_name TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '天灾',
            target_user_id TEXT NOT NULL,
            target_name TEXT NOT NULL DEFAULT '',
            gold_lost INTEGER NOT NULL DEFAULT 0,
            exp_lost INTEGER NOT NULL DEFAULT 0,
            no_event INTEGER NOT NULL DEFAULT 0,
            shielded INTEGER NOT NULL DEFAULT 0,
            create_time INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_calamity_records_time ON calamity_records(create_time)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_calamity_records_user ON calamity_records(target_user_id)"
    )

    await conn.commit()
    logger.info("v25迁移完成：天灾人祸记录已启用")
