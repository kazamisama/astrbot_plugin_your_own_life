# Changelog

本插件版本历史。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格。

## [0.5.23] - 2026-10-28

### Fixed

- 跨日计划：调度器改为读取全部日期的 pending 计划，昨日/上月漏掉的 browse、diary、review 不再永久孤儿；日记与月度/季度回顾按计划所属 `plan_date` 补写，而不是按运行日写错日期或写丢胶囊。
- 等待期变更：长等待结束后重读 `scheduled_at`，等待期间被 defer/reorder 的计划按新时间执行；计划终态变化则跳过。
- 租约：`_acquire_lease` 返回三态，记忆宿主 claim 异常不再被当成“已被别人占用”而把计划标 skipped；真正的租约冲突只记录重复跳过，不再改共享计划状态，赢家仍能回写 done。
- 旧库升级：`staging_notes` / `staging_diary` / `staging_snapshots` / `staging_wishlist` / `staging_interests` 缺列自动补齐（含 `staging_diary.signature`），旧库夜间日记不再整夜失败；`notes` 唯一约束迁移恢复 `sqlite_sequence` 高水位，新短记不再复用已 purge 的 id。
- 计划硬约束：`skip_plan` / `defer_plan` / `reorder_plan` 只接受 pending 行，done/skipped 不可再被改写；同 `scheduled_at` 的 reorder 不再假成功并写假事件。
- 计划预算：`generate_plan` 不再把自己那次 LLM 调用计入随后的动作预算，`daily_llm_call_limit=1` 时计划动作不再全被判 `budget_exhausted`；每日动作上限统计当天已有可选计划，分批调用不能绕过。
- 日记后置动作：封胶囊、wishlist、胶囊回信、重访、回收站清理各自 try/except，一个失败不再阻断其余动作。
- 时间胶囊：短记已软删/清除时不再提前 unlock 成永远无法回信的僵尸胶囊。
- 白名单：`run_browse_session` / `run_peek` / `run_nightly_diary` / `run_review` / `run_quarterly_review` / `run_capsules` / `run_revisit` / `generate_plan` 全部执行端校验 `life_personas`，命令与 WebUI 不再绕过。
- 分享：`share_daily_cap=0` 视为不限；沉默判定一天只掷一次（非沉默也写 `share_awake` 快照）；`recheck_pending` 对非法 JSON / `should_share=false` 的历史 pending 标记 dropped，不再每晚重试。
- 兴趣编辑：`edit_life_memory` 改 weight/name 时保留当前 `seen_count`，不再顺带 +1。
- 配置：`explore_probability` / `share_daily_cap` / `share_max_chars` 增加边界；`share_max_chars` 不再允许 0 导致分享正文为空。
- WebUI：所有查询/请求整数入口改用有界解析，`2**63+10` 不再触发 SQLite `OverflowError` 500；`/personas` 只返回 persona 元数据，不返回完整 `system_prompt`；`/run` 与 `/capsules_open` 校验白名单；回收站 actor 固定为 owner。
- 页面：`loadPersonas` 失败不再让整页卡在加载中；实体图按节点数增高，超出约 5 个不再被 viewBox 裁掉；所有 POST 统一检查 `ok/error`，失败显示在错误横幅。
- 文档：README/design/features 删除不存在的 `register_web_routes` 回退，改为“引擎不提供 `register_web_api` 时只记录 warning、不注册 WebUI API”；`main.py` 同步记录 warning。

### Notes

- 测试：317 条（skipped=1；`test_config` 与生产 AstrBot 混装的已知环境错误除外）。
- 仍未修：watchlist 稳定 URL 首次见过后不再进候选（“持续关注”需要更新语义）；故地重游失败候选的头部阻塞；统一记忆宿主孤儿数据无删除 API；工具 add 无 ESM 精力 gate；结构性重复与页面 usage/archive/interests/injection_log 视图。

## [0.5.22] - 2026-10-27

### Changed

- `life_personas` 白名单判定收敛到 `life/config.py:persona_allowed`：缺省配置视为不限制，空列表一律拒绝，与 `_conf_schema.json` 的「留空 = 不运行任何生活任务」一致；此前聊天钩子在空列表时会放行。
- 调度器每轮调用 `cleanup_expired_leases`，不再只靠测试覆盖；租约助手的 `kind` 死参数移除。
- WebUI 计划板改为复用 `life_tool.query_life_plans`，不再复制一份查询。

