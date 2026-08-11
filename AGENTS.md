# AGENTS.md（Your Own Life 开发守则）

本文件是对本仓库内所有 agent 会话的硬约束，叠加在全局 AGENTS.md（橘雪莉工作准则）之后生效。详细流程见 `docs/workflow.md`；冲突时以本文件与 `docs/` 下的规则为准，再冲突以实际代码为准。

## 北极星目标

从行为、思考层、思想层、发散思维与联想、线性生命链、记忆结构与检索六个维度，实现拟人化的 bot 生命活动与跨平台社交交互。六维度与现状/方向的映射见 `docs/design.md` 定位。

## 文档顺序

每次开始工作先按顺序读取：`docs/workflow.md`（怎么改）→ `docs/devlog.md`（上次做到哪）→ `docs/design.md`（现在是什么样）→ `docs/features.md`（这层做什么、怎么验收）→ `docs/requirements.md`（跨插件边界）→ `docs/roadmap.md`（往哪走）。

## 硬性规则

1. 先读源码再改：入口、核心模块、适配层、`metadata.yaml`、`_conf_schema.json`、测试；跨插件改动先看对方 `_PUBLIC_API.md` 或适配器。未读不改。
2. 小阶段推进：一个阶段 = 一个可交付功能/修复；落地时同步 `metadata.yaml` 版本与 `CHANGELOG.md`；commit 信息按仓库习惯（`chore(release): vX.Y.Z ...`）；review + debug + 测试通过后再 push。
3. 开发日志：每个工作段结束或上下文可能压缩前，更新 `docs/devlog.md`（目标/决策/改动/验证/遗留/下一步）；新会话先读最新条目与 `git status` 再动手；决策、契约、版本点、待办不允许只存在对话里。
4. 外部调研：开发前/中联网搜相关项目/经验/论文，结论带来源并标注“已验证/推测/待验证”；没读过的资料不当事实。
5. Subagent：只做调研/测试/审查/起草；决策、编辑、提交、推送由主 agent 完成；subagent 未获授权不得改文件，结论必须先 review 再落地；七条完整约束见 `docs/workflow.md`。
6. 安全边界：只改工作区内且纳入 git 的文件；不删改工作区外或无 git 仓库内容；缺依赖可装（按需、不扩散）。
7. 现状与方向分开：L0 = v0.2.4 现状，L1+ = 已确认方向；描述现状以代码为准（如 v0.2.4 仍用确定性 fallback，重试/报 error 是 v1.1 目标）。
8. 功能分层：开发按 `docs/features.md`，L0 必须全绿；L1 允许引入上游依赖（须在 features.md 标注并同步 requirements.md）；L1.5 事件链先只读后写；L2 前先与上游对齐契约并整族协调。
9. 硬依赖与生态：v2 起 ESM 与统一记忆宿主为硬依赖；kazamisama 插件族整体兼容，兼容不等于冻结；契约版本化 + 适配层 + 整族协调发版。
10. 交付纪律：完成修改后按“已修改/未修改/已验证/未验证”四象限汇报；无法验证的部分必须如实标注。
11. 代码修改：`.py / .js / .ts` 等代码文件必须经 `safe_edit`（新文件用 `apply_patch` + 语法检查），禁止用 shell 重定向/`Set-Content` 等直接写代码文件；文档优先 `apply_patch`（UTF-8）。

## 测试与环境

- 单测：`python -m unittest discover -s tests -v`，必须全绿。
- 网络冒烟：设置 `LIFE_SMOKE_NET=1` 后执行真实 HN/GitHub 抓取，失败标记跳过。
- 真实运行路径：WebUI / 命令尽量用 astrbot-test-kit 实测，venv：`C:\Users\chiriu\Documents\workspace\astrbot_test_kit_dev\astrbot_test_kit\.venv\Scripts\python.exe`。
- 生产 `~/.astrbot` 只读；测试与实验只在 test kit 环境进行。

## Windows PowerShell 5.1

- PS 5.1 管道把中文喂给 `python -` 会变 `?`；不要用含中文的内联命令直接管道给解释器，改用 UTF-8 临时文件或 `apply_patch`。
- 写中文优先 `apply_patch`；写完用 Python 以 `utf-8` 读回校验 `\ufffd`。
- `safe_edit` 传中文参数用 `$env:SE_OLD / $env:SE_NEW` + `--old-env / --new-env`。
- 控制台乱码不代表文件损坏，以 Python `utf-8` 读回为准。
