# 宗门丹房丹药修复设计说明（ENG-SECTPILL-01）

> 状态：已实现 + 已验证（冒烟 56/56 通过）
> 影响面：`config/utility_pills.json`、`core/pill_manager.py`、`managers/sect_manager.py`
> 未提交（用户未授权 git commit）

---

## 1. 根因

「聚气丹无法使用」是**幽灵物品**问题（本项目 v3.2.0 修过同类问题）：

```
managers/sect_manager.py:683  claim_sect_elixir()
    inventory[pill] = inventory.get(pill, 0) + 1     # 直接写背包，无存在性校验
        ↓
config/*.json 中无「聚气丹 / 回元丹 / 破障丹」任何定义
        ↓
core/pill_manager.py:141  use_pill()
    pill_data = self.get_pill_by_name(pill_name)  →  None
        ↓
return False, "丹药【聚气丹】配置不存在！"          # 玩家：领到了但用不了
```

诊断确认：`pills.json`(26) / `exp_pills.json`(30) / `utility_pills.json`(143→148) / `alchemy_recipes.json`(5) 中，
**聚气丹、回元丹、破障丹均无定义**；`凝神丹`(util_028, 门槛 10)、`洗髓丹`(util_115, 门槛 25) 有定义但门槛过高。

### 附带的第二个幽灵问题（本次新发现，见 §6）

`洗髓丹`(util_115) 的关键字段 `base_attribute_limit_increase: 0.05` **在全部 .py 中无任何消费点**
（grep 全库仅命中配置文件本身）。因此它走 `_use_permanent_pill` 时 `gains_applied` 恒为空，
服用会返回 `False` —— 即「洗髓丹」本身就是一枚摆设丹药。

---

## 2. A 步：字段消费核实结论

核实对象：`core/pill_manager.py`（`use_pill` 分发 + `_use_*_pill`）、
`core/breakthrough_manager.py`、`handlers/breakthrough_handler.py`、`core/cultivation_manager.py`。

### 2.1 分发规则（`use_pill`，pill_manager.py:174-193）

| 判定顺序 | 条件 | 走向 |
|---|---|---|
| 1 | `subtype == "exp"` | `_use_exp_pill`（读 `exp_gain`） |
| 2 | `subtype == "resurrection"` | `_use_resurrection_pill` |
| 3 | `effect_type == "temporary"` | `_use_temporary_pill` |
| 4 | `effect_type == "permanent"` | `_use_permanent_pill` |
| 5 | `effect_type == "instant"` | `_use_instant_pill` |

> 注意：`subtype` 只在 `exp` / `resurrection` 两个值上参与分发；其余丹药**靠 `effect_type` 分发**。
> 破障丹的 `subtype="breakthrough_boost"` 不参与分发，但在**生效阶段**被消费（见下行）。

### 2.2 effect 字段消费核实表

| 字段 | 是否被代码消费 | 要求 `effect_type` | 要求 `subtype` | 消费点 |
|---|---|---|---|---|
| `cultivation_multiplier` | ✅ 是 | `temporary` | 任意（用 `cultivation_boost`） | `_use_temporary_pill` → effect 列表 → `calculate_pill_attribute_effects()["cultivation_speed"]` → `cultivation_manager.calculate_cultivation_exp()` |
| `duration_minutes` | ✅ 是 | `temporary` | 任意 | `_use_temporary_pill`（缺省 60） |
| `breakthrough_bonus` | ✅ 是 | `temporary` | **必须是 `breakthrough_boost` 或 `breakthrough_debuff`** | `get_breakthrough_modifiers()`（pill_manager.py:692）只累加这两种 subtype |
| `max_spiritual_qi_gain` | ✅ 是（**绝对值**，非百分比） | `permanent` | 任意 | `_use_permanent_pill` 的 `attr_mapping` |
| `max_blood_qi_gain` | ✅ 是（**绝对值**，非百分比） | `permanent` | 任意 | 同上 |
| `mental_power_gain` | ✅ 是（绝对值） | `permanent` | 任意 | 同上 |
| `physical/magic_damage_gain`、`*_defense_gain`、`lifespan_gain` | ✅ 是（绝对值） | `permanent` | 任意 | 同上 |
| `death_protection_multiplier` | ✅ 是 | `permanent` | 任意 | `_use_permanent_pill` 独立分支 |
| `spiritual_qi_restore` / `blood_qi_restore` / `blocks_next_debuff` / `resets_permanent_pills` | ✅ 是 | `instant` | 任意 | `_use_instant_pill` |
| `*_regen_per_minute` / `*_cost_per_minute` | ✅ 是 | `temporary` | 任意 | `_apply_periodic_effects` |
| **`base_attribute_limit_increase`** | ❌ **否（无任何消费点）** | — | — | 全库 grep 仅命中 `utility_pills.json`（洗髓丹/易筋丹） |
| **会心率 / crit 相关任意字段** | ❌ **否（不存在该字段）** | — | — | 会心率唯一来源是传承 `impart_know_per`（player_handler:141 / ranking_manager:124 / boss_manager:192） |