### Removed

- 无生产调用的 `LifePresence.conversation_until`、`injection.scan_items`、`LifeDB.mark_seen`、`LifeScheduler._plan_status_review`。
- 页面死代码 `escapeHtml` 与 `eventWrite` 占位，以及 `revisit_chains` 里只写不读的索引。
- 提示词中代码从不解析的输出字段：选择/日记的 `energy_change`、日记的 `revisit_day_offset` / `revisit_note_ids`、回顾/季度的 `highlights`；日记仍保留「后来的我再看这件事」段落要求。
- 测试里的 GBK 乱码 fixture（`浜哄伐鏅鸿兘` → `人工智能`）。

### Fixed

- `ruff --select F,E9` 全绿：清理 3 处未使用异常变量、1 处未使用局部变量、2 处未使用导入，并补上 `db.py` 缺失的 `Sequence` 导入。

### Notes

- 测试：300 条（skipped=1；`test_config` 与生产 AstrBot 混装的已知环境错误除外）。
- 未动（结构性、留待单独设计）：两套 persona 解析、10 个双胞胎 Tool 类、`run_review` / `run_quarterly_review` 的同构主体、`life_plans.started_at` 死列、`change_log` 与 `life_edits` 两个兼容端点、页面尚未使用的 usage/archive/interests/injection_log 接口。

## [0.5.21] - 2026-10-27

### Fixed

- 多实例并发：`ensure_plan` / `add_optional_plan` 改为 `INSERT OR IGNORE` 后回查，两个实例同时排同一计划不再抛 `IntegrityError`；笔记唯一约束迁移在删旧表后立即重建 `idx_notes_persona_url` / `idx_notes_persona_fetched`，迁移当次进程不再全表扫描 notes。
- 变更与事件一致性：软删/恢复/计划 defer/skip/LLM 编辑的事件幂等键加入变更 id 或时间，二次删除→恢复→再删除不再被静默吞掉；owner 批准/拒绝/回滚补写事件链；`purge_trash` 清空 `change_log` 中已删短记/日记的正文快照。
- 记忆编辑：兴趣 weight=0.0 不再被回滚成 0.5，编辑重量也不再顺带 `seen_count + 1`；`_valid_share` 正确解析字符串 "false"；wishlist 转正保留已有兴趣的权重/次数/显示名并写变更账本。
- 提交后副作用：浏览/日记的短记与日记已入库后，能量记账、事件写入或兴趣衰减失败不再把整个任务标为 error；WebUI `/run` 增加单飞与异常日志，重复点击返回 `already running`。
- 工具边界：`edit_life_plan` 的 add/defer 现在遵守睡眠窗、过去时间、每日动作上限与 diary 依赖，并严格校验日期与 reorder 位置；LLM 不能再经工具通道绕过 `plan_daily_action_cap` 等硬约束。
- 统计与检索：overview/status/query_life_status 的计数改为 SQL COUNT，不再被列表 limit 截断；`query_life_status` 历史日期事件按 `ts` 查询；watchlist 字符串 `type:url` 不再被切坏；漫游对每个话题都检索，探索位真正进入最终选题；`notes_min` 未达成时用确定性候选补齐。
- LLM/人格缓存：provider 首次解析失败后允许重试，不再永久无 provider；LLM 调用加 120 秒超时；persona 刷新失败只标状态，不再清空仍可用的缓存 prompt。

### Notes

- 测试：300 条（skipped=1；`test_config` 与生产 AstrBot 混装的已知环境错误除外）。
- 未修：统一记忆宿主先写、本地 commit 失败的孤儿数据无补偿接口（engram_core 无删除 API）；工具通道的 add 仍未做精力 gate（工具未注入 ESM）。

## [0.5.20] - 2026-10-27

### Fixed

