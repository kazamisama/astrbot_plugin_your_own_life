# 功能实现与设计目标一致性审计

审计基线：2026-08-12，版本 v0.5.12（HEAD `54e58b6`），工作树干净。
方法：4 个只读 subagent 分域审查（行为层 / 记忆档案 / 人格安全 / WebUI 适配），主 agent 复核高影响结论；单测基线 `python -m unittest discover -s tests` 246 passed（skipped=1，网络冒烟按配置跳过）。

## 已修复（v0.5.13）

- 实体图 SVG 属性注入：`data-entity` / `data-id` 改为 `escAttr()` 转义，事件链过滤/标签补充 reject。
- 睡眠窗口只对 browse 生效：browse/diary/peek 与月度/年度/季度 review 槽位统一外推，`run_peek` / `run_nightly_diary` 入口也做 `sleep_window.contains` 拦截。
- 系统裁决拒绝事件 kind 由 `change` 改为 `reject`。
- LLM rollback 无 actor 限制：仅允许回滚 `actor=llm` 的 applied 条目，owner 走 WebUI 直接调 db 不受影响。
- 长任务无租约续租：按 TTL/2（最小 1s）定期 `renew_task` / `renew_lease`，任务结束取消 keepalive 后释放。

以上修复的代码与测试证据见 `CHANGELOG.md` v0.5.13；下方矩阵保留 v0.5.12 审计基线，偏差/缺口状态以最新代码为准。

本文档只做「实现 vs 设计目标/验收标准」的一致性核对，不替代 `docs/features.md` 的验收清单。状态含义：对齐 = 实现满足设计验收；偏差 = 实现与设计语义不符；缺口 = 设计承诺但未实现。

## 逐项状态

