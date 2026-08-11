# Changelog

本插件版本历史。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格。

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