- 时间胶囊恢复自动封存链路：夜间复盘每天从当日短记中挑兴趣最高的一条封存（`capsule_days` 天后到期），并写 `capsule` 事件；此前 `seal_capsule_for_note` 无生产调用，`time_capsules` 永远为空，胶囊 tab 与到期回信整链不可达。手动打开不再覆写 `unlock_at`，重复打开不会重复计数。
- 回收站打通：新增 WebUI「回收站」tab 与 `POST /trash_add`，笔记/日记可软删除并恢复；夜间复盘按 `trash_retention_days` 清理过期回收站条目，且清理短记时级联删除引用它的时间胶囊。此前软删除函数无生产调用，`trash_retention_days` 解析后无人读取。
- `reset_all` 补齐 `life_plans` / `event_chain` / `persona_prompts` 三张表，`/life_reset` 后不再残留计划、事件链与人格缓存。
- 调度器状态机：进程内异常不再杀死调度协程（supervisor 5s 重启）；目标落在次日时先播种计划行；当日错过的 pending 计划顺延补做；等待期间被 skip 的计划不再执行；`update_plan` 增加 `only_if_status` 守卫，避免覆盖已终态计划；租约冲突与收尾更新只作用于 pending。
- 计划窗口与 `edit_life_plan` 时间校验改为严格 `HH:MM`：`09:60` / `25:99` 不再被静默归一或落到 23:59；`_plan_window_time` 支持 `24:00` 结束边界，非法窗口返回空。

### Notes

- 测试：282 条（skipped=1；`test_config` 与生产 AstrBot 混装的已知环境错误除外），新增胶囊封存、回收站级联、reset 完整性、调度器补做/次日播种/等待期 skip 等回归用例。

## [0.5.19] - 2026-08-19

### Fixed

- 修复 v0.5.18 桥接改造后插件页整体卡死：页面 JS 注释中的字面量 `</body>` 命中 AstrBot 注入桥脚本的朴素字符串替换（取首个匹配位置），导致桥 `<script>` 标签（含 `</script>`）被注入进注释，提前截断页面主脚本，全部功能失效。已移除注释中的闭合标签字面量并补充警示注释；同时首次 `load()` 改为经 `waitForBridge(3000)` 等待桥注入后再执行，等不到则回退裸 fetch。已在真实生产 dashboard（v4.25.5）用 Playwright 实测：桥加载成功，personas/overview/status/heatmap 均 200，页面正常渲染。

## [0.5.18] - 2026-08-19

### Fixed

- 修复 WebUI 全部面板显示"加载失败"：`pages/life/index.html` 用裸 `fetch("/api/plug/...")` 调用后端，不带 dashboard 凭证，在 AstrBot v4.25+ 的插件页体系（受保护 iframe + 鉴权中间件）下所有请求被 401 拦截。改为优先走官方插件桥 `window.AstrBotPluginPage.apiGet/apiPost`（由父页面携带 JWT 代理请求，与 engram_core 同模式），桥不可用时回退裸 fetch 兼容旧的直接访问方式。

### Notes

- 验证：Playwright 模拟插件桥加载真实页面，默认 tab 四个接口（personas/overview/status/heatmap）经桥渲染成功，11 个 tab 全部经桥取数且无页面错误；`node --check` 语法通过。

## [0.5.17] - 2026-08-16

### Fixed

- 聊天事件与对话结束事件的 `event_chain.ts` 现在使用传入的 persona 本地时钟（`now_fn`），不再回落到数据库墙钟时间；修复时区测试依赖真实日期导致的日期敏感失败。
- 时区回归测试中的第二个 SQLite 连接改为 `try/finally` 关闭，断言失败时不会在 Windows 上因文件占用再抛清理错误。
- 同步 README 与兼容矩阵中的插件版本到 v0.5.17。

### Notes

- 测试：273 passed（skipped=1）。

## [0.5.16] - 2026-08-13

### Fixed

- 修复平台对话事件与 presence 等待窗使用服务器本地时间而不是 persona 时区的问题。
- ShareGate 分享文案渲染改走受管 LLM 路径，纳入每日调用/token 预算与重试上限。
- InterestStore 在同一 run 内对相同兴趣 key 的 staged 更新会累计 weight 和 seen_count。
- 夜间复盘后置动作失败不再把已提交日记标记为 error。
- WebUI `share_note` 对非法 `note_id` 返回结构化错误，不再触发 500。
- persona 缓存过期判断使用 persona 时区。

### Notes

- 测试：272 passed（skipped=1）。

## [0.5.15] - 2026-08-12

### Added

- 平台对话感知：新增 `life_presence_enabled` / `conversation_wait_minutes` / `busy_reply_max_wait_minutes`；生活任务进行中收到的平台消息会等待任务结束再回复，并用 `extra_user_content_parts` 注入 `query_life_status` 的最近经历块。
- 对话等待窗：bot 回复后进入等待窗，窗口内暂停该 persona 的定时事件；超时写 `conversation_end` 事件后继续事件链。
- 平台对话入事件链：`message_in` / `reply_out` / `conversation_end` 三种事件；按 persona 与同一事件去重。

