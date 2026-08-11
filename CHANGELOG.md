# Changelog

本插件版本历史。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格。

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
