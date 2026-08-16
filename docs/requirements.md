# 上游插件需求（Your Own Life 生态对接）

本文档记录 `astrbot_plugin_your_own_life` 对 kazamisama 插件族的对接需求。v0.2.4 现状只消费 ESM 现有能力；v0.4.4 起已消费 ESM v0.11.0 的 `consume_energy` 契约，以下条目用于与上游同步版本计划。

## 未来规划基调（硬依赖）

- v2 起，本插件将把 ESM 与统一记忆宿主（engram_core 或未来 life-chain 插件）视为硬依赖，不再以“缺失静默降级”为默认目标；v0.2.4 现状的降级仅作过渡，v1.1 起计划内新契约（如 `consume_energy`）不再默认静默降级。
- 允许对这两个插件做大规模架构级变动：精力消费语义与后台任务预算、统一记忆 API 与记忆权威、生命链事件流与跨平台身份解析。
- 上游契约按硬依赖设计：能力探测只用于版本兼容诊断与报错，不用于功能开关。

## 生态兼容性约束

kazamisama 仓库下的 AstrBot 插件是一整个需要互操作的家庭，任何架构级变动都必须以全家族兼容为前提：

- 覆盖范围：`astrbot_plugin_emotion_state_machine`、`astrbot_plugin_social_context`、`astrbot_plugin_xml_structured_output`、`astrbot_plugin_vector_meme`、`astrbot_plugin_firewall`、`astrbot_plugin_litepoke`、`astrbot_plugin_private_proactive_reply`、`astrbot_plugin_engram_core`、`astrbot-plugin-media-warden` 与本插件。
- 公开契约版本化：所有跨插件 API（ESM 信号/精力、统一记忆库、社会上下文等）必须版本化并写入对应 `_PUBLIC_API.md`，不得静默改签名。
- 适配层保护：下游只通过适配层调用上游，API 变更只改对应 adapter；上游先发布兼容版本，下游再升级。
- 协调升级：涉及硬依赖的架构变动（如精力消费语义、统一记忆库权威化）需要整族协调发版，避免一个插件升级导致其他插件行为漂移。
- 不吝啬改动：兼容不等于冻结；允许对家族内任一插件做架构级重构、新增共享层或改公开契约，只要通过版本化契约与适配层保证互操作，并整族协调发版。
- 兼容矩阵：见下文「兼容矩阵（2026-08-12 快照）」，作为升级检查表；每次跨插件改动前先复核快照。

### 兼容矩阵（2026-08-12 快照，本插件行已更新至 v0.5.17）

数据来自各仓库 `metadata.yaml` / `CHANGELOG.md` / `_PUBLIC_API.md` / `git remote` / `git log`（读取时间 2026-08-12，subagent 只读调研 + 主 agent 抽查核对）。升级前以对应仓库最新 commit 复核。

| 插件 | 本地版本 | 公开 API 契约 | 远端仓库 | 与本插件对接点 |
| --- | --- | --- | --- | --- |
| astrbot_plugin_emotion_state_machine | v0.11.0 | `_PUBLIC_API.md`（v0.10.0+ 跨插件互操作契约；v0.11.0 新增 `consume_energy`） | kazamisama/astrbot_plugin_emotion_state_machine | v1 已接：精力 gate / 情绪 / `apply_self_reply_signal` / `consume_energy`（经 `life/esm_adapter.py`） |
| astrbot_plugin_social_context | v0.8.19 | 无 | kazamisama/astrbot_plugin_social_context | 方向：群聊氛围快照，群聊入档时只读接入 |
| astrbot_plugin_xml_structured_output | 0.2.9 | `_PUBLIC_API.md`（Public API · v1） | kazamisama/astrbot_plugin_xml_structured_output | 方向：行为/思想层结构化输出路由 |
| astrbot_plugin_vector_meme | 0.7.3 | 无（`search_sticker_for_external()` 见 README/CHANGELOG） | kazamisama/astrbot_plugin_vector_meme | 方向：分享消息表情行为承接 |
| astrbot_plugin_firewall | v0.1.2 | 无 | kazamisama/astrbot_plugin_firewall | 方向：记忆/安全边界（可信块剥离） |
| astrbot_plugin_litepoke | v1.4.8 | 无 | kazamisama/astrbot_plugin_litepoke | 方向：行为层信号源（情绪透传/氛围概率） |
| astrbot_plugin_private_proactive_reply | v0.11.2 | 无 | kazamisama/astrbot_plugin_private_proactive_reply | 方向：主动社交行为层（复用人格/记忆/工具链） |
| astrbot_plugin_engram_core | 1.76.0 | `_PUBLIC_API.md`（Public API · v1；v1.75 日记/召回/租约，v1.76 事件/短记/实体图） | kazamisama/astrbot-plugin-engram-core | v2 硬依赖：统一记忆库/日记写入/召回/实体图/租约，经 `LifeMemoryAdapter` |
| astrbot-plugin-media-warden | 1.8.1 | 无 | kazamisama/astrbot-plugin-media-warden | 方向：素材采集/记忆原料，未见显式契约 |
| astrbot_plugin_your_own_life（本插件） | v0.5.17 | 无独立 `_PUBLIC_API.md`；跨插件调用全部经适配层 | kazamisama/astrbot_plugin_your_own_life | 本插件（L1/L1.5 已交付，L2-01 至 L2-11 全部已落地，v0.5.0-v0.5.17） |