### Notes

- 测试：267 passed（skipped=1；新增 presence、chat_hooks、scheduler 等待窗回归）。

## [0.5.14] - 2026-08-12

### Added

- 新增 LLM 工具 `query_life_status`：查询当前 persona 当天的漫游/peek 会话、状态快照、事件链条目与短记，让 bot 在对话中能知道自己刚才/今天在做什么、读了什么；调用本身写 `recall` 事件（`query=life_status`）。

### Notes

- 测试：256 passed（skipped=1；新增状态查询纯函数、工具调用写 recall、无 persona 拒绝 3 个回归）。

## [0.5.13] - 2026-08-12

### Fixed

- WebUI 实体图 `data-entity` / `data-id` 不再直接拼接注入 SVG 属性，统一经 `escAttr()` 转义；事件链过滤与标签新增 `reject`（拒绝）。
- 睡眠窗口不再只对 browse 生效：browse/diary/peek 抖动槽位与月度/年度/季度 review 槽位统一外推到窗口结束后，`run_peek` / `run_nightly_diary` 入口也做 `sleep_window.contains` 拦截并返回 `skipped/sleep_window`。
- 系统裁决拒绝事件 kind 由 `change` 改为 `reject`，符合事件链设计语义。
- LLM rollback 现在只能回滚 `actor=llm` 的 applied 条目；owner 在 WebUI 直接调 db 不受影响。
- 长任务增加租约续租：按 TTL/2（最小 1s）定期续租，memory_host 走 `renew_task`，本地 SQLite 走 `renew_lease`；任务结束取消 keepalive 后释放。

### Notes

- 测试：253 passed（skipped=1；新增睡眠窗口外推、review 槽位外推、memory_host/本地续租、长任务续租、diary/peek 睡眠拦截、rollback actor 限制回归）。

## [0.5.12] - 2026-08-12

### Fixed

- `commit_staged` 捕获新短记改用 `INSERT ... RETURNING id`，不再按 `(persona_id, url_hash, fetched_at, title)` 反查；同秒同标题同 hash 的旧短记不会再混入返回列表，`run_revisit` 的 `zip(staged, committed)` 配对保持正确。
- 软删日记同日期重写不再不可见：`add_diary` 与 `commit_staged` 的 `ON CONFLICT ... DO UPDATE` 现在会重置 `deleted_at = ''`。
- `recover_stale_runs` 改为按年龄/暂存时间判定残留：近期 running 会话与新鲜 staging 不会被第二个实例启动时清掉；同时清理全部 staging 表的 NULL-session 与合成 token 残留，避免崩溃后的重游短记被下一次日记误提交。
- 夜间日记与重游改为每轮独立负 session token 暂存，`commit_staged(None)` 不再一把提交该 persona 全部匿名 staging。
- `enabled=False` 现在统一拦截调度循环与日记、月度/年度/季度回顾、胶囊、重游，符合"关闭后不漫游、不写日记"的配置语义。
- 调度器跨午夜抖动不再错位记账：`task_id` 与 `plan_date` 锚定原始槽位，jitter 只影响实际执行时刻，原 plan 不会再永久 pending。

### Notes

- 测试：246 passed（skipped=1；新增同字段捕获碰撞、软删日记重写、多实例/孤儿 staging 恢复、合成 token 隔离、enabled 门、跨午夜锚定回归）。

## [0.5.11] - 2026-08-12

### Fixed

- 启动崩溃：`_conf_schema.json` 中 `time_slots` / `review_schedule` 为 `object` 类型但缺少 `items`，AstrBotConfig 加载配置时抛 `KeyError: 'items'`；已补齐子 schema，并给 `time_slots` 补完整默认值、清理重复 `default` 键。
- `commit_staged` 在 `session_id=None` 时会误返回历史 null-session 短记；改为提交后按暂存 ID 关联捕获新短记，`run_revisit` 随之按 `zip(staged, committed)` 配对。
- WebUI `/revisit_chains` 多链 follow-up 时间交错时挂错原短记；改为按 `revisit_of` 分组组装链。
- `memory_overview` 统计未过滤软删除短记；已加 `deleted_at = ''`。
- `_apply_change_payload` 对非法 note id 抛 ValueError；已改为返回 False。
- 测试隔离：`_astrbot_stub` 会遮蔽真实 `AstrBotConfig`，config 回归测试改为显式加载真实实现，并新增 schema `items` 结构校验。

