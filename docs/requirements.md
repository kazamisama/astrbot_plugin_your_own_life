# 上游插件需求（Your Own Life 生态对接）

本文档记录 `astrbot_plugin_your_own_life` 对 kazamisama 插件族的对接需求。v1 只消费 ESM 现有能力；以下条目用于与上游同步版本计划，不阻塞本插件运行。

## ESM（astrbot_plugin_emotion_state_machine）

- 互联网漫游专用 signal：建议新增 `novelty`（新鲜感）、`info_binge`（信息摄入疲劳）等 signal，语义与群聊信号解耦，避免漫游内容污染群聊关系层。
- 后台任务精力语义：当前 `get_bot_energy()` 只反映自回复消耗；建议提供 `consume_energy(amount, reason)` 或等效公开方法，让定时漫游/日记任务真实消耗精力并持久化。
- 非聊天 scope 契约：`internet-life` 这类非群聊 scope 目前依赖内部归一化规则；建议在 `_PUBLIC_API.md` 中明确非群聊 scope 的创建、衰减与清理语义。
- 稳定跨插件契约：为 v0.11 规划版本化适配层（能力探测 + 方法清单），使下游插件无需探测私有方法。

## Your Own Life 自身上游需求

- persona 人格缓存契约：本插件需要按 persona_id 拉取 `persona.system_prompt`，建议 AstrBot 提供稳定的按 ID 查询接口与变更通知，便于缓存失效。
- 分享精力语义：分享成功后本插件调用 ESM `self_reply` 信号；建议 ESM 将"后台主动发送"与"群聊主动回复"的精力消耗语义统一并文档化。

## engram_core（astrbot_plugin_engram_core，后置）

- 公开日记写入 API：把 `DiaryStore.add_line(DailyLine(...))` / `Service.store_diary(...)` 提升为跨插件公开 API，固定字段、返回值和版本承诺。
- Bot 视角生活日记：当前日记层以群聊消息为素材；建议支持外部插件注入“非聊天生活事件”（如互联网漫游短记），并保留来源标签。
- 公开召回接口：供后续把“最近日记/见闻”注入 LLM 请求时使用，避免本插件直接 import `hippocampus` 内部包。

## social_context（后置）

- 群聊入档接入点：当本插件启用群聊生活切片时，需要从 social_context 读取短期氛围与活跃用户摘要；建议提供只读快照 API。

## 生命链（后置，目标架构）

- 统一事件处理：把所有平台、所有消息事件（群聊、私聊、戳一戳、外部生活任务）按 persona 归入一条"生命链"，按时间顺序处理成统一的生活记忆。
- 多平台一致印象：对同一人物的印象（偏好、关系、事件）跨平台合并，避免"QQ 里认识、微信里不认识"。
- 数据契约建议：事件统一为 `{persona_id, platform, session_id, ts, kind, payload}`；记忆统一为 `{persona_id, entity, relation/event/preference, confidence, sources[]}`；后续实现独立于本插件 v2 的本地档案。

## 对接降级策略

- 本插件对 ESM：缺失 / 方法缺失 / 信号非法时全部静默 no-op，并记录 debug 日志。
- 本插件对 engram_core / social_context：v1 不调用；后续版本在能力探测通过后才启用，任何上游 API 变化只改对应 adapter。
