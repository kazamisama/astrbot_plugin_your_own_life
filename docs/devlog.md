# 开发日志

每个工作段结束（或上下文可能压缩/跨会话前）追加一条，最新条目放最上面。条目至少包含：目标、已确认决策、改动文件、验证结果、遗留问题、下一步行动。

## 2026-10-29 交互与清除边界修复（v0.5.41）
- 目标：处理上一轮审计列出的五项可修问题——热力图点击闭包、胶囊手动打开连带运行全部到期项、调度器最终写库失败忙循环、回收站未清理 injection_log 预览、同会话同文消息被幂等键吞掉。
- 已确认决策：
  - 热力图循环变量改用块级 `let`，不引入新的页面框架或 DOM 测试依赖；现有页面测试只能做源码级回归。
  - WebUI 手动打开胶囊只处理指定 `capsule_id`，不改变夜间复盘“处理全部到期胶囊”的语义。
  - 调度器命中 `_done_keys` 后等待 5 秒，覆盖“最终写库失败但 key 已记”的失败路径，不改变正常终态分支。
  - `purge_trash` 只清空与被删短记标题/摘要/观点完全匹配的 `injection_log.preview`，保留无关审计记录；SQLite 开启 `secure_delete`，但不自动 VACUUM 全库，历史 freelist 页仍属外部操作。
  - 聊天事件键优先使用 AstrBot 上游 `message_obj.message_id`；没有消息 ID 的测试/旧平台仍回退到文本哈希。
- 改动：
  - `pages/life/index.html`：热力图 `var key` 改为 `let key`。
  - `life/browser.py`、`life/webui.py`：`run_capsules` 增加 `only_id`，`capsules_open` 传入当前胶囊 id。
  - `life/scheduler.py`：`_wait_for_target` 的 `_done_keys` 分支增加 5 秒退避。
  - `life/db.py`：连接开启 `secure_delete`；`purge_trash` 增加 injection preview 脱敏。
  - `life/chat_hooks.py`：新增 `_event_message_id`，`_event_key` 接受消息 ID。
  - 测试：热力图源码回归、胶囊 only_id、调度器退避、injection preview、secure_delete、聊天键与同文消息。
  - 文档/版本：metadata、`life/__init__.py`、README、CHANGELOG、design.md、devlog 升 v0.5.41。
- 验证：test_db 79、test_browser 67、test_webui 28、test_scheduler 34、test_chat_hooks 12 全绿；全量 358 条（skipped=1；`test_config` 与生产 AstrBot 混装的已知环境错误除外）。
- 遗留：页面日期初始值仍用浏览器本地日期；统一记忆宿主跨系统孤儿仍受 engram_core 无删除 API 限制；真实浏览器 E2E 未重跑。
- 下一步：提交并推送 v0.5.41；页面时区与 E2E 视需要另开工作段。

## 2026-10-29 回收站彻底清除边界与清理重试（v0.5.40）
- 目标：按“目光放长远、不为旧数据打补丁”的原则，明确回收站彻底清除的派生数据边界，并让调度器清理失败可重试；顺带清掉 v0.5.39 后失去调用者的 `mark_revisits`。
- 已确认决策：
  - `reviews` 是独立回顾档案：只从 `source_refs` 移除被清短记/日记的机器引用，保留回顾正文，不因单条短记删除而删整篇回顾。
  - `share_log` 保留时间/状态/目标用于统计与审计，清空 `note_id` 和 `message`；不直接删行。
  - 不对历史 `reviews` / `share_log` 回填；新边界只对之后执行的清除生效。
  - `_purge_expired_trash` 失败不写“当日已清理”，下一轮重试；持续失败会按调度轮次记录 warning。
- 改动：
  - `life/db.py`：`purge_trash` 增加 `scrub_review_refs` 与 `share_log` 脱敏；删除 `mark_revisits`。
  - `life/scheduler.py`：`_purged_trash_dates.add(key)` 移到 `purge_trash` 成功之后。
  - `life/webui.py`：`build_handlers` 拆成模块级 `_build_read_handlers` / `_build_action_handlers`，只读查询与写操作分组；`build_handlers` 只保留 persona helper 与组合，路由名、handler 行为与返回结构不变。
  - 测试：扩展 purge 测试覆盖 reviews/share_log；新增调度器失败重试测试；WebUI 27 条全部通过。
  - 文档/版本：metadata、`life/__init__.py`、README、CHANGELOG、design.md、devlog 升 v0.5.40。
- 验证：全量 351 条（skipped=1；`test_config` 与生产 AstrBot 混装的已知环境错误除外）；扩展的 purge 测试、调度器失败重试测试与 `test_webui` 27 条通过；ruff F,E9、compileall、`git diff --check`、UTF-8 读回通过。
- 遗留：memory_host 跨系统孤儿仍受 engram_core 无删除 API 限制；真实 AstrBot 端到端未重跑。
- 下一步：提交 `chore(release): v0.5.40 ...`。

## 2026-10-29 剩余风险收口：回收站清理、重访事务与工具精力门槛（v0.5.39）
- 目标：处理上一轮审计剩余问题中可独立闭环的三项：回收站清理不能依赖日记成功、重访标记的崩溃窗口、工具通道排期绕过 ESM 精力门槛；同时把 `purge_trash` 对事件链正文的残留一并清掉。
- 已确认决策：
  - 回收站清理由调度器按本地日执行一次，夜间复盘保留一次兜底；不把清理绑在 `run_nightly_diary` 的返回结构上。
  - 重访标记跟随 `commit_staged` 的同一事务，不新增 staging 列；`revisit_of` 列表与本次新短记一一对应，长度不符直接抛错回滚。
  - `purge_trash` 清 `event_chain.payload/source_refs` 时保留事件记录本身（kind/ts/幂等键），只去掉正文引用。
  - 工具基类增加可选 ESM 依赖，仅 `edit_life_plan(add)` 使用；不放宽任何现有校验。
  - 统一记忆宿主“宿主成功、本地失败”的孤儿仍无法补偿：engram_core 没有删除 API，本轮只补文档说明，不写假的回滚。
- 改动：
  - `life/db.py`：`commit_staged` 增加 `revisit_of` 参数并在事务内更新 `notes.revisit_of`；`purge_trash` 擦除 `event_chain` 中匹配的 `payload/source_refs`。
  - `life/browser.py`：`run_revisit` 把原短记 id 列表交给 `commit_staged`，删除提交后的 `mark_revisits` 调用，后续 zip 加 `strict=True`。
  - `life/scheduler.py`：新增 `_purge_expired_trash`，在 `_wait_for_target` 播种前按 persona/日期每日执行一次；`_purged_trash_dates` 防重复。
  - `life/life_tool.py` / `main.py`：工具基类与 `edit_life_plan` 接收可选 `esm`，`add` 在创建前调用 `gate_energy`；主插件把 ESM 注入 `LifePlanEditTool`。
  - `docs/design.md`：补充回收站调度语义与统一记忆宿主的跨系统边界。
- 验证：新增 DB 重访事务/长度回滚/事件擦除、调度器无日记清理、工具 ESM 门槛测试；全量 350 条（skipped=1；`test_config` 与生产 AstrBot 混装的已知环境错误除外），test_db 77、test_scheduler 32、test_life_tool 19、test_browser 66；ruff F,E9、compileall、`git diff --check`、UTF-8 读回通过。
- 遗留：统一记忆宿主孤儿仍受 engram_core 无删除 API 限制；`build_handlers` 等结构性长度问题未在本轮处理；真实 AstrBot 端到端未重跑。
- 下一步：提交 `chore(release): v0.5.39 ...` 并推送。

## 2026-10-29 结构重构第七批：按通用规则收敛主函数（v0.5.38）
- 目标：按用户提供的 8 条通用代码规则审计后，先做低风险、纯提取的结构调整：主函数只保留正常流程，提交后副作用与调度阶段各自成组；同时消除计划校验里重复的拒绝分支与一层冗余防御。
- 已确认决策：
  - 只做纯提取，不改变数据库 schema、WebUI 接口、调度状态机或返回结构。
  - 不按“禁止提前抽只用一次的函数”去全量内联 65 个单调用点 helper；这些多为清楚概念或复杂迁移，保留。
  - 不使用“通用规则”去删除租约、事务等边界守卫：多实例单写者是 `docs/design.md` 的明确设计要求，不是猜测出来的竞态。
  - 本次不引入 Playwright/新工具到仓库测试流程；真实浏览器验收仍是一次性人工流程。
- 改动：
  - `life/browser.py`：`run_browse_session` 的提交后副作用抽成 `_after_browse_commit`；`run_nightly_diary` 的提交后副作用抽成 `_after_diary_commit` 与 `_after_diary_followups`，主函数只保留正常流程与错误返回。
  - `life/scheduler.py`：`_run_loop` 拆成 `_wait_for_target` / `_run_target` / `_finalize_plan`；任务分派抽成 `_dispatch_plan`；等待停止的重复模式收敛到 `_sleep_or_stop`。
  - `life/browser.py`：`_apply_plan_payload` 增加局部 `reject()`，替代 7 处“追加 rejected + 记录拒绝 + continue”；删除 `esm.gate_energy` 外层永远不会触发的 try/except。
- 验证：test_browser 66、test_scheduler 31、test_life_tool 17 全绿；全量 344 条，仅 `test_config` 与生产 AstrBot 混装的已知环境错误（skipped=1）；ruff F,E9、compileall、`git diff --check` 通过。
- 遗留：`build_handlers`（534 行）、`run_review` 同构主体、`run_revisit` 等仍可继续拆分；页面仍无 DOM 自动化测试；真实 AstrBot 端到端未在本轮重跑。
- 下一步：提交 `chore(release): v0.5.38 ...`；之后按需继续结构审查或新功能。

