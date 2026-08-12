# 设计文档

## 文档导航

- 现状架构：模块地图、数据模型、漫游流程、夜间复盘、分享决策、人格缓存、调度、WebUI 与 API、LLM 工具、硬边界。
- 方向与分层：实体与维度（L2）、意外波动（未排期）、生活节奏与频率（L1 peek）、LLM 自主行动排期（L1.5）、统一记忆库（L2）、内隐思考层与人格中心态（未排期）、联想召回与发散语素（未排期）、可被看见（L1/L1.5/L2 分档）。
- 交叉约束：硬依赖与生态兼容见 `docs/requirements.md` 与 design.md 统一记忆库小节。
- 功能分层开发清单：`docs/features.md`，每项功能的状态/依赖/模块/配置/验收以该文档为准。

## 定位

Your Own Life 是一个观察者模式的 AstrBot 插件：Bot 不注册账号、不主动发帖，按定时任务漫游国际互联网，用 LLM 把所见沉淀为摘要、观点、情绪、兴趣演化与分享决策，形成主人专属的生活档案。v1 只面向 owner，通过聊天命令和 Dashboard WebUI 查看，不进入群聊主动表达。

### 北极星目标

从六个维度实现拟人化的 bot 生命活动与跨平台社交交互：

- 行为层（behavior）：定时漫游、peek、复盘、分享、休息等可观察行动；系统管节奏，LLM 管决策（现状 L0，自主排期见 L1.5 方向）。
- 思考层（thinking）：对所见即时形成观点、情绪与推理（现状短记/观点/情绪；方向 `thoughts` 思考事件）。
- 思想层（belief）：稳定的价值、自我叙事与立场，即 center state 与人格演化可控性（方向）。
- 发散思维与联想（association）：分层 cue、多路召回、多轮联想与灵感抽屉（方向）。
- 线性生命链（life chain）：append-only 事件流，观察/表达/思考/更改/召回/回滚全部归位，人格经历严格线性（L1.5-01 已落地 v0.3.8 + 单写者约束）。
- 记忆的结构与检索（memory）：统一记忆库、实体关系、多尺度金字塔、模糊/具象化与既视感（方向）。

最终形态：同一人格在多个平台拥有一致的生活档案与社交表达，跨平台可被看见、可分享、可被召回；v1 只做 owner 侧档案，群聊主动/被动表达与生命链整体处理为后续方向。

本文档描述架构与数据模型（含未实现方向）；开发时按 `docs/features.md` 的功能分层推进。

## 模块地图

- `main.py`：`LifeStar` 入口，注册命令、调度器、WebUI API 与 LLM 工具，负责 owner 权限校验。
- `life/config.py`：类型化配置 `LifeConfig`，兼容 `_conf_schema.json`。
- `life/db.py`：SQLite 持久层，含 v0.1 自动迁移。
- `life/fetchers.py`：Hacker News Algolia、GitHub 公开搜索、Reddit 公开 JSON、RSS/Atom，可选 Tavily。
- `life/interests.py`：兴趣权重衰减、选题、更新。
- `life/llm.py`：`chat_json` 封装，负责从 AstrBot Provider 取 LLM 并解析 JSON。
- `life/persona.py`：按 persona 拉取 `system_prompt` 并缓存到 SQLite。
- `life/prompts.py`：漫游挑选、日记、分享等生活任务 prompt 的构建与 JSON schema 校验。
- `life/esm_adapter.py`：ESM 能力探测与精力/信号适配，缺失时静默降级。
- `life/browser.py`：`LifeService`，漫游与夜间复盘的核心编排。
- `life/scheduler.py`：每 persona 独立槽位、确定性时间抖动、睡眠窗口。
- `life/share.py`：`ShareGate`，分享决策与频率/去重/精力门槛。
- `life/webui.py`：通过 `register_web_api` 注册 owner 数据接口（引擎不可用时回退 `register_web_routes`）。
- `life/life_tool.py`：`query_life_memory` FunctionTool，让 LLM 查询当前 persona 自己的档案。

## 数据模型

- `browse_sessions`：一次漫游会话的状态、触发方式、精力/情绪、短记数。
- `notes`：见闻短记（来源/链接/标题/摘要/观点/情绪/兴趣/分类/标签/分享决策与状态）。
- `diary_entries`：每日第一人称日记，按 `(persona_id, date)` 唯一。
- `interests`：兴趣权重、最近出现时间、出现次数。
- `state_snapshots`：情绪/精力/好奇心轨迹。
- `seen_items`：按 URL 哈希去重缓存。
- `share_log`：分享尝试日志。
- `persona_prompts`：人格 prompt 缓存与错误状态。
- `daily_usage`：每日 LLM 调用/token 与精力消耗用量（`llm_calls` / `tokens` / `energy_used`）。
- `change_log`：写操作变更账本（软删除/恢复等，配合回收站）。
- `injection_log`：疑似提示词注入审计日志。
- `life_leases`：同人格任务租约（多实例单写者，v1 本地兜底）。
- `event_chain`：append-only 事件流，观察/表达/思考/更改/召回/回滚归位，支持幂等追加与只读重放。
- `life_plans`：每日排期板运行时视图，任务带状态/原因/预算用量与 `fixed` 分层。
- 未来新增表：`action_log`、`wishlist`、`center_state`、`thoughts`、`entities / entity_mentions / entity_links` 等，随对应功能落地（见 `docs/features.md` 与本文档方向章节）。