### 2.3 关于 `breakthrough_handler.py:62` 的 `breakthrough_bonus`

该处读的是 **`config_manager.pills_data`**（破境丹，需 `subtype == "breakthrough"` + `target_level_index` 匹配），
与功能丹的临时加成是**两条独立路径**：

- 路径 A（破境丹）：`突破 <丹名>` → `pills_data` 里取 `breakthrough_bonus`，一次性加成。
- 路径 B（功能丹/破障丹）：`服用丹药 破障丹` → 写入 `player.active_pill_effects`
  → `get_breakthrough_modifiers()` 累加 `temp_bonus` → 传入 `execute_breakthrough(temp_bonus=...)`
  → `calculate_breakthrough_success_rate()` 里 `base + temp_bonus`。

**破障丹走路径 B，能真正生效**（已验证：12.00% → 17.00%）。
前提是 `effect_type: "temporary"` **且** `subtype: "breakthrough_boost"`（否则 `get_breakthrough_modifiers` 不认）。
突破后由 `consume_breakthrough_effects()` 统一清除。

### 2.4 商店排除机制核实（重要陷阱）

| 路径 | 是否校验 `shop_weight` | 结论 |
|---|---|---|
| `ShopManager._get_all_shop_items()` | ✅ `shop_weight > 0 and price > 0` | 缺 `shop_weight` → 不上架 |
| `ShopManager.generate_pavilion_items()` | ❌ 且 `i.get('data',{}).get('shop_weight', 100)` —— **缺失时默认权重 100** | **缺失 `shop_weight` 反而会以权重 100 进丹阁/百宝阁** |
| `find_item_by_name()` | ❌ 只校验 `price > 0` | 可被「物品信息」查到，但购买需 `shop_items` 表有库存 → 买不到 |

→ **结论：必须显式写 `"shop_weight": 0`，不能依赖「缺失即专属」的约定。** 本次 5 味丹药均已显式设为 0。

---

## 3. 新增丹药数值表

5 味全部为**宗门丹房专属**（`shop_weight: 0`，商店/丹阁/百宝阁均不上架），
仅通过 `claim_sect_elixir` 发放；`price` 仅用于展示与 `/回收`（50% 变现）。

| id | 名称 | 丹房 | 品阶 | 门槛境界 | price | subtype | effect_type | 关键效果字段 | 文案（SECT_ELIXIR_EFFECTS） |
|---|---|---|---|---|---|---|---|---|---|
| util_144 | 聚气丹 | 1 阶 | 灵品 | 0（炼气期一层） | 400 | `cultivation_boost` | `temporary` | `duration_minutes: 60`<br>`cultivation_multiplier: 0.1` | 闭关修炼速度 +10% |
| util_145 | 回元丹 | 2 阶 | 地品 | 1（炼气期二层） | 1200 | `permanent_attribute` | `permanent` | `max_spiritual_qi_gain_percent: 0.05`<br>`max_blood_qi_gain_percent: 0.05` | 气血与灵气上限 +5% |
| util_147 | 宗门凝神丹 | 3 阶 | 天品 | 1 | 2000 | `permanent_attribute` | `permanent` | `mental_power_gain_percent: 0.05` | 精神力 +5%（原「会心率+3%」见 §6 BLOCKED） |
| util_146 | 破障丹 | 4 阶 | 皇品 | 0 | 4000 | `breakthrough_boost` | `temporary` | `duration_minutes: 1440`<br>`breakthrough_bonus: 0.05` | 突破成功率 +5% |
| util_148 | 宗门洗髓丹 | 5 阶 | 帝品 | 1 | 10000 | `permanent_attribute` | `permanent` | 8 个 `*_gain_percent: 0.02`<br>（物伤/法伤/物防/法防/精神力/寿命/灵气上限/气血上限） | 全部属性 +2% |

