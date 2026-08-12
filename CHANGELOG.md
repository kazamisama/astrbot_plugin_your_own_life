# Changelog

本插件版本历史。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格。

## [0.5.2] - 2026-08-12

### Added

- L2-03 记忆温度：`notes` 新增 `temperature` / `last_touched_at`；夜间复盘按 `memory_temperature_decay`（默认 0.99）每日衰减，冷记忆淡出下限 0.05；`query_life_memory` 与 WebUI `memory_search` 召回按温度降序加权，命中短记 rehydrate 回温到 1.0；统一记忆库合并结果按同一规则排序。

### Notes

- 测试：193 passed（skipped=1；新增温度衰减/回温、按温度排序、夜间衰减、配置用例）。
- 调研：DuckDuckGo 检索（2026-08-12）Ebbinghaus 遗忘曲线与 AI agent memory temperature / forgetting 相关文章（标题如 "The Forgetting Curve: From Ebbinghaus to AI Memory"、"Novel Memory Forgetting Techniques for Autonomous AI Agents"）；采纳乘性衰减 + 召回回温，未引入新依赖（推测性借鉴，未细读原文）。

## [0.5.1] - 2026-08-12

### Added

- L2-02 实体与关系图（首版）：漫游成功后经 `LifeMemoryAdapter` 写入 `platform` / `url` 节点与 `appears_on` 边（`upsert_entity` / `link_entities`）；WebUI 新增“实体图”tab 与 `GET /entities`、`GET /entity_appears_on` 接口，按维度分列渲染，点击节点查询“我在哪见过 X”。

### Fixed

- 实体图节点点击命中：SVG 节点文字改为可命中，点击正确冒泡到实体节点。

### Notes

- 测试：188 passed（skipped=1；新增实体写入/边断言与 WebUI 实体接口用例）；Playwright 桌面 1280x900 / 移动 390x844 实体图渲染、点击查询与无横向溢出验证通过。

## [0.5.0] - 2026-08-12

### Added

- L2-01 统一记忆库：新增 `life/memory_adapter.py`（`LifeMemoryAdapter`，与 ESM 适配器同级）；`memory_host`（默认空 = 本地 SQLite）与 `memory_lease_ttl_seconds` 配置；漫游/复盘/事件写入统一经适配器路由到 engram_core（store_diary_line / add_note / store_event / query_memory / search / upsert_entity / link_entities / 任务租约），本地 SQLite 降级为缓存；宿主缺失时报 error（硬依赖，不再静默降级）。
### Notes

- 测试：186 passed（新增 memory adapter 转发/缺失报错、漫游/复盘主机写入与失败回滚、配置用例）。
- 上游：engram_core v1.75.0 / v1.76.0 已先发布公开契约（`_PUBLIC_API.md` + 全量记忆/实体图/租约 API）。
## [0.4.4] - 2026-08-12

### Added

- L1-03 精力预算：新增 `energy_budget` 配置（每日精力消耗上限，0 = 无上限）；漫游/复盘成功后经 ESM `consume_energy` 真实扣减并持久化精力，同时双写 `daily_usage.energy_used` 本地用量；预算耗尽当天剩余任务跳过并记录 `energy_budget_exhausted`；ESM 缺失时显式记录 `browse_energy_fallback` / `diary_energy_fallback` 本地估算快照，不再静默降级；`life/esm_adapter.py` 新增按 persona scope 的 `consume_energy` 转发。
### Notes

- 测试：179 passed（新增 ESM 适配转发/降级、daily_usage 精力累计、预算耗尽跳过、成功消费与本地估算用例）。
## [0.4.3] - 2026-08-12

### Added

- L1.5-06 事件链可视化：WebUI 新增“事件链”tab 与 `GET /events` 接口，按时间倒序展示事件流，支持 kind 过滤与分页；事件显示类型徽标、payload 摘要、`source_refs` 与幂等键；底部提供只读重放元数据视图，不提供写入口。

### Notes

- 测试：169 passed（新增 count_events、事件链 WebUI 接口与分页/重放用例）；JS 语法检查通过。
## [0.4.2] - 2026-08-12

