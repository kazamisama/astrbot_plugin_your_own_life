# 开发日志

每个工作段结束（或上下文可能压缩/跨会话前）追加一条，最新条目放最上面。条目至少包含：目标、已确认决策、改动文件、验证结果、遗留问题、下一步行动。

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
