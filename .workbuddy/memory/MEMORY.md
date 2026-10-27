# 项目长期记忆

AstrBot 文字修仙（放置 RPG）插件，AGPL-3.0，作者 xiaojuwa。当前 v3.3.11。
> 详细改动见 `.workbuddy/memory/2026-10-*.md` 日志；本文件只留"不可再生的踩坑事实"。

## ⚠️ QQ 官方 @解析（v3.2.4）
- `qq_official` 消息链里的 At **只代表机器人自己** ⇒ **"消息链第一个 At = 目标"永不成立**（v3.1.4 因此致双修/切磋/决斗/赠予/宗门/传承全失效）。
- **被 @ 者不进消息链**，只以 `<@!member_openid>` 留在纯文本，可作玩家库主键；`member_openid` **按群维度** ⇒ 跨群 @ 指向不同数据。
- `extract_target_id` 5 级优先级：①消息链 At（剔除自己）②arg 纯文本 @ ③raw `mentions` ④arg 裸 ID（拒 `<>[]()`）⑤整词数字 token。迁移后 user_id/group_id 变 openid、旧库不互通。

## 架构 & DB 约定
- **玩家数据清除唯一入口**：`db.penalty_mgr.punish(player, PenaltyReason.XXX)`；勿直调 `delete_player_cascade`。**跨模块共享实例**挂 `DataBase`，`getattr(self.db,"xxx_mgr",None)` 降级 ⇒ **注入缺失=功能静默失效**。
- **多活动并行**：`db.activity_mgr`，PK `(user_id,activity_type)`；**别用 `set_user_free` 一把清空**。
- **战力唯一来源**：`managers/combat_manager.py`；概率措辞 `utils/probability.py::describe_roll`。
- **⚠️ 不用「忙碌状态」封锁指令**：瞬时操作不受活动影响，同类重复启动才拒；冷却用 `system_config`。
- **⚠️ 配置层级**：`_conf_schema.json` 的 `VALUES` 是**段**结构，真实项在 `VALUES.items[*]`，运行时读 `config["VALUES"][key]`；顶层段（`BANK`/`ACCESS_CONTROL`/`CALAMITY`）平铺。
- **⚠️ 建表/迁移**：`_create_all_tables_v2()` 是唯一全新安装建表路径（`MIGRATION_TASKS` 全新安装不执行）⇒ 新增表/列**两处都改**；`@migration(N)` + `LATEST_DB_VERSION` 同步；迁移内**勿 import managers**（循环依赖），基准值写 `data/migration.py` 模块级常量并断言。当前 `LATEST_DB_VERSION`=27。
- **⚠️ 模块级常量勿用 `self.` 访问**。**⚠️ 储物戒 lost update**：`storage_ring_manager` 内重读玩家局部重绑，调用方 `update_player()` 会覆盖回旧值（`_sync_ring_items_to_caller()` 解决）。**⚠️ `can_store_item` 不校验存在性** ⇒ 掉落名写错即幽灵物品。
- **⚠️ 文案禁回显内部英文键**：须有 `*_NAMES` 中文映射。**⚠️ `ConfigManager` 无 `adventure_config`**：读 `AdventureManager.CONFIG_FILE`。
- **⚠️ 永久属性丹「每境界 30%」配额按境界+属性分桶**（所有 `*_gain` 共用）；境界 0 基准 0 ⇒ 永久丹对境界 0 恒无效。`breakthrough_boost` 靠 `temp_bonus_cap`(0.05) 双桶夹紧防叠加。
- **⚠️ SQLite `UPDATE...FROM` 的 `RETURNING` 不能引用 FROM 表旧列**；⭐ 取旧值唯一技巧 = `WITH old AS MATERIALIZED` 且 CTE 引用在 `SET` 表达式里。

