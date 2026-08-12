# 开发日志

每个工作段结束（或上下文可能压缩/跨会话前）追加一条，最新条目放最上面。条目至少包含：目标、已确认决策、改动文件、验证结果、遗留问题、下一步行动。

## 2026-08-12 L2-02 实体与关系图落地（v0.5.1）

- 目标：漫游成功后把信息来源固化为分层实体图（`platform / url` 节点 + `appears_on` 边），WebUI 提供按维度分列的实体图与“我在哪见过 X”查询。
- 已确认决策：platform/url 节点只能由系统从漫游结果写入（经 `LifeMemoryAdapter.upsert_entity` / `link_entities`），URL 用 hash 作 `entity_id` 并带 `canonical_url`；`appears_on` 边 weight 1.0；宿主缺失时捕获 `MemoryHostError` 记 warning，不影响漫游主流程；WebUI 新增“实体图”tab 与 `GET /entities`、`GET /entity_appears_on`，节点点击查询聚合平台。
- 改动：`life/browser.py`、`life/webui.py`、`pages/life/index.html`、`tests/test_browser.py`、`tests/test_webui.py`；版本 v0.5.0 → v0.5.1；README / CHANGELOG / features.md L2-02 / design.md / roadmap.md 同步。
- 验证：unittest 188 passed（skipped=1；新增实体写入/边断言与 WebUI 实体接口用例）；Playwright 桌面 1280x900 / 移动 390x844 实体图渲染、点击查询与无横向溢出通过。
- 遗留：语义维度（person/project/community/topic）、`entity_mentions` 共现、`same_as` owner 确认与印象摘要未实现，留待 L2 后续；实体写入仅在配置 `memory_host` 后生效。
- 下一步：L2-03 记忆温度（`memory_temperature_decay` + 温度衰减/召回加权）。

## 2026-08-12 L2-01 统一记忆库落地（v0.5.0）

- 目标：`store_event / add_note / store_diary / upsert_entity / link_entities / query_memory / search` 全部经 `LifeMemoryAdapter` 路由到统一记忆宿主；宿主缺失报 error，不再静默降级；本地 SQLite 降级为缓存。
- 已确认决策：
  - 上游 engram_core 先行发布版本化公开契约：v1.75.0（`store_diary_line` / `query_recent_memory` / `claim_task` / `renew_task` / `release_task` / `task_lease_owner` + `TaskLeaseStore`）、v1.76.0（`store_event` / `add_note` / `query_memory` / `search` / `upsert_entity` / `link_entities` / `list_entities` / `list_links` + `LifeGraphStore` 分层维度实体图），均含 `_PUBLIC_API.md` 与 smoke 测试。
  - 下游：新增 `life/memory_adapter.py`（`LifeMemoryAdapter` + `MemoryHostError`）；`LifeConfig` / `_conf_schema.json` 新增 `memory_host`（默认空 = 本地 SQLite 权威）与 `memory_lease_ttl_seconds`；`LifeService` 注入 memory，复盘/漫游/事件写入经 adapter（`store_diary_line` / `add_note` / `store_event`），失败抛 `MemoryHostError` 且不落本地；`query_life_memory` 工具与 WebUI `memory_search` 在配置 host 后合并统一库结果。
- 改动：`life/memory_adapter.py`（新增）、`life/config.py`、`_conf_schema.json`、`life/browser.py`、`life/life_tool.py`、`life/webui.py`、`main.py`、`tests/test_memory_adapter.py`（新增）、`tests/test_browser.py`、`tests/test_config.py`；版本 v0.4.4 → v0.5.0；README / CHANGELOG / features.md L2-01 / design.md / roadmap.md / requirements.md 同步。
- 验证：unittest 186 passed（skipped=1；新增 adapter 转发/缺失报错、browse/diary 主机写入与失败回滚、配置用例）；engram_core smoke 66 项仅 `_smoke_v36.py` 基线既有失败（已取证与本次改动无关）。
- 遗留：`memory_host` 默认关闭，未配置时仍走本地 SQLite；实体图/租约 API 已就绪，L2-02 实体关系图与 L2-09 多实例租约待接入；WebUI 实体图视图未做。
- 下一步：L2-02 实体与关系图（adapter 实体写入 + WebUI 实体图视图 + “我在哪见过 X”）。

## 2026-08-12 L1-03 精力预算落地（v0.4.4）

- 目标：每日漫游/复盘真实消耗并持久化精力，预算耗尽当天剩余任务跳过并记录；ESM 未提供 `consume_energy` 时显式本地估算，不再静默降级。
- 已确认决策：
  - ESM 上游先发兼容版本：v0.11.0 新增 `consume_energy(amount, reason, scope=None) -> float`（已提交，含 `_PUBLIC_API.md` / CHANGELOG / 测试）。
  - 下游：`life/esm_adapter.py` 新增按 persona scope 的 `consume_energy(persona_id, amount, reason)`，`get_energy` / `gate_energy` 接受 persona_id；`daily_usage` 新增 `energy_used` 列（建表 + ALTER 迁移）与 `increment_energy_usage`；`LifeConfig` / `_conf_schema.json` 新增 `energy_budget`（默认 0 = 无上限）。
  - 消费点：漫游成功后 0.15、复盘有素材时 0.2；成功后 ESM 扣减 + 本地双写；ESM 缺失时写 `browse_energy_fallback` / `diary_energy_fallback` 快照显式标注本地估算。
  - 预算检查：browse/diary 入口先查 `daily_usage.energy_used >= energy_budget`，命中则跳过并记录 `energy_budget_exhausted`（会话/快照 + `change` 事件）。
- 改动：`life/db.py`、`life/config.py`、`_conf_schema.json`、`life/esm_adapter.py`、`life/browser.py`、`life/share.py`、`tests/test_db.py`、`tests/test_esm_adapter.py`、`tests/test_browser.py`、`tests/test_config.py`；版本 v0.4.3 → v0.4.4；README / CHANGELOG / features.md L1-03 / design.md / roadmap.md / requirements.md 同步。
- 验证：unittest 179 passed（skipped=1；新增 ESM 转发/降级、精力累计、预算耗尽跳过、成功消费与本地估算用例）；UTF-8 读回校验无乱码。
- 遗留：`budget_used`（排期板）仍按 tokens 增量，不含精力维度；消费金额为固定常量，未做任务时长/强度调制。
- 下一步：L2 统一记忆库——先为 engram_core 补 `_PUBLIC_API.md` 与公开方法（store_diary_line / query_recent_memory / claim_task / renew_task / release_task），再落地 `life/memory_adapter.py` 与 L2 各子项。