**定价逻辑**：与同赛道商品对齐（聚气丹 ≈ 修炼加速丹 200 的弱化日常版；回元丹 ≈ 灵气/气血容量丹 600 的百分比版；
破障丹 ≈ 幸运丹 50000 的 1/2 效果弱化版），并按丹房阶数单调递增，回收变现 5 阶全领约 8,800 灵石/日。

**新增的 `_percent` 机制**（`core/pill_manager.py`）：
`PillManager.PERCENT_GAIN_KEYS` + `_resolve_percentage_gains()` 把百分比按**玩家当前属性**折算成固定数值，
**折算后仍走既有的「每境界永久增益 ≤ 基础属性 30%」上限**，因此不会因每日领取而无限叠加。

---

## 4. 境界门槛方案：权衡与结论

### 4.1 候选方案

| 方案 | 做法 | 影响面 | 评价 |
|---|---|---|---|
| i 宗门专属低门槛变体 | 新增「宗门凝神丹」「宗门洗髓丹」，同步改 `SECT_ELIXIR_ROOMS` / `SECT_ELIXIR_EFFECTS` 文案 | **仅宗门链路**；全局 `凝神丹`(util_028)、`洗髓丹`(util_115) 完全不动 | ✅ 选此方案 |
| ii 直接下调全局门槛 | `凝神丹` 10→0、`洗髓丹` 25→0 | ❌ 全局：商店（`shop_weight` 200/10）会出现练气期玩家直购「精神力+800」永久丹、`洗髓丹`；早期经济与战力体系被击穿 | 否决 |
| iii 代码层给宗门丹药开豁免 | `use_pill` 里按来源绕过境界校验 | ❌ 需给丹药打来源标记（改数据结构），且污染通用丹药逻辑 | 否决 |

### 4.2 结论：采用方案 i

- 全局 `凝神丹` / `洗髓丹` 的 `required_level_index`、`price`、`shop_weight` **一律未改**，商店与经济零影响。
- 新增的宗门变体门槛设为 **1（炼气期二层）**：之所以不是 0，是因为境界 0 的
  `breakthrough_*_gain` 全为 0 → 每境界 30% 上限额度为 0 → 永久丹药会被判「已达上限」而用不了
  （这是既有行为，非本次引入）。门槛 1 只需 500 修为即可达到，等于「任何弟子领到就能用」。
- `聚气丹` / `破障丹` 是临时效果丹药，不受 30% 上限约束，门槛直接设 0。

---

## 5. 防御性校验（`claim_sect_elixir`）

`managers/sect_manager.py`：

1. `SectManager.__init__` 保留 `config_manager` 引用。
2. 新增 `_is_pill_defined(pill_name)`：只认 `PillManager.get_pill_by_name` 会查的三个配置源
   （`pills_data` / `exp_pills_data` / `utility_pills_data`）。
3. `claim_sect_elixir()` 发放前逐个校验：
   - 未定义 → **跳过 + `logger.warning`**（含 user_id / 宗门 / 丹房等级），不写背包；
   - 部分缺失 → 正常发放其余丹药，消息尾部追加「⚠️ 以下丹药配置缺失已跳过：…」；
   - 全部缺失 → 返回 `False` 且**不置位 `sect_elixir_get`**，玩家修复配置后可重新领取。

这保证今后任何「丹房清单写了但配置里没有」的丹药都不会再变成玩家背包里的死物。

---

## 6. BLOCKED 项 / 已知限制 / 风险

### 🔴 BLOCKED-1：凝神丹「会心率 +3%」无法落地

- **原因**：会心率当前**唯一**来源是传承系统 `impart_know_per`，丹药系统没有任何 crit 字段，
  `Player` 也没有可持久化的 crit 字段。
