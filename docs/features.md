# 功能分层开发清单

本文档是开发的“做什么/怎么做”清单：按功能层拆解，每项给出状态、依赖、模块落点、配置项与验收标准。架构与数据模型细节见 `docs/design.md`，跨插件契约见 `docs/requirements.md`，推进流程见 `docs/workflow.md`。

## 分层总览

| 层 | 版本 | 主题 | 内容 |
| --- | --- | --- | --- |
| L0 | v0.2.4 | 现状基线 | 定时漫游/复盘、人格缓存、信息源、兴趣、分享、SQLite、命令、WebUI、LLM 工具、ESM 降级 |
| L1 | v1.1 | 低成本高体感 | 今日签名、旧事新感、精力预算、随机不出门、时段模式、peek、灵感抽屉、状态卡/热力图/时间轴、预算/重试/崩溃、时区、变更账本+回收站、安全基线、WebUI 美化、同人格单 SQL 租约 |
| L1.5 | v1.5 | 事件链与自主排期 | 事件链、排期板、固定/可选任务分层、LLM 自主排期、系统裁决、事件链可视化 |
| L2 | v2 | 结构性能力（硬依赖） | 统一记忆库、实体关系图、关注对象、故地重游、记忆温度、回顾/胶囊/评估、LLM 自主更改+回滚、多实例租约 |
| 方向 | 未排期 | 生活感方向 | 意外波动、可被看见剩余档、内隐思考/center state、联想召回、冷启动、生命链/群聊入档 |

分层规则：

- L0 必须保持全绿，任何改动不得破坏现状回归。
- L1 允许引入上游依赖（如 ESM 精力消费），依赖项在本文档与 `docs/requirements.md` 同步标注；改动尽量收敛到现有模块。
- L1.5 引入事件链，先只读后写，所有写操作带 `idempotency_key`。
- L2 前先与上游对齐 `_PUBLIC_API.md` 并整族协调发版（见 `docs/requirements.md`）。
- “方向”层默认不承诺落地；实现前先按 `docs/workflow.md` 调研，并把状态从“方向”改为“已排期”。

## L0 现状基线（v0.2.4，已实现）

| 功能 | 模块 | 验收/说明 |
| --- | --- | --- |
| 定时漫游与夜间复盘 | `main.py` / `life/scheduler.py` / `life/browser.py` | 默认 10:00/15:00 漫游、23:00 复盘；确定性抖动 ±120/±60 分钟；`_done_keys` 防重复执行 |
| 人格缓存 | `life/persona.py` / `life/prompts.py` | `life_personas` 白名单；`persona_cache_hours` 刷新；解析失败跳过当天并记 error |
| 信息源 | `life/fetchers.py` | HN/GitHub/Reddit/RSS/Tavily；`source_timeout` 10s；按 URL 哈希去重 |
| 兴趣权重 | `life/interests.py` | `explore_probability` 探索、`interest_decay` 衰减、`interests_initial` 种子 |
| 分享决策 | `life/share.py` | `share_*` 配置；ShareGate 顺序检查；pending 夜间补发 |
| SQLite 档案 | `life/db.py` | 8 张表 + 旧版自动迁移；`db_path` 可配 |
| 聊天命令 | `main.py` | `/life`、`/life_now`、`/life_archive`、`/life_interest`、`/life_personas`、`/life_share`、`/life_reset` |
| WebUI | `life/webui.py` + `pages/life/index.html` | `register_web_api`（引擎不可用时回退 `register_web_routes`）；接口：overview、archive、interests、run、memory、memory_search、personas、persona_refresh、share、share_note |
| LLM 工具 | `life/life_tool.py` | `query_life_memory` 只查当前 persona 自己的档案 |
| ESM 适配 | `life/esm_adapter.py` | 缺失/方法缺失/信号非法时静默降级；`energy_gate`、`esm_scope_prefix` |
| 测试基座 | `tests/` | unittest 全绿；真实网络冒烟需 `LIFE_SMOKE_NET=1` |