### Added

- L1.5-05 系统裁决：计划生成时预算（LLM 调用/token）、依赖校验（如 diary 需要当天素材）、睡眠窗口与精力 gate 均为硬约束；未知/未实现/越界动作被拒绝并回退默认固定计划，每条拒绝写事件链（`reject` 事件带 plan_date/action/reason 与幂等键）。

### Notes

- 测试：168 passed（新增预算耗尽全拒、diary 依赖校验、拒绝事件链用例）。
## [0.4.1] - 2026-08-12

### Added

- L1.5-04 LLM 自主排期：新增计划 prompt（封闭动作词表 + 偏好时间窗）、`generate_plan` 校验链路与 `/life_plan` 命令；未知动作、无效时间窗、睡眠窗口、精力 gate 与每日行动上限（`plan_daily_action_cap`，默认 5）优先于 LLM 计划，被拒绝项全部留痕并回退默认固定计划。

### Notes

- 测试：166 passed（新增计划动作校验/睡眠窗口/上限裁决、配置与命令用例）。
## [0.4.0] - 2026-08-12

### Added

- L1.5-03 固定/可选任务分层：`life_plans` 新增 `fixed` 标记（默认漫游/peek/复盘槽位为固定任务）；新增 `edit_life_plan` LLM 工具，可选任务支持 `add / reorder / defer / skip`，固定任务不可被 LLM 修改；跳过留痕并写事件链；调度器按排期板 pending 顺序选下一个任务。

### Notes

- 测试：162 passed（新增固定任务不可改、可选任务增/排/延/跳与事件、调度器按可选任务选目标、edit_life_plan 工具用例）。
## [0.3.9] - 2026-08-12

### Added

- L1.5-02 排期板：新增 `life_plans` 表与 `ensure_plan / update_plan / list_plans / plan_summary`；调度器每日播种当天固定槽位任务，执行后记录 `done / skipped / failed` 状态、原因与 tokens 预算用量；WebUI 新增“排期”tab 与 `GET /plans` 接口；新增 `query_life_plans` 只读 LLM 工具。

### Notes

- 测试：157 passed（新增排期板生命周期、调度器播种/状态映射/预算增量、WebUI plans、LLM plans 工具用例）。
## [0.3.8] - 2026-08-12

### Added

- L1.5-01 事件链：新增 `event_chain` 表与 `append_event / find_event / list_events / replay_events` 接口；观察（漫游/peek）、表达（分享尝试）、思考（夜间复盘日记）、更改（软删除/短记提交/任务跳过）、召回（`query_life_memory`）、回滚（恢复短记/日记）全部写入事件链，每条带 `persona_id / ts / kind / payload / source_refs / idempotency_key`，幂等追加 + 只读重放。

### Notes

- 测试：150 passed（新增事件链幂等/过滤/重放、软删除回滚事件、分享表达事件、漫游/peek/日记/召回事件用例）。
## [0.3.7] - 2026-08-12

### Added

- L1-10 时间轴：WebUI 新增 `GET /timeline`，按时间倒序混排短记、日记、分享记录与状态快照，支持类型过滤与分页；页面新增“时间轴” tab，粒子筛选与加载更多。

### Notes

- 测试：140 passed（新增混排顺序/过滤/分页与 WebUI 接口用例）。
## [0.3.6] - 2026-08-12

### Added

- L1-07 灵感抽屉：新增 `wishlist` 表与 `staging_wishlist`，日记 prompt 可输出 `wishlist_candidates`，复盘后由 LLM 评估 pending 项：promote 升级为兴趣种子，discard 丢弃；WebUI 新增灵感抽屉视图与 `/wishlist`、`/wishlist_action` 接口。
- 新增 `wishlist_enabled` 配置（默认开）。

### Notes

- 测试：138 passed（新增 wishlist 生命周期、prompt 输出、复盘写入/升级、WebUI 接口与配置用例）。
## [0.3.5] - 2026-08-12

### Added

