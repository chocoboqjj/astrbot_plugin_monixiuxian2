# 项目长期记忆

AstrBot 文字修仙（放置 RPG）插件，AGPL-3.0，作者 xiaojuwa。当前 v3.3.2。
> 详细改动见 `.workbuddy/memory/2026-10-*.md` 日志；本文件只留"不可再生的踩坑事实"。

## ⚠️ QQ 官方 @解析（v3.2.4 踩坑）
- `qq_official` 入站消息链里的 At **只代表机器人自己**（群@时 `mentions` 不含自身 ⇒ 适配器塞 `At(qq="qq_official")` 占位符）⇒ **"消息链第一个 At = 目标"永远不成立**（v3.1.4 因此致双修/切磋/决斗/赠予/宗门/传承全失效）。
- **被 @ 的人不进消息链**，只以 `<@!member_openid>` / `<qqbot-at-user id="..."/>` 留在纯文本（腾讯 openclaw-qqbot `stripMentionText`），可作玩家库主键；`member_openid` **按群维度** ⇒ 跨群 @ 指向不同数据（平台特性）。
- `At` 的 `qq/target/uin/user_id` 中**只有 `qq` 真实存在**；`CommandFilter` 参数来自 `get_message_str()` 空格切分，`str` 型参数**只取一个 token**（要全文得从 Plain 组件重拼）。
- `extract_target_id` 5 级优先级：①消息链 At（剔除自己）②arg/纯文本 @ 标记 ③raw `mentions` 兜底 ④arg 裸 ID（拒 `<>[]()`）⑤整词数字 token；开关 `allow_bare_id`/`allow_text_number` 默认 True。
- 迁移后 user_id/group_id 变 openid、旧库不互通；白名单/管理员配置需重填。

## 架构约定
- **玩家数据清除唯一入口**：`db.penalty_mgr.punish(player, PenaltyReason.XXX)`；不要直接调 `delete_player_cascade`（仅兜底）。**跨模块共享实例**：manager 挂 `DataBase`（`db.penalty_mgr`/`db.activity_mgr`/`db.bank_mgr`），`getattr(self.db,"xxx_mgr",None)` 取用并降级，**注入缺失=功能静默失效**。
- **多活动并行**：`db.activity_mgr`，主键 `(user_id,activity_type)`；只用 `get`/`start`/`finish` 操作自己那格，**别用 `set_user_free` 一把清空**（会误清其他活动）。
- **战斗属性/战力唯一来源**：`managers/combat_manager.py` 的 `calculate_combat_stats`/`calculate_combat_power`；**概率措辞**：`utils/probability.py::describe_roll`。
- **⚠️ 不用「忙碌状态」封锁指令**：瞬时操作（炼丹/打Boss/决斗/宗门/双修/悬赏/商店）不受活动影响，只有同类活动重复启动才拒；`player_required` 不做状态检查。冷却也别用 `set_user_busy`（封锁除签到/银行外全部指令），用 `system_config`。
- **⚠️ 配置层级**：`_conf_schema.json` 的 `VALUES` 是嵌套对象 → 值在 `config["VALUES"][key]`；顶层段（`BANK`/`ACCESS_CONTROL`/`CALAMITY`）平铺。
- **⚠️ 全新安装建表**：`_create_all_tables_v2()` 是唯一建表路径，`MIGRATION_TASKS` 全新安装**不执行**；新增表/列**两处都要改**。
- **DB 迁移**：`@migration(N)` + `LATEST_DB_VERSION` 同步 + 全新安装路径一起改。迁移内**不要** import `managers.*`（循环依赖），基准值写成 `data/migration.py` 模块级常量并断言一致。
- **⚠️ 模块级常量不要用 `self.` 访问**（曾致 AttributeError）。**⚠️ 储物戒变更必须同步回调用方对象**：`storage_ring_manager` 存取方法内部重读玩家并局部重绑定，调用方 `update_player()` 会覆盖回旧值（lost update），已用 `_sync_ring_items_to_caller()` 解决。**⚠️ `can_store_item` 不校验存在性** ⇒ 掉落名写错即幽灵物品。
- **⚠️ 文案禁止回显内部英文键**：须有中文映射（各 manager 的 `*_NAMES` 常量），`.get(key,key)` 一律改中文兜底，回归 `test_i18n_no_english.py`。**⚠️ `ConfigManager` 无 `adventure_config`**：读 `AdventureManager.CONFIG_FILE`。
- **⚠️ 永久属性丹「每境界 30%」配额按境界+属性分桶**（所有 `*_gain` 共用额度）：①免费宗门丹填满名额、架空高价付费丹；②境界 0 基准为 0 ⇒ 永久丹对境界 0 恒无效 ⇒ 宗门丹药门槛不能设 0。**⚠️ `breakthrough_boost` 防无限叠加**：`temp_bonus_cap`（util_146=0.05）双桶夹紧；无 cap 的丹药行为零变化。
- **⚠️ SQLite `UPDATE...FROM` 的 `RETURNING` 不能引用 FROM 表旧列**（实测 `no such column: old.x`）。