## L1 v1.1 低成本高体感（已确认方向）

### L1-01 今日人格签名

- 目标：每晚在日记外生成一句“今日签名”，形成可翻看的签名流。
- 依赖：夜间复盘（L0）。
- 模块：`life/browser.py`（生成）、`life/db.py`（`diary_entries` 加 `signature` 列或独立表）、`life/webui.py` + 页面（展示）。
- 配置：无（或 `signature_enabled`，默认开）。
- 验收：签名落库且随 `/life_archive`、WebUI 状态卡可查；无日记日不生成；迁移测试通过。

### L1-02 旧事新感

- 目标：夜间复盘随机回看 7/30 天前的短记，生成“后来的我再看这件事”。
- 依赖：夜间复盘（L0）、历史短记。
- 模块：`life/browser.py`、`life/prompts.py`、`life/db.py`（查询接口）。
- 配置：`revisit_days`（默认 `[7, 30]`）、`revisit_probability`（默认 0.5）。
- 验收：有历史时日记含回看段落；无历史时不触发（冷启动方向落地后再接入冷启动期判定）；LLM 失败走 L1-11 重试语义。
- 命名区分：本项是夜间日记回看；与 L2-11 故地重游（定期重访收藏链接）不同。

### L1-03 精力预算

- 目标：每日漫游有能量上限，高精力啃重内容、低精力只 peek。
- 依赖：ESM 提供 `consume_energy` 或等效公开方法（上游契约见 `docs/requirements.md`；API 未实现前此项不交付，或用本地估算降级并显式标注）。
- 模块：`life/esm_adapter.py`、`life/browser.py`、`life/scheduler.py`。
- 配置：`energy_budget`（每日上限）、`energy_gate` 沿用。
- 验收：任务真实消耗并持久化精力；预算耗尽后当天剩余任务跳过并记录；ESM 未提供 `consume_energy` 时该项标记 blocked 或退化为只读 gate + 本地估算，不再以静默降级为默认。

### L1-04 随机不出门

- 目标：按概率跳过当天漫游，但写一条状态快照，允许 bot 偶尔躺平。
- 依赖：调度器（L0）。
- 模块：`life/scheduler.py`、`life/browser.py`、`life/db.py`。
- 配置：`rest_probability`（默认 0.1）。
- 验收：跳过时写 `skipped_rest` 快照；夜间复盘能看到“今天没出门”；不影响手动 `/life_now`。

### L1-05 时段模式

- 目标：早高峰/午休/深夜使用不同内容偏好与语气。
- 依赖：漫游流程（L0）。
- 模块：`life/prompts.py`、`life/browser.py`。
- 配置：`time_slots`（morning/afternoon/evening/night 的偏好主题与语气）。
- 验收：同一素材在不同时段生成不同风格摘要；配置缺失回退默认语气。
- 命名区分：`time_slots` 管“内容偏好/语气”（怎么看），与 L1.5-04 的偏好时间窗（什么时候做什么）不同。

### L1-06 轻接触 peek

- 目标：高频低成本的“路过”动作，只更新状态快照不产短记。
- 依赖：调度器（L0）、信息源抓取（L0，可只取热度/标题）。
- 模块：`life/scheduler.py`、`life/fetchers.py`、`life/browser.py`、`life/db.py`。
- 配置：`peek_times`（默认 `["09:00","13:00","17:00","21:00"]`）、`peek_daily_cap`。
- 验收：peek 不调用 LLM、不写 notes；状态快照增加且 `browse_sessions` 可区分 peek/browse；成本统计可查。

### L1-07 灵感抽屉

- 目标：LLM 把“也许有用但今天不展开”的东西放进 wishlist，定期翻出来评估。
- 依赖：漫游流程（L0）。
- 模块：`life/db.py`（`wishlist` 表或 notes 加 kind）、`life/browser.py`、`life/webui.py`。
- 配置：`wishlist_enabled`。
- 验收：LLM 可写入灵感；WebUI 有灵感视图；定期评估任务把灵感升级为兴趣种子或丢弃。
- 命名区分：本项 = 可回看的 wishlist；联想召回的 brainstorm“灵感抽屉”是离线发散输出（见 `docs/design.md`），同名不同物。

