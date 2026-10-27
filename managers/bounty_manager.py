# managers/bounty_manager.py
"""悬赏令系统管理器"""

import json
import random
import time
from pathlib import Path
from typing import Tuple, List, Optional, Dict, TYPE_CHECKING

from astrbot.api import logger

from ..data import DataBase
from ..models import Player

if TYPE_CHECKING:
    from ..core import StorageRingManager

__all__ = ["BountyManager"]


class BountyManager:
    """悬赏令管理器"""

    BOUNTY_CACHE_DURATION = 600  # 任务列表缓存10分钟
    CONFIG_FILE = Path(__file__).resolve().parents[1] / "config" / "bounty_templates.json"
    ADVENTURE_CONFIG_FILE = Path(__file__).resolve().parents[1] / "config" / "adventure_config.json"
    RIFT_CONFIG_FILE = Path(__file__).resolve().parents[1] / "config" / "rift_config.json"
    DEFAULT_CONFIG = {
        "difficulties": {
            "easy": {"name": "F级", "stone_scale": 1.0, "exp_scale": 1.0, "min_level": 0}
        },
        "templates": [
            {
                "id": 1,
                "name": "击退妖兽",
                "difficulty": "easy",
                "category": "巡山",
                "progress_tags": ["adventure_scout"],
                "min_target": 3,
                "max_target": 5,
                "time_limit": 3600,
                "reward": {"stone": 300, "exp": 2500},
                "item_table": "hunt",
                "description": "驱逐骚扰山门的妖兽。"
            }
        ],
        "item_tables": {
            "hunt": [
                {"name": "灵兽毛皮", "weight": 40, "min": 1, "max": 3},
                {"name": "妖兽精血", "weight": 30, "min": 1, "max": 2},
                {"name": "精铁", "weight": 30, "min": 1, "max": 2}
            ]
        }
    }

    # 悬赏进度标签 → 玩家可执行的实际指令（用于「去哪里完成」提示）
    # 顺序即提示展示顺序；gather/collect/kill/escort 等为描述性标签，
    # 当前版本没有独立的对应指令，统一由历练/秘境路线推进，故不单列。
    COMPLETION_HINTS = [
        ("adventure_scout", "历练·巡山问道", "/开始历练 巡山问道"),
        ("adventure_roam", "历练·云游四方", "/开始历练 云游四方"),
        ("adventure_hunt", "历练·猎魔肃清", "/开始历练 猎魔肃清"),
        ("adventure_peril", "历练·九死一生", "/开始历练 九死一生"),
        ("adventure_abyss", "历练·太虚涉险", "/开始历练 太虚涉险"),
        ("adventure_chaos", "历练·混沌问道", "/开始历练 混沌问道"),
        ("rift", "秘境探索", "/秘境列表 查看后 /探索秘境 <ID>"),
        ("explore", "秘境探索", "/秘境列表 查看后 /探索秘境 <ID>"),
    ]

    def __init__(self, db: DataBase, storage_ring_manager: Optional["StorageRingManager"] = None):
        self.db = db
        self.storage_ring_manager = storage_ring_manager
        self._bounty_cache: Dict[str, Dict] = {}
        self.difficulties: Dict[str, dict] = {}
        self.templates_by_id: Dict[int, dict] = {}
        self.templates_by_diff: Dict[str, List[dict]] = {}
        self.item_tables: Dict[str, List[dict]] = {}
        self.adventure_tag_meta: Dict[str, Dict[str, int]] = {}
        self.reload_config()

    # -------- 配置 --------

    def reload_config(self):
        config = self._load_config_file()
        self.difficulties = config.get("difficulties", self.DEFAULT_CONFIG["difficulties"])
        self.item_tables = config.get("item_tables", self.DEFAULT_CONFIG["item_tables"])
        self.templates_by_id = {}
        self.templates_by_diff = {}
        for tpl in config.get("templates", []):
            tpl_copy = dict(tpl)
            tpl_copy["progress_tags"] = [str(tag).lower() for tag in tpl_copy.get("progress_tags", [])]
            self.templates_by_id[tpl_copy["id"]] = tpl_copy
            self.templates_by_diff.setdefault(tpl_copy["difficulty"], []).append(tpl_copy)
        logger.info(f"悬赏配置加载完成：{len(self.templates_by_id)} 条模板")
        self._load_adventure_meta()

    def _load_config_file(self) -> dict:
        if self.CONFIG_FILE.exists():
            try:
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.error(f"加载 bounty_templates.json 失败，将使用默认配置: {exc}")
        return self.DEFAULT_CONFIG

    def _load_adventure_meta(self):
        self.adventure_tag_meta = {}
        if self.ADVENTURE_CONFIG_FILE.exists():
            try:
                with open(self.ADVENTURE_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for route in data.get("routes", []):
                    tag = str(route.get("bounty_tag", "")).lower()
                    if not tag:
                        continue
                    self.adventure_tag_meta[tag] = {
                        "duration": int(route.get("duration", 3600)),
                        "fatigue": int(route.get("fatigue_cooldown", 0)),
                        # 每轮完成为该标签增加的悬赏进度（猎魔肃清 +2、九死一生 +3）
                        "bounty_progress": max(1, int(route.get("bounty_progress", 1))),
                    }
                logger.info("已加载冒险路线元数据用于悬赏校准")
            except Exception as exc:
                logger.warning(f"加载冒险路线配置失败，将使用默认时限: {exc}")
        # 秘境是独立并行槽位：每次探索 +1 点进度、无休整冷却，可连续刷
        self.adventure_tag_meta.setdefault("rift", {
            "duration": self._load_rift_duration(),
            "fatigue": 0,
            "bounty_progress": 1,
        })

    def _load_rift_duration(self) -> int:
        """读取秘境单次时长（rift_config.default_duration），缺失时回退 1800 秒。"""
        try:
            if self.RIFT_CONFIG_FILE.exists():
                with open(self.RIFT_CONFIG_FILE, "r", encoding="utf-8") as f:
                    return max(60, int(json.load(f).get("default_duration", 1800)))
        except Exception as exc:
            logger.warning(f"加载秘境配置失败，将使用默认时长: {exc}")
        return 1800

    # -------- 完成方式提示 --------

    def _completion_command_entries(self, progress_tags) -> List[Tuple[str, str]]:
        """根据悬赏进度标签返回可执行指令列表（去重、稳定顺序）"""
        tags = {str(t).lower() for t in (progress_tags or [])}
        out: List[Tuple[str, str]] = []
        seen = set()
        for tag, label, cmd in self.COMPLETION_HINTS:
            if tag in tags and cmd not in seen:
                seen.add(cmd)
                out.append((label, cmd))
        return out

    def format_completion_hint(self, progress_tags) -> str:
        """生成玩家接取/查看悬赏时的「去哪里完成」提示"""
        entries = self._completion_command_entries(progress_tags)
        if not entries:
            return "💡 通过历练或秘境推进悬赏进度"
        lines = ["📍 完成方式："]
        for label, cmd in entries:
            lines.append(f"  · {label}：{cmd}")
        return "\n".join(lines)

    def format_completion_hint_short(self, progress_tags) -> str:
        """生成悬赏列表用的紧凑提示（仅列指令）"""
        entries = self._completion_command_entries(progress_tags)
        if not entries:
            return "历练 / 秘境"
        return "、".join(cmd for _, cmd in entries)

    def _difficulty_name(self, difficulty_key: str) -> str:
        """难度键 → 中文名（唯一来源）。

        历史悬赏记录的 rewards 可能缺 difficulty_name，直接回退到 difficulty
        会让玩家看到 easy/normal/hard/elite 等英文键，故统一走这里翻译。
        """
        key = str(difficulty_key or "").lower()
        return self.difficulties.get(key, {}).get("name") or "未知难度"

    # -------- 列表 & 缓存 --------

    def _get_cached_bounties(self, user_id: str) -> Optional[List[dict]]:
        cache = self._bounty_cache.get(user_id)
        if cache and cache["expire_time"] > int(time.time()):
            return cache["bounties"]
        return None

    def _set_cached_bounties(self, user_id: str, bounties: List[dict]):
        self._bounty_cache[user_id] = {
            "bounties": bounties,
            "expire_time": int(time.time()) + self.BOUNTY_CACHE_DURATION
        }

    async def get_bounty_list(self, player: Player) -> List[dict]:
        """获取悬赏列表"""
        cached = self._get_cached_bounties(player.user_id)
        if cached:
            return cached

        plan = self._get_difficulty_plan(player.level_index)
        bounties: List[dict] = []
        for diff in plan:
            entry = self._build_bounty_entry(diff, player)
            if entry:
                bounties.append(entry)

        self._set_cached_bounties(player.user_id, bounties)
        return bounties

    def _get_difficulty_plan(self, level_index: int) -> List[str]:
        """按境界解锁难度档位，阈值取自配置 min_level（避免硬编码与配置脱节）。"""
        plan = []
        for diff in ("easy", "normal", "hard", "elite"):
            cfg = self.difficulties.get(diff)
            if cfg is None:
                continue
            if level_index >= int(cfg.get("min_level", 0)):
                plan.append(diff)
        return plan

    def _pick_template(self, difficulty: str) -> Optional[dict]:
        templates = self.templates_by_diff.get(difficulty)
        if not templates:
            return None
        total = sum(max(1, tpl.get("weight", 1)) for tpl in templates)
        roll = random.randint(1, total)
        upto = 0
        for tpl in templates:
            upto += max(1, tpl.get("weight", 1))
            if roll <= upto:
                return tpl
        return templates[0]

    def _build_bounty_entry(self, difficulty: str, player: Player) -> Optional[dict]:
        template = self._pick_template(difficulty)
        if not template:
            return None
        diff_cfg = self.difficulties.get(difficulty, {})
        target = random.randint(template.get("min_target", 1), template.get("max_target", 1))
        reward = self._calculate_reward(template, diff_cfg, player, target)
        progress_tags = [str(tag).lower() for tag in template.get("progress_tags", [])]
        time_limit = self._calculate_time_limit(template, target)
        return {
            "id": template["id"],
            "name": template["name"],
            "category": template.get("category", "任务"),
            "difficulty": difficulty,
            "difficulty_name": diff_cfg.get("name", difficulty),
            "description": template.get("description", ""),
            "count": target,
            "reward": reward,
            "time_limit": time_limit,
            "progress_tags": progress_tags,
            "item_table": template.get("item_table", "gather")
        }

    def _calculate_reward(self, template: dict, diff_cfg: dict, player: Player, target: int) -> Dict[str, int]:
        base_reward = template.get("reward", {"stone": 200, "exp": 2000})
        stone = base_reward.get("stone", 0)
        exp = base_reward.get("exp", 0)
        level_bonus = 1 + max(0, player.level_index - 3) * 0.06
        progress_factor = max(1, target) / max(1, template.get("min_target", 1))
        stone_scale = diff_cfg.get("stone_scale", 1.0)
        exp_scale = diff_cfg.get("exp_scale", 1.0)
        final_stone = int(stone * stone_scale * progress_factor * level_bonus)
        final_exp = int(exp * exp_scale * progress_factor * level_bonus)
        return {"stone": final_stone, "exp": final_exp}

    def _calculate_time_limit(self, template: dict, target: int) -> int:
        base_limit = template.get("time_limit", 3600)
        expected = self._estimate_completion_seconds(template, target)
        if not expected:
            return base_limit
        # 容错缓冲：至少 10 分钟，或预期时长的 1/6（覆盖受伤事件 +600s 与取整误差）
        buffer = max(600, expected // 6)
        return max(base_limit, expected + buffer)

    def _estimate_completion_seconds(self, template: dict, target: int) -> Optional[int]:
        """估算完成 target 点悬赏进度所需的墙上时间（秒）。

        逐条可行路线计算「需要跑几轮 × 单轮时长（duration + fatigue）」，取**最慢**的一条：
        - 时限不应假设玩家一定挑最快路线，且慢路线往往没有境界门槛
          （如 D 级悬赏对 7 阶玩家只有猎魔肃清可用，九死一生要 12 阶）；
        - 猎魔肃清每轮 +2 点、九死一生每轮 +3 点进度，必须按 ceil(target/progress)
          计轮数，否则会把完成时间低估 2~3 倍；
        - 秘境每次探索 +1 点、无休整冷却，可连续刷。
        所有标签都没有路线元数据时返回 None，回退到模板自带 time_limit。
        """
        slowest: Optional[int] = None
        for tag in template.get("progress_tags", []):
            meta = self.adventure_tag_meta.get(tag.lower())
            if not meta:
                continue
            cycle = meta.get("duration", 0) + meta.get("fatigue", 0)
            progress = max(1, int(meta.get("bounty_progress", 1)))
            if cycle <= 0:
                continue
            rounds = -(-max(1, int(target)) // progress)  # 向上取整
            seconds = rounds * cycle
            if slowest is None or seconds > slowest:
                slowest = seconds
        return slowest

    # -------- 接取与状态 --------

    async def accept_bounty(self, player: Player, bounty_id: int) -> Tuple[bool, str]:
        if bounty_id <= 0:
            return False, "无效的悬赏编号。"

        template = self.templates_by_id.get(bounty_id)
        if not template:
            return False, "该悬赏已失效，请刷新列表。"

        diff_key = template.get("difficulty", "easy")
        diff_cfg = self.difficulties.get(diff_key, {})
        cached_bounties = self._get_cached_bounties(player.user_id)
        cached = None
        if cached_bounties:
            cached = next((b for b in cached_bounties if b["id"] == bounty_id), None)
        if not cached:
            return False, "⚠️ 悬赏列表已刷新，请先发送 /悬赏令 重新查看后再接取。"

        now = int(time.time())
        time_limit = cached.get("time_limit", template.get("time_limit", 3600))

        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            active = await self.db.ext.get_active_bounty(player.user_id)
            if active:
                await self.db.conn.rollback()
                return False, f"你已有进行中的悬赏：{active['bounty_name']}，请先完成或放弃。"

            cd_key = f"bounty_abandon_cd_{player.user_id}"
            cd_value = await self.db.ext.get_system_config(cd_key)
            if cd_value:
                cd_time = int(cd_value)
                if now < cd_time:
                    await self.db.conn.rollback()
                    remaining = (cd_time - now) // 60 or 1
                    return False, f"你刚放弃过悬赏，还需等待 {remaining} 分钟才能再次接取。"

            expire_time = now + time_limit
            rewards_json = json.dumps({
                "stone": cached["reward"]["stone"],
                "exp": cached["reward"]["exp"],
                "difficulty": diff_key,
                "difficulty_name": cached.get("difficulty_name") or self._difficulty_name(diff_key),
                "item_table": cached.get("item_table"),
                "description": cached.get("description", ""),
                "progress_tags": cached.get("progress_tags", [])
            }, ensure_ascii=False)

            await self.db.conn.execute(
                """
                INSERT INTO bounty_tasks (
                    user_id, bounty_id, bounty_name, target_type,
                    target_count, current_progress, rewards,
                    start_time, expire_time, status
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 1)
                """,
                (
                    player.user_id,
                    bounty_id,
                    template["name"],
                    cached.get("category", template.get("category", "任务")),
                    cached["count"],
                    rewards_json,
                    now,
                    expire_time
                )
            )
            await self.db.conn.commit()
        except Exception:
            await self.db.conn.rollback()
            raise

        return True, (
            f"🎯 接取悬赏成功！\n"
            f"任务：{template['name']}（{cached.get('difficulty_name') or self._difficulty_name(diff_key)}）\n"
            f"目标：完成 {cached['count']} 次\n"
            f"奖励：{cached['reward']['stone']:,} 灵石 + {cached['reward']['exp']:,} 修为\n"
            f"时限：{time_limit // 60} 分钟\n"
            f"{self.format_completion_hint(cached.get('progress_tags', []))}"
        )

    async def check_bounty_status(self, player: Player) -> Tuple[bool, str]:
        active = await self.db.ext.get_active_bounty(player.user_id)
        if not active:
            return False, "你当前没有进行中的悬赏任务。\n使用 /悬赏令 查看可接取的任务。"

        rewards = json.loads(active["rewards"])
        remaining = max(0, active["expire_time"] - int(time.time()))
        progress = active.get("current_progress", 0)
        target = active.get("target_count", 1)

        diff_name = rewards.get("difficulty_name") or self._difficulty_name(rewards.get("difficulty", "easy"))
        desc = rewards.get("description", "")
        hint = self.format_completion_hint(rewards.get("progress_tags", []))

        return True, (
            f"📜 当前悬赏（{diff_name}）\n"
            f"━━━━━━━━━━━━━━━\n"
            f"任务：{active['bounty_name']}\n"
            f"说明：{desc}\n"
            f"进度：{progress}/{target}\n"
            f"奖励：{rewards.get('stone', 0):,} 灵石 + {rewards.get('exp', 0):,} 修为\n"
            f"剩余时间：{remaining // 60} 分钟\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{hint}\n"
            f"💡 进度满后使用 /完成悬赏 领取奖励"
        )

    async def complete_bounty(self, player: Player) -> Tuple[bool, str]:
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            active = await self.db.ext.get_active_bounty(player.user_id)
            if not active:
                await self.db.conn.rollback()
                return False, "你当前没有进行中的悬赏任务。"

            if int(time.time()) > active["expire_time"]:
                await self.db.conn.execute(
                    "UPDATE bounty_tasks SET status = 0 WHERE user_id = ? AND status = 1",
                    (player.user_id,)
                )
                await self.db.conn.commit()
                return False, "悬赏任务已超时，自动取消。"

            progress = active.get("current_progress", 0)
            target = active.get("target_count", 1)
            if progress < target:
                await self.db.conn.rollback()
                try:
                    _rw = json.loads(active["rewards"])
                except Exception:
                    _rw = {}
                hint = self.format_completion_hint(_rw.get("progress_tags", []))
                return False, (
                    f"❌ 任务尚未完成！\n"
                    f"任务：{active['bounty_name']}\n"
                    f"进度：{progress}/{target}\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"{hint}"
                )

            rewards = json.loads(active["rewards"])
            stone_reward = rewards.get("stone", 0)
            exp_reward = rewards.get("exp", 0)

            await self.db.conn.execute(
                "UPDATE bounty_tasks SET status = 2 WHERE user_id = ? AND status = 1",
                (player.user_id,)
            )

            MAX_VALUE = 2**63 - 1
            player.gold = min(player.gold + stone_reward, MAX_VALUE)
            player.experience = min(player.experience + exp_reward, MAX_VALUE)
            await self.db.conn.execute(
                "UPDATE players SET gold = ?, experience = ? WHERE user_id = ?",
                (player.gold, player.experience, player.user_id)
            )
            await self.db.conn.commit()
        except Exception:
            await self.db.conn.rollback()
            raise

        item_msg = ""
        roll_msg = ""
        if self.storage_ring_manager:
            try:
                rewards = json.loads(active["rewards"])
                # target_type 存的是中文 category，不能当 item_table 键用
                item_table = rewards.get("item_table") or "gather"
                dropped_items, roll_msg = await self._roll_bounty_items(player, item_table)
                if dropped_items:
                    lines = []
                    for item_name, count in dropped_items:
                        success, _ = await self.storage_ring_manager.store_item(player, item_name, count, silent=True)
                        if success:
                            lines.append(f"  · {item_name} x{count}")
                        else:
                            lines.append(f"  · {item_name} x{count}（储物戒已满，丢失）")
                    if lines:
                        item_msg = "\n\n📦 获得物品：\n" + "\n".join(lines)
            except Exception:
                logger.warning("悬赏物品奖励发放异常", exc_info=True)

        rewards = json.loads(active["rewards"])
        diff_name = rewards.get("difficulty_name") or self._difficulty_name(rewards.get("difficulty", "easy"))
        roll_block = f"\n🎰 命数判定：{roll_msg}" if roll_msg else ""
        return True, (
            f"✅ 悬赏完成（{diff_name}）！\n"
            f"任务：{active['bounty_name']}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"获得灵石：+{rewards.get('stone', 0):,}\n"
            f"获得修为：+{rewards.get('exp', 0):,}{item_msg}"
            f"{roll_block}"
        )

    async def abandon_bounty(self, player: Player) -> Tuple[bool, str]:
        active = await self.db.ext.get_active_bounty(player.user_id)
        if not active:
            return False, "你当前没有进行中的悬赏任务。"

        await self.db.ext.cancel_bounty(player.user_id)
        abandon_cooldown = int(time.time()) + 1800
        await self.db.ext.set_system_config(f"bounty_abandon_cd_{player.user_id}", str(abandon_cooldown))
        return True, f"已放弃悬赏：{active['bounty_name']}\n⚠️ 30分钟内无法接取新悬赏"

    # -------- 进度与奖励 --------

    async def _roll_bounty_items(
        self, player: Player, table_name: str
    ) -> Tuple[List[Tuple[str, int]], str]:
        """结算悬赏的物品掉落

        Returns:
            (掉落物品列表, 概率判定说明)
        """
        from ..utils.probability import describe_roll

        dropped_items: List[Tuple[str, int]] = []
        drop_table = self.item_tables.get(table_name, self.item_tables.get("gather", []))
        BOUNTY_DROP_CHANCE = 70
        if not drop_table or random.randint(1, 100) > BOUNTY_DROP_CHANCE:
            return dropped_items, describe_roll("悬赏物品掉落", BOUNTY_DROP_CHANCE, False)

        total_weight = sum(item["weight"] for item in drop_table)
        roll = random.randint(1, total_weight)
        upto = 0
        chosen = drop_table[0]
        for item in drop_table:
            upto += item["weight"]
            if roll <= upto:
                chosen = item
                break

        count = random.randint(chosen["min"], chosen["max"])
        dropped_items.append((chosen["name"], count))
        roll_msg = describe_roll(
            "悬赏物品掉落", BOUNTY_DROP_CHANCE, True,
            result_text=f"{chosen['name']} x{count}"
        )
        return dropped_items, roll_msg

    async def add_bounty_progress(self, player: Player, activity_tag: str, count: int = 1) -> Tuple[bool, str]:
        """根据活动标签推进悬赏"""
        if not isinstance(count, int) or count <= 0:
            return False, ""
        count = min(count, 10)
        activity_tag = (activity_tag or "").strip().lower()
        if not activity_tag:
            return False, ""

        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            active = await self.db.ext.get_active_bounty(player.user_id)
            if not active:
                await self.db.conn.rollback()
                return False, ""

            if int(time.time()) > active["expire_time"]:
                await self.db.conn.rollback()
                return False, ""

            rewards_data = {}
            try:
                rewards_data = json.loads(active["rewards"])
            except Exception:
                rewards_data = {}

            template = self.templates_by_id.get(active["bounty_id"])
            if template:
                allowed_tags = template.get("progress_tags", [])
            else:
                allowed_tags = [str(tag).lower() for tag in rewards_data.get("progress_tags", [])]

            if activity_tag not in allowed_tags:
                await self.db.conn.rollback()
                return False, ""

            progress = active.get("current_progress", 0)
            target = active.get("target_count", 1)
            if progress >= target:
                await self.db.conn.rollback()
                return False, ""

            new_progress = min(target, progress + count)
            await self.db.conn.execute(
                "UPDATE bounty_tasks SET current_progress = ? WHERE user_id = ? AND status = 1 AND current_progress = ?",
                (new_progress, player.user_id, progress)
            )
            await self.db.conn.commit()

            if new_progress >= target:
                return True, f"\n\n📜 悬赏【{active['bounty_name']}】已完成！使用 /完成悬赏 领取奖励"
            return True, f"\n\n📜 悬赏进度：{new_progress}/{target}"
        except Exception:
            await self.db.conn.rollback()
            raise

    async def check_and_expire_bounties(self) -> int:
        now = int(time.time())
        cursor = await self.db.conn.execute(
            "UPDATE bounty_tasks SET status = 3 WHERE status = 1 AND expire_time < ?",
            (now,)
        )
        await self.db.conn.commit()
        return cursor.rowcount