## 债务继承制（v3.2.7）
- **身死不清债**：贷款未还清时身死（走火入魔/战斗死亡/弃道重修）→ 转 `carried`，**重开后恢复**（本金=死亡时锁定「本金+已产生利息」、**利率归零固定免息**、due=now+7天宽限期）。仅「逾期被银行追杀」免除（避免死循环）。**位置**：`bank_manager.py`、`database_extended.py`、入口 `core/penalty_manager.py::apply_death_debt()`。
- **⚠️ 时序铁律**：继承**必须在 `delete_player_cascade` 之前**——cascade 会把 `active` 置 `bad_debt`（免除）。
- **`bank_loans`（v23 起）**：**无表级 UNIQUE**，改 active / carried 两条部分唯一索引。**原 `UNIQUE(user_id,status)` 让玩家一生只能还清一次贷款**。新增列 `inherit_count`/`settled_amount`/`inherit_at`/`grace_until`。
- **`mark_loan_overdue` 必须带 `AND status='active'`**；**恢复后的贷款必须能被 `get_active_loan` 看到**（洞天托管防套利前提）。
- **配置**：`BANK` 段（`DEBT_INHERIT_MAX`=3、`DEBT_INHERIT_GRACE_DAYS`=7），设 0 即退回旧行为。

## 生息资产防「贷款杠杆套利」（v3.2.5）
- **根因**：资产收益 > 贷款利率且还贷后**保留资产** ⇒ 可白赚，**调利率无法根除**。**定案（洞天福地）**：允许贷款存续期购置/升级生息资产，但**产出被银行托管**——`collect_income` 入口检查 `db.ext.get_active_loan`，有活跃贷款则拒收。`BLESSED_LANDS.gold_per_hour` 约 7 天回本，**⚠️ 是入库快照值** ⇒ 改常量只影响新购/新升级，存量须迁移回填（v21 已做）。

## 世界 Boss 挑战限制（v3.2.8）
- **定案**：`boss_config.json` 的次数上限 + 冷却 + 安慰奖封顶（`_cap_consolation` = 50% 石头奖励）；次数按 boss_id 计数，刷新后重置。
- **⚠️ 并发安全**：`reserve_boss_challenge` 用单条 `INSERT...ON CONFLICT DO UPDATE...WHERE challenge_count<?` 完成「检查+递增」，靠 `cursor.rowcount` 判定，**先判 rowcount 再 commit**；**别用 `self.db.conn.total_changes`**。
- **⚠️ `defeat_boss` 必须条件 UPDATE**（`WHERE boss_id=? AND status=1` + rowcount 判定），**只有首个真击杀者**拿完整奖励并广播（`battle_result["actually_killed"]`）。**击杀类状态转移都要套这个模式**。
- **⚠️ `player.hp` 不是核心资源模型**：决斗/切磋也会重算满值 ⇒ 扣气血会造出"血量卡死"风险，故 Boss 战**保留满值入场**。表 `boss_challenges`（v24）`UNIQUE(boss_id,user_id)`。

## 悬赏系统约定
- **⚠️ 改 `bounty_templates.json` 后必跑** `/tmp/xx_test/test_bounty_balance.py`（难度/奖励双单调校验 R1 费率 + R2 总额）。
- **⚠️ 时限模型取「最慢可行路线」**：猎魔/九死一生**须按 ceil 折算轮数**、须含秘境 `rift`、`bounty_progress` 减的是**轮数**不是总耗时；门槛取自配置。**「去哪完成」提示**：`format_completion_hint` 把 `progress_tags` 翻译成指令（描述性标签**不单列指令**）；**专属掉落 `item_tables` 与主线要同步**。

## 天地灵眼系统约定（v3.2.6）
- **时效逐档减半**（24/12/6/3h）。到期自动消散，**消散前先结算持有者未收修为再删除，绝不吞收益**。**被占据的仍可见**：`get_all_spirit_eyes()` 含有的，`get_available_spirit_eyes()` 只返无主。
- **@人 争夺**：`/抢占灵眼 @对方` → 切磋式战斗（不扣气血），发起方 5 分钟冷却，胜/守方 5 分钟守护期。**⚠️ 参数歧义**：参数既可能编号也可能 @目标 ⇒ `extract_target_id(..., allow_bare_id=False, allow_text_number=False)`。**⚠️ 并发抢占靠条件 UPDATE + rowcount**（`WHERE eye_id=? AND (owner_id IS NULL OR owner_id='')`），**先判 rowcount 再 commit**。迁移常量写在 `data/migration.py` 模块级（**不能 import managers**），测试断言与 `SPIRIT_EYE_TYPES` 对齐。