升级检查表：

- 上游升级前先复核本表快照（版本、公开契约、remote），并确认该插件源码中是否有指向本插件的调用。
- 涉及 ESM 精力/信号或统一记忆 API 的升级 = 整族协调发版；先上游兼容版本，后下游适配层升级。
- 本插件对上游只经 adapter 调用；API 变更只改 adapter，不散落进业务模块。
- `_PUBLIC_API.md` 缺失的插件，接入前先补契约文档或至少确认调用面（小阶段 + 测试）。

## ESM（astrbot_plugin_emotion_state_machine）

- 互联网漫游专用 signal：建议新增 `novelty`（新鲜感）、`info_binge`（信息摄入疲劳）等 signal，语义与群聊信号解耦，避免漫游内容污染群聊关系层。
- 后台任务精力语义（已落地）：v0.11.0 新增 `consume_energy(amount, reason, scope=None) -> float`，定时漫游/日记任务真实消耗精力并持久化；本插件经 `life/esm_adapter.py` 接入。
- 非聊天 scope 契约：`internet-life` 这类非群聊 scope 目前依赖内部归一化规则；建议在 `_PUBLIC_API.md` 中明确非群聊 scope 的创建、衰减与清理语义。
- 稳定跨插件契约：v0.11.0 `_PUBLIC_API.md` 已含 `get_bot_energy` 与 `consume_energy` 稳定条目；下游经 `life/esm_adapter.py` 适配，无需探测私有方法。

## Your Own Life 自身上游需求

- persona 人格缓存契约：本插件需要按 persona_id 拉取 `persona.system_prompt`，建议 AstrBot 提供稳定的按 ID 查询接口与变更通知，便于缓存失效。
- 分享精力语义：分享成功后本插件调用 ESM `self_reply` 信号；建议 ESM 将"后台主动发送"与"群聊主动回复"的精力消耗语义统一并文档化。

## engram_core（astrbot_plugin_engram_core，后置）

- 公开日记写入 API（已落地）：v1.75.0 起 `store_diary_line(persona_id, date, content, ...) -> str` 写入 persona 分区的 `diary` 记忆，字段/返回值/版本承诺见 `_PUBLIC_API.md`。
- Bot 视角生活日记：当前日记层以群聊消息为素材；建议支持外部插件注入“非聊天生活事件”（如互联网漫游短记），并保留来源标签。
- 公开召回接口（已落地）：v1.75.0 起 `query_recent_memory`，v1.76.0 起 `query_memory / search`，下游不直接 import `hippocampus` 内部包。
- 每 persona 任务租约 API（已落地）：v1.75.0 起 `claim_task / renew_task / release_task / task_lease_owner`，本插件经 `LifeMemoryAdapter` 调用（L2-09）。

## 待上游落地的契约提案（2026-08-12 已核实）

以下两项曾是本插件剩余阶段（L1-03 精力预算、L2 统一记忆库）的硬闸门；ESM `consume_energy` 已随 v0.11.0 落地并接入（v0.4.4），engram_core 契约已随 v1.75.0 / v1.76.0 落地并接入（v0.5.0）：

### ESM `consume_energy`（已解锁，v0.11.0）