## 2026-10-29 真实浏览器验收与回收站确认修复（v0.5.37）
- 目标：用真实 AstrBot Dashboard + Chromium 验收 WebUI，重点检查 v0.5.36 新增的「档案」「兴趣」视图，并覆盖 v0.5.20 的回收站交互。
- 环境：AstrBot 4.29.3 production backend（`C:\application\AstrBot\backend\python`）+ 同版本 `webui`，`ASTRBOT_ROOT` 指向临时 staged root；插件 v0.5.36 干净副本；Playwright + Edge headless；Dashboard 登录态写入 localStorage。
- 已确认决策：
  - 不使用测试 kit 自带的 AstrBot 4.25.5 前端：其 dashboard 资产缺失，借用生产 4.29.3 前端会因 `/api/v1` 契约不匹配而整页 401，不能作为验收依据。
  - 真实浏览器验收以 AstrBot 4.29.3 全栈为准；插件 iframe 由 AstrBot 注入 sandbox，页面不能依赖原生浏览器模态框。
- 发现并修复：插件 iframe 的 sandbox 只有 `allow-scripts allow-forms allow-downloads`，没有 `allow-modals`，`window.confirm` 被忽略并返回 false，导致回收站两条删除入口永远不执行。改为页面内 `askConfirm` 对话框（overlay + 取消/确定 + Esc + 点遮罩），替换仅有的两处 `window.confirm`。
- 验收结果：登录后进入 `/#/plugin-page/astrbot_plugin_your_own_life/life`，iframe 正常加载；15 个 tab 全部可见且切换无 JS 错误、无 4xx；档案页按日期显示日记/见闻/会话/分享/快照；兴趣页显示 4 条兴趣、权重条、见过次数与最近时间；通过页面确认框删除一条短记（回收站 1 条）并恢复（0 条），接口均 200。
- 改动：`pages/life/index.html`、`tests/test_webui.py`、`README.md`、`CHANGELOG.md`、`docs/design.md`、`docs/devlog.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.36 → v0.5.37。
- 验证：真实浏览器（AstrBot 4.29.3 + Edge）通过；新增 `test_plugin_page_avoids_native_confirm`；全量 344 条，仅 `test_config` 已知环境错误（skipped=1）；页面内联脚本 `node --check`、ruff F,E9、compileall、`git diff --check` 待本轮收尾执行。
- 遗留：页面仍无 DOM 自动化测试，本次验收脚本在临时目录；AstrBot 4.25.5 测试 kit 前端资产缺失，未做该版本浏览器验收。

## 2026-10-29 结构重构第六批：补齐档案/兴趣页面视图（v0.5.36）
- 目标：把已有后端 `GET /archive` 与 `GET /interests` 接到 WebUI，消除“接口存在但页面没有视图”的空缺；顺带收敛页面内重复的笔记渲染与 tab 分派。
- 已确认决策：
  - 不新增后端接口；档案页复用 `archive_for_date` 返回的 diary/notes/sessions/share_logs/snapshots。
  - 档案页使用独立日期选择器，不改写顶部 `dateInput`（它仍服务生活/记忆/分享/热力图）。
  - 状态快照最多展示最近 30 条并提示总数，避免一天几百条撑满页面；会话、分享、快照都有空态。
  - 兴趣页使用完整 `/interests` 列表，展示权重条、见过次数与最近出现时间；生活页的“兴趣排行”保持原样。
  - 笔记条目抽成 `noteListItem` 供生活页与档案页共用；tab 加载分派收敛为 `loadTabContent`，`switchTab` 与 `load` 不再各维护一份 if 列表。
- 改动：`pages/life/index.html`、`docs/design.md`、`docs/features.md`、`README.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.35 → v0.5.36。
- 验证：页面内联脚本 `node --check` 通过；15 个 tab 与 15 个 section 一一对应，无重复 id；全量 343 条，仅 `test_config` 已知环境错误（skipped=1）；ruff F,E9、compileall、`git diff --check` 通过。
- 遗留：未做真实浏览器视觉验收；页面没有 DOM 自动化测试，档案/兴趣渲染只经过结构、接口调用与语法检查。
- 下一步：提交 `chore(release): v0.5.36 ...`；结构重构清单已清空，后续转入真实浏览器验收或新功能。

## 2026-10-29 结构重构第五批：收口改动记录端点（v0.5.35）
- 目标：删除 `change_log` 与 `life_edits` 两个返回同一张表数据的兼容端点，只保留页面实际使用的 `GET /life_edits`。
- 已确认决策：
  - 页面、命令与 LLM 工具都只调用 `life_edits` 或 `db.list_change_log`；`GET /change_log` 没有调用方。
  - `life_edits` 已是更完整的形态（最多 200 条），保留它作为唯一 HTTP 入口；`/change_log` 直接删除，不保留无实现的别名。
  - 这是破坏性接口变更：外部脚本若调用 `/change_log` 会 404，返回结构也从 `logs` 变为 `edits`，在 CHANGELOG 中明确标注。
- 改动：`life/webui.py`、`tests/test_webui.py`、`docs/design.md`、`README.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.34 → v0.5.35。
- 验证：test_webui 26 全绿；全量 343 条，仅 `test_config` 已知环境错误（skipped=1）；路由数 36 → 35，并断言 `/change_log` 不再注册；ruff F,E9、compileall、`git diff --check` 通过。
- 遗留：页面 archive/interests 独立视图仍未做。
- 下一步：提交 `chore(release): v0.5.35 ...`；随后补 archive/interests 页面视图。

## 2026-10-29 结构重构第四批：清理 life_plans.started_at 死列（v0.5.34）
- 目标：移除 `life_plans` 建表里的 `started_at` 死列，减少新库 schema 噪音；不改变计划状态机、排期板接口或 WebUI。
- 已确认决策：
  - grep 全仓确认 `life_plans.started_at` 没有读取/写入调用；其他 `started_at` 命中都属于 `browse_sessions`、会话返回、presence 或 `main.py` 的会话展示，保留不动。
  - 新库从 `_SCHEMA` 的 `life_plans` 建表中删除该列；旧库在启动时调用 `_drop_dead_column` 尝试 `ALTER TABLE ... DROP COLUMN`。
  - 旧版 SQLite 不支持 DROP COLUMN 或列被依赖时只记录 warning 并保留未用列；不重建表、不复制计划数据，避免升级路径承担额外风险。
- 改动：`life/db.py`、`tests/test_db.py`、`README.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.33 → v0.5.34。
- 验证：test_db 74 全绿（新增旧库含 `started_at` 的迁移测试，确认列删除且计划行保留）；全量 343 条，仅 `test_config` 已知环境错误（skipped=1）；ruff F,E9、compileall、`git diff --check` 通过。
- 遗留：`change_log`/`life_edits` 兼容端点、页面 archive/interests 独立视图仍未动。
- 下一步：提交 `chore(release): v0.5.34 ...`；随后收口兼容端点或补页面视图。

## 2026-10-28 结构重构第三批：回顾生命周期收敛（v0.5.33）
- 目标：把 `run_review`（月度/年度）与 `run_quarterly_review` 的重复生命周期收敛到一个私有实现，保留两个公开入口的错误语义与季度 confidence 字段。
- 已确认决策：
  - 启用开关、白名单与 persona 解析留在公开入口，错误返回结构不变；persona 解析完成后的幂等检查、统计、提示词、LLM 失败回退、预算跳过、落库与记忆镜像全部下沉到 `_run_review_common`。
  - 用 `with_confidence` 区分季度形态：季度增加 `mood_distribution`、季度提示词、`confidence` 字段与季度记忆事件；月度/年度不输出 confidence。
  - 月度 `upsert_review` 显式传 `confidence=0.0`（与原默认值一致），不改变存储结果。
- 改动：`life/browser.py`、`tests/test_browser.py`、`README.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.32 → v0.5.33。
- 验证：test_browser 66 全绿（新增月度/季度重复回顾幂等 2 条）；全量 342 条，仅 `test_config` 已知环境错误（skipped=1）；ruff F,E9、compileall、`git diff --check` 通过。
- 遗留：`life_plans.started_at` 死列、`change_log`/`life_edits` 兼容端点、页面 archive/interests 独立视图仍未动。
- 下一步：提交 `chore(release): v0.5.33 ...`；随后处理死列与兼容端点，或转向页面视图。

## 2026-10-28 结构重构第二批：工具类收敛（v0.5.32）
- 目标：把 5 个 LLM 工具在“有 AstrBot / 无 AstrBot”两种环境下的 10 个近似类收敛为每个工具一个类，减少条件分支重复，同时保持 FunctionTool 字段与降级调用面不变。
- 已确认决策：
  - 只把构造差异放进 `_LifeToolBase`：有 AstrBot 时调用 `FunctionTool.__init__` 注入 name/description/parameters/handler，无 AstrBot 时只保存 duck-typed 字段。
  - 工具 schema、参数与执行函数不搬动；每个工具仍显式保留自己的 `call` 签名，避免动态生成影响 AstrBot 的 schema 反射与可读性。
  - `LifeMemoryTool.memory` 与 `LifeEditTool.allowed` 继续在子类构造器注入，不塞进基类。
- 改动：`life/life_tool.py`、`README.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.31 → v0.5.32。
- 验证：全量 340 条，仅 `test_config` 已知环境错误（skipped=1）；test_life_tool 17 全绿；额外用 import blocker 模拟无 AstrBot 环境，5 个降级类可实例化并暴露 name/description/parameters；ruff F,E9、compileall、`git diff --check` 通过。
- 遗留：review/quarterly 同构主体、`life_plans.started_at` 死列、`change_log`/`life_edits` 兼容端点仍未重构。
- 下一步：提交 `chore(release): v0.5.32 ...`；随后评估 review/quarterly 同构主体收敛。

## 2026-10-28 结构重构第一批：persona 解析收敛（v0.5.31）
- 目标：把聊天钩子与 LLM 工具各自维护的 persona 解析收敛成一份实现，作为结构重构的低风险起点；不改变调度、数据模型与提示词。
- 已确认决策：
  - 解析顺序固定为“当前会话显式 persona → 平台默认 persona”；接受 AstrBot 原生上下文与工具层的包装上下文两种形状。
  - 显式无 persona（`[%None]`）必须是空结果，不能回退到默认人格；此前工具通道会回退，聊天钩子不会，两边语义不一致。
  - conversation manager 查询异常时继续尝试 default persona；此前工具通道会在异常时直接放弃，聊天钩子会继续。
  - `life.persona.resolve_persona_id` 是唯一实现；`chat_hooks.resolve_event_persona` 只保留薄包装供现有调用点与测试使用，`life_tool._resolve_persona` 只做空值归一。