## 2026-08-12 上游契约复审计（第二次）

- 复审计结果：ESM 仍为 v0.10.4、源码无 `consume_energy`；engram_core 仍为 1.74.0（HEAD `8dc41f2`）、无 `_PUBLIC_API.md`。L1-03 与 L2 闸门未解锁。
- 决策：把 `LifeMemoryAdapter`（store_diary_line / query_recent_memory / claim_task / renew_task / release_task）与 ESM `consume_energy` 的适配层接口草案写入 `docs/requirements.md`，仅作设计、不实现，等待上游契约定稿。
- 改动：`docs/requirements.md`（适配层接口草案）、`docs/devlog.md`；纯文档，不 bump 版本。
- 验证：UTF-8 读回无乱码。
- 下一步：上游发布后按草案落地；在此之前不再新增下游实现。
## 2026-08-12 上游契约审计与提案

- 目标：确认剩余阶段（L1-03 / L2）的解锁条件，并把契约提案落盘供上游协调。
- 已核实：ESM 本地 v0.10.4 `_PUBLIC_API.md` 仅公开 `get_bot_energy`，源码无 `consume_energy`（L1-03 保持 blocked）；engram_core 本地 1.74.0 无 `_PUBLIC_API.md`（L2 不开工）。
- 决策：在 `docs/requirements.md` 落“待上游落地的契约提案”：ESM `consume_energy(amount, reason, scope=None) -> float`（v0.11 契约）；engram_core `_PUBLIC_API.md` 覆盖日记写入/召回/任务租约三组签名；发布兼容版本前不写下游实现，避免契约未定返工。
- 改动：`docs/requirements.md`（兼容矩阵本插件版本 v0.2.4 → v0.4.3 + 契约提案 + 对齐闸门）、`docs/devlog.md`；纯文档，不 bump 版本。
- 验证：UTF-8 读回无乱码。
- 下一步：等 ESM `consume_energy` 与 engram_core `_PUBLIC_API.md` 上游发布后，落地 L1-03 与 L2（`life/memory_adapter.py` 起步）。
## 2026-08-12 L1.5-06 事件链可视化落地（L1.5 完成）

- 目标：WebUI 按时间倒序展示事件流，事件带类型徽标、来源与可下钻 payload；只读视图支持 kind 过滤、分页与重放元数据。
- 决策：DB 新增 `count_events`；WebUI 新增 `GET /events`（kinds/limit/offset + `replay.read_only` 只读重放前 20 条）；页面新增“事件链”tab：类型徽标、payload 摘要、`source_refs`、幂等键与“重放元数据（只读）”面板；顺手统一 `replay_events(persona_id, kinds, limit)` 参数顺序。
- 改动：`life/db.py`、`life/webui.py`、`pages/life/index.html`、`tests/test_db.py`、`tests/test_webui.py`；版本 v0.4.2 → v0.4.3；README / CHANGELOG / features.md L1.5-06 / design.md / roadmap.md 同步（L1.5 整族标记完成）。
- 验证：unittest 169 passed（skipped=1；新增 count_events 与事件链 WebUI 接口/重放用例）；JS 语法检查通过。
- 遗留：事件 payload 目前按文本摘要展示，未做结构化下钻渲染；重放为只读列表，重建状态机待 L2 检查点。
- 下一步：L2 需先对齐上游 `_PUBLIC_API.md`（统一记忆库/engram_core）并整族协调；L1-03 精力预算继续等 ESM `consume_energy` 契约。
## 2026-08-12 L1.5-05 系统裁决落地

- 目标：预算、精力、依赖校验与睡眠窗口始终是硬约束；越界动作拒绝并回退计划；所有拒绝写事件链。
- 决策：`generate_plan` 裁决顺序固定为：预算耗尽（budget_exhausted）→ 非词表（unknown_action）→ 未实现动作（not_supported_yet）→ 每日行动上限（daily_action_cap）→ 依赖校验（dependency_not_met，diary 需当天短记）→ 时间窗格式（invalid_window）→ 睡眠窗口（sleep_window）→ 精力 gate（energy_gate）→ 重复（duplicate）；每条拒绝通过 `_record_plan_rejection` 写 `change/reject` 事件链（幂等键 `plan/{date}/reject/{action}/{n}`）。
- 改动：`life/browser.py`（`_apply_plan_payload` 硬约束 + `_record_plan_rejection` + `_plan_dependency_ok`）、`tests/test_browser.py`；版本 v0.4.1 → v0.4.2；README / CHANGELOG / features.md L1.5-05 / design.md / roadmap.md 同步。
- 验证：unittest 168 passed（skipped=1；新增预算耗尽全拒、diary 依赖校验、拒绝事件链用例）。
- 遗留：词表内未实现动作仍为 not_supported_yet（需 L1.5-04 后续执行实现）；执行期预算/精力由既有 run 路径兜底。
- 下一步：L1.5-06 事件链可视化（WebUI 时间倒序事件流 + kind 过滤 + 分页 + source_refs）。
## 2026-08-12 L1.5-04 LLM 自主排期落地

- 目标：LLM 产出封闭动作词表与偏好时间窗，系统决定精确时刻；未知动作拒绝并回退默认固定计划。
- 决策：`PLAN_ACTION_VOCABULARY` 常量 + `build_plan_prompt`（排期板/睡眠窗口/动作上限注入）；`LifeService.generate_plan` 走预算受控 LLM 调用，`_apply_plan_payload` 依次裁决：非词表（unknown_action）→ 未实现动作（not_supported_yet）→ 每日上限（daily_action_cap）→ 时间窗格式（invalid_window）→ 睡眠窗口（sleep_window）→ 精力 gate（energy_gate）；通过后取窗口中点落库为可选任务；新增 `plan_daily_action_cap` 配置（默认 5）与 `/life_plan` 命令。
- 改动：`life/prompts.py`、`life/browser.py`、`life/config.py`、`_conf_schema.json`、`main.py`、`metadata.yaml`（help）、`tests/test_browser.py`、`tests/test_config.py`、`tests/test_commands.py`；版本 v0.4.0 → v0.4.1；README / CHANGELOG / features.md L1.5-04 / design.md / roadmap.md 同步。
- 验证：unittest 166 passed（skipped=1；新增计划动作校验/睡眠窗口/上限裁决、配置与命令用例）。
- 遗留：词表内 revisit/signature/share/rest/surprise/memory_review 尚未有执行实现，当前标记 not_supported_yet；能量 gate 在生成期一次性裁决，执行期仍由既有 browse/diary gate 兜底。
- 下一步：L1.5-05 系统裁决（预算/依赖校验硬约束 + 所有拒绝写事件链）。
## 2026-08-12 L1.5-03 固定/可选任务分层落地