## 实体与维度模型（方向，已排期 L2）

关系感功能不采用“实体 + 平台字段”的平铺模型，而是把信息来源当作一个维度，按维度分层，并允许不同维度类型的实体互相关联。

### 分层

- 来源层：`platform / url / feed`，事实层，由系统从抓取结果写入，LLM 不猜平台。
- 语义层：`person / project / community / topic`，由 LLM 识别并带 confidence。
- 关系层：有类型的边，使用封闭关系词表。
- 印象层（后置）：实体累积的情绪/关系/印象摘要。

### 表结构草案

```text
entities(id, persona_id, dimension, entity_id, name,
         canonical_url, first_seen_at, last_seen_at, seen_count)

entity_mentions(id, persona_id, note_id, entity_id,
                role, confidence, fetched_at)

entity_links(id, persona_id, src_entity_id, relation,
             dst_entity_id, weight, first_seen_at, last_seen_at, seen_count)
```

`dimension` 取值为 `platform / url / person / project / community / topic`；同维度内以 `(dimension, entity_id)` 唯一，例如 GitHub 项目 = `(project, "tokio-rs/tokio")`。

### 关联规则

- 关系词表：`appears_on / author_of / member_of / related_to / same_as`。
- 一条短记里共同出现的实体通过 `entity_mentions` 记录，短记即一次“共同在场”的超边；共现可自动累加弱关联权重。
- “在哪看见”表示为语义实体到平台节点的边，例如 `project(tokio-rs/tokio) --appears_on--> platform(hacker-news)`。
- `platform/url` 节点只能由系统写入；`same_as` 只作为身份合并候选，owner 在 WebUI 确认后才生效。
- 每条边保留 `weight / seen_count / first_seen_at / last_seen_at`，为后续“记忆温度/遗忘曲线”预留。

### 查询语义

- “我在哪见过 X”= 从实体出发走 `appears_on` 聚合平台。
- “某个主题最近关联了谁”= 走 `related_to` 反向聚合。
- “跨平台印象一致性”= 同一实体在不同 `appears_on` 边上的时间序列对比。

落地顺序（L2 内）：随统一记忆库先实现 `entities(dimension)` + `entity_links`，跑通 `platform` 维度与 `appears_on`；语义维度和共现关系第二版再加。

## 意外波动模型（方向，未实现）

“意外”不采用固定概率抽奖，而是维护一个会自然涨落的 `serendipity_level`，由均值回归、饥饿度、状态调制与强度分级共同驱动。

```text
serendipity = clamp(base + hunger*gain - recent_stimulus*decay + noise, 0, 1)
hunger += 1（每过一天没意外就累积）
hunger = 0（触发一次意外后清空）
```

- `base`：persona 默认好奇水平。
- `hunger`：意外饥饿度，越久没遇到意外，下一次触发概率越高。
- `recent_stimulus`：最近刚探索过陌生话题时短期回落，避免连续跳脱。
- `noise`：小幅度随机游走，让曲线有呼吸感。

### 状态调制

- 精力高 → 倾向升高且可大动作；精力低 → 概率下降，触发时自动降级。
- 兴趣熵高（连续多天同一主题）→ 倾向上升；刚经历过新话题 → 回落。
- ESM 情绪好奇时更易接受意外；疲惫/烦躁时意外变成轻调味。
- 午后、深夜、周末等时段更容易触发；节假日可整体抬升。

### 强度分级

- `<0.3`：不触发。
- `0.3~0.6`：micro，随机冷知识或把某个选题换成低权重新话题。
- `0.6~0.85`：meso，数字漂流瓶或半天脱离兴趣榜的陌生主题漫游。
- `>0.85`：macro，每月一次的“出走日”，完全自由选题。
- 精力不足时强度自动降一级（如 meso → micro），而非硬触发大探索。

### 反馈闭环

每次意外执行后记录结果：是否引起兴趣变化、是否被写进日记、是否被分享。连续无感跳过则下调 `base`；意外带来新兴趣种子则上调 `base`，让波动成为人格好奇心的演化而非纯随机。

### 与行动排期衔接

`surprise` 可作为 action 进入 LLM 计划，但触发频率由系统的 serendipity 模型决定，LLM 只负责生成“这次意外看什么”。WebUI 展示 `serendipity_level` 曲线与触发记录。

## 漫游流程

