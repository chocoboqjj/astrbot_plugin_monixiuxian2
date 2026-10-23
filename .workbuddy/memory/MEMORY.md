# 项目长期记忆

## 项目方向
- 本插件为 AstrBot 的文字修仙（放置类 RPG）插件，v3.2.7，AGPL-3.0，作者 xiaojuwa。
- 最新决策（2026-10-22）：计划**接入 QQ 官方机器人（qq_official 适配器），放弃 OneBot（aiocqhttp）**。
- 影响：玩家 user_id / 群 group_id 将从数字 QQ 号变为 openid 字符串，旧库数据不互通（玩家需重新「我要修仙」）。

## 平台迁移需修复的兼容性断点
- CQ 码硬编码：`handlers/dual_cultivation_handlers.py`、`handlers/impart_pk_handlers.py` 曾用 `\[CQ:at,qq=(\d+)\]` 解析 @，QQ 官方下失效。**已于 v3.1.4 修复**（统一走 `handlers/utils.py::extract_target_id`）。
- ID 数字假设：`sect_handlers.py`、`storage_ring_handler.py`、`combat_handlers.py` 等多处 `isdigit()` / `re.search(r'(\d{5,12})')` 兜底对 openid 失效。**已于 v3.1.4 修复**。
- At 组件属性：统一补充 `.user_id` 到属性列表（combat_handlers 已含 qq/target/uin/user_id，可作范本）。注意 AstrBot 的 `At` 组件实际只有 `qq`/`name` 两个字段，`target/uin/user_id` 只是防御性 getattr。
- 白名单/管理员配置（WHITELIST_GROUPS/BOSS_ADMINS/SHOP_MANAGERS）需重填为 openid。

## ⚠️ QQ 官方机器人 @解析的关键事实（v3.2.4 踩坑，务必记住）
- **AstrBot `qq_official` 适配器在入站消息链里放的 At 只代表"机器人自己"**：群@消息（`GROUP_AT_MESSAGE_CREATE`）下 QQ 官方的 `mentions` 数组不含机器人自身，适配器取不到 bot id，于是放入 `At(qq="qq_official")`——**字面量占位符**；C2C 同样；只有群全量模式且确实 @了机器人才是 `At(qq=机器人openid)`。**所以"消息链第一个 At = 目标用户"这个假设在 QQ 官方下永远不成立**，v3.1.4 正是因此导致双修/切磋/决斗/赠予/宗门/传承挑战全部失效。
- **被 @ 的其他用户不进消息链**，只以 `<@!member_openid>` / `<qqbot-at-user id="..."/>` 文本标记留在纯文本里（依据：腾讯官方 openclaw-qqbot 的 `stripMentionText`）。该 markup 用的就是 `member_openid`，与 `event.get_sender_id()` 同源，可直接作玩家库主键。
- **`member_openid` 是按群维度的 OpenID**：同一用户在不同群是不同 ID ⇒ 跨群 @ 无法指向同一份玩家数据（平台特性，非插件缺陷）；同群内 @ 可正常命中。
- `handlers/utils.py::extract_target_id` 现为 5 级优先级：①消息链 At（按 `get_self_id()`/`get_sender_id()`+占位符表剔除机器人自己）②arg/纯文本 @ 标记 ③raw payload `mentions` 兜底（仅 qq 平台，优先 member_openid）④arg 作裸 ID（含 `<>[]()` 拒绝）⑤纯文本整词数字 token。配套 `strip_at_markup` / `strip_target_from_text` / `looks_like_user_id`。
- **AstrBot `CommandFilter` 的参数注入**：参数全部来自 `event.get_message_str()` 的空格切分；`str` 型参数**只取一个 token**（想拿全文必须从消息链 Plain 组件重新拼，`storage_ring_handler.handle_gift_item` 就是这么做的）。
- `At` 组件的四个属性名 `qq/target/uin/user_id` 中只有 `qq` 真实存在；`AtAll` 的 `qq="all"`。