### L1-08 状态小卡片

- 目标：Dashboard 顶部展示当前 persona 的心情、精力、今日漫游次数、最近短记标题与日记状态。
- 依赖：WebUI（L0）。
- 模块：`life/webui.py`（新增 `GET /status`）、`main.py`（`/life_today` 命令）、`pages/life/index.html`。
- 配置：无。
- 验收：接口返回字段齐全；无数据时给出空态而不是报错；零 schema 变更；`/life_today` 把状态卡内容发到聊天。

### L1-09 月历热力图

- 目标：按天聚合短记/漫游/日记/分享数量，纯 CSS grid 绘制贡献图式月历。
- 依赖：WebUI（L0）。
- 模块：`life/webui.py`（新增 `GET /timeline/heatmap?month=YYYY-MM`）、`pages/life/index.html`。
- 配置：无。
- 验收：跨月参数正确；空月不报错；点击日期可跳到当日档案。

### L1-10 时间轴

- 目标：按时间倒序混排 notes、diary、share_log、state_snapshots。
- 依赖：WebUI（L0）。
- 模块：`life/webui.py`、`pages/life/index.html`。
- 配置：无。
- 验收：类型过滤与分页正确；每条带来源链接或日期。

### L1-11 预算、重试与崩溃语义

- 状态：已实现（v0.2.6）。
- 目标：LLM 调用有预算与重试上限，崩溃不污染档案，宁缺毋滥。
- 依赖：漫游/复盘流程（L0）。
- 模块：`life/llm.py`、`life/browser.py`、`life/db.py`、`life/webui.py`。
- 配置：`daily_llm_call_limit`（默认 `0` 无上限）、`daily_token_budget`（默认 `0` 无上限）、`llm_retry_limit`（默认 3）。
- 验收：重试 3 次耗尽后任务标记 `failed` 并报 error，不生成伪造内容；run 级暂存，崩溃丢弃未提交数据；现有确定性 fallback 从 L1 起移除（现状 v0.2.4 仍保留）。
- 前置改造（已完成）：run 级原子性采用暂存区（staging）优先——漫游/复盘先写暂存表，全部成功后一次落库；SQLite 写事务只包住最终落库阶段，避免写锁横跨网络/LLM await。`db._execute` 支持 `commit=False`，最终落库走 `BEGIN IMMEDIATE` 事务；fallback 相关测试已按新语义更新。
- 计量说明：`daily_token_budget` 依赖 AstrBot provider 是否返回 usage；拿不到 token 用量时只执行调用次数上限，并在 WebUI 标注“token 计量不可用”。
- 用量落点：每日 LLM 调用与 token 用量写入 `daily_usage` 表（persona_id / date / llm_calls / tokens），WebUI 用量视图读取该表。

### L1-12 时区

- 状态：已实现（v0.2.5）。
- 目标：睡眠窗口、槽位日期与“今日”边界按 persona 本地时间计算。
- 依赖：调度器（L0）。
- 模块：`life/config.py`、`life/scheduler.py`、`life/db.py`。
- 配置：`timezone`（默认 `Asia/Shanghai`）。
- 验收：跨时区部署时各 persona 日记日期正确；配置非法时报 error 并回退默认时区。
- 前置改造：`life/db.py` 的 `_today_str/_now_str` 需按 persona 时区计算（现状为 `datetime.now()`），日记日期与查询边界统一走时区日期。

### L1-13 变更账本与回收站

- 状态：已实现（v0.2.7）。
- 目标：所有写操作可审计、可回滚，删除进回收站。
- 依赖：SQLite（L0）。
- 模块：`life/db.py`（`change_log`、软删除字段）、`life/webui.py`（diff/回收站视图）。
- 配置：`trash_retention_days`（默认 30）。
- 验收：写操作记 `{entity, old_value, new_value, actor, reason, ts, status}`；删除走 tombstone；owner 可恢复。