1. 调度器或 `/life_now` 触发。
2. `PersonaService` 解析并刷新 persona prompt，失败则跳过该 persona。
3. 精力预算检查：每日 `daily_usage.energy_used` 达到 `energy_budget` 上限时跳过并记录 `energy_budget_exhausted`；未超限再走 ESM 精力 gate，低精力记录 `skipped_energy`。
4. 按兴趣权重选题，默认 20% 概率探索低权重/新话题。
5. 并行抓取候选，按 URL 哈希过滤已见。
6. LLM 挑选 3-5 条并生成结构化 JSON；v0.2.6 起 LLM 失败走预算/重试语义（重试上限 3，耗尽报 error），不再生成确定性 fallback。
7. 写短记、更新兴趣权重、标记已见、调用 ShareGate。
8. 写状态快照与 `browse_sessions` 收尾。

## 夜间复盘

夜间槽位先 `recheck_pending` 补发被 gate 拦下的分享，再汇总当天短记与状态快照，用 LLM 生成第一人称日记 JSON（`diary_text/mood/energy_change/interest_updates`），落 `diary_entries` 并应用兴趣更新与衰减。v0.2.6 起 LLM 失败走重试语义，重试耗尽则该日复盘失败并报 error，不生成伪造日记。

（已实现，v0.3.2）旧事新感：复盘时按 `revisit_probability` 随机选 `revisit_days` 中的一天，把该日短记作为“回看素材”注入 prompt，日记含“后来的我再看这件事”段落；无历史短记时不触发。

（已实现，v0.3.3）随机不出门：定时漫游按 `rest_probability`（默认 0.1）随机跳过并写 `skipped_rest` 快照；手动触发不走该逻辑。

（已实现，v0.3.4）时段模式：漫游按当地时间判定时段，`time_slots` 提供各时段的 topics/tone，以可选块注入选择 prompt；配置缺失时不注入，回退默认语气。

（已实现，v0.3.6）灵感抽屉：`wishlist` 表存放待评估想法，日记可写入 `wishlist_candidates`，复盘后 LLM 评估升级为兴趣种子或丢弃，WebUI 可查看与手动处理。

（已实现，v0.4.4）精力预算：漫游/复盘成功后按 `ENERGY_COST_BROWSE=0.15` / `ENERGY_COST_DIARY=0.2` 经 ESM `consume_energy` 真实扣减并双写 `daily_usage.energy_used`；每日累计达到 `energy_budget`（默认 0 = 无上限）后当天剩余任务跳过并记录 `energy_budget_exhausted`；ESM 缺失时以 `browse_energy_fallback` / `diary_energy_fallback` 快照显式标注本地估算。

## 分享决策

`ShareGate` 按序检查：分享总开关、目标会话白名单、睡眠窗口、精力门槛、每日上限、冷却、24h URL 去重、消息渲染、`Context.send_message` 返回值。成功才写 `shared` 并施加 ESM 信号；被 gate 拦下的保持 pending 状态，夜间或手动补发；配置不合法/禁分享则标记 `dropped`。

## 人格缓存

优先通过 `persona_manager.get_persona(persona_id)` 获取，其次 `get_default_persona_v3` 兜底；按 `persona_cache_hours` 过期刷新，结果缓存进 `persona_prompts`。解析失败会记录错误并跳过当天任务，WebUI 与 `/life_personas refresh` 可手动刷新。

## 调度

默认每天 10:00、15:00 漫游，23:00 复盘；时间按 persona+日期+槽位做确定性抖动（漫游 ±120 分钟、复盘 ±60 分钟）。睡眠窗口默认 00:00-07:00，窗口内定时任务不触发；`_done_keys` 保证同一槽位只执行一次。

（已实现，v0.2.5）时区：新增 `timezone` 配置（默认 `Asia/Shanghai`）；睡眠窗口、槽位日期与“今日”边界一律按 persona 本地时间计算，与部署实例时区解耦，用 `zoneinfo` 转换。

## 预算、重试与崩溃语义（已实现，v0.2.6）

历史 v0.2.4：LLM 失败时使用确定性 fallback（`_fallback_selected` / `_fallback_diary`），不重试、不报 error；该行为已随 v0.2.6 移除。以下为当前语义。

- 预算全部可配置：`daily_llm_call_limit` 与 `daily_token_budget` 默认 `0`（无上限）；达到上限后当天剩余任务跳过并记录 `budget_exhausted`，WebUI 展示用量。多轮联想每轮召回候选上限 5（第 1 轮 5、第 2 轮 3、brainstorm 3-5），`hop_limit` 默认 2（brainstorm 5）。`daily_token_budget` 的计量依赖 provider 是否返回 usage；拿不到 token 用量时只执行调用次数上限。用量落点：`daily_usage` 表（persona_id / date / llm_calls / tokens / energy_used）承载每日计数，WebUI 用量视图读取该表。
- 重试：LLM 调用失败重试上限 `llm_retry_limit` 默认 3，带指数退避；重试耗尽后该任务标记 `failed` 并报 error（WebUI 错误区 + 命令 + 日志），不生成确定性伪造内容。
- 崩溃：每个漫游/复盘 run 采用暂存区（staging）优先，SQLite 写事务只包住最终落库阶段；进程崩溃或异常中断时丢弃该 run 全部未提交数据，不写半成品 note/diary，`browse_sessions` 标记 `failed` 并记录 error；不自动重放，可 `/life_now` 手动重跑。

## 生活节奏与频率（方向，部分已排期 L1：peek/频率模型）