- 改动：`life/persona.py`、`life/chat_hooks.py`、`life/life_tool.py`、`tests/test_persona_resolver.py`、`README.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.30 → v0.5.31。
- 验证：新增 persona resolver 7 条测试；受影响 test_chat_hooks 10、test_life_tool 17、test_persona 4 全绿；全量 340 条，仅 `test_config` 已知环境错误（skipped=1）；ruff F,E9、compileall、`git diff --check` 通过。
- 遗留：双胞胎 Tool 类、review/quarterly 同构主体、`life_plans.started_at` 死列、`change_log`/`life_edits` 兼容端点尚未重构。
- 下一步：提交 `chore(release): v0.5.31 ...`；随后评估下一个结构重构项（建议先做 Tool 类收敛或 review 同构主体）。

## 2026-10-28 真实 AstrBot E2E 与统一记忆宿主修复（v0.5.30）
- 目标：用 astrbot-test-kit 验证真实 AstrBot 下的命令与 WebUI API；处理验证中确认的统一记忆宿主适配问题；清理 test kit 目录卫生。
- 已确认决策：
  - AstrBot 的 `Context.get_registered_star()` 返回 `StarMetadata`，可调用的插件实例在 `metadata.star_cls`；适配器必须解包实例，不能把注册记录当宿主。
  - `star_cls is None`（插件注册但未激活）必须显式报错，`available()` 返回 False；不得静默当作可用。
  - 测试用户 ID 必须是数字；管理权限通过 `ASTRBOT_TEST_CONF` 的 `admins_id` 注入，否则 422/权限拒绝。
  - 测试插件目录不能直接用仓库根（含 302MB `astrbot_test_kit_runs/`），应使用 `git archive HEAD` 的干净副本；仓库忽略该目录。
- 改动：`life/memory_adapter.py`、`tests/test_memory_adapter.py`、`.gitignore`、`README.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.29 → v0.5.30。
- 验证：memory adapter 5 条测试全绿；真实 AstrBot 4.25.5 下 `/life`、`/life_today`、`/life_archive`、`/life_interest`、`/life_personas`、`/life_share 999` 全部 PASS；WebUI 登录后 overview/status/heatmap/personas/plans/events/capsules/usage/trash/interests/archive/revisit_chains/watchlist/entities 均 200。全量测试与 ruff/compileall 提交前执行。
- 遗留：LLM 路径（/life_now、/life_plan、夜间日记）未在 E2E 中验证；页面视觉未用真实浏览器检查；结构性重复与记忆宿主孤儿仍待处理。
- 下一步：提交 `chore(release): v0.5.30 ...`，再评估结构性重构。

## 2026-10-28 审计第六批：重访链与手动漫游体验（v0.5.29）
- 目标：处理上一轮列出的低风险项：revisit_chains 截断、/run 固定刷新、实体图错误提示、回顾来源重复扫描。
- 已确认决策：
  - 重访链不能用“所有相关行按时间取前 N”表达，必须拆成“有后续的原短记”与“按 id 取全部后续”两条查询。
  - 手动漫游的 UI 不能猜 3 秒；新增只读 `/run_status`，页面轮询到任务结束。
  - 实体图失败与空态是两件事，失败要显示错误横幅。
  - 回顾来源引用也复用区间日记查询，避免第二遍全表扫描。
- 改动：`life/db.py`、`life/webui.py`、`life/browser.py`、`pages/life/index.html`、`tests/test_webui.py`、`README.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.28 → v0.5.29。
- 验证：webui 26、db 73 全绿；全量与 ruff/compileall/页面 node --check 提交前执行。
- 遗留：页面 archive/interests、结构性重复、统一记忆孤儿、工具 add 无 ESM gate。
- 下一步：提交 `chore(release): v0.5.29 ...`。

## 2026-10-28 审计第五批：竞态、聚合与只读搜索（v0.5.28）
- 目标：处理 v0.5.27 后仍能确认的竞态与语义问题，而不是继续做结构性重构。
- 已确认决策：
  - `commit_staged` 只有 session 行仍是 `running` 才能写终态；行存在但已不是 running 属于跨实例竞态，必须回滚。测试/匿名 staging 没有行，仍允许提交。
  - 回顾统计应在 SQL 里按日期范围聚合；只把区间内日记（30/90 条）取出来算首尾兴趣，不再全库载入。
  - 聊天事件键只由内容决定；时间戳会让重试变成新事件。
  - 调度器禁用/空名单是“暂停”不是“终止”，等待 60 秒并重读配置。
  - 手动分享没有目标时不能调用 `attempt_share`，否则 `invalid_target` 会把短记标 dropped。
  - WebUI 搜索是 GET，只读；需要升温的场景由 LLM 召回工具负责。
- 改动：`life/db.py`、`life/browser.py`、`life/chat_hooks.py`、`life/scheduler.py`、`life/webui.py`、`tests/test_db.py`、`tests/test_webui.py`、`tests/test_chat_hooks.py`、`README.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.27 → v0.5.28。
- 验证：db 73、webui 26、chat_hooks 10、browser 64、scheduler 31 全绿；全量与 ruff/compileall/页面 node --check 提交前执行。
- 遗留：页面 archive/interests、结构性重复、统一记忆孤儿、工具 add 无 ESM gate、revisit_chains 500 窗口。
- 下一步：提交 `chore(release): v0.5.28 ...`。

## 2026-10-28 审计收尾：指纹回归与重访事务（v0.5.27）
- 目标：检查 v0.5.26 后是否引入新问题；发现并修 v0.5.24 的 digest 回归，同时收口重访标记与两处 N+1/全表扫描。
- 已确认决策：
  - `staging_seen.digest` 为空表示“这次不提供新指纹”，不能当成“清空指纹”；SQL 用 CASE 保留旧值。
  - 重访链的 `revisit_of` 是多行同一语义，批量单事务比逐条提交更难留下半完成状态。
  - 同一实体到同一平台的重复边只展示一次；胶囊只查引用短记，避免 10 万行字典。
- 改动：`life/db.py`、`life/browser.py`、`life/webui.py`、`tests/test_db.py`、`README.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.26 → v0.5.27。
- 验证：db 72、browser 64、webui 25 全绿；全量与 ruff/compileall/页面 node --check 提交前执行。
- 遗留：见 CHANGELOG v0.5.27 Notes；下一批若要继续，优先 `commit_staged` 的 running 守卫、review 聚合 SQL、页面 archive/interests。
- 下一步：提交 `chore(release): v0.5.27 ...`。

## 2026-10-28 审计第四批：事务收口与胶囊单飞（v0.5.26）
- 目标：把审计里“改数据 + 写账本”的非原子写路径收口，并处理 WebUI 的重复开销与文档基线。
- 已确认决策：
  - `_execute` 已经支持 `commit=False`，但只有事务内统一抑制自动 commit 才能让 `log_change` / `append_event` 一起回滚；在 `_transaction` 中置 `_in_transaction`，`_execute` 只在事务外 commit。
  - `apply_change` / `rollback_change` / 软删除与恢复是“数据 + 账本 + 事件”三件事，必须同事务；单测证明成功路径不变。
  - 胶囊手动打开会跑逐条 LLM，连点必须单飞；按 persona 记录运行集合，第二个请求直接返回明确错误。
  - 页面请求 `k=20` 但后端上限 10 属于静默截断，统一成 10。
- 改动：`life/db.py`、`life/webui.py`、`pages/life/index.html`、`tests/test_webui.py`、`README.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；`docs/consistency.md` 另以 `docs:` 提交标注历史基线。
- 验证：受影响 test_webui 25、test_db 71 全绿；全量与 ruff/compileall/页面 node --check 提交前执行。
- 遗留：页面 archive/interests 独立视图、结构性重复、统一记忆孤儿、工具 add 无 ESM gate。
- 下一步：提交 `chore(release): v0.5.26 ...`；剩余项属于重构或外部 API 限制，需单独评估。

## 2026-10-28 审计第三批：兴趣增量、事务与页面视图（v0.5.25）
- 目标：处理审计里“写入正确性”和“能力与 UI 脱节”两类剩余项，不再扩大重构范围。
- 已确认决策：
  - 兴趣 staging 必须记录基线；提交时用“当前值 + (staged - base)”合并，才对运行期间的外部修改友好。同一 key 的多次 stage 只取最后一行，避免累加。
  - 计划交换是两步写，必须用同一事务；行未命中就回滚，不能留下半交换。
  - WebUI 已有 `usage` / `injection_log` 接口，只差页面使用；在生活页和改动页补齐，不新增接口。
  - 日记的 `interest_updates` 只是权重反思，不是“又见到一条内容”；`stage_updates` 不再增加 `seen_count`，与 `apply_updates` 对齐。