## 天灾人祸系统约定（v3.2.9）
- **⚠️ 扣减必须「原地加减」**（`gold = MAX(0, gold - ?)`），**不能**「读旧值→算新值→写回绝对值」：所有 manager **共享同一个 aiosqlite 连接**，事务边界是**连接级** ⇒ 写回绝对值会**丢更新**。同理**不能用「条件 UPDATE + 旧值守卫 + rollback」**：`rollback()` 会把其他协程未提交的事务一起回滚。
- **⭐ 取旧值的唯一可靠技巧**：`RETURNING` 只看得到**更新后**的值；须用 `WITH old AS MATERIALIZED(...)` 并把 CTE **引用在 `SET` 表达式里**（强制写入前求值）。⚠️ CTE 只在 `RETURNING` 里引用会拿到新值。护盾判定须同语句。
- **判定顺序**虚惊一场→护盾免疫→实际扣减（虚惊时**不消耗**定魂护盾）。**境界地板**：`experience` 累计不清零，下限 = `exp_needed[level_index]`。**绝不致死**：只扣 `gold`/`experience`，不删号、不走 `punish()`。`has_debuff_shield`（定魂丹）此前是「只设不消」的悬空特性，本系统是其**首个消费点**。新增表 `calamity_records`（v25）+ `calamity_config.json` + `CALAMITY`。

## 遗留缺陷修复包（v3.3.0/3.3.1，细节见 2026-10-23 日志）
- **丹药表以「名称」为键** ⇒ 同名静默覆盖；跨表（新丹药系统 vs `items.json`）共享命名空间须查重。
- **`shop_weight=0` 排雷**：`_weighted_random_choice` 在 `len<=count` 时直接返全部候选；`generate_pavilion_items` 须按 `shop_weight>0` 硬过滤。
- **`permanent_pill_gains` 顶层可能有标量键（BASE_LIMIT_KEY）** ⇒ 遍历 `.values()` 必须 `isinstance(x,dict)`。
- **`base_attribute_limit_increase`** 是倍率提升永久增益上限，不提供属性，须走独立分支。
- **跨系上限兜底在代码层、境界表零改动**（突破各系只读自己能量字段）。
- **改名必须覆盖全部掉落表**（v3.3.1 玄铁→精铁漏两张掉落表 ⇒ 幽灵物品）；`test_drop_item_existence.py` 改材料名必跑。

## 突破丹约定（v3.3.2）
- **⚠️ `/突破 <破境丹名>` 必须先查背包并扣丹**：`pills.json` 里破境丹按 `target_level_index` 指向目标境界（筑基丹→10、结丹丹→13、凝婴丹→16…）。旧版 `handle_breakthrough` 只校验丹配置+适用境界，**从不查 `player.get_pills_inventory()`、从不扣丹** ⇒ 无丹也能白嫖加成（**全境界通用**，所谓「金丹期没事」是当时背包恰好有丹）。现修复：handler 先查背包拒绝无丹，manager 在突破条件满足后才扣 1 枚（修为不足不误扣）。**改突破逻辑时勿删这两道校验**，否则重现无消耗白嫖。
- **灵田一键种植**（v3.3.2）：新增指令 `一键种植 <灵草名> [数量]`，`SpiritFarmManager.plant_all` 把空种植格一次性种满；省略数量填满全部空格。原逐格 `/种植 <名>` 保留。

## 工程约定
- 按 AGENTS.md：功能更新/BUG 修复需同步 README.md、metadata.yaml 版本号、misc_handler.py 修仙帮助；新增玩家可见指令需登记 README 指令表与帮助。
- **测试统一放 `/tmp/xx_test/`**（仓库无 tests/），解释器必须用托管 venv `.../python/envs/default/bin/python`（裸 `python3` 缺 aiosqlite）。
- **导入项目模块需先 mock `astrbot`**，并**预注册合成 `xx_plugin.managers`/`xx_plugin.core`/`xx_plugin.handlers` 包**（`__path__` 指向目录）绕开各自 `__init__.py`；mock 需补 `AstrBotConfig`/`logger`/`all.At`。**⚠️ 先导 `data` 再导 `config_manager`**。
- **aiosqlite 三个坑**：①内存库必须 `conn.row_factory=aiosqlite.Row`；②**测试结束必须 `await conn.close()`**，否则后台线程挂起被 SIGTERM（exit 137）；③INTEGER 0/1 读回是 **int 不是 bool**（断言用真值判断）。
- **`bank_manager.borrow/repay` 内部会重读玩家** ⇒ 测试须把玩家放回 `db.players`。**断言"已封顶/已生效"前须确认前置条件成立**，否则断言恒真。
