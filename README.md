# Your Own Life 互联网生活档案

观察者模式的 AstrBot 插件。每个白名单 persona 独立拥有一份"互联网生活"：Bot 不注册账号、不发帖，按定时任务漫游国际互联网，用 LLM 把所见转化为摘要、观点、情绪、兴趣演化与分享决策，沉淀为主人专属的可查询生活档案。

北极星目标：从行为、思考层、思想层、发散思维与联想、线性生命链、记忆结构与检索六个维度，实现拟人化的 bot 生命活动与跨平台社交交互。

当前 v1 仅 owner 侧档案，不进入群聊主动表达；跨平台社交交互为后续方向。

当前版本：v0.5.32。

## 功能

- 每实例独立生活：`life_personas` 白名单，每个 persona 拥有独立的档案、兴趣、情绪 scope 与分享记录；同人格多实例共享同一 SQLite（v0.2.9 起）或统一记忆宿主租约（v0.5.8 起），租约保证单写者（见 `docs/design.md` 多实例并发）。
- 人格跟随实例：人格 prompt 取自 AstrBot 对应 persona 的 `system_prompt`，缓存进 SQLite，每天自动刷新，WebUI 可查看与手动刷新；解析失败则跳过该 persona 当天任务。
- 定时漫游：默认每天 10:00 / 15:00 各一次（±2 小时确定性波动），夜间 23:00 复盘写日记（±1 小时，日期锚定原始槽位）。
- 免密钥信息源：Hacker News、GitHub 公开搜索、Reddit 公开 JSON、自定义 RSS/Atom；可选 Tavily 搜索。
- 感悟分享：LLM 决定每条感悟是否分享、分享给哪个白名单会话；ShareGate 管每日上限、冷却、去重、睡眠窗口与精力门槛；`/life_share` 与 WebUI 可手动补发。
- 记忆分类：8 类固定分类 + 标签，WebUI 提供分类筛选、关键词搜索与统计；LLM 可通过 `query_life_memory` 查询档案、`query_life_status` 查看当天在做什么/读了什么。
- 高体感视图（v0.3.0）：今日签名、状态小卡片、月历热力图；`/life_today` 可把状态卡直接发到聊天。
- WebUI 视觉优化（v0.3.1）：状态卡行与月历热力图渲染、错误横幅、空态与加载态、移动端适配，零前端依赖。
- 时间轴（v0.3.7）：WebUI 新增时间轴 tab，按时间倒序混排短记/日记/分享/状态，支持类型过滤与分页。
- 事件链（v0.3.8）：append-only 事件流，观察/表达/思考/更改/召回/回滚归位，每条带 `persona_id / ts / kind / payload / source_refs / idempotency_key`，幂等追加、只读重放。
- 排期板（v0.3.9）：`life_plans` 运行时视图，任务带状态/原因/预算，调度器播种与记账；WebUI“排期”tab + `query_life_plans` 只读 LLM 工具。
- 固定/可选任务分层（v0.4.0）：默认漫游/peek/复盘槽位为固定任务，LLM 只能对可选任务执行 `add / reorder / defer / skip`，固定任务不可改，跳过留痕并写事件链。
- LLM 自主排期（v0.4.1）：`/life_plan` 让 LLM 按封闭动作词表与偏好时间窗排可选任务；未知动作、睡眠窗口、精力 gate 与每日行动上限优先，拒绝项留痕并回退默认固定计划。
- 系统裁决（v0.4.2）：预算（LLM 调用/token）与依赖校验成为硬约束，所有越界/未知/未实现动作拒绝并写 `reject` 事件链。
- 事件链可视化（v0.4.3）：WebUI“事件链”tab 按时间倒序展示事件流，kind 过滤 + 分页 + `source_refs` + 幂等键，底部只读重放元数据视图。
- 精力预算（v0.4.4）：`energy_budget` 每日上限，漫游/复盘真实消耗并持久化精力（ESM `consume_energy`），ESM 缺失时本地估算显式标注；预算耗尽当天剩余任务跳过并记录。
- 统一记忆库（v0.5.0）：配置 `memory_host` 后，日记/短记/事件/召回/实体图/任务租约统一经 `LifeMemoryAdapter` 读写 engram_core；本地 SQLite 降级为缓存，宿主缺失报 error。
- 实体与关系图（v0.5.1）：漫游写入 platform/url 节点与 appears_on 边；WebUI 新增“实体图”tab，按维度分列并支持点击查询“我在哪见过 X”。
- 记忆温度（v0.5.2）：短记带热度，夜间按系数衰减，召回按温度加权，被重新提及时回温到满热度。
- 月度/年度回顾（v0.5.3）：按 `review_schedule` 自动回顾漫游/日记/兴趣变化，带来源引用；LLM 失败回退确定性聚合，回顾本身入事件链。
- 时间胶囊（v0.5.4）：短记按 `capsule_days` 封存，到期自动解锁并以“当时的我 / 现在的我”回信；WebUI 时间胶囊 tab 可提前打开。
- 分享沉默率（v0.5.5）：按 `share_silence_rate` 概率“今天不想说”，沉默当天不写分享日志、留快照进日记；手动分享可强制发出。
- 季度自我评估（v0.5.6）：按季度生成带 confidence 的人格总结，WebUI“回顾”tab 可查看并对比上一期 diff。
- LLM 自主更改与回滚（v0.5.7）：`edit_life_memory` 按 `life_edit_allowed` 白名单改短记/兴趣，越界需 owner 确认；WebUI“改动”tab 可批准、拒绝、回滚并审计。
- 多实例租约（v0.5.8）：配置 `memory_host` 后调度器经统一宿主 claim/release 租约串行化同人格任务，拿不到租约跳过；未配置时回退本地 SQLite 租约。
- 关注对象（v0.5.9）：`watchlist` 配置博客/GitHub 项目/用户/RSS，进入漫游选题；实体图标记 watched，WebUI“关注”tab 查看近期更新。
- 故地重游（v0.5.10）：旧短记超过 `revisit_interval_days` 后夜间自动重访链接，LLM 写“后来呢”短记并引用原短记；WebUI“故地重游”tab 可串联查看原短记与后续状态。
- 工程健壮性（v0.5.11-v0.5.13）：修复 `'items'` 启动崩溃、同秒暂存捕获/软删恢复/启动恢复与跨午夜调度锚定；v0.5.13 再收口 SVG 属性转义、睡眠窗口、reject 事件、LLM rollback 权限与长任务租约续租。
- 平台对话感知（v0.5.15）：`life_presence_enabled` 开启后，生活任务进行中收到的平台消息会等到任务结束再回复，并注入当天经历；回复后进入 `conversation_wait_minutes` 等待窗，窗口内暂停该 persona 定时事件，用户消息/bot 回复/会话结束写入事件链。
- 工程修复（v0.5.16-v0.5.17）：v0.5.16 修复平台对话/presence 时区、ShareGate 受管 LLM 预算、兴趣同批累加、夜间复盘后置动作原子性与 WebUI `share_note` 非法输入；v0.5.17 统一 `message_in` / `reply_out` / `conversation_end` 事件时间戳到 persona 本地注入时钟并稳定时区测试。
- 审计修复（v0.5.20）：时间胶囊恢复自动封存（夜间每日从当日短记封一条），WebUI 新增「回收站」tab 与 `POST /trash_add`，删除短记时级联清理胶囊；`/life_reset` 补齐计划/事件链/人格缓存；调度器异常后自愈、次日槽位先播种、当日错过的 pending 计划补做、等待期被 skip 的计划不再执行；`edit_life_plan` 与计划窗口严格校验 `HH:MM`。
- 审计修复（v0.5.21）：计划播种并发改 `INSERT OR IGNORE`、唯一约束迁移后重建索引；软删/恢复/defer/skip/LLM 编辑事件键带变更 id，owner 批准/拒绝/回滚补事件链，回收站清除正文快照；兴趣 weight=0.0 与 seen_count 不再被改写、分享字符串 "false" 正确解析、wishlist 转正保留原兴趣；浏览/日记提交后副作用失败不再报 error，WebUI `/run` 单飞；工具 add/defer 遵守睡眠窗、过去时间、每日上限与 diary 依赖；overview/status 计数不再截断，watchlist、多话题、探索位、notes_min 修正；LLM provider 可重试、调用 120s 超时、persona 刷新失败保留缓存。
- 冗余清理（v0.5.22）：删除无生产调用的 `conversation_until` / `scan_items` / `mark_seen` / `_plan_status_review` 与页面死代码 `escapeHtml` / `eventWrite`；租约清理接回调度器、租约助手去掉死参数；`life_personas` 白名单判定收敛为一个函数（空列表 = 不允许，与配置提示一致）；提示词删掉代码从不解析的 `energy_change` / `revisit_day_offset` / `revisit_note_ids` / `highlights` 字段；WebUI 计划板复用 `query_life_plans`；修复测试中的 GBK 乱码；`ruff --select F,E9` 全绿。
- 审计修复（v0.5.23）：跨日 pending 计划不再永久孤儿，日记/回顾按计划的 `plan_date` 补写；等待期 defer 会重读时间；租约异常不再当成“别人占着”，冲突也不再改写共享计划状态；旧库 `staging_diary` 缺列自动补 `signature`，短记迁移恢复 id 高水位；计划预算不再把自己的 LLM 调用算成越界，动作上限统计当天已有可选计划；`done/skipped` 不可再被 skip/defer/reorder 改写，同时间 reorder 不再假成功；日记后置动作彼此隔离；胶囊缺短记时不再提前解锁成僵尸；浏览/peek/日记/回顾/计划全部执行端校验 `life_personas`；分享每日上限 0 视为不限、沉默判定一天一次、`recheck_pending` 不再卡 `should_share=false`；WebUI 大整数不再 500，人格列表不再返回完整 `system_prompt`，页面加载失败显示错误、实体图按节点数增高、POST 失败会提示。
- 审计修复（v0.5.24）：关注列表的固定 URL 改用内容指纹（标题/摘要/发布时间）判断更新，博客或仓库有新内容时会重新进入候选；故地重游候选按天轮转，失败事件按日期记账，不会再被最旧的几条永久堵住；回收站软删的回滚真正恢复短记/日记，转正一个原本不存在的兴趣后回滚会删除该兴趣而不是留下 0.5 的鬼影；统一记忆与本地记忆合并时去重并截断到 k；RSS 支持 RSS 1.0/RDF、Atom 的 alternate 链接与非 UTF-8 编码声明；热力图的日期格可点击跳到当天。
- 审计修复（v0.5.25）：`commit_staged` 的兴趣更新改为“基线 + 增量”，运行期间 owner/LLM 的权重与 `seen_count` 修改不再被运行开始时的快照覆盖，同一 key 多次 stage 只应用一次；计划板交换顺序改为单事务，第二次更新失败不会留下半交换；生活页新增 LLM 用量、改动页新增注入审计，页面不再零调用 `usage` / `injection_log`；日记里的兴趣权重更新不再虚增 `seen_count`。
- 审计修复（v0.5.26）：`apply_change` / `rollback_change` / 软删除与恢复改为单事务（事务内禁止内层提前 commit），改数据和写账本要么一起成功、要么一起回滚；手动打开胶囊加单飞，连点不会并发生成多次回信；页面记忆搜索的 `k` 与后端上限对齐为 10；`docs/consistency.md` 标注为历史基线。
- 审计修复（v0.5.27）：故地重游的 `stage_seen` 不再用空 fingerprint 覆盖关注项的内容指纹（v0.5.24 的回归）；重访链的 `mark_revisit` 改为单事务批量写入，崩溃窗口不再留下未标记的后续短记；实体“出现平台”按 (name, dimension) 去重；时间胶囊只查引用到的短记，不再为 200 个胶囊加载 10 万条短记。
- 审计修复（v0.5.28）：`commit_staged` 拒绝写已被其他实例标为终态的 session；月度/季度回顾改用 SQL 范围聚合，不再把全库会话/日记/分享读进内存；聊天事件键去掉时间戳，重试同一消息不会重复记账；调度器禁用或人格为空时改为等待重读配置，不再永久退出；手动分享没有配置目标时返回错误而不把短记标 dropped；WebUI 记忆搜索改为只读，不再在 GET 里 rehydrate 升温。
- 审计修复（v0.5.29）：故地重游链先取“有后续的原短记”再按 id 取全部后续，不再被 500 条时间窗口截断；手动漫游后页面轮询新增的 `/run_status`，长任务不会在 3 秒时显示旧数据；实体图加载失败会显示错误横幅；回顾来源引用改用区间日记查询。
- 集成修复（v0.5.30）：统一记忆宿主适配器现在会从 AstrBot 的 `StarMetadata` 注册记录解包 `star_cls` 实例，日记/短记/事件/租约写入才能真正到达 engram_core；宿主已注册但未激活时明确报错，而不是伪装成可用。
- 结构重构（v0.5.31）：聊天钩子与 LLM 工具共用同一套 persona 解析；显式无 persona（`[%None]`）在工具通道也不再回退到默认人格；conversation 查询异常时仍会尝试平台默认人格。
- 结构重构（v0.5.32）：5 个 LLM 工具改由统一的 FunctionTool/降级基类承载，删除原先 10 个条件分支双胞胎类；工具 schema、参数与调用行为不变。
- 摘要优先：只持久化摘要、观点与链接，不保存网页原文。
- 生态联动：可选接入 ESM 读取精力/情绪、施加信号；v0.4.4 起精力消费缺失时显式记录本地估算，不再默认静默降级；配置 `memory_host` 后统一记忆宿主为硬依赖。

