# 项目长期记忆

AstrBot 文字修仙（放置 RPG）插件，AGPL-3.0，作者 xiaojuwa。当前 v3.3.4。
> 详细改动见 `.workbuddy/memory/2026-10-*.md` 日志；本文件只留"不可再生的踩坑事实"。

## ⚠️ QQ 官方 @解析（v3.2.4 踩坑）
- `qq_official` 消息链里的 At **只代表机器人自己**（适配器塞 `At(qq="qq_official")` 占位符）⇒ **"消息链第一个 At = 目标"永不成立**（v3.1.4 因此致双修/切磋/决斗/赠予/宗门/传承全失效）。
- **被 @ 者不进消息链**，只以 `<@!member_openid>`/`<qqbot-at-user id="..."/>` 留在纯文本（`stripMentionText`），可作玩家库主键；`member_openid` **按群维度** ⇒ 跨群 @ 指向不同数据。
- `At` 字段**只有 `qq` 真实存在**；`CommandFilter` str 参数只取一个 token（要全文从 Plain 重拼）。
- `extract_target_id` 5 级优先级：①消息链 At（剔除自己）②arg 纯文本 @ ③raw `mentions` ④arg 裸 ID（拒 `<>[]()`）⑤整词数字 token；`allow_bare_id`/`allow_text_number` 默认 True。迁移后 user_id/group_id 变 openid、旧库不互通。

## 架构约定
- **玩家数据清除唯一入口**：`db.penalty_mgr.punish(player, PenaltyReason.XXX)`；勿直调 `delete_player_cascade`（仅兜底）。**跨模块共享实例**：manager 挂 `DataBase`，`getattr(self.db,"xxx_mgr",None)` 取用降级，**注入缺失=功能静默失效**。
- **多活动并行**：`db.activity_mgr`，PK `(user_id,activity_type)`；只用 `get`/`start`/`finish` 自己那格，**别用 `set_user_free` 一把清空**。
- **战力唯一来源**：`managers/combat_manager.py` 的 `calculate_combat_stats`/`calculate_combat_power`；概率措辞 `utils/probability.py::describe_roll`。
- **⚠️ 不用「忙碌状态」封锁指令**：瞬时操作不受活动影响，同类重复启动才拒；冷却用 `system_config` 别用 `set_user_busy`。
- **⚠️ 配置层级**：`_conf_schema.json` 的 `VALUES` 嵌套 → 值在 `config["VALUES"][key]`；顶层段（`BANK`/`ACCESS_CONTROL`/`CALAMITY`）平铺。
- **⚠️ 建表/迁移**：`_create_all_tables_v2()` 是唯一全新安装建表路径（`MIGRATION_TASKS` 全新安装不执行）；新增表/列**两处都改**。`@migration(N)` + `LATEST_DB_VERSION` 同步；迁移内**勿 import managers**（循环依赖），基准值写 `data/migration.py` 模块级常量并断言。
- **⚠️ 模块级常量勿用 `self.` 访问**（曾致 AttributeError）。**⚠️ 储物戒 lost update**：`storage_ring_manager` 内部重读玩家局部重绑，调用方 `update_player()` 会覆盖回旧值，已用 `_sync_ring_items_to_caller()` 解决。**⚠️ `can_store_item` 不校验存在性** ⇒ 掉落名写错即幽灵物品。
- **⚠️ 文案禁回显内部英文键**：须有 `*_NAMES` 中文映射，`.get(key,key)` 改中文兜底（回归 `test_i18n_no_english.py`）。**⚠️ `ConfigManager` 无 `adventure_config`**：读 `AdventureManager.CONFIG_FILE`。
- **⚠️ 永久属性丹「每境界 30%」配额按境界+属性分桶**（所有 `*_gain` 共用）；境界 0 基准 0 ⇒ 永久丹对境界 0 恒无效、宗门丹药门槛不能设 0。`breakthrough_boost` 防无限叠加：`temp_bonus_cap`(0.05) 双桶夹紧。
- **⚠️ SQLite `UPDATE...FROM` 的 `RETURNING` 不能引用 FROM 表旧列**（实测 `no such column: old.x`）。

## 债务继承制（v3.2.7）
- **身死不清债**：贷款未还清身死 → 转 `carried`，重开后恢复（本金=死亡锁定本金+利息、利率归零、due=now+7天），仅「逾期被银行追杀」免除。入口 `core/penalty_manager.py::apply_death_debt()`。
- **⚠️ 时序铁律**：继承**必须在 `delete_player_cascade` 之前**（cascade 会把 active 置 bad_debt 免除）。
- **`bank_loans`（v23 起）**：无表级 UNIQUE，改 active/carried 两条部分唯一索引（原 `UNIQUE(user_id,status)` 让玩家一生只能还清一次）。新增列 `inherit_count`/`settled_amount`/`inherit_at`/`grace_until`。`mark_loan_overdue` 须带 `AND status='active'`；恢复后须能被 `get_active_loan` 看到（洞天托管防套利）。**配置** `BANK.DEBT_INHERIT_MAX=3`/`DEBT_INHERIT_GRACE_DAYS=7`，设 0 退回旧行为。