- 改动：`life/db.py`、`life/interests.py`、`pages/life/index.html`、`tests/test_db.py`、`README.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.24 → v0.5.25。
- 验证：全量 `unittest discover -s tests` 326 条，仅 `test_config` 已知环境错误，skipped=1；db 71、browser 64 全绿；ruff F,E9、compileall、页面 `node --check` 通过。
- 遗留：`apply_change` / `rollback_change` / 软删除仍非单事务；页面 `archive` / `interests` 独立视图；结构性重复；consistency.md 基线。
- 下一步：提交 `chore(release): v0.5.25 ...`；再决定是否做事务重构与 consistency 文档收口。

## 2026-10-28 第二轮审计收尾：关注更新、回滚与边界（v0.5.24）
- 目标：继续修第二轮审计中不涉及大重构的 P2/P3，优先真实用户可见的断链与错误状态。
- 已确认决策：
  - 关注列表的 URL 是稳定的，单靠 URL 去重等于“永远只记一次”；在 `seen_items` 上记录内容指纹，只有内容变化才重新入选。指纹覆盖标题/摘要/发布时间，普通来源仍按 URL。
  - 故地重游的头部阻塞不能靠“取更多”解决；按天确定性打乱候选，让失败者轮换，失败事件键按日期分区，保留可追溯性。
  - 软删账本的 `old_value` 是整行，不是字段补丁；回滚按 `deleted_at` 恢复，短记和日记都支持。
  - 转正不存在的兴趣必须记 `exists:false`，否则回滚只能按默认 0.5 重建，产生鬼影；已有兴趣则恢复旧 `seen_count`。
  - 统一记忆合并要保留本地 id/url、去重并截断；host 重复条目只抬高温度。
  - RSS 解析交给 XML 编码声明；Atom 取 `rel=alternate`；RDF 单独走 RSS 1.0 命名空间。
  - 热力图点击落到生活页并设置日期，不新增接口。
- 改动：`life/db.py`、`life/browser.py`、`life/life_tool.py`、`life/webui.py`、`life/fetchers.py`、`pages/life/index.html`、`tests/test_db.py`、`tests/test_browser.py`、`tests/test_life_tool.py`、`tests/test_fetchers.py`、`README.md`、`CHANGELOG.md`；版本 v0.5.23 → v0.5.24。
- 验证：全量 `unittest discover -s tests` 324 条，仅 `test_config` 与生产 AstrBot 混装的已知 ImportError，skipped=1；受影响文件 db 70、browser 64、life_tool 17、fetchers 11 全绿；ruff F,E9 与 compileall 通过。
- 遗留：commit_staged 兴趣快照覆盖、事务原子性、页面 usage/archive/interests/injection_log 视图、结构性重复、consistency.md 基线。
- 下一步：提交 `chore(release): v0.5.24 ...`；之后处理事务边界与页面视图。

## 2026-10-28 第二轮审计修复：跨日计划、旧库 staging 与 WebUI 边界（v0.5.23）
- 目标：按用户「依次修改，旧缺陷直接改」的要求，修第二轮审计的 P1/P2 与高影响 P3；不做兼容补丁，直接改真实写路径。
- 已确认决策：
  - 调度器必须看见所有日期的 pending 计划，而不是只查当天；日记/回顾把 `plan_date` 传进服务，补写的是计划所属那天，不是运行日。
  - 等待计划时只等一次是不够的：等待结束重读 `scheduled_at`，defer/reorder 立即生效；计划终态变化则放弃执行。
  - 租约 claim 异常是“后端不可用”，不是“别人占着”；两者必须分开，否则任务会被假 skip 掉。租约冲突不改共享计划行，避免赢家无法回写 done。
  - 旧库升级用 `_ensure_column` 补齐 staging 表列（staging 表是 `CREATE TABLE IF NOT EXISTS` 的盲区）；notes 唯一约束迁移恢复 `sqlite_sequence`，避免 id 复用导致引用错位。
  - 计划状态机把 done/skipped 视作终态；同 `scheduled_at` 的 reorder 没有可交换顺序，直接返回失败而不是写假事件。
  - `generate_plan` 的预算检查放在调用前由 `_llm_call` 做，动作上限按“当天已有可选计划 + 本次 accepted”计算；计划调用本身不占动作预算。
  - 日记提交后的封胶囊/wishlist/胶囊/重访/回收站清理拆成独立 try，失败只进 `aux_error`。
  - `life_personas` 在服务方法执行端统一校验，命令、WebUI、聊天钩子、调度器不再各有一套语义。
  - WebUI 整数入口统一有界解析；`/personas` 投影掉 `system_prompt`；回收站 actor 固定 owner；页面所有 POST 走 `apiPostChecked`，失败可见。
- 改动：`life/db.py`、`life/scheduler.py`、`life/browser.py`、`life/life_tool.py`、`life/webui.py`、`life/config.py`、`life/share.py`、`main.py`、`pages/life/index.html`、`README.md`、`CHANGELOG.md`、`docs/design.md`、`docs/features.md`、`tests/test_db.py`、`tests/test_scheduler.py`、`tests/test_browser.py`、`tests/test_life_tool.py`、`tests/test_webui.py`；版本 v0.5.22 → v0.5.23。
- 验证：全量 `unittest discover -s tests` 317 条，仅 `test_config` 与生产 AstrBot 混装的已知 ImportError，skipped=1；受影响文件 db 68、scheduler 31、browser 63、life_tool 16、webui 24 全绿；页面内联脚本 `node --check` 与 `compileall` 提交前执行。
- 遗留：watchlist 稳定 URL 更新语义、故地重游失败候选头部阻塞、统一记忆宿主孤儿、工具 add 无 ESM 精力 gate、结构性重复与页面未用视图仍未动。
- 下一步：提交 `chore(release): v0.5.23 ...`，随后继续第三轮（watchlist/revisit/rollback 鬼影/fetchers 边界）。

## 2026-10-27 审计后的第三批修复：死代码、重复实现与 lint 基线（v0.5.22）
- 目标：按审计报告 batch 3 清理无生产调用的代码与重复实现，修正文档/提示词里未被消费的字段，并让 `ruff --select F,E9` 回到全绿。
- 已确认决策：
  - 死代码以"生产调用为零"为准删除，不保留"以后可能用"的公共方法；`mark_seen` 的测试改为走真实的 `stage_seen + commit_staged` 路径。
  - `life_personas` 空列表的语义统一为"不允许任何 persona"（与 `_conf_schema.json` 的提示一致）；缺省配置（None）仍视为不限制。这是有意的行为变更，已写入 CHANGELOG。
  - `cleanup_expired_leases` 不删除，改为在调度器每轮调用，避免只为测试存在的死方法，也防止不再被复用的任务键留下过期租约。
  - 提示词只保留执行端真正消费的字段：删除 `energy_change` / `revisit_day_offset` / `revisit_note_ids` / `highlights`，减少无效输出 token；日记叙事要求不变。
  - 租约助手的 `kind` 参数从未参与任何决策，直接移除，测试同步。
  - 不在本批动结构性重复（两套 persona 解析、10 个 Tool 类、review/quarterly 同构主体、`started_at` 死列、兼容端点），避免把清理批次变成高风险重构。
- 改动：`life/config.py`（`persona_allowed`）、`life/life_tool.py`、`life/chat_hooks.py`、`life/presence.py`、`life/injection.py`、`life/db.py`、`life/scheduler.py`、`life/webui.py`、`life/prompts.py`、`pages/life/index.html`、`docs/design.md`、`tests/test_config.py`、`tests/test_db.py`、`tests/test_injection.py`、`tests/test_scheduler.py`、`tests/test_interests.py`、`tests/test_browser.py`、`tests/test_share.py`、`README.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.21 → v0.5.22。
- 验证：全量 `unittest discover -s tests` 300 条，仅 `test_config` 与生产 AstrBot 混装的已知 ImportError，skipped=1；`ruff check --select F,E9 life tests main.py` 全绿；页面内联脚本 `node --check` 通过；`compileall` 通过。
- 遗留：结构性重复见 CHANGELOG Notes；页面仍未给 usage/archive/interests/injection_log 提供视图；`life_plans.started_at` 仍是死列；两个 change_log 端点保持兼容。
- 下一步：提交 `chore(release): v0.5.22 ...`，随后按用户决定是否推送 v0.5.20–v0.5.22 三个提交。

## 2026-10-27 审计后的第二批修复：数据一致性、工具边界与健壮性（v0.5.21）
- 目标：继续按审计报告修 batch 2 —— 并发/迁移索引、事件幂等、记忆编辑与回滚、提交后副作用、工具通道绕过计划硬约束、watchlist/多话题/探索位、LLM 与 persona 缓存的健壮性。
- 已确认决策：
  - 并发用数据库写冲突兜底：`ensure_plan` / `add_optional_plan` 改 `INSERT OR IGNORE` 后回查；不引入全局锁。
  - 事件幂等键必须携带"这一次变更的身份"：软删/恢复带 change_log id，defer 带 scheduled_at，skip 带 now，LLM 编辑带 action/status；owner 批准/拒绝/回滚也补写事件链，避免事件链只剩工具侧一半。
  - 已提交（commit_staged）的浏览/日记不再因为能量记账、事件写入、兴趣衰减失败而返回 error，后置副作用失败只记 warning；LLM 通道的 add/defer 必须先过 config 提供的睡眠窗、过去时间、每日上限与 diary 依赖。
  - `notes_min` 用确定性候选补齐而不是反复重试 LLM；探索位必须进入最终选题，不能再被 `[:count]` 切掉；fetch_all 对每个话题都检索（tavily 暂仍只用首话题）。
  - 回收站删除后把 `change_log` 中的正文快照清空；`wishlist` 转正不重置已有兴趣的 weight/seen_count/名字，并补一条 change_log。
  - 统一记忆宿主没有删除接口，宿主先写、本地 commit 失败的孤儿无法补偿；本次只记录为已知限制，不引入半吊子删除。
