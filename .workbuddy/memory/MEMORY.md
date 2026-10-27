# 项目长期记忆

AstrBot 文字修仙（放置 RPG）插件，AGPL-3.0，作者 xiaojuwa。当前 v3.3.8。
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
- **⚠️ 永久属性丹「每境界 30%」配额按境界+属性分桶**（所有 `*_gain` 共用）；境界 0 基准 0 ⇒ 永久丹对境界 0 恒无效。`breakthrough_boost` 防无限叠加：`temp_bonus_cap`(0.05) 双桶夹紧。
- **⚠️ SQLite `UPDATE...FROM` 的 `RETURNING` 不能引用 FROM 表旧列**；⭐ 取旧值唯一技巧 = `WITH old AS MATERIALIZED` 且 CTE 引用在 `SET` 表达式里（`RETURNING` 只看新值），护盾判定须同语句。

## 债务继承制（v3.2.7）
- **身死不清债**：未还清身死 → 转 `carried`，重开恢复（本金=锁定本金+利息、利率归零、due=now+7天）；仅「逾期被银行追杀」免除。入口 `core/penalty_manager.py::apply_death_debt()`。
- **⚠️ 时序铁律**：继承**必须在 `delete_player_cascade` 之前**（cascade 会把 active 置 bad_debt 免除）。
- **`bank_loans`（v23 起）**：无表级 UNIQUE，改 active/carried 两条**部分唯一索引**；新增列 `inherit_count`/`settled_amount`/`inherit_at`/`grace_until`。`mark_loan_overdue` 须带 `AND status='active'`。配置 `BANK.DEBT_INHERIT_MAX=3`/`GRACE_DAYS=7`，设 0 退回旧行为。

## 生息资产防「贷款杠杆套利」（v3.2.5）
- **根因**：资产收益 > 贷款利率且还贷后**保留资产** ⇒ 白赚。**定案**：贷款存续期可购/升级生息资产，但**产出被银行托管**——`collect_income` 查 `db.ext.get_active_loan`，有活跃贷款则拒收。`BLESSED_LANDS.gold_per_hour` **是入库快照值** ⇒ 改常量只影响新购/升级，存量须迁移回填（v21 已做）。

## 世界 Boss 挑战限制（v3.2.8）
- `boss_config.json` 次数上限+冷却+安慰奖封顶（50% 石头）；次数按 boss_id 计数，刷新重置。
- **⚠️ 并发安全**：`reserve_boss_challenge` 用单条 `INSERT...ON CONFLICT DO UPDATE...WHERE challenge_count<?`「检查+递增」，**先判 `cursor.rowcount` 再 commit**（别用 `total_changes`）。`defeat_boss` 条件 UPDATE（`WHERE boss_id=? AND status=1`+rowcount），仅首个真击杀者拿全奖并广播。**击杀类状态转移套此模式**。
- **⚠️ `player.hp` 非核心资源模型**：决斗/切磋也重算满值 ⇒ 扣气血有"血量卡死"风险，Boss 战**保留满值入场**。表 `boss_challenges`(v24)。

## 悬赏系统约定
- **⚠️ 改 `bounty_templates.json` 后必跑** `/tmp/xx_test/test_bounty_balance.py`（难度/奖励双单调校验）。
- **⚠️ 时限取「最慢可行路线」**：按 ceil 折算轮数、须含秘境 `rift`、`bounty_progress` 减的是**轮数**。专属掉落 `item_tables` 与主线同步。

## 天地灵眼系统约定（v3.2.6）
- **时效逐档减半**（24/12/6/3h），到期自动消散，**先结算未收修为再删，绝不吞收益**；`get_all_spirit_eyes()` 含被占，`get_available_spirit_eyes()` 只返无主。
- `/抢占灵眼 @对方` → 切磋式战斗（不扣气血），双方各 5 分钟冷却/守护期。**⚠️ 参数歧义** ⇒ `extract_target_id(allow_bare_id=False, allow_text_number=False)`；**⚠️ 并发抢占**条件 UPDATE+rowcount（`WHERE eye_id=? AND (owner_id IS NULL OR owner_id='')`）。迁移常量写 `data/migration.py` 模块级。

## 天灾人祸系统约定（v3.2.9）
- **⚠️ 扣减必须「原地加减」**（`gold = MAX(0, gold - ?)`），**不能**读旧值写回绝对值：所有 manager **共享同一 aiosqlite 连接**，事务边界**连接级** ⇒ 写回绝对值**丢更新**；也不能「条件 UPDATE+旧值守卫+rollback」（rollback 连坐其他协程）。
- **判定顺序**虚惊一场→护盾免疫→实际扣减（虚惊不消耗护盾）。**境界地板**：`experience` 不清零，下限=`exp_needed[level_index]`。**绝不致死**：只扣 gold/experience。定魂丹 `has_debuff_shield` 首个消费点。表 `calamity_records`(v25)。