## 架构约定（v3.1.8 起）
- **玩家数据清除统一入口**：`db.penalty_mgr.punish(player, PenaltyReason.XXX)`（`core/penalty_manager.py`）。已接入突破死亡/银行追杀/逾期检查/弃道重修 4 处。不要再直接调 `delete_player_cascade`（仅作兜底安全网保留）。
- **多活动并行状态**：`db.activity_mgr`（`core/activity_manager.py`），`user_activity` 表主键 `(user_id, activity_type)`。闭关/历练/秘境**可同时进行**，各自独立计时；只用 `get`/`start`/`finish` 操作**自己那一个槽位**，不要用 `set_user_free` 一把清空（会误清其他活动）。未注入时降级到旧 `user_cd`。
- **⚠️ 不要用「忙碌状态」封锁指令**：瞬时操作（炼丹/打Boss/决斗/宗门/双修/悬赏/商店）**不受任何活动影响**。只有「同类活动重复启动」才拒绝。`player_required` 装饰器**不做状态检查**。
- **跨模块共享实例的惯用法**：把 manager 挂到 `DataBase` 实例上（如 `db.penalty_mgr`、`db.activity_mgr`），用 `getattr(self.db, "xxx_mgr", None)` 取用并做降级，避免逐层改构造函数签名。
- **战斗属性/战力公式唯一来源**：`managers/combat_manager.py::calculate_combat_stats` / `calculate_combat_power`，决斗、传承PK、Boss 战、玩家面板、排行榜共用。
- **概率透明化**：`utils/probability.py::describe_roll` 统一措辞；随机玩法结果消息统一加「🎰 命数判定」块。
- **⚠️ 配置读取层级**：`_conf_schema.json` 的 `VALUES` 是**嵌套对象**，实际值在 `config["VALUES"][key]`。读配置必须用 `config["VALUES"].get(key, default)`，**不要**用 `config.get(key)`（顶层读不到，配置形同虚设）。本项目已有 `_get_value()` 兼容封装可参考。
- **⚠️ 全新安装建表**：`_create_all_tables_v2()` 是全新安装的唯一建表路径，**必须包含所有玩法所需表/列/种子数据**；`MIGRATION_TASKS`（v2~v20）在全新安装时**不会执行**。新增玩法表时两处都要改，或直接把建表语句放进 v2 函数。
- **不要用 `set_user_busy` 做冷却**：该方法会占用玩家的「忙碌状态」，会封锁除签到/银行外的所有指令。瞬时操作的冷却请用 `system_config` 独立存储。
- **⚠️ 储物戒变更后必须同步回调用方对象**（v3.1.9 修复）：`storage_ring_manager` 的三个存取方法内部会重读玩家并**局部重绑定** `player` 变量。Python 传参是引用传递但重绑定不影响调用方，调用方随后 `update_player()`（43 字段全量 UPDATE）会把改动**覆盖回旧值**（lost update）。已在 manager 内用 `_sync_ring_items_to_caller()` 解决；**若你新写代码调用 store/retrieve/discard 后还要用旧 player 对象写回，必须确认 manager 已同步**。
- **⚠️ 模块级常量不要用 `self.` 访问**：`handlers/shop_handler.py` 曾用 `self.STORAGE_ITEM_TYPES` 访问模块级常量 → 必抛 AttributeError。类内引用模块级常量直接写名字。
- **⚠️ 物品经济断裂（v3.2.0 已部分修复）**：命名归一（百年灵草→灵草、玄铁→精铁、声明8种幽灵材料）、新增 `/回收` 指令（按售价50%变现）、炼丹灵石成本下调（50/100/150/250/500 → 20/30/40/60/100）已完成。剩余未做：① **炼器/功法合成系统**——紫金沙/龙骨髓/玄冰之核等稀有材料目前只有商城买入、无消耗出口；② **10 种功法 `equip_effects` 为空**（装备后属性全零）；③ **10 种 items.json 法器被 weapons.json 高阶武器碾压**（弑神枪 攻500/999万灵石 vs 霸王帝刀 物伤850+法伤500/23.6万）。
- **⚠️ 悬赏「去哪完成」提示约定（v3.2.1）**：`BountyManager.format_completion_hint` / `format_completion_hint_short` 把 `progress_tags` 翻译成可执行指令。`adventure_scout/roam/hunt/peril` → `/开始历练 巡山问道/云游四方/猎魔肃清/九死一生`，`rift/explore` → `/秘境列表` + `/探索秘境 <ID>`（两者同义、去重）。`gather/collect/kill/escort` 为描述性标签，当前由历练/秘境统一推进，**新增模板时不要为它们单列指令**（会误导玩家）。历练路线→bounty_tag 的对应见 `config/adventure_config.json`。该提示已接入 `/悬赏令` 列表、`接取悬赏` 成功、`悬赏状态`、`/完成悬赏` 未完成三处。
- **⚠️ 悬赏专属掉落 `item_tables` 与主线掉落要同步**：v3.2.0 已把主线掉落 `玄铁`→`精铁`，但 `bounty_templates.json` 的 `item_tables`（gather/hunt/supply）遗漏，到 v3.2.1 才清除。以后凡改材料命名，务必同时扫 `config/` 下所有 json（含 item_tables、drop 表、recipe 表）。
- **⚠️ 「领了用不了」问题类（v3.2.3）**：宗门丹房 `SECT_ELIXIR_ROOMS` 发放的 5 味丹药有 3 味（聚气丹/回元丹/破障丹）在 pills/exp_pills/utility_pills/alchemy_recipes 四张配置里**均无定义**，`use_pill` 直接返回「配置不存在」。已补 util_144~148（宗门专属，`shop_weight:0`）。**教训：任何"发放清单"类配置（丹房/掉落表/礼包）都不能直接写名字进背包，必须同时校验「配置存在性」和「境界门槛」**——`claim_sect_elixir` 现已两道校验。
- **⚠️ 永久属性丹的「每境界 30%」配额是全服共享名额**：所有 `*_gain`（含新增的 `*_gain_percent`）共用同一份按境界计算的额度。副作用：① 免费的宗门日常丹会把名额填满，实质架空高价付费丹（45,000 无缺丹 / 200,000 本源丹）；② 境界 0 的 `breakthrough_*_gain` 为 0 ⇒ 配额为 0 ⇒ **永久丹对境界 0 玩家恒无效**（会被判"已达上限"），所以宗门丹药门槛不能设 0。
- **⚠️ `breakthrough_boost` 类丹药叠加必须防无限叠加**：`get_breakthrough_modifiers()` 原本无上限累加，`calculate_breakthrough_success_rate()` 只有 `min(...,1.0)` 截断（`max_success_rate` 只对破境丹生效）。新增 `temp_bonus_cap` 字段（util_146 破障丹 = 0.05）双桶累加夹紧；**无 cap 的丹药（幸运丹/天命幸运丹）走原逻辑，行为零变化**。以后新加带突破加成的丹药，若可每日领取/可持续，必须配 `temp_bonus_cap`。