- 改动：`life/db.py`、`life/browser.py`、`life/life_tool.py`、`life/webui.py`、`life/config.py`、`life/interests.py`、`life/fetchers.py`、`life/persona.py`、`life/llm.py`、`tests/test_db.py`、`tests/test_browser.py`、`tests/test_life_tool.py`、`tests/test_config.py`、`tests/test_interests.py`、`tests/test_fetchers.py`、`tests/test_llm.py`、`tests/test_persona.py`、`tests/test_webui.py`、`README.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.20 → v0.5.21。
- 验证：单文件全绿（db 64、browser 58、life_tool 15、config 27、interests 6、fetchers 8、llm 13、persona 4、webui 21）；全量 `unittest discover -s tests` 300 条，仅 `test_config` 与生产 AstrBot 混装的已知 ImportError，skipped=1；页面本批未改，提交前仍跑 `node --check` 与 `compileall`。
- 遗留：`memory_host` 孤儿数据无补偿；`chat_hooks` 事件键仍含 timestamp（真正去重依赖 event extra `yol_message_in_recorded`，未改以免动真实事件链）；工具通道 add 仍未做精力 gate（工具未注入 ESM）；WebUI memory search 页面传 k=20 仍被后端压到 10；审计 batch 3（死代码/重复实现/词表与提示词字段未消费/测试补齐）未动。
- 下一步：提交 `chore(release): v0.5.21 ...`，随后开始 batch 3。

## 2026-10-27 完备性/冗余性审计后的第一批修复：断链与调度器（v0.5.20）
- 目标：对仓库做完备性与冗余性审计后，按批次修复真实断链与状态机缺陷；本批为 batch 1（胶囊自动封存、回收站视图、reset 完整性、调度器状态机、计划时间校验）。
- 已确认决策：
  - 胶囊封存不再依赖不存在的调用方：夜间复盘每天从当日短记中挑 `(interest_level, id)` 最大的一条封存一条（当日已封存则跳过），复用 `seal_capsule_for_note`；手动打开只把 sealed 改 unlocked，不覆写 `unlock_at`。
  - 回收站入口补在 WebUI（新增 tab + `POST /trash_add`），清理沿用夜间复盘、按 `trash_retention_days` 执行；`purge_trash` 删除短记前先删引用它的 `time_capsules`。
  - 调度器 `_run` 包成 supervisor（异常 5s 后重启），原循环改名 `_run_loop`；目标次日先 `ensure_plan` 播种；当日错过槽位补做；等待期结束重读计划状态，非 pending 则跳过；`update_plan` 增加 `only_if_status`，租约冲突/收尾只改 pending。
  - 计划时间一律严格 `HH:MM`（`datetime.strptime`），非法直接拒绝；窗口结束支持 `24:00`。
  - 胶囊/回收站修复只做"可达 + 幂等"，不改变 `change_log` 语义与权限模型（留待 batch 2/3）。
- 改动：`life/db.py`、`life/browser.py`、`life/scheduler.py`、`life/life_tool.py`、`life/webui.py`、`pages/life/index.html`、`tests/test_db.py`、`tests/test_browser.py`、`tests/test_scheduler.py`、`tests/test_life_tool.py`、`tests/test_webui.py`；版本 v0.5.19 → v0.5.20。
- 验证：受影响 5 个测试文件全绿（db 59、browser 54、webui 20、life_tool 13、scheduler 27）；全量 `unittest discover -s tests` 282 条，仅 `test_config` 与生产 AstrBot 混装的已知环境错误（单独跑通过）；页面内联脚本 `node --check` 通过；`compileall` 通过。
- 遗留：审计 batch 2（宿主/本地写入顺序、commit 后异常仍报 error、`weight=0.0` 回滚、事件幂等键、工具通道绕过计划硬约束、watchlist 解析、多话题丢失等）与 batch 3（死代码/重复实现/词表与提示词字段未消费、测试补齐）未动；仓库根 `astrbot_test_kit_runs/` 仍未纳入 `.gitignore`。
- 下一步：提交 `chore(release): v0.5.20 ...`，随后按审计报告继续 batch 2。

## 2026-08-19 修复 v0.5.18 后插件页整体卡死：桥注入点被注释里的闭合标签截获（v0.5.19）
- 目标：用户反馈 v0.5.18 后 Dashboard 插件页"直接卡住了"，定位并修复。
- 已确认决策：
  - 根因：`pages/life/index.html` 第 452 行 JS 注释含字面量 `</body>`。AstrBot 注入桥脚本用朴素 `replace("</body>", bridge_tag, 1)`（`dashboard/routes/plugin.py` `_rewrite_plugin_page_html`），取首个匹配位置——命中了注释而非真正的闭合标签。注入的桥标签含 `</script>`，落在 `<script>` raw text 里把页面主脚本提前截断，453 行之后的全部 JS 被当成 HTML 解析（console 里大量 SVG 属性报错即证据），页面功能全灭，呈现"卡住"。
  - 生产实证：用 cmd_config.json 的 jwt_secret 自签 dashboard JWT，Playwright 走真实 SPA（hash 路由 `/#/plugin-page/<plugin>/<page>`）复现：注入点错位确认；修复后重跑，bridge-sdk.js 200、`hasBridge: true`、personas/overview/status/heatmap 全 200、errorBanner 为空、截图渲染正常。
  - 修复：移除注释中的闭合标签字面量并加警示注释（JS 注释/字符串内禁止再出现 body/html 闭合标签字面量）；首次 `load()` 改为 `waitForBridge(3000).then(load)`（桥注入在本内联脚本之后，解析期拿不到桥）。
- 改动：`pages/life/index.html`、`life/__init__.py`、`metadata.yaml`、`CHANGELOG.md`、`README.md`、`docs/requirements.md`；版本 v0.5.18 → v0.5.19。
- 验证：生产真实 dashboard Playwright 端到端通过（见上）；全量单测与 UTF-8 读回校验在本次提交前执行。
- 遗留：桥不可用的裸 fetch 回退路径（直接访问场景）未单独实测；AstrBot 上游注入逻辑对注释/字符串内闭合标签的误判属上游行为，本仓库只能规避。
- 下一步：提交 `chore(release): v0.5.19 ...` 并推送 origin main。

## 2026-08-19 修复 Dashboard 全面「XXX加载失败」：接入插件页桥鉴权（v0.5.18）
- 目标：修复 WebUI Dashboard 所有面板均显示「XXX加载失败」的问题。
- 已确认决策：
  - 根因：`pages/life/index.html` 用裸 `fetch("/api/plug/astrbot_plugin_your_own_life/api/...")` 调后端，不带 dashboard JWT；AstrBot（v4.25.5，`C:\application\AstrBot`）的 `auth_middleware` 对非白名单 `/api/...` 无 JWT 一律 401，插件页是受保护 iframe（cookie 为 httponly+samesite=Strict），裸 fetch 拿不到凭据。生产实测 `http://127.0.0.1:6185/api/plug/.../personas` 返回 401 确认。
  - 修复方案：接入官方插件页桥 `window.AstrBotPluginPage.apiGet/apiPost`（dashboard 注入 bridge-sdk.js，父页面带 JWT 代理），桥不可用时回退裸 fetch（开发/独立打开场景）。响应解包遵循桥语义 `data.data ?? data`（本插件 webui.py 返回体无顶层 `data` 键，透传安全）。与 engram_core 家族插件同模式。
  - 端点参数化：26 个 fetch 调用点统一为 `apiGet("xxx", {...})` / `apiPost("xxx", {...})`，助手内拼 `"api/" + path`。
- 改动：`pages/life/index.html`（全部 27 处经 safe_edit）、`life/__init__.py`、`metadata.yaml`、`CHANGELOG.md`、`README.md`、`docs/requirements.md`；版本 v0.5.17 → v0.5.18。
- 验证：test-kit venv 全量 `unittest discover -s tests -v` 273 passed（skipped=1）；提取页面内嵌脚本 `node --check` SYNTAX OK；Playwright 模拟桥加载真实页面：personas/overview/status/heatmap 四调用经桥、渲染正确、无错误横幅；11 个 tab 全部经桥取数、无 pageerror（验证脚本 tmp/verify_bridge/ 已删除）。
- 遗留：真实生产 AstrBot dashboard 内打开页面未实测（需用户刷新插件页确认）；桥不可用的裸 fetch 回退路径未单独测试。
- 下一步：提交 `chore(release): v0.5.18 ...` 并推送 origin main。

## 2026-08-16 review/debug：聊天事件时间戳与日期敏感测试（v0.5.17）
- 目标：review 当前仓库并 debug；修复 `test_chat_hooks` 依赖真实日期导致的失败，以及测试失败后 SQLite 临时文件在 Windows 上的清理锁。
- 已确认决策：`event_chain.ts` 必须使用调用方注入的 persona 本地时钟（`now_fn`），与 payload 内的 `ts` 保持一致；`message_in` / `reply_out` / `conversation_end` 三个聊天事件统一补 `ts=`。
- 改动：`life/chat_hooks.py`、`life/presence.py`、`tests/test_chat_hooks.py`、`tests/test_presence.py`、`README.md`、`docs/requirements.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.16 → v0.5.17。
- 验证：test-kit venv 全量 `unittest discover -s tests -v` 273 passed（skipped=1）；`compileall` OK；`git diff --check` clean。
- 遗留：README/兼容矩阵的版本漂移本次已同步；真实 AstrBot 生产 hook 行为与多时区部署仍待实测。
- 下一步：提交 `chore(release): v0.5.17 ...` 并推送 origin main。

## 2026-08-13 review 修复与测试基线稳定（v0.5.16）
- 目标：修复 review 发现的时区、分享预算、兴趣 staged 累加、夜间复盘后置动作、WebUI 非法输入和 persona 缓存时区问题；先稳定日期敏感的测试基线。
- 已确认决策：
  - 测试日期基线只在测试内统一固定时间，不引入生产时钟基础设施改动。
  - ShareGate 增加可选 `managed_llm`，生产环境复用 `LifeService._llm_call`；测试和旧调用保持 fallback。
  - InterestStore 增加 per-run keyed staging 状态，避免同一批相同 interest key 覆盖。
  - 夜间复盘 `commit_staged` 后的后置动作独立 try/except，失败只返回 `aux_error`，不再把已提交日记标为 error。
- 改动：`main.py`、`life/chat_hooks.py`、`life/share.py`、`life/interests.py`、`life/browser.py`、`life/webui.py`、`life/persona.py`、`life/__init__.py`、`metadata.yaml`、`CHANGELOG.md`、`tests/test_db.py`、`tests/test_browser.py`、`tests/test_chat_hooks.py`、`tests/test_interests.py`、`tests/test_share.py`、`tests/test_webui.py`。
- 验证：test-kit venv 全量 `unittest discover -s tests -v` 272 passed，skipped=1；`compileall` OK；`git diff --check` clean。
- 遗留：网络冒烟和真实生产 WebUI/hook 行为仍未验证；多节点部署与生产时区边界仍需要实测。
- 下一步：按仓库习惯提交 `chore(release): v0.5.16 ...` 并 push origin main。

## 2026-08-12 平台对话感知：忙碌延迟回复 + 对话等待窗 + 对话入事件链（v0.5.15）
- 目标：让“bot 在忙所以晚回、回完等一会儿、然后继续生活”成为真实行为，并把平台对话本身写进事件链。
- 已确认决策：
  - 新增 `life/presence.py`：per-persona busy 状态与对话等待窗；生活任务开始时置忙、结束清忙，聊天侧可 `wait_until_free`。
  - 新增 `life/chat_hooks.py`：`on_llm_request` 记录 `message_in`、忙碌时等待并注入 `<life-presence>` 块（`extra_user_content_parts` + `TextPart.mark_as_temp`）；`on_llm_response` 记录 `reply_out` 并打开等待窗；窗口超时写 `conversation_end`。
  - 调度器按对话等待窗过滤可执行 persona，窗口内不推进该 persona 的定时事件。
  - 新增配置 `life_presence_enabled`（默认 true）、`conversation_wait_minutes`（默认 5）、`busy_reply_max_wait_minutes`（默认 30）。
- 改动：`life/presence.py`、`life/chat_hooks.py`、`life/config.py`、`life/browser.py`、`life/scheduler.py`、`main.py`、`_conf_schema.json`、`tests/test_presence.py`、`tests/test_chat_hooks.py`、`tests/test_scheduler.py`、`README.md`、`docs/features.md`、`docs/design.md`、`docs/roadmap.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.14 → v0.5.15。
- 验证：unittest 267 passed（skipped=1；新增 presence 3、chat_hooks 7、scheduler 等待窗 1）；UTF-8 读回无 `\ufffd`。
- 遗留：“bot 自己觉得不想聊了”目前以等待窗超时作为系统兜底，LLM 主动结束信号未落地；`conversation_end` 只在窗口超时写；coze/dify 等第三方 runner 对 `extra_user_content_parts` 的透传需真实环境验证。
- 下一步：`git diff --check` 后提交 `chore(release): v0.5.15 ...` 并推送 origin main。