| 功能 | 状态 | 主要证据 | 偏差/缺口 |
| --- | --- | --- | --- |
| L0 定时漫游与夜间复盘 | 对齐 | `life/scheduler.py` 默认 10:00/15:00/23:00、确定性抖动 ±120/±60、`_done_keys` 防重复 | - |
| L0 信息源 | 对齐 | `life/fetchers.py` URL 哈希去重、`source_timeout=10`；HN/GitHub/Reddit/RSS/Tavily/watchlist 接入 | - |
| L0 人格缓存 | 对齐 | `life/persona.py` 白名单、过期刷新、默认 persona 兜底、解析失败记 error 跳过任务 | - |
| L0 分享决策 | 对齐 | `life/share.py:59-121` 顺序检查与 pending 补发符合设计 | - |
| L0 SQLite 档案 | 对齐 | 基线表 + 旧版自动迁移；旧 schema（share_log/persona_prompts）无历史证据，待验证 | - |
| L0 聊天命令 | 对齐 | `main.py` 7 条命令全部 owner 校验 | - |
| L0 WebUI 基础接口 | 偏差 | 接口齐全（`life/webui.py:516-558`）；`register_web_api` 为 None 时直接返回 False | P2：`register_web_routes` 回退缺失 |
| L0 LLM 工具 | 对齐 | `query_life_memory` 只查当前 persona，关键词/分类/日期过滤，白名单与解析错误明确返回 | - |
| L0 ESM 适配 | 对齐 | 缺失/方法缺失/信号非法静默 no-op；`consume_energy` 缺失时显式本地估算快照 | - |
| L1-01 今日签名 | 对齐 | 无素材日签名为空、`signature_enabled` 控制、落 `diary_entries.signature` 可查 | - |
| L1-02 旧事新感 | 偏差 | 回看素材与 prompt 注入符合；无历史时仍掷签并返回 `revisit_day` | P3：与「无历史不触发」字面不符 |
| L1-03 精力预算 | 对齐 | 真实扣减 + 双写用量 + 预算耗尽跳过 + ESM 缺失显式 fallback 快照 | - |
| L1-04 随机不出门 | 对齐 | 仅定时掷签，手动 `/life_now` force 绕过 | - |
| L1-05 时段模式 | 对齐 | 四段默认、本地时间判定、可选块注入、缺失回退默认语气 | - |
| L1-06 peek | 对齐 | 不调 LLM、不写 notes、`kind=peek` 且统计不混入正式漫游 | - |
| L1-07 灵感抽屉 | 对齐 | wishlist 写入/评估升级或丢弃/WebUI 手动处理 | - |
| L1-08 状态小卡片 | 对齐 | `/status` 字段齐全、空态不报错、`/life_today` 发聊天 | - |
| L1-09 月历热力图 | 偏差 | 按天聚合与空月正确；heat-cell 无点击跳当日档案 | P2：验收「点击日期跳当日档案」未实现 |
| L1-10 时间轴 | 对齐 | 四类混排、类型过滤、分页 | - |
| L1-11 预算/重试/崩溃 | 偏差 | 预算/重试/staging 语义对齐；`commit_staged` 后副作用异常会把已落库 run 标 failed | P2：数据已写但 session 状态 failed |
| L1-12 时区 | 偏差 | 默认/回退/`timezone_error` 正确；睡眠窗口只对 browse 生效 | P2：diary/peek 可落在窗口内；P3：非法时区仅 warning |
| L1-13 变更账本与回收站 | 偏差 | tombstone/恢复/purge 对齐；普通写操作不进 `change_log` | P2：仅 owner/LLM 编辑与软删/恢复记账，与「所有写操作进账本」不符 |
| L1-14 不可信内容与记忆卫生 | 偏差 | sanitize/扫描/审计接口/封闭 mood 词表对齐 | P3：注入审计无 WebUI 页面入口；LLM 输出校验偏松 |
| L1-15 WebUI 视觉 | 偏差 | vanilla/移动端/空态错误态齐全 | P3：加载态覆盖不全；P2：实体图 SVG 属性未转义 |
| L1-16 同人格单 SQL 租约 | 偏差 | 本地租约/`skipped_duplicate`/TTL 清理对齐 | P2：生产路径从不调用 `renew_lease/renew_task` |
| L1.5-01 事件链 | 对齐 | append-only + 幂等键；观察/表达/更改/召回/回滚接入 | P3：`replay_events` 只读，无「重放重建状态」执行器 |
| L1.5-02 排期板 | 对齐 | `life_plans` 运行时视图 + 只读工具 + WebUI | - |
| L1.5-03 固定/可选分层 | 偏差 | fixed 保护/add/reorder/defer/skip/留痕对齐 | P2：`_plan_time` 不校验 HH:MM 范围；P3：无 owner 修改固定任务入口 |
| L1.5-04 LLM 自主排期 | 偏差 | 封闭词表/时间窗/未知动作拒绝/上限/精力 gate 对齐 | P2：睡眠窗口执行期不完整 |
| L1.5-05 系统裁决 | 偏差 | 预算/依赖/睡眠/精力/上限均判并留痕 | P2：拒绝事件 kind 用 `change` 而非文档要求的 `reject` |
| L1.5-06 事件链可视化 | 对齐 | kind 过滤/分页/source_refs/幂等键，只读 | - |
| L2-01 统一记忆库 | 偏差 | adapter 契约齐全，核心写路径宿主缺失报 error | P2：事件镜像/实体同步/重游 add_note 失败仅 warning；`search` 无生产调用者 |
| L2-02 实体关系图 | 偏差 | platform/url 系统写入 + `appears_on` + 查询接口对齐 | P2：实体图 SVG 属性注入；P3：UI 未渲染 watched 标记 |
| L2-03 记忆温度 | 对齐 | 衰减/下限/召回加权/rehydrate 对齐 | - |
| L2-04 月度/年度回顾 | 对齐 | 聚合/来源引用/失败确定性回退/事件幂等对齐 | - |
| L2-05 时间胶囊 | 对齐 | 到期解锁/回信/失败保留/手动打开对齐 | P3：`purge_trash` 不级联处理胶囊引用 |
| L2-06 分享沉默率 | 偏差 | 沉默不写日志、note 标 dropped、force 绕过对齐 | P2：未命中当天不留 roll 标记，当天第二次分享会再次掷签 |
| L2-07 季度自我评估 | 对齐 | confidence/失败回退/槽位/diff 对齐 | - |
| L2-08 LLM 自主更改与回滚 | 偏差 | 白名单/pending_owner/WebUI 审批对齐 | P2：LLM rollback 无 actor 限制；interest 编辑误加 `seen_count/last_seen_at` |
| L2-09 多实例租约 | 对齐 | memory_host claim/release + 本地回退 + skipped_duplicate 对齐 | P2：无续租生产调用（同 L1-16） |
| L2-10 关注对象 | 偏差 | 四类 watchlist/`source=watchlist/*`/watched 数据对齐 | P2：实体图 UI 不显示 watched 标记 |
| L2-11 故地重游 | 偏差 | 候选/标记/事件幂等/链查询对齐 | P3：`revisit_of` 在提交事务外，崩溃窗口会产生重复重访 |

## P2 偏差清单（建议优先修复）