- 目标：固定任务只有 owner 可改，可选任务 LLM 可 `add / reorder / defer / skip`，跳过留痕，系统按依赖顺序执行。
- 决策：`life_plans` 新增 `fixed` 列（默认漫游/peek/复盘槽位 seed 为固定任务）；DB 新增 `add_optional_plan / reorder_plan / defer_plan / skip_plan`，固定任务一律拒绝修改并写事件链；新增 `edit_life_plan` LLM 工具（kind 限 browse/peek/diary，add 缺省 23:59，reorder 为 1-based 位置且不可越过固定任务）；调度器 `next_target` 改为优先按当天 pending 排期板选目标，fallback 配置槽位，并返回 `task_id` 供记账。
- 改动：`life/db.py`、`life/scheduler.py`、`life/life_tool.py`、`main.py`、`tests/test_db.py`、`tests/test_scheduler.py`、`tests/test_life_tool.py`；版本 v0.3.9 → v0.4.0；README / CHANGELOG / features.md L1.5-03 / design.md / roadmap.md 同步。
- 验证：unittest 162 passed（skipped=1；新增固定任务不可改、可选增/排/延/跳与事件、按可选任务选目标、edit_life_plan 工具用例）。
- 遗留：reorder 目前通过交换 `scheduled_at` 实现，固定任务不可位移；可选任务 kind 暂限可执行类型，revisit/surprise/memory_review 等动作词表在 L1.5-04 扩展。
- 下一步：L1.5-04 LLM 自主排期（动作词表 + 偏好时间窗 + `/life_plan`）。
## 2026-08-12 L1.5-02 排期板落地

- 目标：`life_plans` 运行时视图，任务带状态、预算用量与原因，LLM 可只读查看“做完没/还剩多少”。
- 决策：新增 `life_plans` 表（`persona_id, plan_date, task_id, kind, status, reason, budget_used, scheduled_at, finished_at`，`(persona_id, plan_date, task_id)` 唯一）；调度器每日播种当天固定槽位为 pending，执行后按结果记账（done/skipped/failed + reason），`budget_used` 取任务前后 `daily_usage.tokens` 增量；WebUI 新增 `/plans` 接口与“排期”tab；新增 `query_life_plans` 只读工具（增删改/可换序工具属 L1.5-03/04）。
- 改动：`life/db.py`、`life/scheduler.py`、`life/webui.py`、`life/life_tool.py`、`main.py`、`pages/life/index.html`、`tests/test_db.py`、`tests/test_scheduler.py`、`tests/test_webui.py`、`tests/test_life_tool.py`；版本 v0.3.8 → v0.3.9；README / CHANGELOG / features.md L1.5-02 / design.md / roadmap.md 同步。
- 验证：unittest 157 passed（skipped=1；新增排期板生命周期、调度器播种/状态映射/预算增量、WebUI plans、LLM plans 工具用例）；JS 语法检查通过。
- 遗留：LLM 可加/可换序/跳过工具属 L1.5-03/04；`budget_used` 目前按 tokens 增量，不含精力等维度。
- 下一步：L1.5-03 固定/可选任务分层（fixed 标记 + owner 权限）。
## 2026-08-12 L1.5-01 事件链落地

- 目标：append-only 事件流，观察/表达/思考/更改/召回/回滚全部归位，支持幂等追加与只读重放。
- 决策：新增 `event_chain` 表（`persona_id, ts, kind, payload, source_refs, idempotency_key`，`(persona_id, idempotency_key)` 唯一）；`append_event` 幂等追加，`find_event / list_events / replay_events` 只读接口；事件写入点：漫游成功（observe + change）、peek（observe）、夜间复盘（think）、分享尝试（express）、软删除（change）/恢复（rollback）、任务跳过（change）、`query_life_memory` 召回（recall）；重放为只读重建，写侧幂等由唯一键 + 既有租约/唯一约束兜底。
- 改动：`life/db.py`（`event_chain` 表 + 事件接口 + soft_delete/restore/share 接入）、`life/browser.py`（漫游/peek/复盘/跳过事件）、`life/life_tool.py`（召回事件）、`tests/test_db.py`、`tests/test_browser.py`、`tests/test_life_tool.py`；版本 v0.3.7 → v0.3.8；README / CHANGELOG / features.md L1.5-01 / design.md / roadmap.md 同步。
- 验证：unittest 150 passed（skipped=1；新增事件链幂等/过滤/重放、软删除回滚、分享表达、漫游/peek/日记/召回事件用例）。
- 遗留：事件链 WebUI 可视化属 L1.5-06；`add_diary` 直写等非主路径尚未全部接事件；重放目前只读，重建状态机待 L2 检查点阶段。
- 下一步：L1.5-02 排期板（`life_plans`）。
## 2026-08-12 L1-03 精力预算标记 blocked

- 决策：L1-03 依赖 ESM `consume_energy` 或等效公开方法（`docs/requirements.md` 未实现），按 features.md 允许的“上游 API 未实现前不交付”处置，在 features.md 明确标记 blocked 并留待上游契约同批。
- 改动：`docs/features.md` L1-03 状态与开发顺序标注；本条为纯文档，不 bump 版本。
- 验证：UTF-8 读回无乱码。
- 下一步：L1.5-01 事件链（append-only 流，含 idempotency_key 与重放）。
## 2026-08-12 L1-10 时间轴落地

- 目标：按时间倒序混排四类生活记录，让历史可翻阅。
- 决策：数据层新增 `timeline()` 混排（每源取 limit+offset 窗口再全局切片，确保分页语义）；WebUI `GET /timeline?types=&limit=&offset=`；页面新增“时间轴” tab，粒子筛选 + 加载更多；保持 vanilla JS。
- 改动：
  - `life/db.py`：新增 `timeline(persona_id, types, limit, offset)`。
  - `life/webui.py`：新增 `/timeline` 接口与路由。
  - `pages/life/index.html`：新增时间轴 tab、类型筛选、时间流列表与加载更多。
  - 版本 v0.3.6 → v0.3.7；README / CHANGELOG / features.md L1-10 / design.md / roadmap.md 同步。