- **本次处理**：不做硬配。3 阶丹房改用宗门变体「宗门凝神丹」= 精神力 +5%
  （与既有 `凝神丹` util_028 同属「精神力」赛道，符合「凝神」语义），
  并把 `SECT_ELIXIR_EFFECTS` 文案由「会心率 +3%」改为「精神力 +5%」。
  **这是对玩家承诺文案的变更，需主理人/策划确认。**
- **建议后续（若坚持要会心率）**：新增 `crit_rate_gain`（永久，存 `permanent_pill_gains[level_X]["crit_rate"]`，
  无需 DB 迁移）+ `PillManager.get_crit_rate_bonus()`，并在
  `player_handler.py:141`、`ranking_manager.py:124`、`boss_manager.py:192` 三处统一加上丹药会心率。
  影响战斗（会心 1.5 倍伤害）与战力公式一致性，建议单独立项并做平衡评估。

### 🟠 BLOCKED-2：全局「洗髓丹」(util_115) 仍是摆设丹药

- 其 `base_attribute_limit_increase: 0.05` 无任何消费点 → 服用必然返回 `False`（页面上提示「已达上限」，实为未实现）。
- **本次未改**（改它会动到 500000 灵石、道品的全局商品，超出本次授权范围）。
- 建议后续二选一：① 实现 `base_attribute_limit_increase`（把每境界上限从 30% 抬到 35%）；
  ② 改用本次新增的 `*_gain_percent` 机制改成真正的「全部属性 +X%」。

### 🟡 已知限制-1：百分比增益对「跨系能量」被境界表缺字段压制

- `config/level_config.json`（灵修）**没有** `breakthrough_blood_qi_gain`；
  `config/body_level_config.json`（体修）**没有** `breakthrough_spiritual_qi_gain`。
  `_get_base_attributes_for_level()` 回退默认值 100 → 该系「另一路能量」的每境界永久增益上限只有 **30 点**。
- 表现：灵修吃回元丹，灵气上限 +5% 正常，气血上限只能 +30（体修反之亦然）。
- 建议后续：补齐两张境界表的缺失字段（属全局数值调整，需平衡评估）。

### 🟡 已知限制-2：低境界弟子吃永久丹药增益很小

每境界 30% 上限以「本境界突破增益」为基数，低境界基数只有个位数，
因此 1 阶弟子吃宗门洗髓丹可能只拿到「寿命 +15、其余受限」。
这是**既有永久丹药的普遍行为**（如 `灵气容量丹 +500` 在 3 阶实际只 +4），本次未改。
顺带修好的一点：剩余额度不足 1 点时不再展示「物伤 +0」，改为进入「受限提示」。

### 🟡 风险-1：宗门丹药回收变现是每日金币水龙头

5 阶丹房每日 5 颗，全部 `/回收`（50%）约 8,800 灵石/日。目前丹房 5 阶需 250,000 灵石 + 8,000 资材，
回收回本约 28 天，看着可控；若认为偏高，可下调 `price` 或给宗门丹药加「不可回收」标记（当前无此标记，需新增）。

### 🔴 风险-2（新发现，非本次引入）：`utility_pills.json` 存在重名条目

`util_128 混元血容丹`（皇品 / 15000）与 `util_142 混元血容丹`（混元先天 / 2000000）重名。
`ConfigManager._load_items_data` 以 name 为 key 建字典 → **后者静默覆盖前者**，
导致商店/回收实际用的是 2,000,000 的价格（回收可得 1,000,000/颗）。
建议尽快复查并改名（P1，本次未动）。

---

## 7. 验证结果

### 7.1 冒烟测试（新增）

- 脚本：`/tmp/penalty_test/test_sect_elixir_pills.py`
- 输出：`/tmp/penalty_test/sect_elixir_out.txt`
- 环境：`/Users/adelenaumann/.workbuddy/binaries/python/envs/default/bin/python`
- 结果：**56/56 全部通过 ✅**

关键断言（都是「效果真的生效」，不是只看成功文案）：