## ⚠️ 债务继承制（v3.2.7，务必记住）
- **身死不清债**：贷款未还清时身死（走火入魔/战斗死亡/弃道重修）→ 债务转入 `carried` 状态，**重开后恢复为正常贷款**（本金=死亡时锁定的「本金+已产生利息」、**利率归零固定免息**、due=now+7天宽限期）。仅「逾期被银行追杀」（BANK_KILL）免除债务（避免「逾期→死→继承→再逾期」死循环）。
- **实现位置**：业务 `managers/bank_manager.py::inherit_debt_on_death` / `restore_inherited_debt` / `format_inherit_notice`；数据层 `data/database_extended.py::get_carried_loan` / `restore_carried_loan` / `mark_loan_carried`；入口 `core/penalty_manager.py::apply_death_debt(db, user_id, reason)`（模块级函数，供 `punish()` 与 4 处兜底路径共用）。
- **⚠️ 时序铁律**：债务继承**必须在 `delete_player_cascade` 之前**执行——cascade 会把 `active` 贷款置为 `bad_debt`（免除），顺序反了继承直接失效。
- **⚠️ `db.bank_mgr` 必须注入**（`main.py`）：`apply_death_debt` 用 `getattr(db, "bank_mgr", None)` 取用，未注入则继承逻辑静默失效（降级为旧的免除行为）。
- **`bank_loans` 表结构（v23 起）**：**无表级 UNIQUE**，改为两条部分唯一索引 `idx_bank_loans_user_active`(status='active') + `idx_bank_loans_user_carried`(status='carried')。**原 `UNIQUE(user_id,status)` 让玩家一生只能成功还清一次贷款**（第二次 `active→closed` 抛 IntegrityError，贷款卡死）。新增列 `inherit_count` / `settled_amount` / `inherit_at` / `grace_until`。
- **`mark_loan_overdue` 必须带 `AND status='active'`**：银行逾期流程中 cascade 先把贷款置 `bad_debt`（免除），无守卫会被改写回 `overdue` ⇒ 互相覆盖。
- **恢复后的贷款必须能被 `get_active_loan` 看到**：这是 v3.2.5「洞天产出托管」防套利不被绕过的前提（洞天托管依赖 `get_active_loan`）。
- **配置**：`_conf_schema.json` 新增 `BANK` 段（`DEBT_INHERIT_MAX` 默认 3 = 继承次数上限，第 4 次死亡强制豁免；`DEBT_INHERIT_GRACE_DAYS` 默认 7 = 宽限期）。设 `DEBT_INHERIT_MAX: 0` 即退回「死亡即清债」旧行为。
- **测试**：`/tmp/xx_test/test_loan_debt_survive.py`（44 项）+ `test_loan_debt_e2e.py`（20 项，真实 DataBase 全链路）。
- **⚠️ `shop_weight` 缺失 ≠ 不进商店**：`_get_all_shop_items` 校验 `shop_weight > 0`，但 `generate_pavilion_items` 用 `get('shop_weight', 100)` ⇒ 缺失时默认 100 反而会进丹阁/百宝阁。宗门专属物品必须**显式写 `"shop_weight": 0`**。