## 各玩法系统要点
- **债务继承制（v3.2.7）**：未还清身死 → 转 `carried`，重开恢复；仅「逾期被银行追杀」免除。**⚠️ 时序铁律**：继承**必须在 `delete_player_cascade` 之前**。`bank_loans` 用 active/carried 两条**部分唯一索引**；`mark_loan_overdue` 须带 `AND status='active'`。
- **生息资产防套利（v3.2.5）**：有活跃贷款时 `collect_income` 拒收。`BLESSED_LANDS.gold_per_hour` 是**入库快照值** ⇒ 改常量只影响新购/升级，存量须迁移回填。
- **世界 Boss（v3.2.8）**：`reserve_boss_challenge` 用单条 `INSERT...ON CONFLICT DO UPDATE...WHERE count<?`「检查+递增」，**先判 `cursor.rowcount` 再 commit**。`defeat_boss` 条件 UPDATE+rowcount ⇒ 仅首个真击杀者拿全奖。**击杀类状态转移套此模式**。⚠️ `player.hp` 非核心资源模型，Boss 战保留满值入场。
- **悬赏**：改 `bounty_templates.json` 后必跑 `test_bounty_balance.py`；**时限取「最慢可行路线」**，`bounty_progress` 减的是**轮数**。
- **天地灵眼（v3.2.6）**：时效逐档减半，到期**先结算未收修为再删**；`get_all_spirit_eyes()` 含被占 / `get_available_...()` 只返无主。并发抢占用条件 UPDATE+rowcount。
- **⚠️ 灵眼抢占语义（v3.3.8 修正）**：「直接抢占 + 成功后默认释放」= 成功后自动让出**自己原先那处**，**不是**释放抢到的（那样收益为 0）。**旧位修为结算放在易主成功之后**（否则 rollback 时修为已发无法收回）。
- **天灾人祸（v3.2.9）**：**⚠️ 扣减必须「原地加减」**（`gold = MAX(0, gold - ?)`），**不能**读旧值写回绝对值（manager 共享同一 aiosqlite 连接、事务边界连接级 ⇒ 丢更新）；也不能「条件 UPDATE+旧值守卫+rollback」（rollback 连坐其他协程）。判定顺序：虚惊一场→护盾免疫→实际扣减。**绝不致死**。
- **遗留缺陷包（v3.3.0/3.3.1）**：丹药表**以名称为键**（同名静默覆盖）；`shop_weight=0` 须在 `generate_pavilion_items` 硬过滤（`_weighted_random_choice` 在 `len<=count` 时直返全部候选）；`permanent_pill_gains` 遍历须 `isinstance(x,dict)`。**改名须覆盖全部掉落表**，改材料名必跑 `test_drop_item_existence.py`。
- **突破丹（v3.3.2）**：`/突破 <破境丹名>` **必须先查背包并扣丹**（破境丹按 `target_level_index` 指向目标境界）；曾只校验配置不查背包 ⇒ 无丹白嫖，**勿删这两道校验**。
- **炼器/精炼/装备（v3.3.3/3.3.4，v3.3.8 补齐防具）**：`forge_recipes.json`(18 条，武器+防具，9 档品级 ↔ 境界门槛)；防具在 `items.json`（`type=法器`+`subtype=防具`），`get_weapons_for_display` 须纳入防具才上器阁。精炼 max10/每星+10%/成功率 85-5×星下限 20；**精炼接入战力**走 `calculate_equipment_bonus(refine_map=...)` + `db.get_refine_map`。**⚠️ 战斗与面板必须共用 `models.resolve_equipment_attributes`**（items.json 有 10 件旧格式 `equip_effects` 法器）。**⚠️ 新 manager/handler 必须登记 `__init__.py` 导出**，漏导出=**插件加载即崩** ⇒ 必须跑 smoke 导入。
- **秘境与历练（v3.3.8）：秘境 7 档**（`RIFT_DROP_TABLE` 曾只有 1~3 档 ⇒ 4/5 档掉低级表）；秘境实际列表读 **DB `rifts` 表**。历练 6 路线，`AdventureManager.DEFAULT_CONFIG["drop_tables"]` 须补齐 mid/high/extreme/chaos（否则配置读取失败时退化）。稀有材料闭环：紫金沙/混沌精华/神兽之骨/仙器碎片/远古秘籍 可从历练+秘境获取。
- **炼丹/功法/投毒（v3.3.8）**：破境丹炼制限 `target_level_index <= level_index+1`；投毒识破率 10%~85%，被识破扣灵石**必须原地加减**；功法合成 `TIER_ORDER` 必须 **11 元**（珍品与灵品同级），9 档配方每档带 `floor` 保底，⚠️ items.json 功法品级必须补齐。