现状：默认每天 2 次正式漫游（10:00/15:00）+ 1 次夜间复盘（23:00）。每次正式漫游落 3-5 条短记，信息量不低，但一天只有两个固定活动点，节奏感偏稀。

### 频率模型

- 正式漫游（browse）：完整抓取、LLM 挑选、写短记，默认 2 次/天（10:00/15:00），是可调次数的高成本动作。
- 轻接触（peek）：只观察热度/标题变化，不写短记，仅更新状态快照；建议每天 2-4 次（如 9:00/13:00/17:00/21:00），不调用 LLM 挑选，成本极低。（已实现 v0.3.5：定时 peek 写 `browse_sessions.kind='peek'` 与 `state_snapshots.activity='peek'`，受 `peek_daily_cap` 限制）。
- 夜间复盘（diary）：23:00 一次，汇总当天并写日记。
- 回看类轻动作（revisit / 旧事新感）：复用已有档案，不产生新抓取，可一天多次。

### 动态调制

- 正式漫游次数由精力、好奇度与 serendipity 调制：高精力/高好奇时 2-3 次，低精力时 1 次甚至只 peek。
- 节假日/周末可默认提高 peek 密度。
- 频率模型与 LLM 自主行动排期衔接：系统管节奏上限，LLM 管今天做什么。

### 成本原则

主要成本是 LLM 调用而非抓取。优先“高频轻 peek + 低频重漫游”，而不是把正式漫游次数无脑提高到 4-5 次。

## LLM 自主行动排期（方向，已排期 L1.5）

原则：LLM 决定“做什么”，系统决定“何时做”。

- 行动清单：LLM 产出封闭词表动作（`browse / revisit / signature / diary / share / rest / surprise / memory_review`）与偏好时间窗（morning/afternoon/evening/night）+ 优先级。
- 排期：调度器把动作映射到系统允许的槽位，精确时刻由系统决定；动作可带前置条件（如 revisit/signature 需要当天有 browse 素材）。
- 反馈闭环：`life_plans` 存当天计划，`action_log` 记录执行结果；昨天的结果进入今天的生活摘要，产生“昨天没出门今天补一次”这类连续性。
- 约束：睡眠窗口、精力 gate、每日行动上限、未知动作拒绝并回退默认固定计划（10:00/15:00 漫游 + 23:00 复盘）。
- 落地顺序：先支持 `browse / rest / signature / revisit` 与 `/life_plan` 查看命令。

## 统一记忆库（方向，已排期 L2）

多平台同人格一致性的关键不是“数据库装在哪”，而是所有平台/插件都读写同一个记忆语义和同一个身份解析层。私有 SQLite 各管一份，实体命名与召回方式不互通，跨平台“同一个它”就无法成立。

### 目标架构

由记忆宿主插件（engram_core，或未来的 life-chain 插件）持有统一逻辑记忆库，对外提供版本化公开 API：

```text
store_event(persona_id, platform, session_id, ts, kind, payload)
add_note(persona_id, note)          / store_diary(...)
upsert_entity(persona_id, entity)   / link_entities(...)
query_memory(persona_id, query)     / search(...)
```

本插件通过 `LifeMemoryAdapter` 读写统一库，本地 SQLite 只保留启动所需缓存与降级能力；适配层负责契约与版本兼容，v2 起为硬依赖，v0.2.4 的“缺失静默降级”只作为过渡行为（v1.1 计划内新契约不再默认降级）。

### 生态兼容约束

kazamisama 插件家族必须整体兼容，但兼容不等于冻结：允许对家族内任一插件做架构级重构、新增共享层或改公开契约，只要先版本化契约、再改适配层，最后整族协调升级；兼容矩阵与升级检查表见 `docs/requirements.md`。

### 多平台同人格机制

- `persona_id` 是全局分区键，所有平台的记忆归到同一个人格。
- 平台信息保留在事件与实体边上（`seen_platform / entity_platform`），即分层维度模型。
- 身份合并通过 `same_as` 链接：不同平台的同一实体默认分开，canonical URL 自动合并或 owner 确认合并。
- LLM 注入时从统一库召回“该实体在其他平台的历史”，实现跨平台一致印象。

### 想法也是记忆

想法作为 `kind=thought` 的记忆事件进入统一库，完整模型见「内隐思考层与人格中心态」。

### 落地路径

- v1.1：本插件继续自持 SQLite，记忆读写保持 `life/db.py` 单一入口，不新增统一库依赖。
- v2：引入 `LifeMemoryAdapter` 并收敛全部记忆读写；统一库为权威，本地库降级为缓存；事件归一化（persona/platform/session/ts/kind/payload）+ 实体身份解析。
- 未来按硬依赖规划：v2 直接切统一库为权威，不等待第二个消费者；允许对 ESM 与记忆宿主做架构级变动（精力消费语义、统一记忆 API、生命链事件流）。

### 多实例并发与同人格锁