- **⚠️ 玩家文案禁止回显内部英文键（v3.2.2 修复）**：枚举/配置键（easy/normal、scout/journey、auto_repay、weapon/armor、hp/atk…）写进文案前**必须**有中文映射，且 `.get(key, key)` 这种"回退到原值"的写法一律改成中文兜底（如「未知类型」「历练」）。已建立映射表：`bounty_manager._difficulty_name`、`shop_handler.ITEM_TYPE_NAMES`、`pill_manager.EFFECT_TYPE_NAMES`、`equipment_manager.ITEM_TYPE_NAMES`、`impart_manager.ATTR_NAMES`、银行 `type_names`。回归测试 `test_i18n_no_english.py` 会扫描全项目 trans_type 字面量校验覆盖。
- **⚠️ `ConfigManager` 上没有 `adventure_config` 属性**：`config/adventure_config.json` 只由 `AdventureManager` 与 `BountyManager` 各自用 `Path(...)/config/adventure_config.json` 单独加载，`config_manager._load_all()` 不加载它。任何地方要用历练路线表，**不要**写 `hasattr(config_manager, "adventure_config")`（恒为 False），直接读 `AdventureManager.CONFIG_FILE`。

- **⚠️ 生息资产必须防「贷款杠杆套利」（v3.2.5 定案）**：只要资产收益率 > 贷款利率，且还贷后玩家**保留资产**，就永远可「借钱买资产 → 用资产收益还贷」白赚。单纯调利率**无法根除**。
  - **定案方案（洞天福地）**：**允许**在贷款存续期购置/升级生息资产，但**产出被银行托管**——`collect_income` 入口检查 `db.ext.get_active_loan`，有活跃贷款则拒绝收取（还清后立即恢复）。既切断套利闭环，又保留资金周转灵活性。
  - 配套：`BLESSED_LANDS.gold_per_hour` 定为**约 7 天回本**（60/300/1200/3000/6000，各档统一 6.9 天）。
  - **⚠️ `blessed_lands.gold_per_hour` 是入库快照值**（购置时写入配置值，升级时按 `int(base*(1+level*0.15))` 重算）⇒ **改 `BLESSED_LANDS` 常量只影响新购/新升级**，存量玩家不受影响，**必须配数据库迁移回填**（v21 已做，`data/migration.py`，`LATEST_DB_VERSION` 20→21）。以后改任何"落库的配置派生值"都要同理。
- **⚠️ 悬赏难度/奖励必须双单调校验**：R1 费率单调（上档模板最低灵石/时 > 下档模板最高灵石/时）、R2 总额单调（上档最低总灵石 > 下档最高总灵石）。回归测试 `/tmp/xx_test/test_bounty_balance.py` 扫描全模板×全 target 校验，**改 `bounty_templates.json` 后必跑**。
- **⚠️ 悬赏时限模型（v3.2.5）**：`_estimate_completion_seconds` 取**最慢可行路线**——`expected = max over progress_tags( ceil(target/bounty_progress) × (duration+fatigue) )`，`limit = max(base_limit, expected + max(600, expected//6))`。注意：① 猎魔每轮 +2 点、九死一生每轮 +3 点，**必须按 ceil 折算轮数**；② 须含秘境 `rift`（`rift_config.json` 的 `default_duration`，每轮 +1 点）；③ `bounty_progress` 减少的是**轮数**而非总耗时（猎魔单轮 6300s ≫ 巡山 2100s），写断言时别搞反。
- **⚠️ 悬赏难度门槛取自配置**：`_get_difficulty_plan` 读 `difficulties[diff].min_level`（F0/E3/D7/C12），**不要**硬编码阈值。