## 图片模式（v3.3.5 ~ v3.3.11）
- `main.py` 的 `@filter.on_decorating_result()` **在 ResultDecorateStage 全局触发**（会误伤其它插件/LLM 回复）⇒ 用 `event._xiuxian_owns` 标记限定本插件（在 `require_whitelist`/`player_required` 打标记，钩子开头守卫）。钩子内**禁 yield**，改 `event.get_result().chain`。
- 单条纯文本 ≥ `IMAGE_MODE_MIN_LENGTH`(300) 才转；**⚠️ 组件判定用 type 名 `"Plain"`** ⇒ 测试 stub 类名必须叫 `Plain`。官方 API 是 `self.html_render`/`self.text_to_image`，**无** `event.text_to_picture`。
- `utils/panel_renderer.py::render_panel_html` 先识别面板类型再提字段重排（player/equip/help/shop/item_detail/generic），**绝不丢行**。**⚠️ html_render 用 Jinja2 渲染模板串** ⇒ CSS 全 class（勿用 id 防 `{#`）、模板禁 `{{`/`{%`；文本须转义。
- **双主题** `_CSS_THEME_PAPER`(宣纸金,默认)/`_CSS_THEME_GOLD`(玄金) 共享 `_CSS` ⇒ 同一 DOM 仅换配色；⚠️ 变量化重构须同步改 `_frame()`+4 个 `_render_*()` 形参+调用点+入口分发。**用户偏好宣纸+金第一版配色**，dislikes 逐行换底色的翻译式排版。
- **转图选项 `_render_options()`**：`{"type":"png","full_page":True,"viewport_width":PANEL_WIDTH,"viewport_height":10,"device_scale_factor_level":"high"}`。⚠️ 服务端默认 jpeg/q40 ⇒ 糊；默认视口 800px ⇒ 右侧空白。**⚠️ `full_page` 截图高 = max(内容高, 视口高)** ⇒ `viewport_height` 压到 10 才按实际内容高度裁剪；**关掉 full_page 反而补白/截断**，故默认 true。`ultra`(1.8x) 不如 `high`(1.3x) 稳。
- **⚠️ 远程渲染（v3.3.10 最高频坑）**：`t2i.rcfortress.site` 是 **AstrBot 内置默认远程后端**，非插件写死；日志刷 `Cannot connect ... trying next` = 宿主连不上它（未配本地渲染器时 `text_to_image` 回退触发）。
- **v3.3.11：只走本地 Playwright**。删除 Pillow 实现 `utils/image_generator.py`（v3.3.6 后已无调用）+ requirements 移除 Pillow ⇒ **零额外 Python 依赖**；`IMAGE_MODE_SKIP_REMOTE_FALLBACK` 默认 **true**（只走本地 `html_render`，本地不可用→纯文本，绝不连远程；自建本地 t2i 者可设 false）；`IMAGE_MODE_RENDER_TIMEOUT`（**整数秒**，默认 8，`int()` 取整 ⇒ 写 0.2 会变 0=不限时）兜底挂死。
- 用户**已在本机装好 Playwright + Chromium**；⚠️ 关键前提：必须装在 **AstrBot 所用的那个 Python**（系统 python3 与 WorkBuddy 托管 venv 都不是），否则 `html_render` 仍会失败。判据：发 `/我的信息` 后日志**无** rcfortress 行 = 本地生效。
- **⚠️ 预览页「无样式」多为预览脚本 bug**：只取 `<body>` 会丢自带 `<style>` ⇒ 必须连 `<style>` 一起带或用 iframe srcdoc。
- **⚠️ 内容比对断言**：数值被 `<b class="num">` 包裹 ⇒ 比对前须 `re.sub(r"<[^>]+>","",html)` 去标签。

## 宿主 & 测试踩坑
- **⚠️ `CommandFilter` 的 `str` 参数只取第一个 token**（`/回收 灵草 5` → args 只有 `"灵草"`）⇒ 凡「名称+数量」指令**必须**用 `handlers/utils.py::parse_counted_args(event, args, [CMD], default)` 从 `event.get_message_str()` 重解析。
- **测试统一放 `/tmp/xx_test/`**（仓库无 tests/），解释器必须用托管 venv `.../python/envs/default/bin/python`（裸 python3 缺 aiosqlite）。
- **exit 137（SIGTERM）**：aiosqlite 连接未关闭（断言异常中断 `run()` 致收尾不执行）⇒ **一律把 `run()` 包进 `try/finally`**。⚠️ `test_drop_item_existence.py` 用相对路径找 `config/` ⇒ 必须在项目目录下运行。
- **导入项目模块需先 mock `astrbot`**：预注册 `astrbot.api`(`logger`/`AstrBotConfig`)、`api.star`(`Star` 需真类可作基类)、`api.event`(`filter`)、`api.message_components`(`Image`)、**`api.all`**；⚠️ 有 `from astrbot.api.all import *` ⇒ 桩模块**必须提供 `__all__`**（否则 `'_Perm' object is not iterable`）。装饰器桩须**返回原函数**（否则类方法被替换）。aiosqlite 三坑：内存库须 `row_factory=aiosqlite.Row`；结束必须 `await conn.close()`；INTEGER 0/1 读回是 int 不是 bool。
- ⚠️ **本会话 `/tmp/xx_test/` 下的 `test_*.py` 曾被清空**（只留非测试脚本）⇒ v3.3.11 的回归测试重写为 `test_render_local.py`（18/0，含导入 main.py 的 smoke 校验）。
- ⚠️ **bash `grep "a\|b"` 在本环境失效**（返回空，不是文件没内容）⇒ 用 `grep -E "a|b"` 或专用 Grep 工具。

## 工程约定
- 按 AGENTS.md：功能更新/BUG 修复需同步 README.md、metadata.yaml 版本号、misc_handler.py 修仙帮助；新增玩家可见指令需登记 README 指令表与帮助。
- 物品/丹药两套数据源：**`config/items.json` 是唯一权威登记处**（未登记=幽灵物品）；`PillManager.get_pill_by_name` 须兜底查 `items_data`（33 味旧系统丹药只在该表）。**丹药在 `pills_inventory`、普通物品在 `storage_ring_items`**，赠予/接收/返还三链路按「是否丹药」分流。