## 2026-08-12 新增 query_life_status 聊天侧生活状态工具（v0.5.14）
- 目标：让 bot 在 QQ 等对话场景能知道自己刚才/今天在干什么、读了什么新闻，补上“事件链可查但聊天侧无入口”的缺口。
- 已确认决策：新增只读 LLM 工具 `query_life_status`，按当前 persona 返回当天 browse/peek 会话、状态快照、事件链条目与短记；调用本身写 `recall` 事件（`query=life_status`）；不新增配置项，`life_tool_enabled` 开关统一生效。
- 改动：`life/life_tool.py`、`main.py`、`tests/test_life_tool.py`、`README.md`、`docs/features.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.13 → v0.5.14。
- 验证：unittest 256 passed（skipped=1；新增 3 个回归）；UTF-8 读回无 `\ufffd`。
- 遗留：事件链本地查询仍按当天截取，跨日“最近经历”需要传具体 date；宿主镜像失败仍按 warning 记录。
- 下一步：`git diff --check` 后提交 `chore(release): v0.5.14 ...` 并推送 origin main。

## 2026-08-12 README 配置清单与版本同步（docs 批次）
- 目标：修复根 README 配置项落后于 `_conf_schema.json` 的问题，并把文档中的插件版本同步到 v0.5.13。
- 已确认决策：README 配置章节改为从 schema 生成的完整表格（60 项，含类型/默认值/说明），不再维护精简清单；根 README 补当前版本、v0.5.11-v0.5.13 工程修复条目并更新多实例/生态描述。
- 改动：`README.md`、`docs/requirements.md`（兼容矩阵本插件版本 v0.5.10 → v0.5.13）。
- 验证：脚本对比 README 表格与 `_conf_schema.json`，60 个配置项一一对应、无缺漏/多余；UTF-8 读回 0 个 `\ufffd`；`git diff --check` 干净。
- 遗留：`docs/roadmap.md` 早期版本段落仍保留历史口径（不影响现状）；纯文档改动，未跑代码测试。
- 下一步：提交 `docs: 同步 README 配置清单与插件版本` 并推送 origin main。

## 2026-08-12 矩阵 P2 修复：安全/硬约束类 + 租约续租与文档口径收敛（v0.5.13）
- 目标：按 `docs/consistency.md` 优先级先修安全类（SVG 转义）与硬约束类（睡眠窗口 / reject kind / rollback 权限），再补租约续租与文档口径收敛。
- 已确认决策：
  - WebUI 实体图 `data-entity` / `data-id` 改为 `escAttr()` 转义，事件链过滤/标签新增 `reject`（拒绝）。
  - 睡眠窗口统一外推 browse/diary/peek 与月度/年度/季度 review 槽位，`run_peek` / `run_nightly_diary` 入口也做 `sleep_window.contains` 拦截。
  - 系统裁决拒绝事件 kind 由 `change` 改为 `reject`。
  - LLM rollback 仅允许回滚 `actor=llm` 的 applied 条目，owner 走 WebUI 直接调 db 不受影响。
  - 长任务按 TTL/2（最小 1s）定期续租：memory_host 走 `renew_task`，否则本地 `renew_lease`；任务结束取消 keepalive 后释放。
  - 变更账本文档口径收敛：账本覆盖 owner/LLM 显式变更与删除/恢复等可逆写操作，普通生活写操作以事件链记录。
- 改动：`pages/life/index.html`、`life/scheduler.py`、`life/browser.py`、`life/life_tool.py`、`tests/test_scheduler.py`、`tests/test_browser.py`、`tests/test_life_tool.py`、`docs/features.md`、`docs/design.md`、`docs/consistency.md`、`CHANGELOG.md`、`metadata.yaml`、`life/__init__.py`；版本 v0.5.12 → v0.5.13。
- 验证：unittest 253 passed（skipped=1；新增 7 个回归：睡眠窗口外推 x2、review 槽位外推、续租 memory_host/本地/长任务、diary/peek 睡眠拦截、rollback actor 限制）；`_conf_schema.json` 递归校验无缺 `items` 的 list 节点；UTF-8 读回无 `\ufffd`。
- 遗留：矩阵其余 P2/P3 未动：提交后副作用异常误标 failed、`_plan_time` 范围校验、`share_note` 500、沉默率日掷语义、memory_host 镜像 warning、`purge_trash` 胶囊级联、revisit 崩溃窗口等。
- 下一步：`git diff --check` 后提交 `chore(release): v0.5.13 ...` 并推送 origin main。

## 2026-08-12 功能实现与设计目标一致性审计（docs 批次）
- 目标：按功能逐项确认实现逻辑与设计目标的一致性，沉淀可追踪矩阵。
- 方法：4 个只读 subagent 分域审查（行为层/记忆档案/人格安全/WebUI 适配），主 agent 复核高影响结论；基线 246 passed（skipped=1）。
- 结论：无 P1 级设计矛盾；L0/L1/L1.5/L2 已交付功能主体对齐，偏差集中在边界语义与低概率一致性问题，完整矩阵见新增 `docs/consistency.md`。
- 主要偏差（P2）：睡眠窗口只对 browse 生效；提交后副作用异常把已落库 run 标 failed；变更账本仅覆盖 owner/LLM 变更；热力图点击跳档缺失；`register_web_routes` 回退缺失；`_plan_time` 不校验范围；系统裁决拒绝事件 kind 用 `change`；LLM rollback 无 actor 限制；interest 编辑误改 seen_count；实体图 SVG 属性未转义；沉默率不是每天只掷一次；memory_host 镜像失败仅 warning；生产无租约续租；`share_note` 非法 body 500。
- 改动：新增 `docs/consistency.md`，`docs/README.md` 索引加行；版本不变（纯文档）。
- 验证：UTF-8 读回无 `\ufffd`；未改代码，无需重跑单测。
- 下一步：按矩阵优先级修安全类（SVG 转义）与硬约束类（睡眠窗口/reject kind/rollback 权限），再补租约续租与文档口径收敛。

## 2026-08-12 第二轮全量 review 修复：暂存捕获/软删/启动恢复与调度锚定（v0.5.12）
- 目标：三个只读 subagent（db、服务层/调度、WebUI/适配层）再 review 一遍，落地确认的 P1，其余 P2/P3 记录遗留。
- 已确认决策：
  - `commit_staged` 用 `INSERT ... RETURNING id` 精确捕获本次插入，移除按 URL hash/标题/时间 JOIN 反查（v0.5.11 的 JOIN 修复仍有同秒碰撞）。
  - 日记 upsert 重写时重置 `deleted_at`，软删后同日重写可再次可见。
  - `recover_stale_runs` 增加 1 小时年龄门槛，清理全部 staging 表的 NULL-session 与负 token 残留；diary/revisit 每轮用独立负 token，`commit_staged(None)` 不再聚合匿名 staging。
  - `enabled=False` 统一门控调度器与日记/回顾/胶囊/重游；调度 `task_id`/`plan_date` 锚定原始槽位，jitter 跨午夜不再错位。
- 改动：`life/db.py`、`life/browser.py`、`life/scheduler.py`、`tests/test_db.py`、`tests/test_scheduler.py`、`tests/test_browser.py`；版本 v0.5.11 → v0.5.12；CHANGELOG 同步。
- 验证：unittest 246 passed（skipped=1；新增 8 个回归：捕获碰撞、日记软删重写 x2、恢复多实例/孤儿清理、token 隔离、enabled 门、跨午夜锚定、disabled 循环退出）。
- 遗留（subagent 已确认、本轮未修）：
  - P2：share 渲染未计入 LLM 预算；调度循环无顶层异常兜底；长任务无租约续租；睡眠窗口只对 browse jitter 生效；commit 后副作用异常会把 session 标 failed；兴趣键/名无注入清洗；日记同日重跑无幂等事件；WebUI 实体图 SVG 属性注入；memory 合并去重；interest 编辑误改 seen_count；timeline 分页；share_note 非法 body 500；time_slots schema 与解析器不一致；LLM rollback 可回滚 owner 变更；`_plan_time` 不校验范围。
  - P3：config clamp 不齐、review_schedule 逐键合并、错过槽位永补、`_done_keys` 无界、迁移非崩溃安全等。
- 下一步：按 P2 优先级修 share 预算与调度健壮性；提交推送 v0.5.12。

## 2026-08-12 全量 review 修复：启动配置崩溃与重访链漏洞（v0.5.11）

- 目标：修掉用户报告的插件加载错误 `'items'`，并把全量 review 发现的 P2/P3 一起收口。
- 已确认决策：
  - AstrBotConfig 对 `type: "object"` 强制读取 `v["items"]`，`time_slots` / `review_schedule` 补子 schema；`time_slots` 补完整 default 并清理重复键。
  - `commit_staged` 改为提交前记录 staging IDs、提交后按 `notes JOIN staging_notes` 捕获新短记，只返回本次提交内容。
  - WebUI 重访链按 `revisit_of` 分组，避免多链 follow-up 交错挂错。
  - `memory_overview` 排除软删除短记；`_apply_change_payload` 非法 note id 返回 False。
  - config 回归测试显式加载真实 AstrBotConfig（绕过 `_astrbot_stub` 遮蔽），并新增 schema 结构校验。
- 改动：`_conf_schema.json`、`life/db.py`、`life/browser.py`、`life/webui.py`、`tests/test_config.py`、`tests/test_db.py`、`tests/test_webui.py`；版本 v0.5.10 → v0.5.11；CHANGELOG 同步。
- 验证：unittest 238 passed（skipped=1，网络冒烟按配置跳过）；真实 AstrBotConfig 加载 schema 无 `'items'` 异常且保留用户值；JSON / UTF-8 校验通过。
- 遗留：`commit_staged` 捕获查询仍用 `%` 拼接占位符（参数已核对，整数 id 无注入面），后续可改纯参数化。
- 下一步：提交 `chore(release): v0.5.11 全量 review 修复启动配置与重访链漏洞`，测试通过后推送。

## 2026-08-12 L2-11 故地重游落地 + L2 全部完成（v0.5.10）

- 目标：定期重访旧短记链接，写“后来呢”，并完成 L2 最后一个阶段。
- 已确认决策：新增 `revisit_interval_days`（默认 30，最小 1）；夜间复盘在胶囊处理后调用 `run_revisit`：按阈值选未重访旧短记（`list_revisit_candidates`，排除已有重访的），LLM 以“后来呢”视角生成 `title/summary/opinion/mood`，新短记 `source=revisit/*` 复用原 URL hash 并 `mark_note_revisit` 指向原短记；`notes` 去掉 `UNIQUE(persona_id, url_hash)` 并新增 `idx_notes_persona_url`，旧库启动自动重建迁移；`revisit` 事件幂等键 `revisit/{original_id}`（失败用 `.../failed`），预算耗尽停止并写 `revisit_skipped` 快照；WebUI 新增 `GET /revisit_chains` 与“故地重游”tab 串联原短记/后续短记。
- 改动：`life/db.py`（`revisit_of` 列 + `_migrate_notes_unique` 表重建 + `list_revisit_candidates / list_notes_by_url_hash / mark_note_revisit / list_revisit_chains` + `commit_staged(None)` 返回查询修复）、`life/config.py`、`_conf_schema.json`、`life/prompts.py`（`build_revisit_prompt`）、`life/browser.py`（`run_revisit` + 夜间接入）、`life/webui.py`（`/revisit_chains`）、`pages/life/index.html`（tab + 列表）、`tests/test_db.py`、`tests/test_config.py`、`tests/test_browser.py`、`tests/test_webui.py`；版本 v0.5.9 → v0.5.10；README / CHANGELOG / features.md L2-11 与 L2 小结 / design.md / roadmap.md / requirements.md 兼容矩阵同步。
- 验证：unittest 232 passed（skipped=1；重访候选/同链接查询/标记/链查询、旧库唯一约束迁移、`revisit_interval_days` 默认与 clamp、`run_revisit` 生成/幂等跳过/预算跳过、夜间复盘接入、WebUI 接口与路由）；HTML 内联 JS `node --check` 通过；Playwright 故地重游 tab 桌面 1280x900 / 移动 390x844 渲染、链内容与无横向溢出通过。
- 遗留：重访短记不更新兴趣权重（轻动作，刻意不做）；统一记忆宿主侧的 `revisit_of` 仅作为 note 字段透传，宿主无专门重访链查询。
- 下一步：提交 `chore(release): v0.5.10 落地 L2-11 故地重游`；L1/L1.5/L2 全部完成后，推送需用户确认（当前 own_life 领先 origin/main 33 个提交，ESM 1 个，engram_core 2 个，均未推送）。

## 2026-08-12 L2-10 关注对象落地（v0.5.9）

- 目标：主人配置持续关注名单（博客、GitHub 用户/项目、RSS），形成追更感。
- 已确认决策：新增 `watchlist` 配置（dict 或 `type:id:url` 字符串，支持 blog/github_repo/github_user/rss）；`fetch_watchlist` 抓取并把来源统一标记为 `watchlist/*`，`fetch_all` 并入选题候选；漫游写入统一记忆库时带 `watched`，实体图 URL 节点标记 `watched`；DB 新增 `list_watched_notes`；WebUI 新增“关注”tab（`GET /watchlist`）展示关注项与近期更新；状态卡/时间轴复用 notes 天然可见。
- 改动：`life/config.py`、`_conf_schema.json`、`life/fetchers.py`、`life/browser.py`、`life/db.py`、`life/webui.py`、`pages/life/index.html`、`tests/test_config.py`、`tests/test_fetchers.py`、`tests/test_db.py`、`tests/test_browser.py`、`tests/test_webui.py`；版本 v0.5.8 → v0.5.9；README / CHANGELOG / features.md L2-10 / design.md / roadmap.md 同步。
- 外部调研（DuckDuckGo，2026-08-12，已验证检索可访问）：personal watchlist / feed curation 相关文章标题（如 "Your Watchlist, Curated: How a Personalized Feed Replaces the Morning..."）；采纳持续关注源进入选题候选，未细读原文，结论按推测性借鉴标注。
- 验证：unittest 225 passed（skipped=1；watchlist 解析、关注短记查询、HTML 解析、实体 watched、WebUI 接口/路由）；JS 语法检查通过；Playwright 关注 tab 桌面/移动无溢出通过。
- 遗留：watchlist 抓取失败只 debug 日志，不写审计；博客类型仅抓首页 title/description，不做全文解析。
- 下一步：L2-11 故地重游（`revisit_interval_days`，链接级 revisit，新短记带 `revisit` 标记并引用原链接）。

## 2026-08-12 L2-09 多实例租约接入 scheduler（v0.5.8）

- 目标：配置统一记忆宿主后，同人格多实例任务经宿主租约串行化，保证事件链单写者。
- 已确认决策：scheduler 新增 `_acquire_lease / _release_lease`；配置 `memory_host` 且有 memory adapter 时调用宿主 `claim_task / release_task`（TTL 用 `memory_lease_ttl_seconds`，holder 用实例 ID），claim 失败走既有 `skipped_duplicate` 跳过路径；未配置 host 时回退本地 SQLite `acquire_lease / release_lease`；释放统一走 helper，不重复记录。
- 改动：`life/scheduler.py`、`tests/test_scheduler.py`；版本 v0.5.7 → v0.5.8；README / CHANGELOG / features.md L2-09 / design.md / roadmap.md 同步。
- 外部调研（DuckDuckGo，2026-08-12，已验证检索可访问）：分布式租约/单写者相关文章标题（"AI Agent Distributed Locking: TTL Leases, Fencing Tokens, and Recovery"、"Designing a Correct Distributed Lease Service"、"Building Distributed Leases With Consensus, Heartbeats, and Fencing Tokens"）；采纳 claim/release + TTL 过期释放，未细读原文，结论按推测性借鉴标注。
- 验证：unittest 220 passed（skipped=1；内存宿主租约 claim/release、拒绝跳过、本地回退）。
- 遗留：长任务执行期间未做 `renew_task` 续约（当前任务通常短于 TTL）；宿主侧租约过期自动释放由 engram_core `TaskLeaseStore` 保证。
- 下一步：L2-10 关注对象（`watchlist` 配置 + fetcher/browser 接入）。

## 2026-08-12 L2-08 LLM 自主更改与自动回滚落地（v0.5.7）

- 目标：LLM 可改生活记忆/兴趣/计划，白名单外需 owner 确认，owner 可批准、拒绝、回滚任何改动。
- 已确认决策：新增 `life_edit_allowed` 白名单（默认 `note.summary / note.opinion / interest.weight`）；`edit_life_memory` 工具支持 `update / rollback`；白名单内直接应用并写 `change_log`（status=applied）与 `change` 事件，越界动作写 `pending_owner`；DB 新增 `update_note_field / get_change_log_entry / apply_change / reject_change / rollback_change`，回滚还原 old_value 并追加一条 `rolled_back` 审计条目；WebUI 新增“改动”tab：`GET /life_edits` + `POST /life_edits_approve|reject|rollback`。
- 改动：`life/config.py`、`_conf_schema.json`、`life/db.py`、`life/life_tool.py`、`main.py`、`life/webui.py`、`pages/life/index.html`、`tests/test_config.py`、`tests/test_db.py`、`tests/test_life_tool.py`、`tests/test_webui.py`；版本 v0.5.6 → v0.5.7；README / CHANGELOG / features.md L2-08 / design.md / roadmap.md 同步。
- 外部调研（DuckDuckGo，2026-08-12，已验证检索可访问）：agent 自主编辑与人工审批安全边界相关论文/指南标题（"SafeHarbor: Defining Precise Decision Boundaries..."、"LLM Guardrails: The Complete Guide to AI Safety Guardrails"）；采纳白名单 + owner 确认 + 回滚审计，未细读原文，结论按推测性借鉴标注。
- 验证：unittest 218 passed（skipped=1；字段更新、apply/reject/rollback 生命周期、LLM 工具白名单/待确认/回滚、WebUI 接口与路由）；JS 语法检查通过；Playwright 改动 tab 桌面/移动无溢出、按钮交互通过。
- 遗留：计划类改动仍走既有 `edit_life_plan`（固定任务不可改）；记忆宿主（engram_core）侧编辑/回滚尚未经 adapter 同步，后续可在 L2 收尾时补。
- 下一步：L2-09 多实例租约接入 scheduler（配置 memory_host 时改用 `claim_task / renew_task / release_task`）。

## 2026-08-12 L2-07 季度自我评估落地（v0.5.6）

- 目标：基于兴趣与情绪轨迹生成带 confidence 的季度人格总结，owner 可在 WebUI 对比上一期。
- 已确认决策：新增 `quarterly_review_enabled`（默认 true）；调度器在 1/4/7/10 月首日 09:15 播种 `review-quarterly` 固定任务；`_review_range` 支持季度区间；`run_quarterly_review` 聚合漫游/日记/兴趣/情绪分布，LLM 输出 `review_text` + `confidence`，失败回退确定性聚合（confidence 0.5）并标 fallback；`reviews` 表新增 `confidence` 列（含迁移）；WebUI 新增“回顾”tab：`GET /reviews` 列表 + `GET /reviews_diff`（difflib unified diff）对比上一期季度评估。
- 改动：`life/config.py`、`_conf_schema.json`、`life/db.py`、`life/prompts.py`、`life/browser.py`、`life/scheduler.py`、`life/webui.py`、`pages/life/index.html`、`tests/test_db.py`、`tests/test_config.py`、`tests/test_scheduler.py`、`tests/test_browser.py`、`tests/test_webui.py`；版本 v0.5.5 → v0.5.6；README / CHANGELOG / features.md L2-07 / design.md / roadmap.md 同步。
- 外部调研：本次 DuckDuckGo 检索两次均无输出（工具失败，疑似限流），未获得新来源；沿用 L2-04 memory reflection 检索标题，季度结构按设计文档与推测性借鉴落地，结论标注推测。
- 验证：unittest 213 passed（skipped=1；季度评估生成/回退、confidence、调度槽位、WebUI 回顾与 diff）；JS 语法检查通过；Playwright 回顾 tab 桌面 1280x900 / 移动 390x844 渲染、diff 交互与无横向溢出通过。
- 遗留：center state（未排期）落地后季度评估可接入人格中心态做漂移分析；当前 diff 为文本级 unified diff，非结构化观点对比。
- 下一步：L2-08 LLM 自主更改与自动回滚（权限边界 + 变更账本回滚）。

## 2026-08-12 L2-06 分享沉默率落地（v0.5.5）

- 目标：ShareGate 增加概率性“今天不想说”，避免每次都机械表达；沉默当天不写分享日志，日记能体现。
- 已确认决策：新增 `share_silence_rate`（默认 0.15，clamp 0-1）；每天第一次分享按概率掷一次，命中后写 `share_silent` 状态快照（含 reason），当天后续分享全部跳过；沉默时 note 标记 `dropped`、不写 share_log、不发送；手动分享（`/life_share` 与 WebUI `share_note`）传 `force=True` 绕过沉默；`ShareGate` 支持注入 `rng` 便于测试。
- 改动：`life/config.py`、`_conf_schema.json`、`life/db.py`（`has_snapshot_activity`）、`life/share.py`、`main.py`、`life/webui.py`、`tests/test_share.py`、`tests/test_config.py`；版本 v0.5.4 → v0.5.5；README / CHANGELOG / features.md L2-06 / design.md / roadmap.md 同步。
- 外部调研（DuckDuckGo，2026-08-12，已验证检索可访问）：bot / human posting behavior 相关研究标题（如 "A global comparison of social media bot and human characteristics"）；采纳概率性沉默增加表达自然度，未细读原文，结论按推测性借鉴标注。
- 验证：unittest 208 passed（skipped=1；新增沉默概率跳过、全天沉默、手动 force 绕过、配置 clamp）。
- 遗留：沉默快照目前仅作为日记素材，WebUI 分享页未单独展示“今天沉默”状态；可后续补充。
- 下一步：L2-07 季度自我评估（`quarterly_review_enabled` + 兴趣/情绪轨迹长期总结 + owner 查看 diff）。

## 2026-08-12 L2-05 时间胶囊落地（v0.5.4）

- 目标：封存一条短记，到期自动解锁并让 LLM 以“当时的我 / 现在的我”回信，owner 可在 WebUI 提前打开。
- 已确认决策：新增 `time_capsules` 表（`UNIQUE(persona_id, note_id)`，状态 sealed/unlocked/replied）与 `capsule_days`（默认 30，最小 1）；`run_capsules` 在夜间复盘内自动执行，到期/已手动打开的胶囊先 `unlock_capsule` 再经 `build_capsule_reply_prompt` 生成回信；成功写 `capsule` 事件（幂等键 `capsule/{id}/reply`），LLM 失败保留 unlocked 并写 `reply_failed` 事件，预算耗尽停止并记录快照；WebUI 新增时间胶囊 tab（`GET /capsules`、`POST /capsules_open`）；`.tabs` 加 `flex-wrap: wrap` 修复移动端溢出。
- 改动：`life/config.py`、`_conf_schema.json`、`life/db.py`、`life/prompts.py`、`life/browser.py`、`life/webui.py`、`pages/life/index.html`、`tests/test_db.py`、`tests/test_config.py`、`tests/test_browser.py`、`tests/test_webui.py`；版本 v0.5.3 → v0.5.4；README / CHANGELOG / features.md L2-05 / design.md / roadmap.md 同步。
- 外部调研（DuckDuckGo，2026-08-12，已验证检索可访问）：time capsule / future self letter 站点（TimeCapsule、FutureSelf AI、Send To The Future 等标题）；采纳“封存 → 到期解锁 → 以过去素材回信”结构，未细读原文，结论按推测性借鉴标注。
- 验证：unittest 204 passed（skipped=1；胶囊生命周期、自动解锁回信、LLM 失败、WebUI 接口/路由）；JS 语法检查通过；Playwright 实体图与时间胶囊 tab 桌面 1280x900 / 移动 390x844 渲染、点击、无横向溢出通过。
- 遗留：封存入口目前由未来功能（如 L2-10/11）调用 `seal_capsule_for_note`；尚无独立“封存这条短记”的命令/按钮；回信失败后不会自动重试。
- 下一步：L2-06 分享沉默率（`share_silence_rate` 默认 0.15，ShareGate 概率“今天不想说”）。

## 2026-08-12 L2-04 月度/年度回顾落地（v0.5.3）

- 目标：按 `review_schedule` 自动生成月度/年度回顾，带来源引用、失败回退，回顾本身入事件链。
- 已确认决策：`review_schedule` = `{"monthly": 每月几号, "yearly": "MM-DD"}`（默认 1 / 01-01，monthly 1-28、yearly 01-01 至 12-28，非法回退默认）；调度器在触发日播种 `review-monthly`（09:00）与 `review-yearly`（09:30）固定任务；新增 `reviews` 表（`UNIQUE(persona_id, period, period_start)`）与 `count_notes_between / list_notes_between / category_counts_between`；`run_review` 聚合漫游次数/出门天数/短记/日记/分享/兴趣首尾与分类，LLM 生成回顾，失败（`LLMError`）回退确定性聚合文本并标 `fallback`，预算耗尽标 `review_skipped`；回顾写 `review` 事件（幂等键 `review/{period}/{period_start}`），配置 memory_host 时镜像到宿主。
- 改动：`life/config.py`、`_conf_schema.json`、`life/db.py`、`life/prompts.py`、`life/browser.py`、`life/scheduler.py`、`tests/test_db.py`、`tests/test_config.py`、`tests/test_scheduler.py`、`tests/test_browser.py`；版本 v0.5.2 → v0.5.3；README / CHANGELOG / features.md L2-04 / design.md / roadmap.md 同步。
- 外部调研（DuckDuckGo，2026-08-12，已验证检索可访问）：AI agent periodic review / memory reflection 相关文章标题（如 "How to Build a Reflection and Meditation System for AI Agents"、"Memory Reflection in LLM Agents"、"Reflect — AI Agent Memory & Reflection Skill"）；采纳确定性聚合回退 + 回顾事件，未细读原文，结论按推测性借鉴标注。
- 验证：unittest 199 passed（skipped=1；新增 reviews 表 upsert、区间统计、review_schedule 解析、调度槽位、回顾生成/回退/预算跳过用例）。
- 遗留：多尺度金字塔摘要仍未实现，回顾统计使用确定性聚合；WebUI 暂无回顾查看视图（后续可加）。
- 下一步：L2-05 时间胶囊（`capsule_days` 默认 30 + 到期解锁 + “当时的我/现在的我”回信）。

## 2026-08-12 L2-03 记忆温度落地（v0.5.2）

- 目标：短记带热度与遗忘曲线，冷记忆淡出，被重新提及时“想起来”。
- 已确认决策：`notes` 新增 `temperature`（0-1，默认 1.0）与 `last_touched_at`；夜间复盘按 `memory_temperature_decay`（默认 0.99，clamp 0.5-1.0）乘性衰减，下限 0.05；`query_life_memory` 与 WebUI `memory_search` 经 `search_notes(temperature_weighted=True)` 按温度降序召回，命中短记 `rehydrate_notes` 回温到 1.0；统一库结果与本地合并后按同一 temperature 规则排序。
- 改动：`life/db.py`、`life/config.py`、`_conf_schema.json`、`life/browser.py`、`life/life_tool.py`、`life/webui.py`、`tests/test_db.py`、`tests/test_config.py`、`tests/test_life_tool.py`、`tests/test_webui.py`、`tests/test_browser.py`；版本 v0.5.1 → v0.5.2；README / CHANGELOG / features.md L2-03 / design.md / roadmap.md 同步。
- 外部调研（DuckDuckGo，2026-08-12，已验证检索可访问）：Ebbinghaus 遗忘曲线与 AI agent memory temperature / forgetting 相关文章标题（如 "The Forgetting Curve: From Ebbinghaus to AI Memory"、"Novel Memory Forgetting Techniques for Autonomous AI Agents"）；采纳乘性衰减 + 召回回温，未细读原文，结论按推测性借鉴标注。
- 验证：unittest 193 passed（skipped=1；新增温度衰减/回温、按温度排序、夜间衰减、配置 clamp 用例）。
- 遗留：统一记忆宿主端没有温度字段时不参与加权（按 0.5 处理）；多尺度金字塔摘要仍未实现，rehydrate 目前恢复的是本地原子短记而非摘要展开。
- 下一步：L2-04 月度/年度回顾（`review_schedule` + 确定性聚合回退 + 回顾事件）。

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