- 验证：unittest 140 passed（新增混排顺序、类型过滤、分页与 WebUI 接口用例）；JS 语法检查通过。
- 遗留：时间轴每源窗口取整体前 limit+offset，极大历史时未做引擎级床索；后续可加日期筛选与无限分页。
- 下一步：L1-03 精力预算（等 ESM 契约）；L1 剩余项全部完成后进 L1.5 事件链与排期板。
## 2026-08-12 L1-07 灵感抽屉落地

- 目标：让 LLM 把“也许有用但今天不展开”的想法放入可回看的 wishlist，并定期评估。
- 决策：新增 `wishlist` / `staging_wishlist` 表；日记 prompt 输出增 `wishlist_candidates`，复盘成功后一并落库；再由专用评估 prompt 对 pending 项做 promote/discard，promote 同时写入兴趣表；评估失败不影响日记，保留 pending。
- 改动：
  - `life/db.py`：新增 `wishlist` / `staging_wishlist` 表、`stage_wishlist` / `list_wishlist` / `update_wishlist_status` 与 commit 集成。
  - `life/prompts.py`：日记输出增 `wishlist_candidates`；新增 `build_wishlist_eval_prompt`。
  - `life/browser.py`：新增 `_wishlist_candidates` 与 `_evaluate_wishlist`，复盘流程接入。
  - `life/webui.py` / `pages/life/index.html`：新增 `/wishlist`、`/wishlist_action` 与灵感抽屉视图。
  - `life/config.py` / `_conf_schema.json`：新增 `wishlist_enabled`。
  - 版本 v0.3.5 → v0.3.6；README / CHANGELOG / features.md L1-07 / design.md / roadmap.md 同步。
- 验证：unittest 138 passed（新增 wishlist 生命周期、prompt 输出、复盘写入/升级、WebUI 接口与配置用例）。
- 遗留：灵感评估仅在复盘成功后触发，不另设独立调度任务；后续可在 L1.5 排期板中将其作为可选任务。
- 下一步：L1-03 精力预算（等 ESM 契约）→ L1-10 时间轴。
## 2026-08-12 L1-06 轻接触 peek 落地

- 目标：高频低成本“路过”，让状态快照更密集，不产生短记。
- 决策：`browse_sessions` 新增 `kind` 列（默认 browse）区分 peek/browse；peek 不调用 LLM、不写 notes，只写 会话记录 + `state_snapshots.activity='peek'`；调度器接受 `peek_times` 与 `peek_daily_cap`；overview/status 统计不混入 peek，热力图单独计 peeks。
- 改动：
  - `life/db.py`：`browse_sessions` 增 `kind` 列（含 ALTER），`start_browse_session(kind=...)`、`count_sessions_by_kind`；overview/status/heatmap 调整统计。
  - `life/browser.py`：新增 `run_peek`（不调 LLM，受日上限限制）。
  - `life/scheduler.py`：新增 peek 槽位与执行分支。
  - `life/config.py` / `_conf_schema.json`：新增 `peek_times` / `peek_daily_cap`。
  - `pages/life/index.html`：热力图计入 peeks。
  - 版本 v0.3.4 → v0.3.5；README / CHANGELOG / features.md L1-06 / design.md / roadmap.md 同步。
- 验证：unittest 132 passed（新增 peek 会话/kind、日上限跳过、统计不混入 peek、调度器 peek 槽位与配置用例）。
- 遗留：peek 目前不获取热度/标题数据（只更新状态）；后续可选择性接入低成本信息源观察。
- 下一步：L1-03 精力预算（等 ESM 契约）→ L1-07 灵感抽屉 → L1-10 时间轴。
## 2026-08-12 L1-05 时段模式落地

- 目标：同一素材在不同时段以不同偏好与语气见解。
- 决策：`time_slots` 为可配置字典，默认提供 morning/afternoon/evening/night 四段；时段块作为可选素材注入选择 prompt，不改变规则与 JSON schema；配置缺失时不注入，回退默认语气。
- 改动：
  - `life/config.py`：新增 `DEFAULT_TIME_SLOTS` / `_parse_time_slots` / `current_time_slot` 与 `time_slots` 字段。
  - `life/prompts.py`：`build_select_prompt` 新增可选 `time_slot`，有值时注入“当前时段偏好”块。
  - `life/browser.py`：漫游时按本地时间计算当前时段并传递。
  - `_conf_schema.json`：新增 `time_slots`。
  - 版本 v0.3.3 → v0.3.4；README / CHANGELOG / features.md L1-05 / design.md / roadmap.md 同步。
- 验证：unittest 126 passed（新增时段解析与判定、prompt 时段块、漫游 prompt 实际注入用例）。
- 遗留：时段只影响选择 prompt，日记 prompt 尚未注入时段语气；后续可选择性扩展。
- 下一步：L1-03 精力预算（等 ESM 契约）→ L1-06 peek → L1-07 灵感抽屉 → L1-10 时间轴。
## 2026-08-12 L1-04 随机不出门落地

- 目标：定时漫游有概率跳过，让 bot 偶尔躺平但留下迹迹。
- 决策：在 `run_browse_session` 对 scheduled 且非 force 触发按 `rest_probability` 掷签，命中时写 `skipped_rest` 快照并返回，不产生漫游会话与短记；手动 `/life_now` 不受影响。
- 改动：
  - `life/config.py` / `_conf_schema.json`：新增 `rest_probability`（默认 0.1）。
  - `life/browser.py`：`run_browse_session` 新增 rest 判定，命中时写 `skipped_rest` 快照并返回 `BrowseResult("rest", "rest_probability")`。
  - 版本 v0.3.2 → v0.3.3；README / CHANGELOG / features.md L1-04 / design.md / roadmap.md 同步。
- 验证：unittest 122 passed（新增定时 rest 、概率 0 不跳过、手动不受影响与配置用例）。
- 遗留：日记依然只通过“今天没出门”空日记文案反映，暂未显式引用 `skipped_rest`；后续可在复盘 prompt 中注入当天 rest 状态。
- 下一步：L1-03 精力预算（等 ESM 契约）→ L1-05 时段模式 → L1-06 peek → L1-07 灵感抽屉 → L1-10 时间轴。
## 2026-08-12 L1-02 旧事新感落地