### L1-14 不可信内容与记忆卫生

- 状态：已实现（v0.2.8）。
- 目标：外部内容只当素材，记忆以数据身份注入，防提示词注入与记忆污染。
- 依赖：漫游/复盘（L0）、LLM 工具（L0）。
- 模块：`life/fetchers.py`、`life/prompts.py`、`life/browser.py`、`life/db.py`、`life/webui.py`（注入日志/审计视图）。
- 配置：`injection_log_enabled`（默认开）。
- 验收：抓取内容/平台消息/RSS 元数据一律按不可信数据处理；LLM 输出严格按 JSON schema 解析；疑似注入记录日志并在 WebUI 审计；记忆注入带来源与时间，不携带执行指令。

### L1-15 WebUI 视觉优化

- 目标：统一后台工具风格：排版、空态、错误态、加载态、移动端适配。
- 依赖：L1-08/09/10 视图。
- 模块：`pages/life/index.html`（vanilla HTML/CSS/JS）、`life/webui.py`（必要时补字段）。
- 配置：无。
- 验收：桌面/移动视口无元素重叠；空数据与错误态有明确提示；不引入外部前端依赖；用 Playwright 截图检查。

### L1-16 同人格单 SQL 与任务租约（v1 多实例兜底）

- 目标：同人格多实例只共享一个 SQLite 文件，租约保证事件链单写者。
- 依赖：SQLite（L0）。
- 模块：`life/config.py`（校验同人格 `db_path` 一致）、`life/db.py`（`life_leases` 表）、`life/scheduler.py`。
- 配置：`lease_ttl_seconds`（默认 300）。
- 验收：同人格所有实例必须指向同一 `db_path`；两个进程同时触发同一槽位只有一个执行，另一个记录 `skipped_duplicate`；不做按 persona 分文件的复杂度。
- 部署前提：同一 SQLite 文件仅适用于共享卷（同一主机或挂载盘）；跨主机共享 SQLite 文件不在 v1 支持范围，跨主机场景直接走 v2 统一库租约。

## L1.5 v1.5 事件链与自主排期（已确认方向）

### L1.5-01 事件链

- 目标：append-only 事件流，支持重放与幂等。
- 依赖：变更账本（L1-13）。
- 模块：`life/db.py`（`event_chain` 表）、`life/browser.py`、`life/scheduler.py`。
- 配置：无。
- 验收：观察/表达/思考/更改/召回/回滚都是事件；每条带 `{persona_id, ts, kind, payload, source_refs, idempotency_key}`；重放不产生重复副作用。

### L1.5-02 排期板

- 目标：`life_plans` 运行时视图，任务带状态、预算用量与原因。
- 依赖：事件链（L1.5-01）。
- 模块：`life/db.py`、`life/scheduler.py`、`life/webui.py`。
- 配置：无。
- 验收：LLM 可见“做完没、还剩多少、可加/可换序”；跳过/失败必须带 reason。

### L1.5-03 固定/可选任务分层

- 目标：固定任务只有 owner 可改，可选任务 LLM 可 `add_task / reorder_task / defer_task / skip_task`。
- 依赖：排期板（L1.5-02）。
- 模块：`life/scheduler.py`、`life/life_tool.py`（新增计划工具）。
- 配置：固定任务清单在代码中，`life_plans` 中标记 `fixed=true`。
- 验收：LLM 不能改固定任务；跳过可选任务留痕；系统按依赖顺序执行。

### L1.5-04 LLM 自主排期

- 目标：LLM 产出封闭动作词表与偏好时间窗，系统决定精确时刻。
- 依赖：L1.5-02/03。
- 模块：`life/prompts.py`、`life/scheduler.py`、`life/life_tool.py`、`main.py`（`/life_plan`）。
- 配置：动作词表（`browse / revisit / signature / diary / share / rest / surprise / memory_review`）。
- 验收：未知动作拒绝并回退默认固定计划；睡眠窗口、精力 gate、每日行动上限优先于 LLM 计划。