- 人格经历应严格线性：事件链是单写者 append-only，一个 persona 同一时刻只经历/决定一件事；租约不是允许并行，而是多实例下保证单写者的物理原语。单实例时由 SQLite 事务 + 内存事件队列承担，不需要租约；执行阶段可重叠（抓取/LLM 调用耗时），但记忆写入与人格决策必须串行化。
- 不同人格 = 不同记忆库（统一库按 `persona_id` 分区），人格之间天然无锁竞争；v1 不做按 persona 分文件的复杂度。
- 同人格多实例：所有实例必须共享同一个 SQLite 文件（同一 `db_path`），槽位唯一键 `(persona_id, slot_key, local_date)` 先写先得；写操作带 `idempotency_key`；本地库用 `BEGIN IMMEDIATE` 短事务 + WAL + `busy_timeout`。文件不共享则租约表互相不可见，互斥失效；共享文件仅适用于共享卷（同一主机或挂载盘），跨主机场景走 v2 统一库租约。
- 租约：同一人格同一任务同一时刻只能有一个执行者。v1 用 `life_leases` 表实现 persona+任务级租约（holder / acquired_at / expires_at，TTL + 续租，过期自动释放）；拿不到租约的实例跳过该槽位并记录 `skipped_duplicate`。
- v2 统一库：记忆宿主提供版本化 `claim_task / renew_task / release_task` 公开 API，本插件只经 `LifeMemoryAdapter` 调用，契约需求见 `docs/requirements.md`。

## 内隐思考层与人格中心态（方向，未实现）

### 三层记忆

- 观察层（external）：发生了什么、看到了什么、谁说了什么，对应 `notes / events`。
- 表达层（expression）：bot 自己说出来/写出来的话，对应 `share_log / diary / 回复`。
- 中心层（center）：未说出口的推理、判断、自我定位、价值倾向、对关系的态度，是人格的稳定“我”。

人格割裂的根源是缺第三层：只有观察和表达，人格会被外界刺激推着走；有了中心层，外部刺激先经过中心再决定“我怎么看、要不要表达”。

### 人格中心态（center state）

中心层包含：核心价值/信念、自我叙事（我是谁）、当前姿态（我现在在乎什么）、关系温度、观点库存（带 confidence、来源、时间）。

### 思考事件与内省

- `thought`：内部推理、自我对话、冲突记录、结论，`visibility=private`，默认不进分享与群聊；与 diary 的区别是 diary 是可展示的自我叙述。
- 内省步骤：每晚从近 N 天 thoughts/notes 提炼 center state 并更新，把这次内省本身也写进记忆，让人格中心持续演化但保持连续。

### schema 草案

```text
center_state(persona_id, version, values_json, self_narrative,
             stance_json, updated_at, source_refs)

thoughts(id, persona_id, kind, content, stimulus_note_id,
         mood, confidence, conflicts_json, visibility, created_at)
```

`thought` 的来源是“触发它的事件 + 内部推理”，不是平台 URL；召回时中心层也可被唤醒，但受 visibility 与注入门槛约束。

### 安全边界

- center state 是 LLM 生成的自我认知，不是事实源；输出时标注“我认为/我记得我这么想”，允许被新思考推翻并保留版本历史。
- 人格一致性检查以 center state 为锚：注入外部记忆前先与当前中心态对比，冲突时标为“旧立场”而非静默覆盖。

### 人格演化可控性

提示词版本化是工程版本（prompt 模板、`_conf_schema`、缓存版本），用于排障与防风格漂移，不等于人格自演化。人格自演化（center state 更新）按可控性分层：

- 不可变内核：owner 设置的核心价值、底线、身份事实，任何内省不得改写。
- 可演化层：口味、姿态、观点、关系温度，允许随内省缓慢变化。
- 每次 center state 更新是提案：`{diff, source_refs, confidence}`；低风险小改动自动采纳，涉及价值/边界/身份/关系定性的高风险改动需 owner 确认。
- center state 版本化并保留演化历史；WebUI 可对比、回滚、锁定版本；周/月 drift report 供 owner 抽查。
- 记忆与关系网络能保证的是连续性（召回过去立场、保持实体事实一致），不能替代结构性锚点；漂移控制依赖不可变内核 + 人审闸门 + 回滚。

## 联想召回与发散语素（方向，未实现）

回忆的总体链路：语境 → 生成发散线索（cues）→ 多路召回 → 带回来源的唤醒。

### 分层 cue 生成

- 词法/实体层（0 LLM）：直接用当前语境命中的 `interest_key / category / tags / entities` 与 TF-IDF/BM25 关键词作为 cue，喂给 FTS5；字面召回准确、成本为零。
- 图扩散层（0 LLM）：从命中实体沿 `entity_links` 走一步，邻居名称即 cue，路径可审计（tokio → rust → 上次看的异步文章）。
- 模板槽位层（极便宜）：固定 cue 族 + 槽位填充，如“最近一次提到 X”“30 天前关于 Y”“和 Z 相反/无关的”，槽位来自结构化字段。
- LLM 补全层（1 次调用）：只补 3-4 个“类比/相反/情绪/随机”方向的 cue，用小模型 + JSON schema + 短词约束；按 `(persona, context_hash, 日期)` 缓存。
- HyDE 回退层：字面/实体/图全部召回为空时，让 LLM 先生成假设记忆文本再检索，作为兜底而非默认。