- 目标：夜间复盘随机回看 7/30 天前短记，让日记出现“后来的我再看这件事”。
- 决策：回看作为可选素材注入原日记 prompt，不额外增加 LLM 调用；无历史时不触发，走现有空日记不变；回看素材同样可信化处理。
- 改动：
  - `life/config.py` / `_conf_schema.json`：新增 `revisit_days`（默认 `[7, 30]`）、`revisit_probability`（默认 0.5）。
  - `life/prompts.py`：`build_diary_prompt` 新增可选 `revisit` / `revisit_day`，输出 schema 新增 `revisit_day_offset` / `revisit_note_ids`。
  - `life/browser.py`：`LifeService` 新增可注入随机源，`_pick_revisit` 按概率选日并查历史短记，日记无今日短记但有回看短记时也调用 LLM；快照 extra 与返回值记录回看日期/数量。
  - 版本 v0.3.1 → v0.3.2；README / CHANGELOG / features.md L1-02 / design.md / roadmap.md 同步。
- 验证：unittest 118 passed（新增回看端到端、无历史不触发、prompt 回看段、按日期查询与配置用例）；UTF-8 读回无乱码。
- 遗留：冷启动期判定未接入，等冷启分方向落地后再控制新 persona 是否触发回看；回看只取短记，不包含旧日记引用。
- 下一步：L1-03 精力预算（等 ESM 契约）→ L1-04 随机不出门 → L1-05 时段模式 → L1-06 peek → L1-07 灵感抽屉 → L1-10 时间轴。
## 2026-08-12 L1-15 WebUI 视觉优化落地

- 目标：统一后台工具风格：排版、空态、错误态、加载态、移动端适配；为状态卡/热力图提供可用的视觉层。
- 决策：保持 vanilla HTML/CSS/JS 零前端依赖；错误横幅全局复用，生活档案失败时页头改“档案加载失败”；状态卡/热力图失败静默保留占位（不掩盖主档案错误）；热力图按月份本地聚合渲染，无记录显示空态。
- 改动：
  - `pages/life/index.html`：新增状态卡行（心情/精力/今日漫游/日记/今日签名，接 `/status`）、月历热力图面板（接 `/timeline/heatmap`）、`#errorBanner`、加载态“加载中”、空态文案与移动端断点样式；`loadLife()` 并行拉取 overview/status/heatmap，各数据加载失败进入 catch。
  - 版本 v0.3.0 → v0.3.1；README / CHANGELOG / features.md L1-15 / design.md / roadmap.md 同步。
- 验证：unittest 113 passed；Playwright 自托管静态服务 + route mock：桌面 1280×900 与移动 390×844 无横向溢出，正常态 37 个热力格且状态卡渲染，错误态 `#errorBanner` 可见、meta 提示“档案加载失败”。
- 遗留：L1-10 时间轴视图未落地（依赖混排接口，单独排期）；状态卡/热力图失败目前静默，主档案失败才出横幅，后续可细化分区错误提示。
- 下一步：L1 剩余项按 features.md 顺序推进：L1-03 精力预算（等 ESM 契约）→ L1-02 旧事新感 → L1-04 随机不出门 → L1-05 时段模式 → L1-06 peek → L1-07 灵感抽屉 → L1-10 时间轴。
## 2026-08-12 高体感第一批：L1-01/08/09 落地

- 目标：今日签名、状态小卡片、月历热力图三个“一眼可感知”视图先落地，为 WebUI 视觉优化打底。
- 决策：签名随夜间复盘生成（素材不足留空），落 `diary_entries.signature`；状态卡零 schema 变更，`/life_today` 复用同一数据源；热力图按本地日期聚合四类计数。
- 改动：
  - `life/db.py`：`diary_entries`/`staging_diary` 增加 `signature`（含旧库 ALTER），`add_diary`/`stage_diary`/`commit_staged` 透传；新增 `get_status`、`timeline_heatmap`。
  - `life/prompts.py`：日记 prompt 输出增加 `signature` 字段与规则。
  - `life/browser.py`：夜间复盘生成并暂存签名（受 `signature_enabled` 控制）。
  - `life/webui.py`：新增 `/status`、`/timeline/heatmap`。
  - `main.py`：新增 `/life_today`；`/life` 与 `/life_archive` 展示签名。
  - `life/config.py` / `_conf_schema.json`：新增 `signature_enabled`。
  - 版本 v0.2.9 → v0.3.0；README / CHANGELOG / features.md L1-01/08/09 / design.md / roadmap.md 同步。
- 验证：unittest 113 passed（新增签名、状态卡、热力图、配置与命令用例）；UTF-8 读回校验无乱码。
- 遗留：WebUI 页面尚未实际渲染状态卡/热力图（L1-15 视觉层），时间轴（L1-10）仍未排期实现。
- 下一步：L1-15 WebUI 视觉优化（排版/空态/错误态/移动端 + Playwright 检查）。

## 2026-08-12 L1-16 同人格单 SQL 与任务租约落地

- 目标：同人格多实例共享同一 SQLite 时保证单写者，槽位不会重复执行。
- 决策：租约表按 `(persona_id, task_key)` 唯一；调度器执行前先抢租约，拿不到则记录 `skipped_duplicate` 并跳过；TTL 过期自动释放；跨主机场景不承诺（走 v2 统一库租约）。
- 改动：
  - `life/db.py`：新增 `life_leases` 表与 `acquire_lease` / `renew_lease` / `release_lease` / `cleanup_expired_leases`；启动回收时顺带清理过期租约。
  - `life/scheduler.py`：实例 id + 槽位租约抢锁，未抢到调用 `record_skipped_duplicate`。
  - `life/browser.py`：新增 `record_skipped_duplicate`（browse 落会话，diary 落快照）。
  - `life/config.py` / `_conf_schema.json`：新增 `lease_ttl_seconds`（默认 300）。
  - 版本 v0.2.8 → v0.2.9；README / CHANGELOG / features.md L1-16 / design.md / roadmap.md 同步。
- 验证：unittest 105 passed（新增租约互斥/续租/过期重获、配置与 skipped_duplicate 用例）；UTF-8 读回校验无乱码。
- 遗留：多进程真实并发需 test kit 双实例冒烟（本机单库可跑，未在本轮执行）；跨主机共享 SQLite 不在 v1 范围。
- 下一步：工程基线全部完成，进入高体感批次：L1-01 今日签名 → L1-08 状态卡 → L1-09 热力图 → L1-15 WebUI 优化。

## 2026-08-12 L1-14 不可信内容与记忆卫生落地