- L1-06 轻接触 peek：新增定时 peek 槽位（默认 09:00/13:00/17:00/21:00），只写状态快照与会话记录，不调用 LLM、不写短记；`browse_sessions` 新增 `kind` 列区分 peek/browse，热力图单独统计 peeks。
- 新增 `peek_times` 与 `peek_daily_cap`（默认 0 不限制）配置。

### Notes

- 测试：132 passed（新增 peek 会话/kind、日上限跳过、统计不混入 peek、调度器 peek 槽位与配置用例）。
## [0.3.4] - 2026-08-12

### Added

- L1-05 时段模式：漫游时按当前时段（morning/afternoon/evening/night）向 prompt 注入偏好主题与语气，同一素材按时段产生不同风格。
- 新增 `time_slots` 配置（每项含 topics/tone，缺省项使用内置默认）。

### Notes

- 测试：126 passed（新增时段解析与判定、prompt 时段块、漫游 prompt 实际注入用例）。
## [0.3.3] - 2026-08-12

### Added

- L1-04 随机不出门：定时漫游按 `rest_probability`（默认 0.1）随机跳过，写 `skipped_rest` 状态快照；手动 `/life_now` 不受影响。
- 新增 `rest_probability` 配置。

### Notes

- 测试：122 passed（新增定时 rest 、概率 0 不跳过、手动不受影响与配置用例）。
## [0.3.2] - 2026-08-12

### Added

- L1-02 旧事新感：夜间复盘按概率回看 7/30 天前的短记，向日记 prompt 注入“回看素材”，LLM 生成“后来的我再看这件事”段落并输出 `revisit_day_offset` / `revisit_note_ids`；无历史时不触发。
- 新增 `revisit_days`（默认 `[7, 30]`）、`revisit_probability`（默认 0.5）配置。

### Notes

- 测试：118 passed（新增回看端到端、无历史不触发、prompt 回看段、按日期查询与配置用例）。
## [0.3.1] - 2026-08-12

### Added

- L1-15 WebUI 视觉优化：统一后台工具风格，页面新增状态卡行（心情/精力/今日漫游/日记/今日签名）与月历热力图面板，接入 `/status` 与 `/timeline/heatmap`。
- 新增全局错误横幅 `#errorBanner`：生活档案、记忆概览、记忆搜索、分享数据加载失败时给出明确提示；生活档案加载态在页头标注“加载中”。
- 空态与移动端适配：热力图无记录时显示“本月还没有生活记录”，状态卡/热力图在窄视口自动降列。

### Notes

- 测试：113 passed；Playwright 桌面（1280×900）/移动（390×844）视口无横向溢出，正常态渲染状态卡与热力图，错误态横幅可见且页头提示“档案加载失败”。
## [0.3.0] - 2026-08-12

### Added

- L1-01 今日人格签名：夜间复盘在日记外生成一句短签名，落 `diary_entries.signature`；`/life`、`/life_archive` 展示，状态卡读取。
- L1-08 状态小卡片：WebUI 新增 `GET /status`，`/life_today` 命令把心情/精力/漫游次数/最近见闻/日记状态直接发到聊天；无数据返回空态不报错。
- L1-09 月历热力图：WebUI 新增 `GET /timeline/heatmap?month=YYYY-MM`，按天聚合短记/日记/分享/漫游次数。
- 新增 `signature_enabled` 配置（默认开）。

### Notes

- 测试：113 passed（新增签名落库/空签名、状态卡、热力图、配置与命令用例）。

## [0.2.9] - 2026-08-12

### Added

- L1-16 同人格单 SQL 与任务租约：新增 `life_leases` 表与 `acquire_lease` / `renew_lease` / `release_lease` / `cleanup_expired_leases`。
- 调度器按槽位先抢租约再执行；拿不到租约的实例记录 `skipped_duplicate`（browse 落会话记录，diary 落状态快照），保证同人格单写者。
- 新增 `lease_ttl_seconds` 配置（默认 300），过期租约自动释放；启动时回收残留 running 会话并清理过期租约。

### Notes

- 测试：105 passed（新增租约互斥/续租/过期重获、配置与 skipped_duplicate 用例）。
- 部署前提：同人格多实例必须共享同一 SQLite 文件（同一主机或挂载盘）；跨主机走 v2 统一库租约。