### L1.5-05 系统裁决

- 目标：预算、精力、依赖校验与睡眠窗口始终是硬约束。
- 依赖：L1.5-01 至 04。
- 模块：`life/scheduler.py`、`life/esm_adapter.py`。
- 配置：L1-11 预算配置 + `sleep_window`。
- 验收：越界动作被拒绝并回退计划；所有拒绝写事件链。

### L1.5-06 事件链可视化

- 目标：WebUI 按时间倒序展示事件流，事件带类型徽标、来源与可下钻 payload。
- 依赖：事件链（L1.5-01）。
- 模块：`life/db.py`（查询接口）、`life/webui.py`、`pages/life/index.html`。
- 配置：无。
- 验收：只读视图（不提供写入口）；支持 kind 过滤与分页；事件显示 `source_refs`；重放元数据可见。

## L2 v2 结构性能力（硬依赖）

### L2-01 统一记忆库

- 目标：由记忆宿主持有统一逻辑库，本插件经 `LifeMemoryAdapter` 读写，本地 SQLite 降级为缓存。
- 依赖：engram_core 或未来 life-chain 提供版本化 API（见 `docs/requirements.md`）。
- 模块：`life/memory_adapter.py`（与 `life/esm_adapter.py` 同级）、`life/db.py`。
- 配置：`memory_host`（插件 ID）。
- 验收：`store_event / add_note / store_diary / upsert_entity / link_entities / query_memory / search` 全部经 adapter；宿主缺失时报 error（硬依赖，不再静默降级）。

### L2-02 实体与关系图

- 目标：`entities / entity_mentions / entity_links` 分层维度模型。
- 依赖：统一记忆库（L2-01）。
- 模块：`life/memory_adapter.py`、`life/webui.py`（实体图视图）。
- 配置：封闭关系词表（`appears_on / author_of / member_of / related_to / same_as`）。
- 验收：平台节点只能系统写入；`same_as` 需 owner 确认或 canonical URL 完全一致；查询“我在哪见过 X”可聚合平台。

### L2-03 记忆温度

- 目标：短记带热度与遗忘曲线，冷记忆淡出，被重新提及时“想起来”。
- 依赖：统一记忆库（L2-01）。
- 模块：`life/db.py`、`life/memory_adapter.py`、`life/interests.py`。
- 配置：`memory_temperature_decay`。
- 验收：温度随时间衰减；召回按温度加权；rehydrate 后恢复原子细节。

### L2-04 月度/年度回顾

- 目标：自动生成“这个月漫游 N 次、兴趣从 X 变成 Y、有几天没出门”。
- 依赖：统一记忆库 + 多尺度金字塔摘要（方向，未落地时回顾先用确定性聚合回退）。
- 模块：`life/browser.py`、`life/prompts.py`。
- 配置：`review_schedule`。
- 验收：回顾带来源引用；LLM 失败走重试语义；回顾本身是事件。

### L2-05 时间胶囊

- 目标：封存一条短记，30 天后解锁并让 LLM 以当时人格回信。
- 依赖：统一记忆库。
- 模块：`life/browser.py`、`life/db.py`、`life/webui.py`。
- 配置：`capsule_days`（默认 30）。
- 验收：到期自动解锁；回信标注“当时的我/现在的我”；可手动提前打开。

### L2-06 分享沉默率

- 目标：分享 gate 增加概率性“今天不想说”。
- 依赖：ShareGate（L0）。
- 模块：`life/share.py`。
- 配置：`share_silence_rate`（默认 0.15）。
- 验收：沉默不写分享日志；日记可体现“今天不想说话”。

### L2-07 季度自我评估

- 目标：基于兴趣与情绪轨迹生成长期人格总结。
- 依赖：统一记忆库 + center state（方向）。
- 模块：`life/browser.py`、`life/prompts.py`。
- 配置：`quarterly_review_enabled`。
- 验收：评估带来源与 confidence；owner 可在 WebUI 查看 diff。