| 项 | 断言 | 实测 |
|---|---|---|
| 聚气丹 | `cultivation_multiplier=0.1` 进生效列表；`cultivation_speed` 倍率 = 1.10；闭关 60 分钟修为真的 +10% | 6000 → 6600 ✅ |
| 破障丹 | `get_breakthrough_modifiers().temp_bonus = 0.05`；突破成功率真的 +5pp | 12.00% → 17.00% ✅ |
| 回元丹（灵修） | 最大灵气 50000 → 52500（+5%） | ✅ |
| 回元丹（体修） | 最大气血 40000 → 42000（+5%） | ✅ |
| 宗门凝神丹 | 精神力 50000 → 52500（+5%） | ✅ |
| 宗门洗髓丹 | 物伤/法伤/物防/法防/精神力/灵气上限各 +2%，体修气血上限 +2% | ✅ |
| 商店排除 | `get_all_shop_items` / `generate_pavilion_items` 均不出现 5 味新丹药 | ✅ |
| 5 阶丹房领取 | 5 味全部入背包，且每味都能服用成功 | ✅ |
| 低境界弟子（level_index=1） | 5 味全部领取成功且全部服用成功 | ✅ |
| 防御：部分缺失 | 发聚气丹、跳过「幽灵丹」、消息提示已跳过 | ✅ |
| 防御：全部缺失 | 拒绝发放、不置位每日标记、给出提示 | ✅ |
| 文案一致性 | 丹房清单每味都有文案且都在丹药系统有定义 | ✅ |

### 7.2 既有回归（全部通过）

| 脚本 | 结果 |
|---|---|
| `test_sect_building.py` | 15/15 ✅（已同步更新其 FakeConfigManager 载入真实 utility_pills，否则会被新的防御校验拦下） |
| `test_penalty.py` | 17/17 ✅ |
| `test_recycle_alchemy.py` | 16/16 ✅ |
| `test_shop_config.py` | 9/9 ✅ |
| `test_fresh_install.py` | ✅ |
| `test_init_and_blessed.py` | 11/11 ✅ |
| `test_parallel_activity.py` | 22/22 ✅ |
| `test_lost_update_fix.py` | 44/44 ✅ |

---

## 8. 改动文件清单

| 文件 | 改动 | 是否本次授权范围 |
|---|---|---|
| `config/utility_pills.json` | 新增 5 条（util_144~util_148） | ✅ 授权 |
| `managers/sect_manager.py` | 丹房清单/文案改宗门变体；新增 `_is_pill_defined` + 发放前校验 | ✅ 授权 |
| `core/pill_manager.py` | 新增 `PERCENT_GAIN_KEYS` + `_resolve_percentage_gains()`；`_use_permanent_pill` 消费折算结果；额度不足 1 点不再展示 +0 | ⚠️ 未列出但**必要**：回元丹「+5%」与洗髓丹「+2%」在既有代码里只有绝对值增益，不补这条就只能写假数值 |
| `docs/design/sect_elixir_pills.md` | 本文档（新建目录） | ✅ 交付物 |
| `/tmp/penalty_test/test_sect_elixir_pills.py`（新增）、`test_sect_building.py`（同步修正 mock） | 测试脚手架 | 非仓库文件 |

---

## 9. ENG-SECTPILL-02 · 质量门阻塞项收尾（v3.2.3）

设计评审（CONCERNS，BLOCKER-1）与 QA（CONCERNS，BUG-1）判定后，用户拍板三项决策，本轮落地。

### 9.1 BLOCKER-1：破障丹可无限叠加 → 已修复

**问题**：`get_breakthrough_modifiers()` 对 `subtype=breakthrough_boost` 无上限累加，`calculate_breakthrough_success_rate()` 仅有 `min(...,1.0)` 截断（`max_success_rate` 只对破境丹路径生效）。破障丹门槛 0、每日免费领、持续 1440 分钟 ⇒ 24h 内叠 N 颗 = +5pp×N，单日上限 20 颗可达 +95pp：渡劫期 1%→96%、混元期 0.01%→95%。

**修法（用户选：加单次上限）**：
- `config/utility_pills.json` util_146 新增 `"temp_bonus_cap": 0.05`
- `core/pill_manager.py::_use_temporary_pill` 的 `effect_keys` 增加 `temp_bonus_cap`，使 cap 随效果记录持久化
- `core/pill_manager.py::get_breakthrough_modifiers` 改为双桶累加：带 cap 的增益单独累计后 `min(capped_bonus, capped_cap)` 夹紧；不带 cap 的走原逻辑