## 安装

把插件目录放入 `data/plugins/`，在 AstrBot 管理面板启用并配置。首次运行自动创建 SQLite 数据库并迁移旧版数据（归入 `default` persona）。

## WebUI

插件页面由 AstrBot Dashboard 自动发现：在管理面板的插件详情里进入「Your Own Life」页面（`pages/life/index.html`），无需单独注册路由。页面数据接口由插件在启动时通过 `register_web_api` 注册，统一挂在 `/api/plug/astrbot_plugin_your_own_life/api/...` 下，访问需要 Dashboard 登录态；引擎不提供该接口时插件不注册 WebUI API（没有 `register_web_routes` 回退），只记录 warning。

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

完整配置项与默认值（以 `_conf_schema.json` 为准）：

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enabled` | bool | `true` | 启用互联网生活插件 |
| `browse_times` | list | `["10:00", "15:00"]` | 每日漫游时间（HH:MM） |
| `diary_time` | string | `"23:00"` | 夜间复盘/写日记时间（HH:MM） |
| `sleep_window` | string | `"00:00-07:00"` | 睡眠窗口（如 00:00-07:00） |
| `timezone` | string | `"Asia/Shanghai"` | 生活任务时区（IANA 名称） |
| `owner_ids` | list | `[]` | 允许执行命令的主人 ID |
| `life_llm` | string | `""` | 生活任务专用 LLM Provider ID |
| `energy_gate` | float | `0.3` | 精力门槛（0-1） |
| `energy_budget` | float | `0.0` | 每日精力消耗上限（0 = 无上限） |
| `explore_probability` | float | `0.2` | 探索新话题概率（0-1） |
| `interest_decay` | float | `0.98` | 兴趣每日衰减系数 |
| `interests_initial` | list | `["technology:科技", "ai:人工智能", "open-source:开源", "science:科学", "internet-culture:互联网文化"]` | 初始兴趣领域（key 或 key:展示名） |
| `hn_enabled` | bool | `true` | 启用 Hacker News（Algolia API） |
| `github_enabled` | bool | `true` | 启用 GitHub 公开搜索 API |
| `reddit_enabled` | bool | `true` | 启用 Reddit 公开 JSON |
| `reddit_subreddits` | list | `["programming", "artificial", "MachineLearning", "technology"]` | Reddit 子版块列表 |
| `rss_feeds` | list | `[]` | 自定义 RSS/Atom 源 |
| `watchlist` | list | `[]` | 持续关注名单（blog / github_repo / github_user / rss） |
| `tavily_api_key` | string | `""` | 可选：Tavily 搜索 API Key |
| `db_path` | string | `""` | SQLite 数据库路径 |
| `source_timeout` | float | `10.0` | 信息源请求超时（秒） |
| `notes_min` | int | `3` | 每次漫游最少短记数 |
| `notes_max` | int | `5` | 每次漫游最多短记数 |
| `life_personas` | list | `[]` | 允许过互联网生活的 persona 白名单 |
| `browse_jitter_minutes` | int | `120` | 漫游时间随机波动范围（±分钟） |
| `diary_jitter_minutes` | int | `60` | 夜间复盘时间随机波动范围（±分钟） |
| `daily_llm_call_limit` | int | `0` | 每日 LLM 调用上限 |
| `daily_token_budget` | int | `0` | 每日 token 预算 |
| `llm_retry_limit` | int | `3` | LLM 失败重试上限 |
| `trash_retention_days` | int | `30` | 回收站保留天数 |
| `injection_log_enabled` | bool | `true` | 记录疑似提示词注入内容到审计日志 |
| `lease_ttl_seconds` | int | `300` | 同人格任务租约 TTL（秒） |
| `signature_enabled` | bool | `true` | 夜间复盘生成今日签名 |
| `revisit_days` | list | `[7, 30]` | 夜间复盘回看旧短记的天数 |
| `revisit_probability` | float | `0.5` | 夜间复盘触发旧事新感的概率（0-1） |
| `revisit_interval_days` | int | `30` | 故地重游间隔天数 |
| `rest_probability` | float | `0.1` | 随机不出门概率（0-1） |
| `time_slots` | object | `{"morning": {"topics": "", "tone": ""}, "afternoon": {"topics": "", "tone": ""}, "evening": {"topics": "", "tone": ""}, "night": {"topics": "", "tone": ""}}` | 时段模式：每个时段的偏好主题与语气 |
| `peek_times` | list | `["09:00", "13:00", "17:00", "21:00"]` | 轻接触 peek 时间（HH:MM） |
| `peek_daily_cap` | int | `0` | 每日 peek 上限（0 = 不限制） |
| `plan_daily_action_cap` | int | `5` | LLM 自主排期每日可选任务上限 |
| `wishlist_enabled` | bool | `true` | 启用灵感抽屉 |
| `share_enabled` | bool | `true` | 启用感悟分享 |
| `share_daily_cap` | int | `2` | 每 persona 每日成功分享上限 |
| `share_cooldown_minutes` | int | `360` | 同一会话分享冷却（分钟） |
| `share_silence_rate` | float | `0.15` | 每日“今天不想说”概率（0-1） |
| `quarterly_review_enabled` | bool | `true` | 启用季度自我评估 |
| `life_edit_allowed` | list | `["note.summary", "note.opinion", "interest.weight"]` | LLM 可直接修改的实体字段白名单 |
| `share_include_link` | bool | `true` | 分享消息末尾附带源链接 |
| `share_max_chars` | int | `200` | 分享消息最大字数 |
| `share_sessions` | list | `[]` | 每 persona 允许分享的会话 sid 白名单 |
| `persona_prompt_max_chars` | int | `6000` | 注入生活 prompt 的人格 system_prompt 最大字数 |
| `persona_cache_hours` | float | `24.0` | 人格缓存刷新间隔（小时） |
| `esm_scope_prefix` | string | `"internet-life"` | ESM 作用域前缀 |
| `memory_host` | string | `""` | 统一记忆宿主插件 ID（留空 = 使用本地 SQLite） |
| `memory_lease_ttl_seconds` | int | `300` | 统一记忆宿主任务租约 TTL（秒） |
| `memory_temperature_decay` | float | `0.99` | 短记记忆温度每日衰减系数（0.5-1.0） |
| `review_schedule` | object | `{"monthly": "1", "yearly": "01-01"}` | 月度/年度回顾触发日 |
| `capsule_days` | int | `30` | 时间胶囊封存天数 |
| `life_tool_enabled` | bool | `true` | 向 LLM 注册 query_life_memory 自查询工具 |
| `life_presence_enabled` | bool | `true` | 启用平台对话感知：忙碌时延迟回复并进入对话等待窗 |
| `conversation_wait_minutes` | int | `5` | bot 回复后等待用户继续对话的分钟数 |
| `busy_reply_max_wait_minutes` | int | `30` | 忙碌时聊天最多等待回复的分钟数 |

各字段的详细提示以 AstrBot 管理面板中展示的 schema hint 为准。

## 命令

| 命令 | 说明 |
| --- | --- |
| `/life [persona]` | 今日概览 |
| `/life_today [persona]` | 今日状态卡（心情/精力/漫游/最近见闻） |
| `/life_now [persona]` | 立即漫游一次 |
| `/life_plan [persona]` | 让 LLM 按封闭动作词表生成今日可选任务 |
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