## 遗留缺陷修复包（v3.3.0/3.3.1，细节见 2026-10-23 日志）
- **丹药表以「名称」为键** ⇒ 同名静默覆盖；跨表共享命名空间须查重。**`shop_weight=0` 排雷**：`_weighted_random_choice` 在 `len<=count` 时直返全部候选 ⇒ `generate_pavilion_items` 须按 `shop_weight>0` 硬过滤。
- **`permanent_pill_gains` 顶层可能有标量键** ⇒ 遍历 `.values()` 必须 `isinstance(x,dict)`；`base_attribute_limit_increase` 是倍率提升上限、不提供属性、须走独立分支。
- **跨系上限兜底在代码层、境界表零改动**。**改名须覆盖全部掉落表**（v3.3.1 玄铁→精铁漏两张 ⇒ 幽灵物品）；改材料名必跑 `test_drop_item_existence.py`。

## 突破丹约定（v3.3.2）
- **⚠️ `/突破 <破境丹名>` 必须先查背包并扣丹**：破境丹按 `target_level_index` 指向目标境界（筑基丹→10）。曾只校验丹配置不查背包不扣丹 ⇒ 无丹白嫖。**改突破逻辑勿删这两道校验**（handler 查背包拒绝 + manager 条件满足后才扣 1 枚）。
- **灵田一键种植**：`一键种植 <灵草名> [数量]`，`SpiritFarmManager.plant_all` 一次填满空种植格；逐格 `/种植` 保留。

## 炼器/精炼与装备属性（v3.3.3/v3.3.4）
- `forge_recipes.json`(8 档)、`forge_config.json`(精炼 max10/每星+10%/成功率 85-5×星下限 20)、`forge_manager.py`+`forge_handlers.py`。紫金沙闭环：储物戒材料+高阶掉落+顶层配方硬消耗。
- **精炼接入战力**：`calculate_equipment_bonus` 加可选 `refine_map`；5 个战斗入口串联 `db.get_refine_map`。**DB**：`LATEST_DB_VERSION`=26 新增 `equipment_refine` 表（迁移+全新安装两处都改）。
- **⚠️ 战斗与面板必须共用 `models.resolve_equipment_attributes`**（items.json 有 10 件旧格式 `equip_effects` 法器：attack→物伤、defense→物防）。曾因战斗链只读新格式 ⇒ 旧装备「面板显示、战斗恒 0」。查找顺序=先 items 后 weapons。
- **⚠️ 新 manager/handler 必须登记 `__init__.py` 导出**（main.py 顶层 import），漏导出=**插件加载即崩**；manager 测试走合成包绕过 `__init__` 抓不到 ⇒ **必须跑 smoke_import.py**。
- **⚠️ 面板精炼口径**：`get_total_attributes(..., refine_map, refine_per_star)` 武器/防具攻防 ×(1+star×per_star)，精神力/心法不放大，逐项 int(round)。**⚠️ 测试替身 `_DB` 须补 `get_refine_map`（返回 `{}`）**；迁移断言用 `==26`。

