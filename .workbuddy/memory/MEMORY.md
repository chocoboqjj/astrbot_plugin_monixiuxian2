# 项目长期记忆

## 项目方向
- 本插件为 AstrBot 的文字修仙（放置类 RPG）插件，v3.1.7，AGPL-3.0，作者 xiaojuwa。
- 最新决策（2026-10-22）：计划**接入 QQ 官方机器人（qq_official 适配器），放弃 OneBot（aiocqhttp）**。
- 影响：玩家 user_id / 群 group_id 将从数字 QQ 号变为 openid 字符串，旧库数据不互通（玩家需重新「我要修仙」）。

## 平台迁移需修复的兼容性断点
- CQ 码硬编码：`handlers/dual_cultivation_handlers.py:54`、`handlers/impart_pk_handlers.py:88` 用 `\[CQ:at,qq=(\d+)\]` 解析 @，QQ 官方下失效。**已于 v3.1.4 修复**（统一走 `handlers/utils.py::extract_target_id`）。
- ID 数字假设：`sect_handlers.py`、`storage_ring_handler.py`、`combat_handlers.py` 等多处 `isdigit()` / `re.search(r'(\d{5,12})')` 兜底对 openid 失效。**已于 v3.1.4 修复**。
- At 组件属性：统一补充 `.user_id` 到属性列表（combat_handlers 已含 qq/target/uin/user_id，可作范本）。
- 白名单/管理员配置（WHITELIST_GROUPS/BOSS_ADMINS/SHOP_MANAGERS）需重填为 openid。

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

## 约定
- 按 AGENTS.md：功能更新/BUG修复需同步更新 README.md、metadata.yaml 版本号、misc_handler.py 的修仙帮助。
- 新增玩家可见指令需同时登记到 README 指令表与 misc_handler.py 的帮助文本。