- 目标：外部抓取/历史素材只当数据，防提示词注入与记忆污染，疑似注入可审计。
- 决策：注入检测采用保守启发式（少误报优先），素材进入 prompt 前统一 sanitize；审计默认开启，WebUI 只读查看。
- 改动：
  - 新增 `life/injection.py`（`is_suspicious` / `sanitize_text` / `scan_items`）。
  - `life/db.py`：新增 `injection_log` 表与 `log_injection` / `list_injection_log`。
  - `life/prompts.py`：三个生活 prompt 增加“不可信素材”硬化规则。
  - `life/browser.py`：漫游/日记前扫描并记录疑似注入，标题/摘要/观点 sanitize，mood 走封闭词表。
  - `life/share.py`：分享素材 sanitize + 审计。
  - `life/webui.py`：新增 `/injection_log`；`life/config.py` / `_conf_schema.json` 新增 `injection_log_enabled`。
  - 版本 v0.2.7 → v0.2.8；README / CHANGELOG / features.md L1-14 / design.md / roadmap.md 同步。
- 验证：unittest 101 passed（新增注入检测、prompt 硬化、审计接口与抓取审计用例）；UTF-8 读回校验无乱码。
- 遗留：启发式无法覆盖全部注入变体，后续可叠加模型侧判断；`query_life_memory` 工具返回仍为结构化记忆，未接入执行指令面。
- 下一步：工程基线 L1-16 同人格单 SQL 与任务租约。

## 2026-08-12 L1-13 变更账本与回收站落地

- 目标：写操作可审计、可回滚，删除进回收站，owner 可恢复。
- 决策：`change_log` 只先覆盖软删除/恢复等可逆写操作，后续 L1.5 事件链在账本上扩展；软删除采用 `deleted_at` tombstone，正常查询自动排除回收站；`trash_retention_days` 默认 30。
- 改动：
  - `life/db.py`：新增 `change_log` 表、`deleted_at` 列（含旧库 ALTER 迁移）、`log_change` / `list_change_log`、`soft_delete_note/diary`、`restore_note/diary`、`list_trash`、`purge_trash`；正常查询加 deleted 过滤。
  - `life/config.py` / `_conf_schema.json`：新增 `trash_retention_days`。
  - `life/webui.py`：新增 `/trash`、`/trash_restore`、`/change_log` 接口。
  - 版本 v0.2.6 → v0.2.7；README / CHANGELOG / features.md L1-13 / design.md / roadmap.md 同步。
- 验证：unittest 92 passed（新增 5 个 L1-13 用例）；UTF-8 读回校验无乱码。
- 遗留：WebUI 页面尚未渲染回收站/账本视图（属 L1-15 视觉层）；`change_log` 尚未覆盖兴趣/分享等内部写操作（事件链阶段扩展）。
- 下一步：工程基线 L1-14 不可信内容与记忆卫生。

## 2026-08-12 L1-11 预算/重试/崩溃落地

- 目标：LLM 调用有预算与重试上限，run 级崩溃不污染档案，移除确定性 fallback。
- 决策：`daily_llm_call_limit` / `daily_token_budget` 默认 0 无上限，`llm_retry_limit` 默认 3；预算耗尽当天任务跳过并记 `budget_exhausted`；重试耗尽任务标记 `failed` 并报 error；漫游/复盘先写 staging 表，最终 `BEGIN IMMEDIATE` 一次落库；启动时回收残留 running 会话。
- 改动：
  - `life/db.py`：新增 `daily_usage` 与 `staging_notes/diary/snapshots/seen/interests` 表、`_transaction`、`commit_staged` / `discard_staged` / `recover_stale_runs`、用量接口。
  - `life/llm.py`：新增 `BudgetExhausted`、`extract_usage_tokens`、`chat_json_managed`（指数退避重试 + 预算/用量回调）。
  - `life/browser.py`：`_llm_call` 统一预算/重试；漫游/复盘改 staging 提交；移除 `_fallback_selected` / `_fallback_diary`。
  - `life/interests.py`：新增 `stage_note` / `stage_updates`。
  - `life/config.py` / `_conf_schema.json`：新增三个配置项；`life/webui.py` 新增 `/usage`；`main.py` 补充 `failed` 状态文案。
  - 版本 v0.2.5 → v0.2.6；README / CHANGELOG / features.md L1-11 / design.md / roadmap.md 同步。
- 验证：unittest 87 passed（新增 13 个 L1-11 用例）；网络冒烟按配置跳过；UTF-8 读回校验无乱码。
- 遗留：`daily_token_budget` 依赖 provider 返回 usage，拿不到 token 时只执行调用次数上限并在 WebUI 标注；多进程同库场景留待 L1-16 租约兜底。
- 下一步：工程基线 L1-13 变更账本与回收站。

## 2026-08-12 L1-12 时区落地

- 目标：按 `docs/features.md` 开发顺序推进工程基线第一项，睡眠窗口、槽位日期与“今日”边界按 persona 本地时间计算。
- 决策：`timezone` 为全局配置，默认 `Asia/Shanghai`；非法配置回退默认并置 `timezone_error` 告警；服务器本地 naive 时间统一经 `life/timeutil.py` 换算为配置时区。
- 改动：
  - 新增 `life/timeutil.py`（normalize / is_valid / to_local / local_now / local_today）。
  - `life/config.py` 增加 `timezone` / `timezone_error`；`_conf_schema.json` 补配置项。
  - `life/db.py` 接受 timezone，全部时间戳/日期边界走 `self._now()` / `self._today()`。
  - `life/scheduler.py` 新增 `_current_target`，调度按配置时区换算槽位。
  - `life/browser.py`、`life/share.py`、`life/webui.py`、`main.py` 的“今日”与睡眠边界统一走配置时区。
  - 版本 v0.2.4 → v0.2.5；README / CHANGELOG / features.md L1-12 状态同步。
- 验证：unittest 74 passed（新增 8 个时区用例）；网络冒烟按配置跳过。
- 遗留：`life/persona.py` 缓存过期判断仍用服务器本地时间（不涉及“今日”边界，未纳入本次）。
- 下一步：工程基线下一项 L1-11 预算/重试/崩溃（含 db 事务化前置改造）。

## 2026-08-12 第五轮 review 修复

- 修正：`docs/workflow.md` 提交信息规则与 AGENTS.md 对齐——纯文档 `docs: ...` 不 bump 版本，功能/修复 `chore(release): ...` 同步版本与 CHANGELOG。
- 验证：UTF-8 读回无乱码。
- 下一步：如需提交推送请告知；否则按 `docs/features.md` 开发顺序开工。

## 2026-08-12 第四轮 review 修复

- 修正：
  - `docs/features.md` L1-02：验收改为“无历史时不触发”，冷启动期判定待冷启动方向落地后接入。
  - `docs/features.md` L2-04：依赖注明金字塔未落地时用确定性聚合回退。
  - `AGENTS.md` 规则 2：commit 信息区分纯文档（`docs: ...`）与功能/修复（`chore(release): ...`）。