### L2-08 LLM 自主更改与自动回滚

- 目标：LLM 可改生活参数/计划/记忆，自动撤销与编辑。
- 依赖：事件链 + 变更账本（L1.5/L1-13）。
- 模块：`life/life_tool.py`、`life/db.py`。
- 配置：权限边界（LLM 可改/不可改清单）。
- 验收：越界动作需 owner 确认；回滚级联处理派生数据；owner 可覆盖任何操作。

### L2-09 多实例租约

- 目标：同人格多实例串行化，保证事件链单写者。
- 依赖：统一记忆库宿主提供 `claim_task / renew_task / release_task`。
- 模块：`life/memory_adapter.py`、`life/scheduler.py`。
- 配置：`memory_lease_ttl_seconds`（默认 300；与 v1 本地 `lease_ttl_seconds` 区分）。
- 验收：拿不到租约的实例跳过并记录 `skipped_duplicate`；租约过期自动释放。

### L2-10 关注对象

- 目标：主人配置持续关注名单（博客、GitHub 用户/项目、RSS），形成追更感。
- 依赖：统一记忆库（L2-01）、信息源（L0）。
- 模块：`life/config.py`（`watchlist`）、`life/fetchers.py`、`life/browser.py`、`life/webui.py`。
- 配置：`watchlist`（每项：类型/标识/URL）。
- 验收：关注对象进入选题候选；实体图可标记“正在关注”；状态卡/时间轴可见更新。

### L2-11 故地重游

- 目标：定期 revisit 收藏链接或项目，写“后来呢”。
- 依赖：统一记忆库 + 关注对象（L2-10）。
- 模块：`life/browser.py`、`life/db.py`。
- 配置：`revisit_interval_days`（默认 30）。
- 验收：到期自动触发 revisit；新短记带 `revisit` 标记并引用原链接；原短记与后续状态可串联查看。
- 命名区分：与 L1-02 旧事新感（日记回看）不同，本项是对链接/项目的定期重访。

## 方向（未排期）

以下项已有模型设计，未承诺落地时间；实现前按 `docs/workflow.md` 调研并把状态改为“已排期”。

- 意外波动：`serendipity_level` 均值回归 + 饥饿度 + 状态调制 + 强度分级，见 `docs/design.md`。
- 可被看见：状态卡/热力图/时间轴已列入 L1；签名（L1-01）、计划卡（L1.5-02）、serendipity 曲线（未排期）、实体图（L2-02）按依赖落地。
- 内隐思考层：观察/表达/中心三层、`thoughts`、center state 与人格演化可控性，见 `docs/design.md`。
- 联想召回：分层 cue、多路召回、多轮联想（每轮候选上限 5）、记忆金字塔、既视感，见 `docs/design.md`。
- 冷启动：新人格自由探索 + owner 手动干预，见 `docs/design.md`。
- 生命链/群聊入档：全平台消息事件统一处理，依赖统一记忆库与 social_context 只读快照。

## 开发顺序建议

1. 工程基线：L1-12 时区、L1-11 预算/重试/崩溃（含 db 事务化前置改造）、L1-13 变更账本/回收站、L1-14 安全基线、L1-16 同人格单 SQL 租约。
2. 高体感：L1-01 今日签名、L1-08 状态卡、L1-09 热力图；L1-15 WebUI 美化随前两项视图落地后推进。
3. L1 剩余：L1-03 精力预算（依赖 ESM `consume_energy`，与上游契约同批）、L1-02 旧事新感、L1-04 随机不出门、L1-05 时段模式、L1-06 peek、L1-07 灵感抽屉、L1-10 时间轴。
4. L1.5：事件链（L1.5-01）→ 排期板（L1.5-02/03）→ 自主排期（L1.5-04/05）→ 事件链可视化（L1.5-06）。
5. L2：先与上游对齐 `_PUBLIC_API.md` 并整族协调，再按 L2 项推进。