1. 睡眠窗口只对 browse 生效：`life/scheduler.py:88-94` 只外推 browse 抖动，`run_nightly_diary`/`run_peek` 无窗口检查。修复：调度器对全部定时任务统一窗口校验/顺延，入口也补 `sleep_window.contains` 检查。
2. 提交后副作用异常把已落库 run 标 failed：`life/browser.py:400-505`。修复：提交后固定 session 状态为 `completed`，后续异常只写快照/日志。
3. 变更账本口径不符：`log_change` 只覆盖 LLM 编辑与软删/恢复（`life/db.py` 调用点）。修复：补 append 型账本，或把文档口径收敛为「owner/LLM 变更」。
4. 热力图点击跳档缺失：`pages/life/index.html:497-533`。修复：heat-cell 加 click 跳转当日档案。
5. `register_web_routes` 回退缺失：`life/webui.py:514-516`。修复：`register_web_api` 缺失时探测并注册同一组 handlers。
6. `_plan_time` 不校验范围：`life/life_tool.py:345-351`，`25:99` 会落成永久 pending。修复：校验 `0<=hour<24`、`0<=minute<60`。
7. 系统裁决拒绝事件 kind 错用 `change`：`life/browser.py:1603-1614`。修复：改 kind=`reject` 并同步 WebUI 过滤/标签。
8. LLM rollback 无 actor 限制：`life/db.py:1645-1672`。修复：LLM 只允许回滚 `actor=llm` 的 applied 条目。
9. interest 编辑误改统计：`life/db.py:779-805` 与 `life/life_tool.py:531`。修复：提供只更新 `name/weight` 的接口，不触碰 `seen_count/last_seen_at`。
10. 实体图 SVG 属性注入：`pages/life/index.html:1592`。修复：用 `setAttribute`/dataset 构造，或属性级转义。
11. 沉默率不是每天只掷一次：`life/share.py:140-148`。修复：首次分享无论命中与否都落当天 roll 标记，命中时另写 `share_silent` 快照。
12. memory_host 硬依赖不统一：`life/browser.py:419-470,1437-1446` 事件/实体/重游镜像失败仅 warning。修复：按 L2-01 语义报 error 或显式标 fallback。
13. 长任务无租约续租：`life/scheduler.py:233-267`。修复：按 TTL/2 定期 `renew_lease/renew_task`，并补测试。
14. `share_note` 非法 body 抛 500：`life/webui.py:335`。修复：`int()` 包 try 返回错误 JSON。

## P3 偏差/缺口清单

- 无历史时 `revisit` 仍掷签并返回 `revisit_day`（`life/browser.py:653-661`）。
- 时区非法仅 `logger.warning`（`main.py:67-68`），设计要求报 error。
- 注入审计接口无 WebUI 页面入口（`life/webui.py:545` 注册但 `index.html` 无 tab）。
- WebUI 加载态未全覆盖（`.loading` 类未使用）。
- 实体图 UI 不显示 watched 标记（数据已带）。
- `replay_events` 无「重放重建状态」执行器（`life/db.py:1764-1781`）。
- `purge_trash` 硬删 note 不级联 `time_capsules`（`life/db.py:2157-2179`）。
- 唯一约束迁移只识别 `autoindex`（`life/db.py:367-371`），显式命名 UNIQUE 索引不会移除（推测）。
- LLM 输出非完整 JSON schema 强校验（`life/llm.py` 只要求 dict，调用点字段校验覆盖不全）。
- `memory_adapter.search` 无生产调用者；`memory_search` 本地与宿主合并未去重。
- 无 owner 修改固定任务的界面/命令。
- 事件/timeline 分页缺深度 offset 断言。

## 测试覆盖缺口

- 睡眠窗口对 peek/diary/可选任务、提交后副作用异常、续租、`_plan_time` 非法输入、rollback actor 限制、interest seen_count 保留均无测试。
- `register_web_routes` 回退、热力图点击跳档、SVG 属性转义、watched 渲染、reject 事件 kind 无测试。
- memory host 的事件/实体/重游镜像失败路径无测试。
- 普通写操作进 `change_log`、旧版 `share_log/persona_prompts` 迁移、命名 UNIQUE 索引迁移无测试。
- 回顾/季度评估 duplicate 分支、胶囊/wishlist 成功路径、purge 与胶囊级联无测试。
- 网络冒烟只覆盖 HN/GitHub；真实 engram/ESM 集成与 Playwright 视口检查不在仓库测试内。

## 未验证

- 真实 engram_core/ESM 集成、真实 AstrBot 进程路由、Playwright 桌面/移动渲染、`LIFE_SMOKE_NET=1` 网络冒烟。
- 崩溃注入（`revisit_of` 事务窗口）、旧库命名唯一索引形态、`share_log/persona_prompts` 历史 schema。

## 结论

未发现 P1 级设计矛盾。L0/L1/L1.5/L2 已交付功能主体与设计目标对齐，偏差集中在边界语义（睡眠窗口、变更账本口径、reject 事件 kind、沉默率日掷、租约续租、rollback 权限、SVG 转义、WebUI 回退/跳档）与低概率数据一致性问题（revisit 崩溃窗口、purge 胶囊级联）。修复优先级建议：先安全类（SVG 转义）与硬约束类（睡眠窗口、reject kind、rollback 权限），再补租约续租与文档口径收敛。
