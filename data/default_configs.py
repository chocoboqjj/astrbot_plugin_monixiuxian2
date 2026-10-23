# data/default_configs.py

SECT_CONFIG = {
    "create_cost": 10000,
    "create_level_required": 3, # 筑基
    "positions": {
        "0": {"name": "宗主", "permission": 10},
        "1": {"name": "长老", "permission": 8},
        "2": {"name": "亲传弟子", "permission": 5},
        "3": {"name": "内门弟子", "permission": 2},
        "4": {"name": "外门弟子", "permission": 1}
    },
    "scale_ratio": 10, # 1灵石 = 10建设度
}

BOSS_CONFIG = {
    "spawn_interval": 3600,
    # v3.2.8：每只 Boss 每个玩家最多可挑战次数（0 = 不限制）；Boss 刷新后自动重置
    "max_challenges": 1,
    # v3.2.8：两次挑战之间的冷却秒数（0 = 不限制）
    "challenge_cooldown": 600,
    "levels": [
        {"name": "练气", "level_index": 0, "hp_mult": 1.0, "atk_mult": 1.0, "reward_mult": 1.0},
        {"name": "筑基", "level_index": 3, "hp_mult": 1.5, "atk_mult": 1.2, "reward_mult": 1.5},
        {"name": "金丹", "level_index": 6, "hp_mult": 2.0, "atk_mult": 1.5, "reward_mult": 2.0},
        {"name": "元婴", "level_index": 9, "hp_mult": 2.5, "atk_mult": 1.8, "reward_mult": 2.5},
        {"name": "化神", "level_index": 12, "hp_mult": 3.0, "atk_mult": 2.0, "reward_mult": 3.0},
        {"name": "炼虚", "level_index": 15, "hp_mult": 4.0, "atk_mult": 2.5, "reward_mult": 4.0},
        {"name": "合体", "level_index": 18, "hp_mult": 5.0, "atk_mult": 3.0, "reward_mult": 5.0},
        {"name": "大乘", "level_index": 21, "hp_mult": 6.0, "atk_mult": 3.5, "reward_mult": 6.0},
    ]
}

RIFT_CONFIG = {
    "default_duration": 1800, # 30分钟
    "rifts": [
        {"id": 1, "name": "青云秘境", "level": 2, "exp_range": [100, 500], "gold_range": [50, 200]},
        {"id": 2, "name": "幽冥鬼域", "level": 5, "exp_range": [500, 2000], "gold_range": [200, 800]},
        {"id": 3, "name": "太古遗迹", "level": 10, "exp_range": [5000, 10000], "gold_range": [1000, 5000]},
    ]
}

ALCHEMY_CONFIG = {
    "recipes": {
        "1": {
            "name": "聚气丹",
            "level_required": 0,
            "materials": {"灵草": 3, "灵石": 100},
            "success_rate": 80,
            "effect": {"type": "exp", "value": 1000},
            "desc": "增加1000修为"
        },
        "2": {
            "name": "筑基丹",
            "level_required": 2,
            "materials": {"灵草": 5, "灵石": 500},
            "success_rate": 60,
            "effect": {"type": "exp", "value": 5000},
            "desc": "增加5000修为"
        },
        "3": {
            "name": "金丹",
            "level_required": 5,
            "materials": {"灵草": 10, "灵石": 2000},
            "success_rate": 40,
            "effect": {"type": "exp", "value": 20000},
            "desc": "增加20000修为"
        },
        "4": {
            "name": "回春丹",
            "level_required": 1,
            "materials": {"灵草": 2, "灵石": 200},
            "success_rate": 70,
            "effect": {"type": "hp_restore", "value": 50},
            "desc": "恢复50%气血"
        },
        "5": {
            "name": "聚灵丹",
            "level_required": 1,
            "materials": {"灵草": 2, "灵石": 200},
            "success_rate": 70,
            "effect": {"type": "mp_restore", "value": 50},
            "desc": "恢复50%真元"
        },
    }
}

# ===== v3.2.9 天灾人祸 =====
# 每小时随机触发一次天灾人祸，随机惩罚一名玩家（扣灵石 + 修为）。
# 惩罚按「被罚者当前资产的比例」计算，天然适配不同境界的玩家：
# 新玩家不会被一击打爆，大佬才会真正感到痛。
# `no_event_chance`（百分比）表示「虚惊一场」的概率——此时不扣任何东西，
# 但事件仍会播报，制造「今天差点遭殃」的戏剧感。
CALAMITY_CONFIG = {
    "enabled": True,
    "interval": 3600,           # 触发间隔（秒）
    "no_event_chance": 30,      # 无事发生概率（百分比）
    "min_gold_loss": 0,         # 灵石扣除下限（0 = 可能不扣灵石）
    "min_exp_loss": 0,          # 修为扣除下限（0 = 可能不扣修为）
    "rate_jitter": 0.2,         # 扣减比例抖动幅度（±20%，避免每次都是同一个数字）
    "shield_consumed_on_block": True,  # 定魂护盾抵挡天灾后是否消耗
    "calamities": [
        {
            "id": "thunder", "name": "九天雷劫", "category": "天灾",
            "weight": 20, "gold_rate": 0.12, "exp_rate": 0.08,
            "desc": "紫霄神雷劈落洞府",
        },
        {
            "id": "earthquake", "name": "地脉崩裂", "category": "天灾",
            "weight": 15, "gold_rate": 0.15, "exp_rate": 0.05,
            "desc": "地脉翻涌，洞府剧震",
        },
        {
            "id": "plague", "name": "瘟疫横行", "category": "天灾",
            "weight": 15, "gold_rate": 0.08, "exp_rate": 0.12,
            "desc": "邪气入体，修为涣散",
        },
        {
            "id": "fire", "name": "业火焚身", "category": "天灾",
            "weight": 12, "gold_rate": 0.10, "exp_rate": 0.10,
            "desc": "红莲业火凭空燃起",
        },
        {
            "id": "flood", "name": "天河倒灌", "category": "天灾",
            "weight": 12, "gold_rate": 0.14, "exp_rate": 0.06,
            "desc": "九天银河倾泻而下",
        },
        {
            "id": "beast", "name": "妖兽下山", "category": "天灾",
            "weight": 14, "gold_rate": 0.11, "exp_rate": 0.07,
            "desc": "群妖下山，扫荡洞府",
        },
        {
            "id": "robber", "name": "劫修夺宝", "category": "人祸",
            "weight": 18, "gold_rate": 0.18, "exp_rate": 0.04,
            "desc": "蒙面劫修为夺宝闯入门庭",
        },
        {
            "id": "jealousy", "name": "同道觊觎", "category": "人祸",
            "weight": 16, "gold_rate": 0.13, "exp_rate": 0.09,
            "desc": "同道窥伺，趁机暗算",
        },
        {
            "id": "sect_pressure", "name": "宗门逼债", "category": "人祸",
            "weight": 12, "gold_rate": 0.16, "exp_rate": 0.05,
            "desc": "宗门催讨功德与资财",
        },
        {
            "id": "rumor", "name": "谣言四起", "category": "人祸",
            "weight": 10, "gold_rate": 0.09, "exp_rate": 0.11,
            "desc": "流言蜚语，心神大乱",
        },
    ],
}
