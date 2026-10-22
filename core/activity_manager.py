"""多活动并行状态管理

## 为什么需要这个模块

原设计用 `user_cd` 表的**单行单 type 字段**记录"玩家正在做什么"，导致两个问题：

1. **互锁**：闭关 / 历练 / 秘境共用一个槽位，开历练会覆盖闭关状态，
   且 `player_required` 装饰器会在检测到"忙碌"时封锁几乎所有指令，
   玩家闭关期间连签到、商店、宗门都做不了。
2. **互相覆盖**：三种活动无法同时进行，实际上它们是三种**可并行的离线收益**。

## 新设计

新增 `user_activity` 表，以 `(user_id, activity_type)` 为主键，
每种活动各占一行、互不影响：

| activity_type | 对应玩法 | 时间字段 |
|---------------|---------|---------|
| `cultivation` | 闭关 | `player.cultivation_start_time`（沿用 players 表） |
| `adventure`   | 历练 | `create_time` / `scheduled_time` |
| `rift`        | 秘境 | `create_time` / `scheduled_time` |

各活动**独立计时、独立结算、可以并存**：
- 玩家可以同时闭关 + 历练 + 探索秘境，三份收益各自累计
- 只有「重复启动同类活动」才会被拒绝（例如已在闭关时再点闭关）

指令层面不再有全局封锁，只有各玩法自己检查"同类活动是否已在进行"。
"""

import json
import time
from typing import Dict, List, Optional

from astrbot.api import logger

__all__ = ["ActivityType", "ActivityManager"]


class ActivityType:
    """活动类型常量（对应 user_activity.activity_type）"""

    CULTIVATION = "cultivation"   # 闭关
    ADVENTURE = "adventure"       # 历练
    RIFT = "rift"                 # 秘境探索

    ALL = (CULTIVATION, ADVENTURE, RIFT)

    @classmethod
    def names(cls) -> Dict[str, str]:
        return {
            cls.CULTIVATION: "闭关中",
            cls.ADVENTURE: "历练中",
            cls.RIFT: "探索秘境中",
        }


class ActivityManager:
    """玩家活动状态管理（多活动并行）"""

    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # 表结构
    # ------------------------------------------------------------------
    async def ensure_table(self):
        """确保 user_activity 表存在（幂等）"""
        try:
            await self.db.conn.execute("""
                CREATE TABLE IF NOT EXISTS user_activity (
                    user_id TEXT NOT NULL,
                    activity_type TEXT NOT NULL,
                    create_time INTEGER NOT NULL DEFAULT 0,
                    scheduled_time INTEGER NOT NULL DEFAULT 0,
                    extra_data TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (user_id, activity_type)
                )
            """)
            await self.db.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_activity_type ON user_activity(activity_type)"
            )
            await self.db.conn.commit()
        except Exception as e:
            logger.warning(f"[ActivityManager] 创建 user_activity 表失败: {e}")

    # ------------------------------------------------------------------
    # 读写接口
    # ------------------------------------------------------------------
    async def start(
        self,
        user_id: str,
        activity_type: str,
        scheduled_time: int = 0,
        extra_data: Optional[dict] = None,
        create_time: Optional[int] = None,
    ):
        """启动一项活动（覆盖同类型的旧记录）

        Args:
            create_time: 活动开始时间，默认为当前时间（迁移旧数据时传入原值以保留时长）
        """
        await self.ensure_table()
        await self.db.conn.execute(
            """
            INSERT OR REPLACE INTO user_activity
                (user_id, activity_type, create_time, scheduled_time, extra_data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                activity_type,
                int(create_time if create_time is not None else time.time()),
                int(scheduled_time or 0),
                json.dumps(extra_data or {}, ensure_ascii=False),
            ),
        )
        await self.db.conn.commit()

    async def finish(self, user_id: str, activity_type: str):
        """结束一项活动"""
        await self.ensure_table()
        await self.db.conn.execute(
            "DELETE FROM user_activity WHERE user_id = ? AND activity_type = ?",
            (user_id, activity_type),
        )
        await self.db.conn.commit()

    async def get(self, user_id: str, activity_type: str) -> Optional[dict]:
        """获取某项活动的状态（未在进行则返回 None）"""
        await self.ensure_table()
        async with self.db.conn.execute(
            "SELECT * FROM user_activity WHERE user_id = ? AND activity_type = ?",
            (user_id, activity_type),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            try:
                data["extra_data"] = json.loads(data.get("extra_data") or "{}")
            except Exception:
                data["extra_data"] = {}
            return data

    async def is_active(self, user_id: str, activity_type: str) -> bool:
        """某项活动是否正在进行"""
        return await self.get(user_id, activity_type) is not None

    async def get_all(self, user_id: str) -> List[dict]:
        """获取玩家所有进行中的活动"""
        await self.ensure_table()
        async with self.db.conn.execute(
            "SELECT * FROM user_activity WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        result = []
        for row in rows:
            data = dict(row)
            try:
                data["extra_data"] = json.loads(data.get("extra_data") or "{}")
            except Exception:
                data["extra_data"] = {}
            result.append(data)
        return result

    async def active_types(self, user_id: str) -> List[str]:
        """获取玩家进行中的活动类型列表"""
        return [a["activity_type"] for a in await self.get_all(user_id)]

    async def get_any(self, user_id: str) -> Optional[dict]:
        """获取任意一项进行中的活动（兼容旧的单槽位语义）"""
        activities = await self.get_all(user_id)
        return activities[0] if activities else None

    # ------------------------------------------------------------------
    # 兼容层：把旧 user_cd 语义映射到新模型
    # ------------------------------------------------------------------
    async def is_any_active(self, user_id: str) -> bool:
        """玩家是否有任何进行中的活动"""
        return len(await self.get_all(user_id)) > 0

    async def migrate_legacy(self, user_id: str):
        """把旧 user_cd 里的状态迁移到 user_activity（兼容存量数据）

        旧结构只有一行 type，无法区分"曾经闭关"和"正在闭关"，
        这里按 type 映射到对应活动类型；闭关的起始时间从 players 表取。
        """
        await self.ensure_table()
        try:
            cd = await self.db.ext.get_user_cd(user_id)
            if not cd or cd.type == 0:
                return
            mapping = {
                1: ActivityType.CULTIVATION,
                2: ActivityType.ADVENTURE,
                3: ActivityType.RIFT,
            }
            activity_type = mapping.get(cd.type)
            if not activity_type:
                return
            # 已有该活动的记录则不覆盖
            if await self.is_active(user_id, activity_type):
                return
            await self.start(
                user_id,
                activity_type,
                scheduled_time=cd.scheduled_time,
                extra_data=cd.get_extra_data() if hasattr(cd, "get_extra_data") else {},
                create_time=cd.create_time,
            )
        except Exception as e:
            logger.warning(f"[ActivityManager] 迁移旧状态失败 user={user_id}: {e}")