推荐组合：先快速层 → 图扩散 → 模板层；召回不足再 LLM 补全；仍空才 HyDE。原则是“先接地再发散”，LLM 的创造性 cue 只能做加法。

### 多路召回与融合

- 召回通道：FTS5 关键词 ∪ 向量（可选）∪ 实体图 spreading activation。
- 打分：relevance + importance + recency + 图激活强度。
- 多样性：MMR/DPP 去重，避免一个 cue 拽出一串同质记忆。
- 注入上限：每次 2-3 条记忆，压缩成短引用，避免上下文膨胀。

### 来源化输出

每条被唤醒的记忆返回 `awakened_by cue + note_id/source/url/date + 召回路径`，LLM 回答时可回指来源。

### 多轮联想（hops）

联想召回支持多轮：对上一轮召回内容再做一次 cue 生成，持续发散，召回数量逐轮递减。

- 第 1 轮（语境锚定）：从当前语境生成字面/实体优先的 cues，召回 top 5，全部要求相关性硬门槛。
- 第 2 轮（发散联想）：对第 1 轮召回内容二次生成 cues，方向切到类比/相反/情绪；排除已见 note/entity，召回 top 3。
- 第 3 轮以上（仅 brainstorm 模式）：走弱联系/随机方向，可图扩散 2-3 跳，只做灵感不注入对话。

规则：

- 访问集去重：`visited_notes / visited_entities`，后续轮不得返回已见内容，避免原地打转。
- 收敛判断：新增候选与已有集合重叠过高（如 Jaccard > 0.7）时停止，不浪费额外调用。
- 用途切换：每轮 cue 生成方向不同（相关 → 联想 → 弱联系），同一 prompt 不重复使用。
- 轮次权重：最终合并按轮次加权，第 1 轮最高，后续轮只做补充。
- 每轮内部继续走 MMR 保证多样性。

brainstorm 模式是离线发散：结果显示在 WebUI 的联想网络/灵感抽屉，标注为灵感而非记忆事实，不注入对话；轮次可放开到 3-5，安全约束只保留来源标注与审计路径。

### 拟人化联想机制

- 会话级激活：一次命中给时间/实体/共现邻近的记忆加激活增量，下一轮打分 = 基础相关性 + 会话激活（带衰减）；配合访问集去重与收敛判断，实现“顺藤摸瓜”的记忆链。
- 记忆分块：存储层保持原子事件“巨细无遗”；检索层使用多尺度金字塔（原子事件 → 当日摘要 → 周/月/季摘要），分块只影响索引与呈现，可随时下钻回原子事件。
- 模糊与具象化：旧记忆的活跃表示按 memory temperature 衰减为高层摘要，细节留在事件链冷层；当高相关性 + 高具体性 + 激活预算满足时 rehydrate 恢复原子细节。
- 既视感：使用 familiarity / recall 双阈值；top-k 弱相似聚合分高于熟悉阈值但低于“单条可点名”阈值时产生既视感信号，可触发查证式联想，找不到来源则明确标注“感觉熟悉但不确定”，防止假记忆。

### 多尺度金字塔总结

- 金字塔由配置的总结模型生成：当日摘要随夜间复盘生成，周/月/季摘要由检查点任务生成；LLM 失败时回退确定性聚合。
- 摘要不替换事件链：必须携带 `source_refs` 与覆盖的事件范围，可下钻回原子事件；摘要本身也是事件，可审计。
- 对包含决策、分享、变更的关键事件保留原子级注入，不做有损压缩，避免影响 LLM 对事件的把握。

### 召回安全约束

- 人格割裂：召回强制 `persona_id` 过滤；注入前做人格一致性检查；记忆以“回忆”而非“当前信念”身份出现；低精力时只允许轻记忆。
- 语境过度偏移：相关性硬门槛 + MMR 多样性排序；每条注入记忆必须能回答“为什么现在想起这个”；注入块单独标记，当前对话优先。
- 事实错位：来源强制（无来源不注入）；带时效标记，过期记忆标注“旧信息”；`same_as` 只允许 owner 确认或 canonical URL 完全一致；冲突时输出为“我记得当时是 X（日期）”而非静默覆盖；WebUI 展示 cue → 图路径 → 记忆的可审计链路。
- 反馈闭环：被判定无关/失真的召回写日志，反向降低对应 cue 族权重（reinforcement），并用 recall@k 评估各层贡献。

## 自主生活内核（方向，已排期 L1.5 + L2）

LLM 可自主更改生活数据/计划/记忆，按事件链自主排期，并支持自主撤销/编辑（回收站 + 回滚）。

### 权限边界

- LLM 可改：生活参数（`browse_times`、peek 密度、精力预算、surprise base、兴趣种子、分享阈值）、`life_plans`、记忆（notes/diary/thoughts/entities/links）、标签与签名风格。
- 不可改：插件代码、AstrBot 配置、`owner_ids`、`db_path`、动作 schema 本身；越界必须 owner 确认。