## 天地灵眼系统约定（v3.2.6）
- **灵眼时效逐档减半**：下品 24h / 中品 12h / 上品 6h / 极品 3h（`SPIRIT_EYE_TYPES[*].lifetime_hours`）——高收益配短窗口。到期自动消散，**消散前先结算持有者未收修为再删除，绝不吞收益**（`_settle_pending_exp` / `_cleanup_expired_eyes`）。
- **被占据的灵眼必须仍然可见**：`get_all_spirit_eyes()` 返回所有未过期灵眼（含有主的），`get_available_spirit_eyes()` 只返回无主的（供抢占列表）。`/灵眼信息` 分「无主」「已被占据」两段。
- **@人 争夺**：`/抢占灵眼 @对方` → `challenge_spirit_eye()`，走切磋式战斗（`combat_type=1`，不扣气血），胜者易主、败方给守方守护期。发起方 5 分钟冷却（`combat_cooldowns.last_eye_time`），胜方/守方 5 分钟守护期（`spirit_eyes.protect_until`）。
- **⚠️ 指令参数歧义**：`/抢占灵眼` 的参数既可能是**灵眼编号**（数字）也可能是**@目标**。handler 里靠 `extract_target_id(event, arg, allow_bare_id=False, allow_text_number=False)` 只认「显式 @」，纯数字才当编号。`extract_target_id` 新增的两个开关默认 `True`，**既有调用方行为零变化**。
- **⚠️ 并发抢占靠条件 UPDATE + rowcount**：`claim_spirit_eye` 里 `WHERE eye_id = ? AND (owner_id IS NULL OR owner_id = '')`，**先判 `cursor.rowcount == 0` 再 commit**（commit 后 rollback 无效）。**不要用 `self.db.conn.total_changes`**（那是连接累计值，不是本次影响行数）。
- **⚠️ 迁移常量不能 import managers**：v22 迁移用到灵眼时效表时，把 `SPIRIT_EYE_LIFETIME_HOURS` 写成 `data/migration.py` 的模块级常量，并在测试里断言与 `managers/spirit_eye_manager.py::SPIRIT_EYE_TYPES` 一致。存量灵眼按档位**从当前时间起算**回填完整一个时效窗口（不是从 spawn_time 算），避免上线即全灭。
- **`spirit_eyes` 三列（v22 起）**：`expire_time`（消散时间戳）、`protect_until`（守护期截止）、`last_collect_time`（上次收取时间）。`delete_player_cascade` 释放灵眼时必须一并清 `last_collect_time` / `protect_until`。

## 约定
- 按 AGENTS.md：功能更新/BUG修复需同步更新 README.md、metadata.yaml 版本号、misc_handler.py 的修仙帮助。
- 新增玩家可见指令需同时登记到 README 指令表与 misc_handler.py 的帮助文本。
- **测试文件统一放 `/tmp/xx_test/`**（仓库无 tests/ 目录）。解释器必须用托管 venv `/Users/adelenaumann/.workbuddy/binaries/python/envs/default/bin/python`（裸 `python3` 缺 aiosqlite）。导入项目模块需先 mock `astrbot`，并**预注册合成 `xx_plugin.managers` 包**（`__path__` 指向 managers 目录）绕开其 `__init__.py`（会连带拉起 sect/data→aiosqlite）；测 `handlers` 包同理要用合成 `xx_plugin.handlers` 包绕开 `player_handler`（依赖 `AstrBotConfig`）。
- **⚠️ 测试用 aiosqlite 的三个坑**：① 内存库必须设 `conn.row_factory = aiosqlite.Row`（真实 `DataBase.connect()` 会设），否则 `dict(row)` 报 "cannot convert dictionary update sequence"；② **测试结束必须关闭所有连接**，否则 aiosqlite 后台线程让进程挂起被沙箱 SIGTERM（exit 137）；③ 断言场景要**隔离**（独立库 + 独立玩家），否则前一个用例赢下灵眼会让后续全部被「已占据/守护期」拦截。
- **DB 迁移写法**：`@migration(N)` 注册 + `LATEST_DB_VERSION` 同步 + 全新安装路径（`_create_all_tables_v2`）的列 DEFAULT 也要一起改。迁移函数内**不要**直接 import `managers.*`（会循环依赖），把基准值写成模块级常量并在测试里断言与 `BLESSED_LANDS` 一致。