**零影响保证**：幸运丹(util_112, +0.1)、天命幸运丹(util_113, +0.2)、虚弱丹(debuff) 均无 `temp_bonus_cap` ⇒ 完全走原累加路径，行为逐位不变。

### 9.2 BUG-1：境界 0 弟子领到 3 味永久丹却用不了 → 已修复

**问题**：`join_sect` 无境界门槛，但回元丹/宗门凝神丹/宗门洗髓丹 `required_level_index=1`，境界 0 弟子领到手判「境界不足」。这正是本次要根除的「领了用不了」问题类的残留。

**修法（用户选：本次修）**：
- `managers/sect_manager.py` 新增 `_get_pill_level_requirement()`，与 `PillManager.use_pill` 同源读取三张丹药配置表的 `required_level_index`
- `claim_sect_elixir()` 在既有「配置存在性校验」之后追加**境界过滤**：不足的不发放
- 分三种情况给不同回执：
  - 部分发放 → 正常发放 + 列出境界不足的丹药
  - **全部因境界不足** → 拒绝发放且**不置位每日标记**（弟子升境后仍可领），背包不污染
  - 全部因配置缺失 → 沿用原有回执
- **未下调门槛**：设计侧已论证境界 0 的各项 `breakthrough_*_gain` 为 0 ⇒ 每境界 30% 配额为 0，门槛设 0 会让永久丹被判「已达上限」而无效，等于换个形式复刻原 BUG

### 9.3 文案变更签字

`SECT_ELIXIR_EFFECTS` 的「凝神丹 = 会心率 +3%」→「宗门凝神丹 = 精神力 +5%」，已在 `sect_manager.py:36-47` 加注释说明原因，用户已签字。config 与文案效果要素一致（精神力 / +5%）。

### 9.4 README 同步

README 第 132 / 502 行「聚气丹 → 洗髓丹」→「聚气丹 → 宗门洗髓丹」，避免把玩家引向 500,000 灵石且服用必失败的全局摆设丹药 util_115。

### 9.5 验证

| 测试 | 结果 |
|---|---|
| `test_sect_elixir_cap_level.py`（本轮新增，26 项） | 26/26 ✅ |
| `test_sect_elixir_pills.py`（工程侧，断言修正 1 处） | 58/58 ✅ |
| `qa_sect_elixir_verify.py`（QA 独立） | 47/54 → **48/54**（BUG-1 两项转绿） |
| `qa_sect_elixir_nc.py` 商店负向对照 | PASS（断言非空转） |
| 既有回归 5 套 | lost_update 44/44、recycle 16/16、bounty 17/17、i18n 29/29、sect_building 15/15 全绿 |

破障丹上限实测：连服 20 颗 → `temp_bonus = 0.05`；100 颗极端 → 仍 0.05；幸运丹×3+天命×2 = 0.7（原行为）；混合破障×10+幸运×1 = 0.15；虚弱丹 -0.2 不受影响；顺序不敏感。

### 9.6 仍开放的已知限制（已备案，未在本次授权范围）

| 级别 | 问题 | 状态 |
|---|---|---|
| P2 | 回元丹/洗髓丹的跨系能量（灵修气血、体修灵气）实得 +30，因境界表缺 `breakthrough_blood_qi_gain` / `breakthrough_spiritual_qi_gain` | 待立项 |
| P3 | 洗髓丹 8 项属性仅 6/8（灵修）、5/8（体修）达标，体修法伤 +0 | 待立项 |
| P3 | `_weighted_random_choice` 抽样数 ≥ 候选池时不看权重 ⇒ `shop_weight=0` 失效（仅当 `PAVILION_PILL_COUNT ≥ 203` 触发） | 待立项 |
| P1 | `util_128` / `util_142` 混元血容丹重名，200 万静默覆盖 1.5 万 | 已单独立项 |
| P3 | `test_recycle_alchemy.py` 炼丹 `random.randint` 未固定种子，约 8% flaky | 已单独立项 |
