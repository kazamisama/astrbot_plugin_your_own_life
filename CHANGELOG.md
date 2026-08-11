# Changelog

本插件版本历史。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格。

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