## 生息资产防「贷款杠杆套利」（v3.2.5）
- **根因**：资产收益 > 贷款利率且还贷后**保留资产** ⇒ 白赚，调利率无法根除。**定案**：贷款存续期可购/升级生息资产，但**产出被银行托管**——`collect_income` 查 `db.ext.get_active_loan`，有活跃贷款则拒收。`BLESSED_LANDS.gold_per_hour` **是入库快照值** ⇒ 改常量只影响新购/升级，存量须迁移回填（v21 已做）。

## 世界 Boss 挑战限制（v3.2.8）
- **定案**：`boss_config.json` 次数上限+冷却+安慰奖封顶（`_cap_consolation`=50% 石头）；次数按 boss_id 计数，刷新重置。
- **⚠️ 并发安全**：`reserve_boss_challenge` 用单条 `INSERT...ON CONFLICT DO UPDATE...WHERE challenge_count<?`「检查+递增」，`cursor.rowcount` 判定，**先判 rowcount 再 commit**，别用 `total_changes`。**⚠️ `defeat_boss` 条件 UPDATE**（`WHERE boss_id=? AND status=1`+rowcount），仅首个真击杀者拿全奖并广播（`actually_killed`）；击杀类状态转移套此模式。
- **⚠️ `player.hp` 非核心资源模型**：决斗/切磋也重算满值 ⇒ 扣气血有"血量卡死"风险，Boss 战**保留满值入场**。表 `boss_challenges`(v24) `UNIQUE(boss_id,user_id)`。

## 悬赏系统约定
- **⚠️ 改 `bounty_templates.json` 后必跑** `/tmp/xx_test/test_bounty_balance.py`（难度/奖励双单调校验）。
- **⚠️ 时限模型取「最慢可行路线」**：猎魔/九死一生按 ceil 折算轮数、须含秘境 `rift`、`bounty_progress` 减的是**轮数**。`format_completion_hint` 把 `progress_tags` 翻成指令（描述性标签不单列）；专属掉落 `item_tables` 与主线同步。

## 天地灵眼系统约定（v3.2.6）
- **时效逐档减半**（24/12/6/3h）。到期自动消散，**先结算持有者未收修为再删，绝不吞收益**。`get_all_spirit_eyes()` 含被占，`get_available_spirit_eyes()` 只返无主。
- **@人 争夺**：`/抢占灵眼 @对方` → 切磋式战斗（不扣气血），发起方/胜守方各 5 分钟冷却/守护期。**⚠️ 参数歧义**（编号或@目标）⇒ `extract_target_id(allow_bare_id=False, allow_text_number=False)`。**⚠️ 并发抢占**靠条件 UPDATE+rowcount（`WHERE eye_id=? AND (owner_id IS NULL OR owner_id='')`），先判 rowcount 再 commit。迁移常量写 `data/migration.py` 模块级（勿 import managers），测试断言对齐 `SPIRIT_EYE_TYPES`。

## 天灾人祸系统约定（v3.2.9）
- **⚠️ 扣减必须「原地加减」**（`gold = MAX(0, gold - ?)`），**不能**读旧值写回绝对值：所有 manager **共享同一 aiosqlite 连接**，事务边界**连接级** ⇒ 写回绝对值**丢更新**；也不能「条件 UPDATE+旧值守卫+rollback」（rollback 连坐其他协程）。
- **⭐ 取旧值唯一技巧**：`RETURNING` 只看新值；须 `WITH old AS MATERIALIZED(...)` 且 CTE **引用在 `SET` 表达式里**（只在 RETURNING 引用拿到新值）；护盾判定须同语句。
- **判定顺序**虚惊一场→护盾免疫→实际扣减（虚惊不消耗护盾）。**境界地板**：`experience` 不清零，下限=`exp_needed[level_index]`。**绝不致死**：只扣 gold/experience。定魂丹 `has_debuff_shield` 首个消费点。新增表 `calamity_records`(v25)+`calamity_config.json`+`CALAMITY`。

## 遗留缺陷修复包（v3.3.0/3.3.1，细节见 2026-10-23 日志）
- **丹药表以「名称」为键** ⇒ 同名静默覆盖；跨表（新丹药系统 vs `items.json`）共享命名空间须查重。
- **`shop_weight=0` 排雷**：`_weighted_random_choice` 在 `len<=count` 时直返全部候选；`generate_pavilion_items` 须按 `shop_weight>0` 硬过滤。
- **`permanent_pill_gains` 顶层可能有标量键（BASE_LIMIT_KEY）** ⇒ 遍历 `.values()` 必须 `isinstance(x,dict)`；`base_attribute_limit_increase` 是倍率提升永久增益上限、不提供属性、须走独立分支。
- **跨系上限兜底在代码层、境界表零改动**（突破各系只读自己能量字段）。**改名须覆盖全部掉落表**（v3.3.1 玄铁→精铁漏两张 ⇒ 幽灵物品）；`test_drop_item_existence.py` 改材料名必跑。

