# Your Own Life 互联网生活档案

观察者模式的 AstrBot 插件。每个白名单 persona 独立拥有一份"互联网生活"：Bot 不注册账号、不发帖，按定时任务漫游国际互联网，用 LLM 把所见转化为摘要、观点、情绪、兴趣演化与分享决策，沉淀为主人专属的可查询生活档案。

北极星目标：从行为、思考层、思想层、发散思维与联想、线性生命链、记忆结构与检索六个维度，实现拟人化的 bot 生命活动与跨平台社交交互。

当前 v1 仅 owner 侧档案，不进入群聊主动表达；跨平台社交交互为后续方向。

## 功能

- 每实例独立生活（现状 v0.3.0）：`life_personas` 白名单，每个 persona 拥有独立的档案、兴趣、情绪 scope 与分享记录；v1.1 起同人格多实例共享同一 SQLite 档案（见 `docs/design.md` 多实例并发）。
- 人格跟随实例：人格 prompt 取自 AstrBot 对应 persona 的 `system_prompt`，缓存进 SQLite，每天自动刷新，WebUI 可查看与手动刷新；解析失败则跳过该 persona 当天任务。
- 定时漫游：默认每天 10:00 / 15:00 各一次（±2 小时确定性波动），夜间 23:00 复盘写日记（±1 小时，日期锚定原始槽位）。
- 免密钥信息源：Hacker News、GitHub 公开搜索、Reddit 公开 JSON、自定义 RSS/Atom；可选 Tavily 搜索。
- 感悟分享：LLM 决定每条感悟是否分享、分享给哪个白名单会话；ShareGate 管每日上限、冷却、去重、睡眠窗口与精力门槛；`/life_share` 与 WebUI 可手动补发。
- 记忆分类：8 类固定分类 + 标签，WebUI 提供分类筛选、关键词搜索与统计；LLM 可通过 `query_life_memory` 工具查询自己写过的档案。
- 高体感视图（v0.3.0）：今日签名、状态小卡片、月历热力图；`/life_today` 可把状态卡直接发到聊天。
- WebUI 视觉优化（v0.3.1）：状态卡行与月历热力图渲染、错误横幅、空态与加载态、移动端适配，零前端依赖。
- 摘要优先：只持久化摘要、观点与链接，不保存网页原文。
- 生态联动（现状 v0.3.0）：可选接入 ESM 读取精力/情绪、施加信号；缺失时静默降级；v1.1 计划内新契约不再默认降级。

## 安装

把插件目录放入 `data/plugins/`，在 AstrBot 管理面板启用并配置。首次运行自动创建 SQLite 数据库并迁移旧版数据（归入 `default` persona）。

## WebUI

插件页面由 AstrBot Dashboard 自动发现：在管理面板的插件详情里进入「Your Own Life」页面（`pages/life/index.html`），无需单独注册路由。页面数据接口由插件在启动时通过 `register_web_api` 注册，统一挂在 `/api/plug/astrbot_plugin_your_own_life/api/...` 下，访问需要 Dashboard 登录态。

## 文档

- `AGENTS.md`：项目开发守则（agent 会话自动加载）。
- `docs/README.md`：文档索引与阅读顺序。
- `docs/devlog.md`：开发日志，跨会话/上下文压缩后的续接入口。
- `docs/design.md`：架构、数据流与方向模型。
- `docs/features.md`：功能分层开发清单（状态/依赖/模块/配置/验收）。
- `docs/roadmap.md`：生活感功能路线图（v1.1 / v2 / 未排期方向）。
- `docs/requirements.md`：上游对接需求、硬依赖与生态兼容约束。
- `docs/workflow.md`：开发与发布工作流。

## 配置

关键项：

- `life_personas`：允许生活的 persona 白名单；留空 = 插件不运行生活任务。
- `browse_times` / `diary_time` / `browse_jitter_minutes` / `diary_jitter_minutes`：漫游与日记时间及波动。
- `sleep_window` / `timezone`：睡眠窗口与生活任务时区（默认 `Asia/Shanghai`；非法配置回退默认并告警）。
- `daily_llm_call_limit` / `daily_token_budget` / `llm_retry_limit`：LLM 每日调用/token 预算（0 = 无上限）与失败重试上限。
- `trash_retention_days`：回收站保留天数（默认 30），超期内容可彻底清除。
- `injection_log_enabled`：记录疑似提示词注入内容到审计日志（默认开）。
- `lease_ttl_seconds`：同人格任务租约 TTL（默认 300 秒），多实例共享 SQLite 时保证单写者。
- `signature_enabled`：夜间复盘生成今日签名（默认开）。
- `revisit_days` / `revisit_probability`：旧事新感回看天数（默认 `[7, 30]`）与触发概率（默认 0.5）。
- `rest_probability`：定时漫游随机跳过概率（默认 0.1），写 `skipped_rest` 快照；手动 `/life_now` 不受影响。
- `time_slots`：时段模式（morning/afternoon/evening/night 各项含 topics/tone）；缺省时使用内置默认语气。
- `peek_times` / `peek_daily_cap`：轻接触时间（默认 09:00/13:00/17:00/21:00）与每日上限（0 = 不限制）；peek 不调用 LLM、不写短记。
- `owner_ids`：允许执行命令的主人 ID（留空则仅要求管理员权限）。
- `share_sessions` / `share_daily_cap` / `share_cooldown_minutes`：分享白名单（每行 `persona_id:sid`）与频率控制。
- `persona_cache_hours` / `persona_prompt_max_chars`：人格缓存刷新间隔与截断长度。
- `rss_feeds` / `tavily_api_key`：扩展信息源。

## 命令

| 命令 | 说明 |
| --- | --- |
| `/life [persona]` | 今日概览 |
| `/life_today [persona]` | 今日状态卡（心情/精力/漫游/最近见闻） |
| `/life_now [persona]` | 立即漫游一次 |
| `/life_archive <YYYY-MM-DD> [persona]` | 查看指定日期档案 |
| `/life_interest [persona]` | 兴趣排行 |
| `/life_personas [refresh <persona>]` | 查看/刷新人格缓存 |
| `/life_share <note_id>` | 手动补发一条感悟 |
| `/life_reset confirm [persona]` | 清空指定 persona 档案 |

## 测试

```bash
python -m unittest discover -s tests -v
```

冒烟测试默认跳过真实网络请求，设置 `LIFE_SMOKE_NET=1` 后执行真实 HN/GitHub 抓取。

## Roadmap

- 详细路线图与未排期方向见 `docs/roadmap.md`。
- 上游插件对接需求见 `docs/requirements.md`。