## 图片模式（v3.3.5/v3.3.6/v3.3.7）
- `main.py` `on_decorating_result` 钩子 + `long_plain_text`：单条纯文本 ≥ `IMAGE_MODE_MIN_LENGTH`(300) 自动转图，富媒体/短文本不转。钩子内**禁 yield**，改 `event.get_result().chain`。
- **⚠️ 组件判定用 type 名 `"Plain"`** ⇒ 测试 stub 类名必须叫 `Plain`/`Image`。官方 API 是 `self.text_to_image`/`self.html_render`/`event.image_result`，**无** `event.text_to_picture`。
- **v3.3.6+ 版式**：`utils/panel_renderer.py::render_panel_html` 先识别面板类型再从原文提字段重排（player 角色卡 / equip 装备卡 / help 指令手册 / shop 商品卡 / item_detail 详解卡 / generic 条目式），**不再逐行翻译旧文本**。**⚠️ html_render 用 Jinja2 渲染模板串** ⇒ CSS 全 class（勿用 id 防 `{#`）、模板禁 `{{`/`{%`；文本须转义。
- **v3.3.6 美化**：`utils/panel_renderer.py::render_panel_html` 按行宽容解析（**绝不丢行**）→ 仙侠模板 → 优先 `html_render(html,{},return_url=False)`，失败回退 `text_to_image`，再回退纯文本。**⚠️ html_render 用 Jinja2 渲染模板串** ⇒ CSS 全 class（勿用 id 防 `{#`）、模板禁 `{{`/`{%`；文本须转义；无冒号 `+数值` 行靠 `_emphasize`。
- **v3.3.7 双主题**：`_CSS_THEME_PAPER`(宣纸金,默认)/`_CSS_THEME_GOLD`(玄金) 两套 `:root` CSS 变量 + 共享 `_CSS` 结构 ⇒ **同一 DOM 仅换配色**。配置 `VALUES.PANEL_THEME`(string, default `paper`)。**⚠️ 变量化重构须同步改 `_frame()`+4 个 `_render_*()` 形参+4 处调用点+入口分发，漏一处=主题不生效/TypeError**。
- **⚠️ 预览页「无样式」= 预览脚本 bug，非用户机器**：摘 `render_panel_html` 产物时只取 `<body>` 会**丢掉自带 `<style>`** ⇒ 浏览器按裸文字渲染。**必须连 `<style>` 一起带，或用 iframe srcdoc 独立渲染**（与宿主 html_render 环境一致 + CSS 隔离；高度靠 JS 读 `contentDocument.body.scrollHeight` 自适应，srcdoc 同源可读）。
- **⚠️ 用户偏好（设计）**：偏好**宣纸+金**第一版配色； dislikes "文字换底色"式逐行翻译排版。改面板视觉先确认主题取向。
- **v3.3.7 转图选项**（`main.py::_render_options()`）：`{"type":"png","full_page":True,"viewport_width":PANEL_WIDTH,"viewport_height":10,"device_scale_factor_level":"ultra"}`。
  - **⚠️ t2i 服务端默认 `{"type":"jpeg","quality":40}`** ⇒ 糊；**默认视口 800px** ⇒ 右侧空白色块（面板 490px）。
  - **⚠️ `full_page` 截图高 = max(内容高, 视口高)** ⇒ 矮内容面板（商店等）底部必补白；**`viewport_height` 压到极小(10)** 才能按内容实际高度裁剪。视口宽度优先级：显式 `viewport_width` > HTML `<meta viewport>` > 默认 800。
- **v3.3.8 商店专属布局**：`_parse_shop_items()` 以**商品头行**为锚点重新聚合（通用解析会把商品 3 行拆散⇒排版乱）；`_render_shop()` 商品卡 2 列网格；`_render_item_detail()` 物品详情卡。12 品级→`RANK_TIER` 6 档配色(rk0~rk5)。**⚠️ `_is_shop` 须 (标题含"阁") 且 (至少一件商品带价格)**，否则「藏经阁(无价格行)」等误判。
- **⚠️ 内容比对断言**：数值被 `<b class="num">` 包裹后字符串不连续 ⇒ 比对前须 `_re.sub(r"<[^>]+>","",html)` 去标签。

## 工程约定
- 按 AGENTS.md：功能更新/BUG 修复需同步 README.md、metadata.yaml 版本号、misc_handler.py 修仙帮助；新增玩家可见指令需登记 README 指令表与帮助。

## ⚠️ 宿主 CommandFilter 截断（v3.3.8 踩坑，最高价值）
- **`CommandFilter` 的 `str` 参数只取消息里的第一个 token**：`/回收 灵草 5` 传给 handler 的 `args` 实为 `"灵草"`，数量在到达 handler 前就丢了。
- ⇒ 凡需「名称 + 数量」的指令（回收/服用/赠予/存入/取出）**必须**用 `handlers/utils.py::parse_counted_args(event, args, [CMD], default)` 从 `event.get_message_str()` **原始消息**重解析（支持 "名 数量" 与 "名x数量"）。

## 物品/丹药表「两套数据源」（v3.3.8）
- **`config/items.json` 是所有物品的唯一权威登记处**；掉落表引用的物品未在此登记 = **幽灵物品**（可掉落、可拾取，但回收/赠送查不到配置）。`smoke_import.py` 有永久守护（扫 config 掉落表 + manager 源码正则）。
- **`PillManager.get_pill_by_name` 须兜底查 `items_data`**：items.json 里 33 味「旧系统丹药」（含三品凝神增益丹）只登记在该表，三张新丹药表查不到 ⇒ 一律报「配置不存在」。旧格式 `effect` 字典语义由 `apply_legacy_pill_effects()` 统一（百宝阁购买与丹药背包服用共用）。
- **丹药在 `pills_inventory`（丹药背包），普通物品在 `storage_ring_items`（储物戒）**，且 `can_store_item` 明确拒绝存丹药 ⇒ 赠予/接收/拒绝返还三条链路必须按「是否丹药」分流（`_is_pill`/`_take_for_gift`/`_give_to_player`）。