## 突破丹约定（v3.3.2）
- **⚠️ `/突破 <破境丹名>` 必须先查背包并扣丹**：破境丹按 `target_level_index` 指向目标境界（筑基丹→10、结丹丹→13…）。曾只校验丹配置不查背包不扣丹 ⇒ 无丹白嫖（全境界通用）。现 handler 先查背包拒绝，manager 条件满足后才扣 1 枚（修为不足不误扣）。**改突破逻辑勿删这两道校验**。
- **灵田一键种植**（v3.3.2）：新增指令 `一键种植 <灵草名> [数量]`，`SpiritFarmManager.plant_all` 把空种植格一次性种满；省略数量填满全部空格。原逐格 `/种植 <名>` 保留。

## 炼器/精炼与装备属性（v3.3.3/v3.3.4）
- **根因**：README 早承诺材料用于"装备升级"但代码从未实现炼器 ⇒ 精铁/星辰石/灵兽内丹/天材地宝/紫金沙掉落无消耗；紫金沙曾全仓库仅 `items.json` 一处 = 死内容。
- **新增**：`forge_recipes.json`(8档配方,顶层九霄帝剑耗紫金沙×5)、`forge_config.json`(精炼:max10/每星+10%/成功率85-5×星下限20/≥6星耗紫金沙)、`forge_manager.py`+`forge_handlers.py`(炼器配方/炼器/精炼)。**紫金沙闭环**：储物戒材料清单+高阶掉落表(weight4)+顶层配方硬消耗。
- **精炼接入战力**：`calculate_equipment_bonus` 加可选 `refine_map`；5 个战斗入口串联 `db.get_refine_map`：combat_handlers/boss_manager/impart_pk_manager/spirit_eye_manager。**DB**：`LATEST_DB_VERSION`=26 新增 `equipment_refine` 表（迁移+全新安装两处都改）；`data_manager` 加 get/set_refine_level、get_refine_map。
- **⚠️ 战斗与面板必须共用 `models.resolve_equipment_attributes`**：items.json 有 10 件旧格式 `equip_effects` 法器（attack→物伤、defense→物防）。曾因战斗链只读新格式字段 ⇒ 旧装备「面板显示加成、战斗恒 0」（用户报告根因）。战斗链查找顺序=先 items 后 weapons（与 parse_item_from_name 一致）。
- **⚠️ 新 manager/handler 必须登记 `__init__.py` 导出**：main.py 顶层 `from .handlers import X`，漏导出=**插件加载即崩**（ForgeHandlers/ForgeManager 曾漏）；manager 测试走合成包绕过 __init__ 全绿也抓不到，**必须跑 smoke_import.py**。
- **⚠️ 面板精炼口径**：`get_total_attributes(..., refine_map, refine_per_star)` 武器/防具攻防 ×(1+star×per_star)、精神力/心法不放大、逐项 int(round)（round 银行家舍入）；排行/我的属性/我的装备均传 refine_map，不传参=旧行为。
- **⚠️ 测试替身 `_DB` 须补 `get_refine_map`**（返回 `{}`），否则 spirit_eye/boss 测试 AttributeError；迁移断言用 `==26`。

## 工程约定
- 按 AGENTS.md：功能更新/BUG 修复需同步 README.md、metadata.yaml 版本号、misc_handler.py 修仙帮助；新增玩家可见指令需登记 README 指令表与帮助。
- **测试统一放 `/tmp/xx_test/`**（仓库无 tests/），解释器必须用托管 venv `.../python/envs/default/bin/python`（裸 `python3` 缺 aiosqlite）。
- **导入项目模块需先 mock `astrbot`**，并**预注册合成 `xx_plugin.managers`/`xx_plugin.core`/`xx_plugin.handlers` 包**（`__path__` 指向目录）绕开各自 `__init__.py`；mock 需补 `AstrBotConfig`/`logger`/`all.At`。**⚠️ 先导 `data` 再导 `config_manager`**。
- **aiosqlite 三个坑**：①内存库必须 `conn.row_factory=aiosqlite.Row`；②**测试结束必须 `await conn.close()`**，否则后台线程挂起被 SIGTERM（exit 137）；③INTEGER 0/1 读回是 **int 不是 bool**（断言用真值判断）。
- **`bank_manager.borrow/repay` 内部会重读玩家** ⇒ 测试须把玩家放回 `db.players`。**断言"已封顶/已生效"前须确认前置条件成立**，否则断言恒真。