### Notes

- 测试：238 passed（skipped=1）。

## [0.5.10] - 2026-08-12

### Added

- L2-11 故地重游：新增 `revisit_interval_days`（默认 30）；夜间复盘自动重访超期且未被重访过的旧短记，LLM 以“后来呢”视角生成新短记并标记 `revisit_of`；`notes` 去掉 `UNIQUE(persona_id, url_hash)`（含旧库自动迁移）以支持同链接多次记录；WebUI 新增“故地重游”tab 与 `GET /revisit_chains`，原短记与后续短记可串联查看。

### Changed

- `notes` 表唯一约束迁移：旧库在启动时自动重建表并去掉 url_hash 唯一约束，历史数据原样保留。

### Notes

- 测试：232 passed（skipped=1；新增重访候选/同链接查询/标记、旧库唯一约束迁移、`revisit_interval_days` 配置、`run_revisit` 生成/幂等/预算跳过、夜间复盘接入、WebUI 重访链接口与路由）；JS 语法检查通过；Playwright 故地重游 tab 桌面 1280x900 / 移动 390x844 渲染、链内容与无横向溢出通过。
- 调研：复用此前 L2 系列的个人记忆/回顾类检索结论；revisit 语义与 L1-02 旧事新感区分（日记回看 vs 链接级重访）。

## [0.5.9] - 2026-08-12

### Added

- L2-10 关注对象：新增 `watchlist` 配置（blog / github_repo / github_user / rss，支持 dict 或 `type:id:url` 字符串）与 `fetch_watchlist` 抓取（来源标记 `watchlist/`），关注对象自动进入漫游选题；实体图 URL 节点标记 `watched`；WebUI 新增“关注”tab（`GET /watchlist`）展示关注项与近期更新，状态卡/时间轴随关注短记自然可见。

### Notes

- 测试：225 passed（skipped=1；新增 watchlist 解析、关注短记查询、HTML 标题/描述解析、实体 watched 标记、WebUI 接口与路由）；JS 语法检查与 Playwright 关注 tab 桌面/移动无溢出通过。
- 调研：DuckDuckGo 检索（2026-08-12）personal watchlist / feed curation 相关文章标题（如 "Your Watchlist, Curated: How a Personalized Feed Replaces the Morning..."）；采纳持续关注源进入选题候选，未细读原文，结论按推测性借鉴标注。

## [0.5.8] - 2026-08-12

### Added

- L2-09 多实例租约接入 scheduler：配置 `memory_host` 时调度器改用统一记忆宿主 `claim_task / release_task`（TTL 用 `memory_lease_ttl_seconds`），拿不到租约跳过并记录 `skipped_duplicate`；未配置 host 时回退本地 SQLite `acquire_lease / release_lease`。

### Notes

- 测试：220 passed（skipped=1；新增内存宿主租约 claim/release、拒绝跳过、本地回退用例）。
- 调研：DuckDuckGo 检索（2026-08-12）分布式租约/单写者相关文章标题（如 "AI Agent Distributed Locking: TTL Leases, Fencing Tokens, and Recovery"、"Designing a Correct Distributed Lease Service"）；采纳 claim/release + TTL 过期释放，未细读原文，结论按推测性借鉴标注。

## [0.5.7] - 2026-08-12

### Added

- L2-08 LLM 自主更改与自动回滚：新增 `life_edit_allowed` 白名单（默认 `note.summary / note.opinion / interest.weight`）与 `edit_life_memory` LLM 工具（update/rollback）；白名单内直接应用并写 `change_log` 与 `change` 事件，越界动作落 `pending_owner`；DB 支持 `apply_change / reject_change / rollback_change`（回滚还原字段并追加回滚审计条目）；WebUI 新增“改动”tab（`GET /life_edits`、`POST /life_edits_approve|reject|rollback`），owner 可批准、拒绝、回滚任意改动。

### Notes

- 测试：218 passed（skipped=1；新增字段更新、apply/reject/rollback 生命周期、LLM 工具白名单/待确认/回滚、WebUI 改动接口与路由）；JS 语法检查与 Playwright 改动 tab 桌面/移动无溢出、按钮交互通过。
- 调研：DuckDuckGo 检索（2026-08-12）agent 自主编辑与人工审批安全边界相关论文/指南（如 "SafeHarbor: Defining Precise Decision Boundaries..."、"LLM Guardrails: The Complete Guide to AI Safety Guardrails"）；采纳白名单 + owner 确认 + 回滚审计，结论按推测性借鉴标注。