## 炼丹/炼器/功法/投毒（v3.3.8）
- **破境丹炼制限境界**：`target_level_index <= player.level_index + 1`（筑基后期最高炼结丹丹）。稀有材料限量防泛滥。
- **投毒**（参考电鱼）：识破率 10%~85%（境界差/3×5% + 精神力差/1000×3%，基准 35%）；被识破扣灵石**必须原地加减** + 30min 冷却；得手挂 `subtype=poisoned` 负值倍率。只影响属性不杀人。
- **功法合成**：`TIER_ORDER` 必须 **11 元**（珍品与灵品同级但命名不同，两个都保留）；9 档配方每档带 `floor` 保底。**⚠️ items.json 功法品级必须补齐**（此前灵品~仙品全空 ⇒ 保底后无货可摇、一路 fallback 凡品）。
- **炼器**：`forge_recipes.json` 18 条（武器+防具，9 档品级 ↔ 境界门槛一一对应）；防具在 `items.json`（`type=法器` + `subtype=防具`），`shop_manager.get_weapons_for_display` 须纳入防具才上得了器阁。

## 秘境与历练档位（v3.3.8）
- **秘境 7 档**（`rift_manager.RIFT_DROP_TABLE` 覆盖 1~7）：⚠️ 原表只有 1~3 档而种子有 5 档 ⇒ 4/5 档掉的是**低级表**（已修）。额外掉落概率按档位递增（`RIFT_EXTRA_DROP_CHANCE`）。秘境实际列表读 **DB `rifts` 表**，`config/rift_config.json` 的 rifts 列表只是展示参考（已对齐 DB）。
- **DB**：`LATEST_DB_VERSION`=27 新增太虚秘境/混沌秘境种子（迁移+全新安装两处都改）。
- **历练 6 路线**（配置驱动，`adventure_config.json`）：⚠️ `AdventureManager.DEFAULT_CONFIG["drop_tables"]` 原本只有 low 档 ⇒ 配置读取失败时所有路线退化；现已补齐 mid/high/extreme/chaos。
- **稀有材料闭环**：紫金沙/混沌精华/神兽之骨/仙器碎片/远古秘籍 均可从历练+秘境随机获取（此前只能靠高阶 Boss 独供）。新历练标签不在悬赏模板 progress_tags 里 ⇒ 不影响悬赏时限计算。

## ⚠️ 灵眼抢占语义（v3.3.8 修正）
- **「直接抢占 + 成功后默认释放」= 允许直接发起 + 成功后自动让出*自己原先那处***，**不是**「抢到的也释放」（那样收益为 0、玩法作废）。
- 实现：战前只记 `mine`；**成功后**先把旧位 owner 清空再易主；**⚠️ 旧位修为结算放在易主成功之后**（否则易主失败 rollback 时修为已发无法收回）。失败/平局时原灵眼分毫不动。

## 测试 exit 137（SIGTERM）根因
- **aiosqlite 连接未关闭 ⇒ 后台线程挂起 ⇒ 进程被 SIGTERM**。根因通常是**断言异常中断了 `run()`**，尾部的「关闭所有内存库连接」永远执行不到。
- **解法：一律把 `run()` 包进 `try/finally`**（`_run_guarded()`）保证任何异常路径都关连接。
- ⚠️ `test_drop_item_existence.py` 用**相对路径**找 `config/` ⇒ 必须在**项目目录**下运行，在 /tmp/xx_test 下跑会 FileNotFoundError（不是回归）。
- **测试统一放 `/tmp/xx_test/`**（仓库无 tests/），解释器必须用托管 venv `.../python/envs/default/bin/python`（裸 `python3` 缺 aiosqlite）。
- **导入项目模块需先 mock `astrbot`**，并**预注册合成 `xx_plugin.managers`/`xx_plugin.core`/`xx_plugin.handlers` 包**（`__path__` 指向目录）绕开各自 `__init__.py`；mock 需补 `AstrBotConfig`/`logger`/`all.At`。**⚠️ 先导 `data` 再导 `config_manager`**。
- **aiosqlite 三个坑**：①内存库必须 `conn.row_factory=aiosqlite.Row`；②**测试结束必须 `await conn.close()`**，否则后台线程挂起被 SIGTERM（exit 137）；③INTEGER 0/1 读回是 **int 不是 bool**（断言用真值判断）。
- **`bank_manager.borrow/repay` 内部会重读玩家** ⇒ 测试须把玩家放回 `db.players`。**断言"已封顶/已生效"前须确认前置条件成立**，否则断言恒真。