- 现状（已验证）：`astrbot_plugin_emotion_state_machine` 本地 v0.11.0，`_PUBLIC_API.md` 公开 `get_bot_energy(scope=None) -> float` 与 `consume_energy(amount, reason, scope=None) -> float`；源码含 `consume_energy`，扣除并持久化精力、返回剩余精力，`amount` 范围 `(0, 1]`，非法入参抛 `ValueError`。
- 本插件落点（已实现，v0.4.4）：`life/esm_adapter.py` 新增 `consume_energy(persona_id, amount, reason)` 并按 persona scope 转发；漫游/日记成功后真实扣减并双写 `daily_usage.energy_used` 本地用量；ESM 缺失时显式记录本地估算（`browse_energy_fallback` / `diary_energy_fallback` 快照）；预算耗尽当天剩余任务跳过并记录 `energy_budget_exhausted`。
- 契约版本：ESM v0.11.0 `_PUBLIC_API.md`。

### engram_core `_PUBLIC_API.md`（已落地，v1.75.0 / v1.76.0）

- 现状（已验证）：本地 1.76.0，仓库已有 `_PUBLIC_API.md`（Public API · v1）；日记写入/召回/租约/事件/短记/实体图均有稳定公开方法。
- 覆盖范围：`store_diary_line`、`query_recent_memory`、`query_memory / search`、`claim_task / renew_task / release_task / task_lease_owner`（v1.75.0），`store_event`、`add_note`、`upsert_entity / link_entities / list_entities / list_links`（v1.76.0）；明确 `persona_id` 分区键与来源标签 `source:your_own_life`。
- 本插件落点（已实现，v0.5.0）：`life/memory_adapter.py`（`LifeMemoryAdapter`）路由全部记忆读写，本地 SQLite 降级为缓存；L2 各子项按 `docs/features.md` 顺序推进。
- 发布流程：上游已先发兼容版本并补契约，本插件按整族协调升级（见“生态兼容性约束”）。

### 适配层接口草案（仅设计，不实现）

已按以下接口实现 ESM 部分（`consume_energy` 为同步方法，签名以 v0.11.0 为准）；engram_core 部分已实现（v0.5.0，经 `LifeMemoryAdapter`，签名以 v1.75.0 / v1.76.0 `_PUBLIC_API.md` 为准）：

```python
# life/memory_adapter.py（草案）
class LifeMemoryAdapter:
    async def store_diary_line(
        self, persona_id: str, date: str, content: str,
        mood: str = "", signature: str = "", source_refs: list = None,
    ) -> str: ...
    async def query_recent_memory(
        self, persona_id: str, query: str = "", k: int = 5,
        since: str = "",
    ) -> list[dict]: ...
    async def claim_task(self, persona_id: str, task_kind: str, ttl: int) -> bool: ...
    async def renew_task(self, persona_id: str, task_kind: str, ttl: int) -> bool: ...
    async def release_task(self, persona_id: str, task_kind: str) -> bool: ...

# life/esm_adapter.py（草案，L1-03）
    async def consume_energy(self, persona_id: str, amount: float, reason: str) -> float: ...
```

### 对齐闸门

- ESM `consume_energy`：v0.11.0 已发布并接入（L1-03 完成，见 features.md）。
- engram_core `_PUBLIC_API.md`：v1.75.0 / v1.76.0 已发布并接入（L2-01 完成，见 features.md）。

## social_context（后置）

- 群聊入档接入点：当本插件启用群聊生活切片时，需要从 social_context 读取短期氛围与活跃用户摘要；建议提供只读快照 API。

## 生命链（后置，目标架构）

- 统一事件处理：把所有平台、所有消息事件（群聊、私聊、戳一戳、外部生活任务）按 persona 归入一条"生命链"，按时间顺序处理成统一的生活记忆。
- 多平台一致印象：对同一人物的印象（偏好、关系、事件）跨平台合并，避免"QQ 里认识、微信里不认识"。
- 数据契约建议：事件统一为 `{persona_id, platform, session_id, ts, kind, payload}`；记忆统一为 `{persona_id, entity, relation/event/preference, confidence, sources[]}`；后续实现独立于本插件 v2 的本地档案。

## 对接降级策略

- 本插件对 ESM：v0.2.4 现状缺失 / 方法缺失 / 信号非法时静默 no-op 并记录 debug 日志；v0.4.4 起 `consume_energy` 缺失时按 features.md L1-03 显式记录本地估算，不再默认静默降级。
- 本插件对 engram_core：v0.5.0 起经 `LifeMemoryAdapter` 调用，`memory_host` 配置后为硬依赖，宿主缺失报 error；任何上游 API 变化只改对应 adapter。
- 本插件对 social_context：v1 不调用；后续版本在能力探测通过后才启用，任何上游 API 变化只改对应 adapter。