## [0.5.6] - 2026-08-12

### Added

- L2-07 季度自我评估：新增 `quarterly_review_enabled`（默认开）与 `review-quarterly` 调度槽位（1/4/7/10 月首日 09:15）；`run_quarterly_review` 聚合上季度漫游/日记/兴趣与情绪分布，LLM 生成带 confidence 的长期总结，失败回退确定性聚合（confidence 0.5）；`reviews` 新增 `confidence` 列；WebUI 新增“回顾”tab（`GET /reviews`、`GET /reviews_diff`）查看季度评估并对比上一期。

### Notes

- 测试：213 passed（skipped=1；新增季度评估生成/回退、confidence、调度槽位、WebUI 回顾与 diff 用例）；JS 语法检查与 Playwright 回顾 tab 桌面/移动无溢出、diff 交互通过。
- 调研：本次 DuckDuckGo 检索未返回可引用结果（工具无输出，可能限流），沿用 L2-04 memory reflection 检索标题；季度自我评估结构按设计文档与推测性借鉴落地。

## [0.5.5] - 2026-08-12

### Added

- L2-06 分享沉默率：新增 `share_silence_rate`（默认 0.15），ShareGate 每天第一次分享按概率“今天不想说”，沉默当天不再分享、不写分享日志，仅写 `share_silent` 状态快照供夜间日记体现；手动分享（`/life_share` 与 WebUI）走 `force=True` 绕过沉默。

### Notes

- 测试：208 passed（skipped=1；新增沉默概率跳过、全天沉默、手动 force 绕过、配置 clamp 用例）。
- 调研：DuckDuckGo 检索（2026-08-12）bot/human posting behavior 相关研究标题（如 "A global comparison of social media bot and human characteristics"）；采纳概率性沉默增加表达自然度，未引入新依赖，结论按推测性借鉴标注。

## [0.5.4] - 2026-08-12

### Added

- L2-05 时间胶囊：新增 `capsule_days`（默认 30）与 `time_capsules` 表；夜间复盘自动解锁到期胶囊，LLM 按封存短记写“当时的我 / 现在的我”回信并写 `capsule` 事件；WebUI 新增“时间胶囊”tab（`GET /capsules`）与手动提前打开（`POST /capsules_open`）。

### Fixed

- WebUI 移动端 tab 栏换行：`.tabs` 增加 `flex-wrap: wrap`，修复多 tab 时 390px 视口横向溢出。

### Notes

- 测试：204 passed（skipped=1；新增胶囊生命周期、自动解锁回信、LLM 失败、WebUI 接口与路由用例）；Playwright 实体图/时间胶囊桌面与移动视口无横向溢出、渲染与点击通过。
- 调研：DuckDuckGo 检索（2026-08-12）time capsule / future self letter 相关站点（如 TimeCapsule、FutureSelf AI、Send To The Future）；采纳“封存 → 到期解锁 → 以过去素材回信”结构，未引入新依赖。

## [0.5.3] - 2026-08-12

### Added

- L2-04 月度/年度回顾：新增 `review_schedule`（monthly = 每月几号，yearly = MM-DD），调度器按计划播种 `review` 固定任务；`reviews` 表存回顾（幂等 upsert）；`run_review` 聚合漫游次数/出门天数/短记/日记/分享/兴趣变化与分类统计，LLM 生成回顾并带来源引用；LLM 失败走重试语义后确定性聚合回退（status=fallback）；回顾写 `review` 事件（幂等键 `review/{period}/{period_start}`）并可镜像到统一记忆宿主。

### Notes

- 测试：199 passed（skipped=1；新增 reviews 表、区间统计、配置解析、调度槽位、回顾生成/回退/预算跳过用例）。
- 调研：DuckDuckGo 检索（2026-08-12）AI agent periodic review / memory reflection 相关文章标题（如 "How to Build a Reflection and Meditation System for AI Agents"、"Memory Reflection in LLM Agents"、"Reflect — AI Agent Memory & Reflection Skill"）；采纳确定性聚合回退 + 回顾事件，与设计文档多尺度金字塔方向一致。

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