- 验证：UTF-8 读回无乱码。
- 下一步：如需提交推送请告知；否则按 `docs/features.md` 开发顺序开工。

## 2026-08-12 第三轮 review 修复

- 修正：
  - `docs/requirements.md` 对接降级策略：ESM 静默 no-op 限定为 v0.2.4 现状，v1.1 新契约按 L1-03 处理。
  - `docs/design.md` 数据模型补未来新增表索引（daily_usage / life_leases / change_log / event_chain / life_plans / action_log / wishlist / center_state / thoughts / entities 族）。
  - `docs/design.md` 硬边界“不注册账号、不发帖”加 v1 限定，指向 v1.5+ 社交表达方向。
  - `README.md` 生态联动补“现状 v0.2.4”标注。
- 验证：UTF-8 读回无乱码。
- 下一步：如需提交推送请告知；否则按 `docs/features.md` 开发顺序开工。

## 2026-08-12 第二轮 review 修复

- 决策（用户拍板）：修掉第二轮 review 的 P2/P3。
- 修正：
  - 静默降级表述区分版本：v0.2.4 现状降级仅作过渡，v1.1 计划内新契约（`consume_energy`）不再默认静默降级（design.md / requirements.md）。
  - run 级原子性明确“暂存区优先”：漫游/复盘先写暂存表，SQLite 事务只包住最终落库，避免写锁横跨网络/LLM await（features.md L1-11 / design.md）。
  - 同人格单 SQL 补部署前提：仅适用于共享卷（同一主机或挂载盘），跨主机走 v2 统一库租约（features.md L1-16 / design.md）。
  - 预算用量落点：新增 `daily_usage` 表（persona_id / date / llm_calls / tokens）（features.md L1-11 / design.md）。
  - `lease_ttl_seconds` 拆分：L2-09 改用 `memory_lease_ttl_seconds`，与 v1 本地租约区分。
  - L1-02 与 L2-11 的 revisit 语义补命名区分。
- 验证：UTF-8 读回无乱码；变更 grep 通过。
- 下一步：如需提交推送请告知；否则按 `docs/features.md` 开发顺序开工。

## 2026-08-12 review 问题修复

- 决策（用户拍板）：`/life_today` 并入 L1-08；`LifeMemoryAdapter` 收敛放 L2；热力图接口用 `/timeline/heatmap`。
- 修正：
  - `docs/requirements.md`：v1 只消费 ESM 现有能力的表述改为“v0.2.4 现状 / v1.1 起按计划消费新增契约”。
  - `docs/design.md`：统一记忆库落地路径改为 v1.1 自持 SQLite、v2 引入 `LifeMemoryAdapter`；热力图接口改 `/timeline/heatmap`；6 个章节标题状态同步到 L1/L1.5/L2 分层；实体维度落地顺序标注 L2 内。
  - `docs/features.md`：L1-08 并入 `/life_today`；L1-09 热力图接口改 `/timeline/heatmap`；L1-05/L1-07 补同名概念区分。
  - `docs/roadmap.md`：统一记忆库方向改为 v2 引入 adapter；落地顺序第 2 步与 features 对齐。
  - `README.md`：补 `AGENTS.md` 文档入口；“每实例独立生活”标注现状 v0.2.4 与 v1.1 共享 SQLite 方向。
- 验证：UTF-8 无乱码；交叉引用 grep 通过。
- 下一步：按 `docs/features.md` 开发顺序开工（工程基线第一项）。

## 2026-08-12 全量文档整理

- 目标：整完整理文档，消除 roadmap / features / design 之间过期与矛盾表述。
- 修正：
  - `docs/roadmap.md`：一览表与 v1.1/v2 内容对齐 features.md；未排期移除已归位项（自主排期→L1.5、统一记忆库→L2、可被看见→分档、自主生活内核→L1.5+L2），并加“以 features.md 为准”说明；v1.1 补工程基线条目；原则区明确 v1 owner-only 边界。
  - `docs/features.md`：补 L2-10 关注对象、L2-11 故地重游；L1-12 补 db 时区日期前置改造；L2-01 模块表述修正；开发顺序第 2 步修正 L1-15 依赖；方向区可被看见条目指向具体功能号。
  - `docs/design.md`：文档导航按分层更新。
  - `docs/requirements.md`：ESM 稳定契约条目注明现状 v0.10.4 已有契约、v0.11 为契约升级版。
- 验证：UTF-8 无乱码；交叉引用 grep 通过。
- 下一步：按 `docs/features.md` 开发顺序开工（工程基线第一项）。

## 2026-08-12 review 结论落地

- 决策：
  - 1-1 v1 同人格单 SQL：所有实例共享同一 `db_path`，`life_leases` 建在同一文件；不做按 persona 分文件的复杂度（design.md、features.md L1-16）。
  - 1-2 开发顺序统一：工程基线 → 高体感 → L1 剩余 → L1.5（含事件链可视化）→ L2；roadmap 与 features.md 已对齐。
  - 1-3 取消“L1 不引入硬依赖”，改为“允许引入上游依赖，须在 features.md 标注并同步 requirements.md”（features.md、AGENTS.md）。
  - 2-1 已解释并落档：run 级原子性需要 db 事务化改造 + 更新 fallback 测试（features.md L1-11 前置改造）。
  - 2-2 接受：`daily_token_budget` 计量依赖 provider usage，不可用时只执行次数上限（design.md、features.md）。
  - 2-3 覆盖完整步骤：新增 L1-14 安全基线、L1-15 WebUI 美化、L1-16 同人格单 SQL 租约、L1.5-06 事件链可视化。
- 改动文件：`docs/features.md`、`docs/design.md`、`docs/roadmap.md`、`AGENTS.md`、`README.md`。
- 验证：UTF-8 读回无乱码；一致性 grep 通过。
- 下一步：按统一后的顺序开工，先做工程基线第一项。

## 2026-08-12 兼容矩阵落地

- 决策：把 `docs/requirements.md` 的“兼容矩阵”从一句话落实为真实表格（本地版本 / 公开契约 / 远端仓库 / 对接点 + 升级检查表）。
- 执行：派 1 个只读 subagent（Laplace）调研 9 个家族仓库；主 agent 抽查 ESM/engram/xml 三家的版本、API 文档、remote 与 commit，全部一致后落表。
- 关键事实：ESM v0.10.4（有 `_PUBLIC_API.md`）、engram_core 1.74.0（无公开契约文件）、xml_structured_output 0.2.9（Public API · v1）；其余 7 家无 `_PUBLIC_API.md`。
- 验证：UTF-8 读回无乱码；subagent 结论与本地抽查一致。
- 遗留：7 个家族插件缺 `_PUBLIC_API.md`，接入前需补契约或确认调用面。
- 下一步：按 `docs/features.md` 开发顺序推进；提交不着急（用户已确认）。