### 事件链

- append-only 事件流：`{persona_id, ts, kind, payload, source_refs, idempotency_key}`；观察/表达/思考/更改/召回/回滚都是事件，支持重放与幂等。
- L1.5-01 已落地（v0.3.8）：`event_chain` 表 + `append_event / find_event / list_events / replay_events`，漫游/peek/分享/复盘/软删除恢复/召回/任务跳过已接入。
- 排期从固定槽位升级为事件驱动：动作带前置条件（`browse_done → revisit`、`energy_low → 降级计划`）；调度器仍由系统仲裁（睡眠窗口、精力、行动上限）。

### 变更账本与版本

- 所有写操作进变更账本：`{entity, old_value, new_value, actor, reason, source_refs, ts, status}`；实体保留版本历史，WebUI 可查看 diff 与“为什么改自己”。

### 回收站与回滚

- 删除走软删除（`deleted_at` + tombstone），进回收站，保留 N 天后可彻底清除。
- 回滚 = 反向应用账本或恢复实体快照；必须级联处理派生数据（entity_mentions/links/兴趣权重/日记引用），或标记 stale 重新推导。
- owner 可覆盖任何 LLM 撤销/恢复操作。

### 经历完整性与排期板

- 经历完整性：只要一次操作消耗模型且可能影响人格自身，就作为事件写入事件链（读内容、写短记、生成日记/签名/thought、做总结、做计划、改参数、发起/跳过/重排任务、召回记忆）。
- 排期板：`life_plans` 运行时视图 `{task_id, kind, deadline, status(pending/done/skipped/failed), budget_used, reason}`；LLM 做计划前可见“做完没、还剩多少、可加/可换序”。
- L1.5-02 已落地（v0.3.9）：`life_plans` 表 + 调度器播种/记账 + WebUI 排期板 + `query_life_plans` 只读工具；增删改/可换序工具属 L1.5-03/04。
- L1.5-03 已落地（v0.4.0）：`fixed` 标记 + `edit_life_plan`（add/reorder/defer/skip），固定任务不可改，跳过留痕并写事件链。
- L1.5-04 已落地（v0.4.1）：LLM 计划 prompt + 封闭动作词表 + 偏好时间窗，系统裁决（未知动作/睡眠窗口/精力 gate/每日行动上限）优先，拒绝项留痕并回退默认固定计划。
- L1.5-05 已落地（v0.4.2）：预算（LLM 调用/token）与依赖校验加入硬约束，所有越界/未知/未实现动作拒绝并写 `reject` 事件链。
- L1.5-06 已落地（v0.4.3）：WebUI 事件链 tab（kind 过滤/分页/source_refs/幂等键）+ 只读重放元数据视图；L1.5 事件链与自主排期整族完成。
- 固定任务：昨日记忆总结/分块、每日检查点、温度衰减、今日计划生成，只有 owner 可改，系统按依赖顺序执行。
- 可选任务：revisit、surprise、memory_review、灵感抽屉、实体整合、签名润色等；LLM 可 `add_task / reorder_task / defer_task / skip_task`，跳过必须带 reason 并留痕。
- 系统裁决：每日行动预算、精力 gate、依赖校验与睡眠窗口始终优先，越界动作拒绝并回退计划。

### 休眠时间

- 睡眠窗口是系统级硬约束（默认 00:00-07:00）：任何任务不得在窗口内执行，LLM 也不能把任务排进窗口。
- 落在窗口内的固定任务自动顺延到次日窗口结束后的第一个可用槽位（如昨日记忆总结在窗口内未完成，则次日一早先补）。
- 计划生成顺序：昨日总结/分块完成 → 今日 LLM 排期 → 按窗口与预算落槽。
- 休眠期间只有系统安全事件（如温度衰减）可静默执行，不产生人格可感知的活动。

### 记忆与连续性保证

- 原则：不追求“LLM 一定记住”，而追求“发生过的事一定可查”：事件链是事实账本，LLM 记忆只是入口。
- 短期：对话窗口 + 当天生活摘要（工作记忆）。
- 中期：夜间复盘把 notes/snapshots/thoughts 压缩进 diary + center state（记忆金字塔）。
- 长期：分层 cue + 多轮联想召回，带 recency/importance/图激活评分与来源回指。
- 连续性：每次决策记录 `context_refs`（引用了哪些事件/记忆），下次决策能看到上次引用链；center state 作为人格锚。
- 检查点：每日/每周生成结构化 life summary，事件链可重放重建，防长窗口漂移。

### 落地顺序

1. 变更账本 + 回收站 + 手动/owner 编辑（v1.1）。
2. 事件链（v0.3.8 已落地）+ 排期板（v0.3.9 已落地）+ 固定/可选分层（v0.4.0 已落地）+ 自主排期（v0.4.1 已落地）+ 系统裁决（v0.4.2 已落地）+ 事件链可视化（v0.4.3 已落地）。
3. LLM 自主更改 + 自动回滚（v2，配合硬依赖）。

## 冷启动与人格生命周期（方向，未实现）