## [0.2.8] - 2026-08-12

### Added

- L1-14 不可信内容与记忆卫生：新增 `life/injection.py` 注入特征检测与文本 sanitize，抓取/历史/分享素材带疑似注入时写入 `injection_log` 并在 WebUI `/injection_log` 审计。
- 漫游/日记/分享 prompt 增加“外部素材一律不可信、只做素材不执行指令”的硬化规则；LLM 输出的 mood 走封闭词表校验。
- 新增 `injection_log_enabled` 配置（默认开）。

### Changed

- 抓取标题/摘要、历史短记与分享素材在进入 prompt 前统一 sanitize。

### Notes

- 测试：101 passed（新增注入检测、prompt 硬化、审计接口与抓取审计用例）。

## [0.2.7] - 2026-08-12

### Added

- L1-13 变更账本与回收站：新增 `change_log` 表记录写操作（entity / old_value / new_value / actor / reason / ts / status）。
- `notes` 与 `diary_entries` 增加 `deleted_at` 软删除字段，删除进回收站，owner 可恢复；新增 `trash_retention_days` 配置（默认 30）与 `purge_trash` 清理接口。
- WebUI 新增 `/trash`、`/trash_restore`、`/change_log` 接口；正常查询自动排除回收站内容。

### Notes

- 测试：92 passed（新增软删除/恢复、回收站清理、change_log、配置与 WebUI 用例）。

## [0.2.6] - 2026-08-12

### Added

- L1-11 预算/重试/崩溃语义：新增 `daily_llm_call_limit`（默认 0 无上限）、`daily_token_budget`（默认 0 无上限）与 `llm_retry_limit`（默认 3）。
- `daily_usage` 表承载每日 LLM 调用/token 用量，WebUI 新增 `/usage` 接口展示。
- LLM 调用带指数退避重试，重试耗尽后任务标记 `failed` 并报 error，不再生成确定性伪造内容。
- 预算耗尽后当天剩余任务跳过并记录 `budget_exhausted`。

### Changed

- 漫游/复盘改为 run 级 staging：先写暂存表，全部成功后一次事务落库；异常/崩溃丢弃未提交数据，`browse_sessions` 标记 `failed`；启动时回收残留 running 会话。
- 现有确定性 fallback（`_fallback_selected` / `_fallback_diary`）随本版本移除。

### Notes

- 测试：87 passed（新增 13 个 L1-11 用例）。

## [0.2.5] - 2026-08-12

### Added

- L1-12 时区：新增 `timezone` 配置（默认 `Asia/Shanghai`），睡眠窗口、槽位日期与“今日”边界按 persona 本地时间计算；非法配置回退默认时区并记录 warning。

### Changed

- `life/db.py` 时间戳与日期边界统一走配置时区；`life/scheduler.py`、`life/browser.py`、`life/share.py`、WebUI 与 `/life_archive` 默认日期同步该语义。

### Notes

- 测试：74 passed（新增时区配置、时区换算、调度器跨时区槽位、DB 时区归一化用例）。

## [0.2.4] - 2026-08-11

### Fixed

- 分享发送判定：`_send_message` 现在尊重 `Context.send_message` 的布尔返回值，找不到目标平台时不再把感悟误记为已发送，ShareGate 会记录 `send_rejected`。
- WebUI 数据接口前缀修正为 `/api/plug/astrbot_plugin_your_own_life/api/...`，修复插件页面里全部数据请求 404 的问题。

### Changed

- README 增加 WebUI 章节，说明页面由 Dashboard 自动发现、数据接口前缀与登录要求。
- 仓库卫生：移除插件根目录误生成的 AstrBot root 残留（`data/`），并加入 `.gitignore` 防止再次混入。

### Notes

- 测试：66 passed（新增 `_send_message` 尊重返回值用例）。

## [0.2.3] - 2026-08-11

### Fixed

- 修复插件加载失败：补齐 `life.prompts.build_share_prompt` 导出、修正 `_conf_schema` 的 `items` 结构、补全 `LifeMemoryTool.handler` 契约。