## 2026-08-12 AGENTS.md 补强：工具规则与测试环境

- 决策：`AGENTS.md` 补充代码修改工具规则（代码文件必须 `safe_edit` / `apply_patch`）与测试环境（unittest、`LIFE_SMOKE_NET=1`、astrbot-test-kit venv、生产目录只读）；`docs/workflow.md` 注明先读仓库根 `AGENTS.md`。
- 遗留缺口：`docs/requirements.md` 只有“维护兼容矩阵”一句话，还没有真实矩阵表；需逐个家族仓库核对版本后补表（可交 subagent 调研）。
- 验证：UTF-8 读回无乱码。
- 下一步：提交当前文档批次，然后按 `docs/features.md` 开发顺序推进。

## 2026-08-12 项目守则落地：AGENTS.md

- 决策：把开发要求（文档顺序、硬性规则十条、PS 5.1 中文处理、Subagent 约束、安全边界、功能分层、硬依赖/生态）写入仓库根 `AGENTS.md`，作为本仓库 agent 会话的附加约束，叠加在全局 AGENTS.md 之后。
- 改动文件：新增 `AGENTS.md`；`docs/README.md` 索引补充。
- 验证：UTF-8 读回无乱码。
- 下一步：按 `docs/features.md` 开发顺序推进。

## 2026-08-12 目标确立：北极星目标六维度

- 决策：以“行为 / 思考层 / 思想层 / 发散思维与联想 / 线性生命链 / 记忆结构与检索”六维度作为北极星目标，写入 `design.md` 定位、`roadmap.md` 原则、`docs/README.md` 与 `README.md`。
- 关联：六维度分别对应现状 L0 行为、方向 thoughts/center state、联想召回、事件链、统一记忆库；最终形态为跨平台一致人格，可被看见、可分享、可被召回。
- 验证：UTF-8 读回无乱码。
- 下一步：按 `docs/features.md` 开发顺序推进。

## 2026-08-12 工作流补充：Subagent 使用约束

- 决策：允许 subagent 辅助调研/测试/审查/起草，但七项严格约束：职责边界、任务封装、事实纪律、权限边界、落地闸门、记录、安全边界；已写入 `docs/workflow.md`。
- 改动文件：`docs/workflow.md`（新增「Subagent 使用约束」）、`docs/README.md`（索引描述同步）。
- 验证：UTF-8 读回无乱码。
- 下一步：继续按 `docs/features.md` 开发顺序推进；subagent 结果先 review 再落地。

## 2026-08-12 文档整理：功能分层与现状/方向修正

- 目标：整理文档，描述详细准确，功能分层方便开发。
- 已确认决策/动作：
  - 新增 `docs/features.md`：L0 / L1 / L1.5 / L2 / 方向 五层开发清单，每项含状态、依赖、模块落点、配置项与验收标准。
  - `docs/design.md` 明确现状与方向边界：确定性 fallback 是 v0.2.4 现状，重试 3 次后报 error 是 v1.1 目标；时区、预算/重试/崩溃标为“方向，v1.1 起”。
  - 模块地图补 `life/prompts.py`；WebUI 接口清单补 `persona_refresh`、`share_note`；`register_web_routes` 回退已注明。
  - `docs/roadmap.md` 收敛为阶段目标，开发细节指向 `docs/features.md`。
- 代码事实核对：模块清单、`_conf_schema.json` 配置键、WebUI routes、`browser.py` fallback 均以代码为准。
- 验证：UTF-8 读回无乱码；rg 确认新增链接与标题。
- 遗留：全部文档仍未提交（建议 `docs: 新增功能分层开发清单并修正现状/方向边界`）；上一轮“下一步”被本条目取代。
- 下一步：按 `docs/features.md` 开发顺序先落 L1-12 时区、L1-11 预算/重试/崩溃、L1-13 变更账本/回收站，每个功能按 workflow 小阶段推进。

## 2026-08-12 文档规划：生活感方向与工程约束

- 目标：把「互联网生活」方向讨论固化为 `design / roadmap / requirements / workflow` 文档。
- 已确认决策：
  - 硬依赖：v2 起 ESM 与统一记忆宿主为硬依赖，本地 SQLite 降级为缓存；兼容不等于冻结，契约版本化 + 整族协调。
  - 人格经历严格线性，事件链单写者；同人格多实例用槽位唯一键 + 幂等 + 任务租约保证串行化，租约不是允许并行。
  - 预算可配置：LLM 调用/token 默认无上限；多轮联想每轮候选上限 5；LLM 失败重试上限 3，耗尽报 error，不生成伪造内容。
  - 崩溃语义：run 级暂存，崩溃丢弃未提交数据并报 error（宁缺毋滥）。
  - 时区：`timezone` 可配置，默认 `Asia/Shanghai`，睡眠窗口与“今日”按 persona 本地时间。
  - 冷启动：人格自由探索 + owner 手动干预，达到最小素材量后进入常规节奏。
  - 人格演化可控：不可变内核 + 可演化层 + 版本化 center state + owner 确认/回滚/drift report；提示词版本化是工程版本，不是人格自演化。
  - 提示词注入面清单与记忆卫生：除 owner 直接配置外一律不可信，记忆以数据身份注入、不携带执行指令。
- 改动文件：
  - `docs/design.md`：新增预算/重试/崩溃、时区、并发与锁、人格演化可控、冷启动、注入面与记忆卫生。
  - `docs/roadmap.md`：新增「工程基线（已确认）」。
  - `docs/requirements.md`：新增每 persona 任务租约 API 需求。
  - `docs/workflow.md`：新增「调研与开发日志（贯穿全程）」。
  - `docs/README.md` / `README.md`：文档索引补充 devlog。
- 验证：全部文档 UTF-8 读回无乱码；旧「确定性 fallback」表述已替换；git status 确认改动范围。
- 遗留：文档尚未提交推送（建议 `docs: 补齐预算/时区/并发/演化可控/冷启动设计与开发日志机制`）。
- 下一步：按 roadmap 落地顺序做第一个 v1.1 小功能（今日人格签名 / 月历热力图 / 精力预算三选一），先联网调研同类实现，再按 workflow 小阶段推进。