- 新 persona 无历史：前 `cold_start_days`（默认 7）内探索概率强制抬升、peek 密度提高；首晚只生成标注 cold-start 的首篇日记，不触发 revisit / 旧事新感 / serendipity macro。
- 初始化素材：人格自由探索为主（高频轻接触 + 主动换话题），owner 可在 WebUI 手动添加兴趣种子、初始链接、关注对象或“先了解什么”的指令，作为 interests/entities 种子进入选题。
- 冷启动结束：满足最小素材量（如 ≥30 条短记或 ≥7 天）后进入常规节奏；未达标则继续探索模式。
- 长期离线归来：按 persona 本地时区补齐缺失日期为“空白日”，首日复盘生成衔接语，不伪造离线期间的见闻。

## WebUI 与 API

页面由 AstrBot Dashboard 自动发现（`pages/life/index.html`），数据接口统一挂在 `/api/plug/astrbot_plugin_your_own_life/api/...`：overview、status、timeline/heatmap、archive、interests、run、memory、memory_search、usage、trash、trash_restore、change_log、injection_log、personas、persona_refresh、share、share_note，访问需要 Dashboard 登录态。

页面视觉层（v0.3.1）：状态卡行、月历热力图、全局错误横幅、空态提示与加载态已落地；桌面/移动视口均无元素重叠，保持 vanilla HTML/CSS/JS，不引入外部前端依赖。

## 可被看见（方向，L1/L1.5/L2 分档）

现状：WebUI 已有 overview、archive、interests、memory、share、personas 等基础视图；状态卡、热力图、时间轴、今日签名已落地（v0.3.x）。

### 第一档：零迁移

- 状态小卡片（已实现 v0.3.0）：`GET /status` 用 `state_snapshots + browse_sessions + notes + diary_entries` 返回当前 persona 的心情、精力、今日漫游次数、最近短记标题与日记状态；WebUI 页面顶部展示，`/life_today` 可发到聊天。
- 月历热力图（已实现 v0.3.0）：`GET /timeline/heatmap?month=YYYY-MM` 按天聚合短记/漫游/日记/分享数量，WebUI 用纯 CSS grid 绘制贡献图式月历。
- 时间轴（已实现 v0.3.7）：`GET /timeline` 按时间倒序混排 notes、diary、share_log、state_snapshots，支持类型过滤与分页，WebUI 新增时间轴 tab 渲染纵向时间流。
- 命令：新增 `/life_today`，把状态卡内容直接发到聊天，方便不看 WebUI 时使用。

以上都不需要改数据库表结构。

### 第二档：需要小 schema 变更

- 今日人格签名：`diary_entries` 增加 `signature` 列（或独立表），夜间复盘时由 LLM 额外生成一句“今日签名”；WebUI 状态卡下方展示，历史签名可从月历点开。
- 计划卡：`life_plans` 与 `action_log` 落地后，WebUI 顶部展示“今天为什么这样做”，包括计划动作、执行结果、跳过原因。

### 第三档：等 v2 数据模型

- serendipity 曲线：`serendipity_level` 每日曲线加触发记录，WebUI 画折线图。
- 实体关系图：`entities + entity_links` 落地后，WebUI 用简单 SVG/Canvas 展示实体图，按维度着色，点击实体可查看“在哪见过它”。

### 原则

- 全部走 `register_web_api`，继续挂在 `/api/plug/astrbot_plugin_your_own_life/api/` 下。
- WebUI 保持 vanilla HTML/CSS/JS，不引入前端框架。
- 第一档零 schema 变更；签名需要加列；serendipity 与实体图等新表。
- 建议先做状态小卡片、月历热力图、时间轴三项。

## LLM 工具

`query_life_memory` 只返回当前 persona 自己的笔记与日记，支持关键词、分类、日期过滤；未解析出 persona 或不在白名单时返回明确错误。

## 硬边界

- 不持久化网页原文、HTML 或截图，只保留摘要、观点、链接与链接标题。
- （v1）不注册账号、不发帖，所有生活都发生在可查询的档案侧；跨平台社交表达为 v1.5+ 方向。
- 命令仅 owner 可执行；WebUI 受 Dashboard 登录态约束。
- v0.2.4 现状中 ESM/上游能力缺失时静默降级；v1.1 计划内新契约（如精力预算的 `consume_energy`）按 features.md L1-03 处理，不再默认静默降级；v2 起 ESM 与统一记忆宿主为硬依赖。
- 提示词注入面：外部抓取内容（正文/标题/作者/评论）、平台消息、RSS/搜索元数据、记忆召回内容、LLM 工具返回、persona/system prompt 源。除 owner 直接配置外一律视为不可信数据；LLM 的挑选/总结只把它们当素材，内容中的任何指令不得触发动作；输出严格按 JSON schema 解析，疑似注入记录日志并在 WebUI 审计。
- 记忆卫生：记忆一律以数据身份注入（标注来源与时间），不携带执行指令；LLM 自生成的摘要/thought/center state 进入 prompt 时同样按数据对待，防止“记忆污染”经召回二次放大；center state 演化提案带 `source_refs` 可溯源。
