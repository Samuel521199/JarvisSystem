# 公共接口与数据契约

> 状态：proposed（总体设计）；局部 implemented（K0 六类契约、预检、主人恢复、固定 Worker、浏览器消息、网页队列、项目导出与 0.1.12 单次聊天取消） · 更新：2026-10-16
> [文档入口](README.md) · [维护规则](MAINTENANCE.md) · [架构图册](architecture-atlas.md)

<!-- book-nav:start -->
[全书目录](README.md#book-tree) › [第二篇 · 核心与工程基础](README.md#part-foundation) › 第 08 章 · 公共接口与数据契约

## 本章导航

- [8.1 K0 当前实现与验证](#k0-contracts)
- [8.2 个人助手核心接口（设计）](#personal-assistant-contracts)
  - [8.2.1 身份、个人上下文与行动意图的边界](#personal-context-contract)
- [8.3 K1/K2 下一轮最小接口面](#next-control-contracts)
  - [8.3.1 0.1.5 已实现的只读预检报告](#preflight-contract)
  - [8.3.2 0.1.7 已实现的固定 Worker 消息](#worker-contract)
  - [8.3.3 0.1.8 浏览器任务与动作契约](#computer-contract)
    - [8.3.3.1 0.1.10 网页任务与队列接口](#computer-web-contract)
  - [8.3.4 0.1.13 共用后台任务接口](#task-queue-contract)
  - [8.3.5 0.1.31 会话任务接口](#conversation-task-contract)
  - [8.3.6 0.1.30 自然语言样例报告接口](#sample-task-contract)
  - [8.3.7 0.1.15 本机运行版本与临时目录契约](#runtime-slots-contract)
  - [8.3.8 0.1.14 旧版停止状态兼容消息](#recovery-contract)
  - [8.3.9 0.1.11 项目与文本导出接口](#project-workspace-contract)
  - [8.3.10 项目组织与可恢复归档接口（2026-10-17）](#project-organization-contract)
  - [8.3.11 0.1.24 本机会话归档接口](#conversation-archive-contract)
  - [8.3.12 0.1.25 明确事实记忆与聊天引用接口](#explicit-memory-contract)
  - [8.3.13 0.1.39 个人指令与表达扩展](#personal-core-contract)
  - [8.3.14 0.1.62 交流配置、三库查询与接续推荐扩展](#personal-profile-v2)
  - [8.3.15 0.1.40 接续记录与会话来源扩展](#continuity-contract)
  - [8.3.16 本人消息候选整理接口（0.1.43 起，0.1.44 扩展）](#personal-candidates-contract)
  - [8.3.17 语义事实候选接口（0.1.50）](#semantic-candidates-contract)
  - [8.3.18 规则与语义事实候选的本地核对与显式处理（0.1.58—0.1.60）](#memory-candidate-review-contract)
  - [8.3.19 候选事实来源与数据库迁移（0.1.44）](#memory-provenance-contract)
  - [8.3.20 事实分类、用途与兼容接口（0.1.47）](#memory-domain-contract)
  - [8.3.21 0.1.42 接续与执行账本关联](#work-continuity-contract)
  - [8.3.22 0.1.26 项目文档登记、检索和来源引用](#project-knowledge-contract)
  - [8.3.23 0.1.21 聊天附件接口](#chat-attachments-contract)
  - [8.3.24 聊天完成状态字段（0.1.21）](#chat-completion-contract)
  - [8.3.25 0.1.12 单次聊天取消接口](#chat-cancel-contract)
  - [8.3.26 设置总览资源快照接口（2026-10-16 增量）](#resource-usage-contract)
  - [8.3.27 并行运行指标接口（0.1.34）](#parallel-runtime-contract)
  - [8.3.28 精确计算聊天回执（0.1.37）](#deterministic-calculation-contract)
  - [8.3.29 模型后台配置与统计接口（0.1.19）](#model-admin-contract)
  - [8.3.30 0.1.63 应用网络控制接口](#application-network-contract)
  - [8.3.31 0.1.22 模块观察与维护接口](#module-monitor-contract)
  - [8.3.32 独立 CosyVoice3 文件语音接口](#cosyvoice3-contract)
  - [8.3.33 独立主力 Qwen 语音接口](#qwen-tts-contract)
    - [8.3.33.1 分层表达、分段预览与语音合成](#speech-expression-score)
    - [8.3.33.2 聊天回复的有界朗读通道](#chat-readout-contract)
  - [8.3.34 独立快速本地语音接口](#fast-speech-contract)
- [8.4 记忆组件的替换契约（proposed）](#memory-provider-contracts)
  - [8.4.1 开源提取器、编纂器与路由的适配要求（proposed）](#memory-extractor-adapter)
  - [8.4.2 联合知识视图运行契约（0.1.33）](#memory-view-runtime-contract)
  - [8.4.3 MemoryView 与知识候选的必要语义（proposed）](#memory-view-contract)
- [8.5 上下文编排：当前装配与后续压缩](#context-assembly-contract)
  - [8.5.1 0.1.23 已实现的临时聊天上下文](#context-assembly-current)
  - [8.5.2 后续完整 ContextAssembler 契约（proposed）](#context-assembly-future)
- [8.6 接口与数据契约](#interfaces)
  - [8.6.1 模块生命周期](#interfaces-1)
  - [8.6.2 任务与动作分离](#interfaces-2)
  - [8.6.3 事件信封](#interfaces-3)
  - [8.6.4 技能和模块包清单](#interfaces-4)
  - [8.6.5 接口类型选择](#interfaces-5)
- [8.7 技能选择、策略与调用记录契约](#skill-selection-contract)
  - [8.7.1 编程副本与验证状态字段（0.1.69）](#bounded-coding-contract)
- [8.8 资源租约、本地组件与安全事件契约](#extensions-3)
- [8.9 项目资源与工程文件契约（0.1.27）](#project-resources-contract)
- [8.10 MCP 与技能登记契约（0.1.27；0.1.37 管理增量）](#extension-catalog-contract)
  - [8.10.1 Context7 只读文档任务（0.1.55）](#mcp-documentation-task-contract)
- [8.11 限定成长运行接口](#evolution-runtime-contract)
  - [8.11.1 会话需求适配接口（0.1.41）](#growth-demand-contract)
- [8.12 三能力消息与旧接口迁移](#growth-center-contract)
- [8.13 统一对话受理、意图与事件契约（proposed）](#dialogue-turn-contract)
  - [8.13.1 对话意图与限定任务受理契约（0.1.56—0.1.59）](#dialogue-intent-shadow-contract)
  - [8.13.2 已实现的回复回执接口（0.1.48—0.1.49 / dialogue-receipt-v1）](#dialogue-receipt-contract)
    - [8.13.2.1 普通会话的持久回复恢复（0.1.49）](#dialogue-recovery-contract)
    - [8.13.2.2 对话与后台模型进程边界（0.1.54）](#dialogue-process-contract)
<!-- book-nav:end -->

<a id="k0-contracts"></a>
## K0 当前实现与验证

原型 **0.1.0** 已提供以下六份机器可读契约，统一采用 **JSON Schema Draft 2020-12**，公共对象的 `schema_version` 固定为 `1.0.0`。原型版本与数据契约版本分别管理。下列源文件是当前字段、必填项、版本和状态枚举的唯一权威；本页不复制 schema 全文。

| 契约 | 当前职责 | 权威源文件 |
|---|---|---|
| Task | 任务身份、归属、预算、授权引用与任务状态 | [task.schema.json](../contracts/schemas/task.schema.json) |
| Action | 动作身份、宿主代次、参数摘要、幂等声明、执行状态与错误对象 | [action.schema.json](../contracts/schemas/action.schema.json) |
| Capability | 能力版本、可用状态、输入输出 schema、执行器引用与权限范围声明 | [capability.schema.json](../contracts/schemas/capability.schema.json) |
| Artifact | 产物关联、相对路径、摘要、媒体类型与大小 | [artifact.schema.json](../contracts/schemas/artifact.schema.json) |
| Module | 模块包身份、运行环境、接口、状态迁移和发布声明 | [module.schema.json](../contracts/schemas/module.schema.json) |
| Build profile | 构建目标、工具链、argv 命令、资源限制与验证标记 | [build-profile.schema.json](../contracts/schemas/build-profile.schema.json) |

六份契约的顶层与已声明的固定结构拒绝附加字段，不接受静默增加的权限或未来版本。Action 的动态 `arguments` 还必须按对应 Capability 的 `input_schema` 校验，不能仅依靠 Action 外壳判断参数有效。schema 合法只说明数据结构满足契约，不等于已经授权、完成执行或具备操作系统隔离。

[K0 种子清单](../seed/system-manifest/seed-bundle.json) 当前登记 **22 个资产摘要**：6 份 schema、知识/规则/技能三份 JSON，以及包含索引的 13 份夹具文件。其中 [夹具索引](../tests/fixtures/contracts/cases.json) 定义 **12 个正反例**，六份契约各一正一反。规则基线还由校验器中的独立摘要固定；校验器只读检查，不自动重写规则基线或资产摘要来消除失败。

[能力目录](../seed/skills/catalog.json) 的 `system.status.v1` 输出明确区分未初始化、正常状态与停止后的诊断失败三个闭合分支；正常状态可附带严格的 Task/Action/Artifact 记录。`filesystem.read_sample.v1` 的输出是产物内的目录清单 JSON，包括 `files`、每项的 `path/size_bytes/type` 和合计值；外层任务、动作与产物回执仍分别遵守上述公共契约。内嵌公共契约与源 schema 的一致性由测试检查。

[种子校验器](../tools/check_seed.py) 和 [K0 测试](../tests/test_seed.py) 已通过：22 个资产、12 个夹具，22 项 K0 测试。[核心测试](../tests/test_core.py) 另以运行时真实返回验证状态查询、任务详情、停止结果与目录清单输出，避免只验证手写示例。可重跑：

```text
python tools/check_seed.py --root .
python -m unittest discover -s tests -p test_seed.py
python -m unittest discover -s tests -p test_core.py
```

Module 与 Build profile 已有契约和夹具，但这不表示模块升级器、候选构建器或自主发布已经实现；`build.candidate.v1` 仍为 `planned`。以下保留的生命周期、事件、协议、租约与社区停止契约属于未来扩展设计，示例也可能使用未来字段或版本，**不是当前 0.1.12 的可调用接口**；明确标注已实现的预检、Worker、恢复、浏览器和项目导出消息除外。

<a id="personal-assistant-contracts"></a>
## 个人助手核心接口（设计）

<a id="personal-context-contract"></a>
### 身份、个人上下文与行动意图的边界

**完整接口 proposed；0.1.39 已实现[个人指令与表达子集](#personal-core-contract)，不代表下表全部落地。** 服务于[助手核心架构](architecture.md#pc-runtime-convergence)，复用现有会话、记忆、任务和模型接口；不改写已冻结的 K0 种子摘要。落地时建立版本化唯一机器定义与正反例，不能把以下概念名当作已可调用 API。

| 接口责任 | 最小约束 | 写入与失败语义 |
|---|---|---|
| PersonaProfile 读取/预览/激活 | 稳定主体引用、配置版本、表达/关系设置、作用域；配置不存执行授权 | 激活验证预期旧版本，在轮次边界生效；失败保留原配置；身份与人格表达分开管理 |
| PersonalContext 装配 | 当前会话、人格版本、相关事实/经历引用、作用域与来源版本、上下文预算 | 有界只读视图；模型缓存不成为记忆源；失效、删除、外发禁止的内容排除，不足时明确降级 |
| MemoryIntent 受理 | 明确记住/纠正/遗忘、说话者及来源、作用域、预期修订；引用/推断独立标注 | 交给现有记忆写入者校验；重复意图幂等，冲突返回可解释状态；不能从人格模块直接改事实表 |
| Response / WorkIntent 分流 | 普通交流、记忆意图、建议、具体行动不同类型；带会话和当前请求关联 | 纯交流不创建执行任务；明确行动复用唯一任务受理，能力未开放时说明缺口；不把普通文本响应包装成动作成功 |
| Commitment / Attention 视图 | 约定来源、有效时间/范围、提醒偏好、已撤销状态；实际任务引用 | 约定与执行结果分开；需要定时/外部动作时使用已有受理语义，去重与取消可查；观察不凭自身内容创造新授权 |

<a id="next-control-contracts"></a>
## K1/K2 下一轮最小接口面

以下用于[下一轮工作包](core-bootstrap.md#next-implementation)。[只读预检报告](#preflight-contract)与[主人恢复消息](#recovery-contract)已有实现，其余新增控制消息仍为 proposed；先沿用现有六类对象，新增消息须在 `contracts/schemas/` 建立唯一机器定义及正反例后才能接入。这里定义职责与失败语义，不另存第二份字段规范。

| 接口职责 | 请求/返回的必要信息 | 权威与失败处理 |
|---|---|---|
| 运行预检 | 运行版本、角色、资源权限检查、依赖状态、未满足条件及证据引用 | 只读；不得为了让检查变绿而自动提升权限、安装服务或清除锁存 |
| 提交与查询任务 | 客户端稳定请求标识、目标、输入引用、授权引用；返回持久任务 ID 与当前状态 | Host 受理提交后才确认；同标识不同参数拒绝；网页断线后凭标识查询，不能默认再次创建 |
| 提交候选计划 | 目标修订、能力目录版本、步骤依赖、类型化参数或前序产物引用、预期输出、迭代与时间上限 | 规划器只提出计划；Host 验证 schema、授权、资源和依赖，确定动作身份；不接受任意 Shell 文本 |
| Worker 派发与回执 | 固定能力/包版本、Task/Action ID、宿主与安全代际、限定输入、输出配额；返回结果引用和实际状态 | 身份由受保护传输验证；自报角色或代际不是凭据；回执丢失沿用 UNKNOWN 语义 |
| 状态读取与变更通知 | 实体 ID、持久状态、单调事件游标、产物/错误引用；允许状态快照补偿丢失事件 | 通知只是视图更新；乱序或重复事件不能触发再次执行，终态由账本和回执确定 |
| 当前回复停止与任务取消 | 回复停止针对 request_id，任务取消针对 task_id；全局监督延期 | “已收到”与“已取消”分开返回；助手继续运行或待命，不能把断开网页当成后台已经取消 |
| 旧版停止状态兼容 | 本机显式迁移，核对节点、代际、事件集合并保留审计；无密钥/密码 | 当前机器定义见[兼容消息](#recovery-contract)；完整认证设计延期，日常会话停止不使用此入口 |

本机控制通道须版本化、限定消息大小与等待时间，拒绝未知字段和不兼容版本；使用[已选 IPC 边界](stack-project-layout.md#technology-selection-2)。固定枚举操作必须与能力目录匹配，不能用一个通用 `execute(command)` 绕过准入。大输入、报告和日志走带摘要的对象引用，返回给界面的错误采用规范化代码与可展示说明。

当前 CLI/网页通过兼容应用服务接入，不能另外维护自己的任务状态机。迁移验证要覆盖旧请求的查询与终态回执；破坏性协议变化须升级契约版本，并保留正在运行任务的支持路径。

<a id="preflight-contract"></a>
### 0.1.5 已实现的只读预检报告

`preflight --json` 使用 [preflight.schema.json](../contracts/schemas/preflight.schema.json) 作为唯一机器定义，版本 `1.0.0`。它是诊断消息，独立于 K0 六类业务契约和冻结的 22 个种子资产；正反例放在 [valid.json](../tests/fixtures/preflight/valid.json) 与 [invalid.json](../tests/fixtures/preflight/invalid.json)，由 [test_preflight.py](../tests/test_preflight.py) 校验，不改写 K0 资产摘要或放宽种子检查。

固定外壳拒绝未知字段、版本与未定义状态；各检查项的 `evidence` 允许操作系统相关观察数据，不承载授权或可执行参数。当前协议只产生 `blocked` 或 `incomplete`，没有“授权执行”分支。`pass` 表示该项所描述的观察已完成；例如读取 ACL 不等于验证了隔离访问权。字段不得被未来派发器当作授权凭据。

运行角色与资源访问声明来自 [runtime-boundaries.json](../config/runtime-boundaries.json)，只表达当前实现职责，不能通过编辑声明令隔离检查通过。固定元数据 Worker 已实现；恢复密钥和密码流程已取消，受保护身份和全局监督延期，预检保留未验证的部署差异。完整控制消息仍须按前述契约准入流程实现。

<a id="worker-contract"></a>
### 0.1.7 已实现的固定 Worker 消息

唯一字段和匹配实现见 [Host broker](../runtime/node-host/jarvis_core/worker.py) 与[固定 Worker](../runtime/worker-host/worker.py)。这是内部操作 `inventory.metadata.v1`，不是通用脚本/工具派发协议；不改变 K0 冻结的六份 schema 或 Task/Action 外部格式。

请求只含 `binding` 与 `inventory`。绑定携带版本、固定操作、节点、Host、任务/动作/attempt、owner/security 代际、参数摘要、随机 nonce 与输入摘要。结果必须回显同一绑定；Host 拒绝重复 JSON 键、额外字段、类型偷换、旧 nonce/代际或不等于获准元数据快照的内容。结果计算完成不等于提交成功，最终产物仍由 Host 经过停止和代际检查后写入。

运行包缺失/变动、启动隔离失败、CPU/时间/内存/输出失败或消息不匹配，不触发无隔离重试。无产物前记录 FAILED 或取消；提交结果不确定时仍按既有 UNKNOWN 规则处理。具体限额和权限归[Worker 安全范围](security-sovereignty.md#worker-isolation)，验证入口见[Worker 证据](delivery-validation.md#worker-evidence)。

<a id="computer-contract"></a>
### 0.1.8 浏览器任务与动作契约

任务唯一机器定义为 [computer-task.schema.json](../contracts/schemas/computer-task.schema.json)，动作定义为 [computer-action.schema.json](../contracts/schemas/computer-action.schema.json)，版本整数 `1`。这是可选扩展，不改 K0 的六份冻结契约。

任务固定 URL/origin、目标 ID/role/name、允许的操作/值、成功元素文字、1—20 步与 10—600 秒预算。模型只返回 `observation_id/op/target/value`；拒绝额外字段、重复键、旧观察、不可用目标、类型偷换和范围外值。schema 后还需执行 [protocol.py](../adapters/computer-use/jarvis_computer/protocol.py) 的跨字段检查。目标有歧义或页面摘要变化时拒绝派发，不能改用模型自造选择器。

主账本使用 `browser.operate.v1`，Action 的 `idempotency_support=none`：本地重复请求可去重，外站效果没有幂等保证。现有 `max_cost_units` 在该能力中表示最坏模型请求数量上限（最多步骤 × 5 个路由候选），不是货币预算或余额；实际次数由有限规划循环及既有路由约束。`--scripted` 演示为零模型请求。

同一 SQLite 账本新增 `computer_steps` 附表，主键 `(task_id, ordinal)`，记录 IN_FLIGHT/CONFIRMED/UNKNOWN、动作 JSON、观察摘要和模型元数据。它不改变主任务状态权威，也不保存整份网页文本。执行后检查的是页面成功元素，不是外站的独立交易回执。任何 UI 动作尝试后中断，主 Action 按 UNKNOWN 保留且不自动重放；步骤 CONFIRMED 只表示驱动调用完成并通过当时检查。

成功产物沿用 Artifact 契约，JSON 内引用 PNG 的名称、大小与 SHA-256；读取时同时检查两个文件。范围、停止与残留语义见[安全页](security-sovereignty.md#computer-boundary)。

<a id="computer-web-contract"></a>
#### 0.1.10 网页任务与队列接口

HTTP 接入由 [server.py](../apps/web/server.py)校验本机 Host/Origin 和页面 nonce，[ComputerWeb](../adapters/computer-use/jarvis_computer/web.py)校验提交字段。没有新增或改变 K0 契约；完整任务内容仍使用上节 schema。

| 接口 | 语义 |
|---|---|
| `POST /api/computer/tasks` | 仅接收 `request_id/mode/model/task`；request_id 为 `web-` 加 32 位十六进制，mode 为 demo/scripted/custom。只有 custom 接受 task，其余使用固定合成任务；model 必须为目录中的 ID 或 auto |
| `GET /api/computer/tasks` | 最多 30 条浏览器任务（未完成优先）、queue_position、模块可用/核心准入状态与 queue；不读取文件内容或凭据 |
| `GET /api/computer/tasks/<task-id>` | 主任务状态、取消标志、错误、步骤及截图是否存在；尚未执行时步骤可以为空 |
| `GET /api/computer/tasks/<task-id>/screenshot` | 只按已提交回执查找 PNG，并复核摘要；不接受客户端文件路径 |
| `POST /api/computer/tasks/<task-id>/cancel` | 只接受空对象；仅能取消浏览器任务，不能通过此入口取消其他能力任务或解除核心停止 |

`queue` 返回 paused、owned、waiting、capacity、running（在途任务 ID）、positions（等待次序）和 error。`POST /api/computer/queue` 仅接受 `{"paused":true|false}`，返回同一队列快照；必须通过原 Host/Origin/nonce 检查。暂停不取消在途任务，继续不能清除核心锁存。执行语义只在[任务章](tasks-agents.md#browser-durable-queue)维护。

所有任务读取也要求 `X-Jarvis-Nonce`，POST 另要求同源 Origin。接纳成功返回 202 和 task_id，不代表执行成功；队列满、同 ID 改参数或待运行版本/演示内容不匹配返回 409；服务被新宿主接管返回 503。不同新任务可排队，已完成/UNKNOWN 同请求返回原 ID。网络超时不证明受理失败，调用方先查询并沿用原请求 ID 核对，不能自动换 ID 重发。服务重启使旧 nonce 失效，但历史任务仍可通过新页面查询。状态与 CANCELLING/UNKNOWN 语义沿用主账本。

<a id="task-queue-contract"></a>
### 0.1.13 共用后台任务接口

以下接口复用原 Host/Origin/nonce 保护及唯一持久队列；原 `/api/computer/tasks` 的列表和取消仍只接受浏览器任务，`/api/computer/queue` 控制同一共享队列，不新建第二个调度器。

| 接口 | 字段与语义 |
|---|---|
| `POST /api/tasks` | 浏览器模式沿用已有字段；目录模式严格接受 `{request_id, mode:"inventory", relative_path}`，request_id 同为 `web-` 加 32 位十六进制，不接受 model/task/绝对目录或其他字段；获准根来自实例初始化配置 |
| `GET /api/tasks` | 最多 30 条目录/浏览器任务、共享 queue 与 inventory_root；任务带 kind；目录能力不依赖 Playwright 可用 |
| `GET /api/tasks/<task-id>` | 浏览器详情沿用原契约；目录详情在核验已提交回执及文件摘要后提供 report、artifact、artifact_path，不提供任意文件读取 |
| `POST /api/tasks/<task-id>/cancel` | 只接受空对象，可取消这两类已有任务；不能解除核心锁存 |
| `POST /api/tasks/queue` | 仅 `{paused:true|false}`，使用原队列暂停/继续语义 |

0.1.16 的 queue 增加 `resources` 只读快照：`waiting`、`reason`（memory_pressure / resource_recovering / resource_unavailable 或 null）、最近 `sample`（物理总量/可用量与 Host 可提交字节）、`capability`、`required_bytes`、`resume_threshold_bytes`、`foreground_reserve_bytes` 和 `checked_at`。无等待/采样时只有 waiting/reason/sample；不新增 Task 状态。具体阈值和恢复语义仅由[任务章](tasks-agents.md#queue-resource-admission)维护。

接纳仍返回 202；取消、幂等、队列满、版本不符、宿主交接及 UNKNOWN 状态沿用[队列语义](tasks-agents.md#browser-durable-queue)。任务产物路径是核验后的回执，不成为其他读取或执行接口的授权。

<a id="conversation-task-contract"></a>
### 0.1.31 会话任务接口

`cid` 为 32 位小写十六进制会话标识；`tid` 为 `task_` 加 32 位小写十六进制；请求编号为 `web-` 加 32 位小写十六进制。服务实现见[conversation_tasks.py](../runtime/node-host/jarvis_core/conversation_tasks.py)。所有接口继承本机 Host/Origin 边界及页面 nonce；POST 要求严格 JSON、同源 Origin，受理还需核心及 effect guard 就绪。取消保留核心已停止时的收口能力，不清除旧停止记录。

| 接口 | 输入及语义 |
|---|---|
| `POST /api/conversation-tasks/<cid>` | `{request_id,prompt,model?,relative_path?}`，字段限制沿用[固定报告契约](#sample-task-contract)；模式由宿主固定为 natural，未知字段拒绝。202 表示已持久受理，返回 task_id/request_id，不代表完成 |
| `GET /api/conversation-tasks/<cid>` | 从账本返回本会话最多 30 项 tasks（未完成优先、同组按最新记录排序）、原 queue 和 inventory_root；先过滤会话再截取 |
| `GET /api/conversation-tasks/<cid>/requests/<request_id>` | 仅查询本会话原编号是否受理；返回 task、action_status、error、kind 和 conversation_id；report=null、steps=[]，不据此断言产物有效；不存在时 404 |
| `GET /api/conversation-tasks/<cid>/<tid>` | 核对会话绑定后返回原任务详情及 conversation_id；已确认产物重新核验 |
| `POST /api/conversation-tasks/<cid>/<tid>/cancel` | 只接受 `{}`；仅取消已绑定任务，返回原任务详情及 conversation_id |
| `GET /api/conversation-tasks/<cid>/<tid>/artifact` | 只在已确认产物大小与摘要再次核对后返回原始 JSON 字节；最多既有产物 2 MiB 上限，不接受客户端路径，不重新生成 |

跨会话、无绑定或绑定其他工作流的详情/取消/下载返回 404。会话绑定参加原请求内容摘要，重复的同编号同参数返回原受理结果，改参或改绑冲突。归档中的编号仅用于定位，不能建立或修改账本关联。作用域、恢复和临时会话语义归[任务章](tasks-agents.md#conversation-task-runtime)。

<a id="sample-task-contract"></a>
### 0.1.30 自然语言样例报告接口

`POST /api/tasks` 增加严格模式 `{request_id,mode:"natural",prompt,model,relative_path}`。request_id 沿用 web-32 位十六进制；prompt 必填，非空且最多 1,024 UTF-8 字节；model 默认 auto，必须是已登记型号或 provider::model；relative_path 默认 `.`、最多 256 字符，必须在初始化样例根内，不能选绝对目录或改变根。未知字段在持久受理前拒绝。成功 202 返回 task_id/request_id，表示已保存至共用队列，不表示模型或执行已成功。

0.1.32 在内部 ChatService 使用 sample_report 规划用途及宿主选择的相对范围，禁止混入普通历史、附件、记忆与项目上下文。用途不是 HTTP 字段或执行授权。本地网关额外接收至多 8 KiB 的宿主 schema：只能输出给定范围的两步报告对象或 unsupported 对象，普通聊天及云端调用不携带该参数；实际结果仍必须通过下述完整计划校验，不因解码约束跳过检查。

候选计划唯一机器契约为 [sample-plan.schema.json](../contracts/schemas/sample-plan.schema.json)：支持时顶层 schema_version=1、kind=inventory_report，steps 恰为 sample_metadata_read 与 artifact_output；不支持则 kind=unsupported 与有界 reason。重复 JSON 字段、非有限数字、包装层、未知步骤、额外路径或格式字段拒绝。相对路径除 schema 形状校验外还须与宿主保存参数完全一致。模型不能选择执行器、预算、产物目录或代码。

`GET /api/tasks` 增加 kind=natural；详情沿用 task/action_status/error/artifact/artifact_path/report/has_screenshot，steps 包含 ordinal/state/plan_json/model_json/created_at。规划状态为 MODEL_REQUESTED、MODEL_UNRESOLVED、MODEL_FAILED、PLAN_REJECTED、PLAN_VALIDATED；计划 JSON 仅在通过校验时保存，拒绝时不展示原始模型正文。model_json 仅为状态、实际供应商/型号、请求 ID、数值用量、耗时与完成标志。它不代替唯一 Task/Action 终态。

成功 report 保留目录清单字段，并增加 kind=jarvis.sample-report、scope=sample-input、by_type[]（type/file_count/total_bytes）、verified、plan 与 model；verified 表示本次固定元数据、数量及字节分组的确定性校验通过，产物回执另外绑定完整字节摘要。它不是通用回答正确率证明。原浏览器专用列表/取消不接受该任务，统一查询/取消沿用 `/api/tasks`。规划和资源语义归[任务章](tasks-agents.md#sample-task-runtime)。

<a id="runtime-slots-contract"></a>
### 0.1.15 本机运行版本与临时目录契约

[releases.py](../runtime/node-host/jarvis_core/releases.py)是版本槽位与 `releases.db` 私有持久格式的唯一实现。包成员仍由 `release.json` 及[归档校验器](../tools/release_bundle.py)定义；版本标识绑定归档摘要，包安装后为 installed，独立健康检查后为 verified 或 failed。只有 verified 且即时完整性复核通过的槽位能被选择。

选择记录保存 active、previous 和递增 generation；修改选择与写入操作历史同事务提交。回退只交换运行代码指向，不覆盖、复制或降级业务数据。启动期间持有本机版本使用锁，选择/回退报告繁忙，不终止活跃服务。启动入口只支持 status、inventory、web，不接受任意 Shell 命令；具体使用归[核心章](core-bootstrap.md#runtime-package)。

0.1.17 增加 `start` 固定入口与私有 `starts(id,document)` 表。document 包含启动 ID、时间、模式、requested/selected、候选 attempts、版本、fallback、selection_committed、status 及终态 exit_code 或 error/message。状态为 checking → launching → exited，异常为 failed/interrupted；它独立于 Task/Action 状态。status 只显示最近 10 次，旧记录保留；失败候选不得触发业务任务。完整流程由[启动恢复规则](evolution-release.md#runtime-startup-policy)维护。

[browser_recovery.py](../runtime/node-host/jarvis_core/browser_recovery.py)维护独占临时目录登记：随机标识、目录身份、使用锁、命名 Job、驱动 PID 与启动阶段。此文件不是任务状态库，任务继续由原账本拥有。它不把 PID 当身份凭据、不按 PID 杀进程；回收只在使用锁释放、退出可确认且完整删除集合核查通过后执行。登记之前崩溃留下的不确定目录保留，不猜测删除。此私有元数据不进入聊天上下文或模型接口。

<a id="recovery-contract"></a>
### 0.1.14 旧版停止状态兼容消息

兼容迁移快照以 [recovery.schema.json](../contracts/schemas/recovery.schema.json) 为唯一机器定义，版本 `1.1.0`，kind 为 `jarvis.local-maintenance`。它只包含节点 ID、当前代际、排序且不重复的未解除事件 ID 和原因，由本机命令在内存中构造；不要求用户创建 JSON、密码、密钥、挑战或签名。额外字段、旧版本、空原因以及与数据库不匹配的节点/代际/事件集合均拒绝。成功后递增代际并记录审计，重复提交旧快照失效；这是一致性校验，不是身份认证。测试见 [test_control.py](../tests/test_control.py)。

安全语义归[当前停止与恢复实现](security-sovereignty.md#prototype-security)，CLI 选项与操作归[核心使用页](core-bootstrap.md#runtime-control)。业务库 v2 的任务另存安全代际，不改变 Task/Action 的 K0 外部格式；既有 v1 任务迁移时不被自动授予当前代际。恢复后需要新宿主和明确的新请求，不自动重放旧意图。

`GET /api/status` 另提供 `assistant_state`：`standby` 为无活动待命、`working` 为有在途聊天或正在运行的后台任务、`needs_attention` 为核心当前不可用；`active_chat_requests` 与 `active_tasks` 是本机进程观察到的数量。等待队列不计入运行数。`POST /api/chat/cancel` 只取消给定 `request_id`，不提供全局停止 HTTP 接口；产品状态显示规则归[生命周期](interaction-persona.md#personal-assistant-lifecycle)。

0.1.18 在健康和异常状态响应中均增加 `app="Jarvis"`、`version`、`instance_id`。实例标识是每次 Host 启动生成的 32 位小写十六进制随机值，用于托盘关联，不是密码、凭据或授权。托盘仅接受与启动参数一致的实例；不一致、超时或 HTTP 失败显示连接中断。桌面退出使用 `Local\Jarvis.Tray.<instance_id>.quit` 命名事件，关闭图标和就绪分别使用 `.close`、`.ready`；这些事件只在进程生命周期内存在，不写持久锁存，也不扩展网页可执行接口。

0.1.38 增加 `ui_assets`：`status` 为 `ready` 或 `degraded`，`unavailable` 为 `{asset, reason}` 列表；`asset` 仅含固定界面清单的相对文件名，`reason` 为 `missing / empty / unreadable`，不返回异常原文、绝对路径或文件正文。它与 `core_ready` 相互独立；界面资源降级不能伪造核心健康。具体降级行为归[界面资源隔离](health-maintenance.md#ui-asset-degradation)。

<a id="project-workspace-contract"></a>
### 0.1.11 项目与文本导出接口

字段校验与回执定义以 [workspace.py](../runtime/node-host/jarvis_core/workspace.py) 为准，传输层见 [server.py](../apps/web/server.py)。这是明确的用户界面导出协议，不是模型工具或另一个 Task 调度器；K0 冻结的六类 schema 与既有浏览器任务契约保持不变。

| HTTP 接口 | 输入与结果 |
|---|---|
| `GET /api/workspace/projects` | 最近项目，含稳定 ID、完整路径、目录身份是否仍有效；不枚举文件 |
| `POST /api/workspace/projects` | 严格 `{path}`：登记现有绝对目录；同一路径重复打开复用 ID，目录已被替换则拒绝 |
| `POST /api/workspace/pick-folder` | 严格空对象；调用一次本机目录选择器，取消不创建项目；最多一个选择器，120 秒退出 |
| `POST /api/workspace/outputs/prepare` | `{project_id, request_id, path?}`；ID 为 32 位小写十六进制。固定项目、最终路径及现存父目录身份，返回准备回执 |
| `POST /api/workspace/outputs/<request_id>` | 严格 `{content}`；只保存非空、无 NUL、至多 1 MiB 的 UTF-8 文本。保存端不接受另一个路径 |
| `GET /api/workspace/outputs` | 最近 50 项回执：请求/项目 ID、最终路径、状态、字节数、SHA-256、时间及错误分类；不返回内容 |

全部项目 GET/POST 要求原有 Host/Origin 检查与页面 nonce，POST 额外要求同源 Origin 和严格 JSON。路径受[项目保存边界](security-sovereignty.md#project-workspace-boundary)约束；保存内容的 JSON 体上限为 6 MiB + 1 KiB，用于容纳转义，解码后文本仍限 1 MiB；聊天附件的独立上限见[附件契约](#chat-attachments-contract)。

导出回执为 `PREPARED → WRITING → SAVED / FAILED / UNKNOWN`。写前持久化 WRITING，查询将未确认 WRITING 显示为 UNKNOWN，崩溃后不重放。成功时同步写入、校验实际文件大小和摘要后才返回 SAVED；数据库与用户目录不声称跨资源原子事务。原请求重送相同内容只验证原文件并返回原回执，改路径/项目/内容拒绝；失败或 UNKNOWN 需核对后明确另存，不自动换请求。准备阶段的路径错误不调用模型；模型失败只留下准备记录，不创建交付文件。该回执库属于界面项目/导出元数据，不承接后台执行或取代核心任务账本。

<a id="project-organization-contract"></a>
### 项目组织与可恢复归档接口（2026-10-17）

[project_catalog.py](../runtime/node-host/jarvis_core/project_catalog.py)独占管理 `project-catalog.db` v1，保存显示档案与聊天归档标记；不更改 workspace.db 的根目录/导出结构或 conversations.db 的正文协议。原有项目列表接口仍返回目录身份；前端按稳定 ID 合并组织数据，因此旧客户端可以继续读取原项目与聊天接口。

| 接口 | 严格输入 / 结果 |
|---|---|
| `GET /api/workspace/organization` | 返回 profiles（项目 ID → revision 与显示字段）、archived_chats（id/project_id）。只提供本机组织元数据 |
| `POST /api/workspace/projects/<id>/edit` | `{revision,document}`；document 严格含 name/description/pinned/section/removed。name 最多 120 字符，description 最多 2048 字符，section 最多 64 字符，后两种状态必须是布尔值。空名称回落到目录名；不接受根路径更改 |
| `POST /api/workspace/projects/<id>/archive` | `{archived,chat_ids}`；archived 为布尔值，ID 为不重复的 32 位小写十六进制，单次最多 500 个。每个 ID 都须属于目标项目且仍有有效聊天正文；全部核对后同事务更改标记 |
| `POST /api/workspace/projects/<id>/reveal` | 严格空对象；核对登记的根路径/目录身份后调用固定系统文件浏览器，参数独立传入，不使用 shell。返回 opened 只表示启动请求被接受，不证明系统窗口已呈现 |

修改档案采用预期 revision，成功递增；相同规范化内容和当前/前一修订的重试返回原成功版本，其他陈旧写入返回 `409 project_conflict`，不覆盖后来编辑。归档请求绑定明确 ID 快照，重复请求只影响同一批聊天，不能顺带归档后来新建会话；归档标记独立于会话正文修订。移除/恢复只是 removed 字段，不能通过该接口删除根目录、聊天正文或撤销资料外发范围。

最多沿用 200 个登记项目、32 个非空分区和 10,000 个归档标记。控制字符被拒绝，项目说明只允许换行/Tab；显示文字均作为文本处理。新存储拒绝未知版本、链接/重解析点与硬链接，写入沿用 effect_guard；HTTP 保留本机 Host/Origin、页面 nonce、严格 JSON 与原控制体积上限。此协议不承担共同体同步、任务执行或模型访问授权。实际交互归[项目管理](interaction-persona.md#project-management-ui)。

<a id="conversation-archive-contract"></a>
### 0.1.24 本机会话归档接口

字段校验与限额的代码权威为 [conversations.py](../runtime/node-host/jarvis_core/conversations.py)，页面串行保存客户端为 [conversations.js](../apps/web/conversations.js)。ID 使用 32 位小写十六进制；普通归档仅存 title、project_id、messages 与 context_note。消息只接受 user/assistant/error/stopped 的纯文本、调用说明和附件省略/回答不完整标记，不接受 system、工具权限、HTML 字段或附件载荷。0.1.31 起消息可包含布尔 task_control、task_ref（task_32 位小写十六进制）、task_request_id（web-32 位小写十六进制）；有编号时 task_control 必须为 true。这些可选字段兼容原归档，只表示文字类型和定位提示，不授予执行权；实际绑定仍按[会话任务契约](#conversation-task-contract)核对。

| 接口 | 作用 |
|---|---|
| `GET /api/conversations` | 最近更新顺序的归档元数据，不返回正文 |
| `GET /api/conversations/<id>` | 返回当前 revision 与结构化文字快照 |
| `POST /api/conversations/<id>` | `{revision, document}`：按预期版本原子保存；相同内容的最近一次重试可复用原回执 |
| `POST /api/conversations/<id>/delete` | `{revision}`：核对版本后清空正文并写删除标记；已删除 ID 禁止重新写入 |

GET 需要既有本机 Host/Origin 边界和页面 nonce；POST 另要求同源 Origin、严格 JSON、核心运行及 effect guard。不同页面的旧版本写入返回 409，不静默覆盖。每个会话最多 500 条消息、编码后 2 MiB，正文存量合计最多 64 MiB、500 个有效会话；达到上限明确返回错误，旧记录不自动截断。HTTP 归档体单独限制为 2 MiB + 64 KiB，不扩大聊天/其他控制请求的上限。

本接口不是任务账本或长期事实协议；删除对导出文件、计费用量和任务审计的影响及恢复限制归[知识章](knowledge-learning.md#local-chat-archive)。未发送草稿与附件不落盘；恢复时不把缺失附件的轮次伪装成完整模型上下文。UI 只在保存回执后标记成功，失败或冲突不触发模型重试。

<a id="explicit-memory-contract"></a>
### 0.1.25 明确事实记忆与聊天引用接口

字段唯一机器定义为 [memory-fact.schema.json](../contracts/schemas/memory-fact.schema.json)；实现为 [memory.py](../runtime/node-host/jarvis_core/memory.py)，不修改 K0 冻结的六份契约。事实正文只有 `title/content/project_id/providers`，返回 ID、递增 revision、时间及明确保存来源；ID 为 32 位小写十六进制，项目必须已登记。HTTP 沿用本机 Host/Origin、页面 nonce、严格 JSON 和核心 guard；普通控制请求体上限仍为 128 KiB。

| 接口 | 语义 |
|---|---|
| `GET /api/memory?project_id=…&q=…` | 列出通用与指定项目的有效事实；q 为最多 128 字符的字面片段。省略项目时只列通用记录；拒绝重复/未知查询参数 |
| `POST /api/memory/<id>` | `{revision,document}`；新增 revision 为 0，更新必须匹配当前修订。相同内容的最近重试返回原结果；冲突/已删除返回 409 |
| `POST /api/memory/<id>/delete` | `{revision}`；核对修订后清正文、写 tombstone 和无正文回执；重复删除幂等，未知 ID 返回 404 |
| `POST /api/chat` 的可选扩展 | `memory_context={enabled,project_id}` 与和 history 等长的 `history_memory` 引用数组。旧客户端省略时不装配事实；每个引用只有 id/revision，不接收事实正文或权限声明 |

事实最多 1,000 条有效记录、10,000 个累计 ID、20,000 条修订回执；达到上限拒绝新增/修改并提示，不自动淘汰。忘记仍可执行并留下回执，故回执不是不可突破的磁盘硬配额。名称最多 120 字符、正文 2,048 字符、允许接入方最多 16 个；空 providers 表示仅本地，不接受 auto 或通配授权。SQLite 使用当前正文、元数据修订回执及 secure_delete；这不是加密或备份擦除证明。

每次候选调用最多选 20 条完整事实、6,144 UTF-8 字节，并受所选模型剩余输入预算进一步限制；必要用户输入优先。`history_info.memory` 返回 enabled/provider/references/available/omitted/bytes 和 dropped_history_messages，不返回额外事实正文。references 包含本轮选取和历史继承的依赖，最多 100 条；历史依赖最多 80 条，其余预算留给本轮。此摘要属于聊天扩展，不改既有 context-report schema。

会话归档的消息新增可选 `memory_refs`（同一引用定义），兼容旧归档。ChatService 按实际候选接入方、项目和当前修订过滤引用链，按完整轮次排除失效历史，再做普通上下文预算装配。引用保守继承，预算后未实际使用的历史依赖也可能保留，允许多排除但不能放宽范围。失败显示可诊断结果；同页可关闭记忆继续聊天。临时会话、遗忘和传播边界归[知识章](knowledge-learning.md#explicit-memory-runtime)，验收归[验证章](delivery-validation.md#explicit-memory-evidence)。

<a id="personal-core-contract"></a>
### 0.1.39 个人指令与表达扩展

复用 `POST /api/chat`，新增可选 `personal_context={temporary:boolean}`，其中 temporary 必须为布尔；0.1.40 兼容增加的可选 source 仅用于[接续来源](#continuity-contract)；唯一运行校验与解析器为 [personal.py](../runtime/node-host/jarvis_core/personal.py)，正反例见 [test_personal_core.py](../tests/test_personal_core.py)。旧客户端省略该字段时不启用持久表达，个人指令拒绝读写；普通聊天保持兼容。临时模式在服务端关闭事实装配及持久表达，即使客户端同时传入启用记忆也不采用。它是本机应用模式约束，不是认证边界。

完整显式指令先由 Host 分流；存储模块独立于网关，不依赖可用模型配置。`X-Jarvis-Request` 的 32 位小写十六进制标识传入内部写入者，指令变更与回执在同一 SQLite 事务内提交，核心 effect_guard 串行化停止与写入。同一存储内重复请求标识/相同操作只返回原修订的回执，不返回可能已过时或遗忘的正文；同标识不同内容拒绝。当前 HTTP 进程的重复请求保护仍可先返回冲突，持久回执用于跨进程重放保护，不自动重试远端调用。

成功响应仍为 `status/text/provider/model/history_info`，其中 provider 为 `builtin`、model 为 `personal-core-v1`，额外 `personal` 回执有 `kind/committed`；变更带 `revision/replayed`，记忆变更另带 `action/id/project_id`，查询 `committed=false`。失败保留可诊断类别和 `personal.committed=false`。已提交本地变更不会因随后到达的取消信号伪装成未执行。已存在的记忆面板接口继续使用预期修订；聊天指令在一个事务内精确查找当前目标后写入，不把对话描述当作旧页面的 CAS 修订。

记忆库 v1 兼容增加 `chat_commands` 表，只保存请求标识、操作摘要和无正文回执，上限 20,000；达到上限后聊天变更拒绝，既有面板仍可管理和忘记。人格库 v1 保存一份当前配置、一份上一版和最多 10,000 个无自由正文的指令回执；达到上限拒绝变更，不静默淘汰重试保护。SQLite 大小随回执增长，这些逻辑上限不是整机磁盘硬配额；没有新增服务、第三方依赖或后台整理循环。

会话消息兼容增加布尔 `personal_control`；官方客户端在归档及恢复时标记并排除整条个人控制消息，避免查询正文通过历史再次外发。`history_info.persona` 返回 `applied` 和使用的 `revision/style/relationship`，不改既有 context-report schema。一般事实与派生回答仍执行原修订引用过滤；人为复制粘贴旧正文不受该引用机制保护。完整使用语法归[交互节](interaction-persona.md#personal-core-ui)，表达生效与回退规则归[人格运行范围](interaction-persona.md#persona-runtime)。

<a id="personal-profile-v2"></a>
### 0.1.62 交流配置、三库查询与接续推荐扩展

`GET /api/persona` 返回 `schema_version=2`、修订和当前 `style/relationship/preferred_name`。`POST /api/persona` 严格接受 `{action,revision,request_id,profile}`；action 为 profile、undo、reset，后两者 profile 必须为空。完整 profile 以一个事务保存，旧修订返回 409；同请求的原操作先返回原回执，不重复写入。接口独立于记忆模块的开关，仍核验 Host/Origin、页面 nonce 和核心写入约束。正文、错误与校验只在 [persona_routes.py](../apps/web/persona_routes.py) 和 [persona.py](../runtime/node-host/jarvis_core/persona.py) 实现。

称呼是最多 32 字符的字母/汉字、组合标记、数字及空格、间隔点、单引号或连字符；不允许换行或任意提示词。姓名属于表达配置，不能据此改写主体身份或授权。旧两字段配置与上一版读入时补空称呼，不在读取时写库；旧请求摘要仍可辨认。数据库仍为 v1，新 JSON 配置包含第三字段，**不兼容把已经写入新配置的数据直接交给严格两字段的旧 Host**；跨版本降级必须先验兼容性，不能删除新配置换取启动成功。

三库显式查询复用个人控制回执，`kind=reference/committed=false`，附带来源、版本、状态与派生索引状态；答复不交给云模型，官方客户端不把这类控制消息带入后续模型历史。范围与重建规则归[三库运行入口](knowledge-learning.md#seed-runtime-entry)。

`GET /api/continuity?q=…&provider=…&project_id=…` 返回最多 3 条词法相关的有效记录及分数，q 限 1—512 字符；逐条重验原来源、精确项目和接入方。无 q 继续使用原列表接口。推荐不等于选择、任务派发或模型推断；实际消息装配仍重新检查，原配额不变。

<a id="continuity-contract"></a>
### 0.1.40 接续记录与会话来源扩展

运行字段与校验的唯一实现为 [continuity.py](../runtime/node-host/jarvis_core/continuity.py)；管理载荷见 [continuity_routes.py](../apps/web/continuity_routes.py)，正反例见 [test_continuity.py](../tests/test_continuity.py)。沿用本机 Host/Origin、页面 nonce、严格 JSON、核心运行检查和写入 effect guard，不引入另一套任务协议或冻结种子变更。

| 入口 / 字段 | 契约 |
|---|---|
| `POST /api/chat` 的 `personal_context.source` | 保存/更新接续时必须提供 `{conversation_id,message_index}`；前者为 32 位小写十六进制 ID，后者为 0—499 整数。Host 核对原消息后生成来源摘要，不接受客户端声称的摘要 |
| `continuity_context` | `{enabled:boolean,ids:[id…]}`，最多 3 个唯一 ID；旧客户端省略时关闭，临时/未声明个人模式或关闭记忆时服务端强制关闭 |
| `history_continuity` | 与 history 等长，基本引用为 `id/revision` 数组；0.1.42 关联摘要扩展见[下节](#work-continuity-contract)，不接受客户端提供接续正文 |
| `history_info.continuity` | `references/bytes/omitted/issues/dropped_history_messages`；包含保留历史继承的依赖，问题分为缺失/越域、接入方未授权、来源改变/删除 |
| `GET /api/continuity?project_id=…` | 读取一个准确范围的有效记录；无参数为无项目范围。管理列表不逐条读原会话，也不意味着所有来源仍有效 |
| `POST /api/continuity/<id>` | `{action,revision,request_id,project_id}`；action 为 permissions / close / reopen / forget。仅 permissions 另需 providers。预期修订冲突为 409；重复同请求原操作回放回执，不能复活已忘正文 |
| 会话归档扩展 | 顶层可选 `continuity_ids`；消息可选 `continuity_refs`。旧文档仍可读取；个人控制消息继续使用 `personal_control` 排除模型历史 |

存储 v1：最多 200 条有效记录、累计 2,000 个 ID（含墓碑）、10,000 个操作回执；标题最多 120 字符、进展 2,048 字符、下一步 1,024 字符，接入方列表复用事实记忆许可定义。达到上限拒绝相应变更，不自动淘汰防重放记录；上限不是磁盘硬配额。schema 初始化与业务操作分开提交，使首次被拒绝的操作留下可读取空库；业务变更和无正文回执在同一事务提交，异常则回滚。未知版本或坏正文不覆盖、不用于模型。新版本兼容读取旧会话；降级到不认识 continuity_ids/continuity_refs 的旧 Host 仍需兼容适配，不能宣称任意旧版本直接读取新归档。

无任务关联时，一次最多核验三个来源会话，现有归档单份上限 2 MiB，所以归档正文读取上界为 6 MiB；只在本机核验。接续装配最多 4,096 字节，且不超过必需输入之外剩余预算的一半；优先完整记录，容不下的条目显式报告。已选择但全部不可用、或一条也放不下时，在模型派发前返回明确错误；不会把缺失上下文静默当成成功接续。

`personal.kind=continuity` 回执的 action 区分 save/update/view/resume/close/reopen/forget，变更带 id/revision/committed/replayed；查看与选择不是持久状态变更。管理接口还允许 permissions；0.1.42 的 link_work 见[关联契约](#work-continuity-contract)。完整语义见[接续数据](knowledge-learning.md#continuity-runtime)，不能用该回执授予执行权限。

<a id="personal-candidates-contract"></a>
### 本人消息候选整理接口（0.1.43 起，0.1.44 扩展）

唯一运行校验器为 [personal_candidates.py](../runtime/node-host/jarvis_core/personal_candidates.py)，正反例见 [test_personal_candidates.py](../tests/test_personal_candidates.py)和 [0.1.60 入口一致性测试](../tests/test_rule_memory_review.py)。各接口沿用 Host/Origin、页面 nonce、严格 JSON 和记忆接口大小限制；不接收模型生成的执行命令。

| 接口 | 严格输入与结果 |
|---|---|
| `POST /api/personal-candidates/suggest` | `{source,project_id}`；source 为原有 `{conversation_id,message_index}`，project_id 可 null。读取同范围普通本人消息，返回 engine、原输入、source_digest、source_text、candidates、`model_used:false,committed:false`；0.1.60 的事实候选另含 quote、classification，非空事实批次另有 preview_token |
| `POST /api/personal-candidates/confirm` | `{source,project_id,source_digest,candidate,scope}`，0.1.60 可选 preview_token；candidate 为 `{kind,title,content,next_step}`，可选 candidate_id，fact 可原样携带 quote/classification。新事实必须有有效预览；该兼容入口不接受修改来源元数据或分类。未结事项仍沿原路径。未知字段拒绝，返回原存储 receipt 和显示文字 |
| `POST /api/personal-candidates/rule-review` / `rule-resolve` | 0.1.60 新增；字段及事务语义与下述[公共核对契约](#memory-candidate-review-contract)一致，使用规则入口签发的 token，不能混用语义 token |

规则引擎标识 `personal-candidates-v1`；只分析不超过 800 字符的消息，按句切分，每句不超过 240 字符，最多返回 3 项。长输入没有截断后提取，source_text 的展示最多 800 字符。确认内容上限为 title 60、content 1024、next_step 512 字符，禁止 NUL；前两者非空，continuity 的下一步非空，fact 的下一步必须为空。候选类型必须与当前来源可提取类型一致，文本可由主人明确编辑。

scope 为 current / global；continuity 只接受 current，项目必须仍登记。确认重新验证来源 SHA-256；旧 confirm 的 UUID5 根据引擎标识与规范化 JSON 输入计算稳定请求 ID，剔除新增 candidate_id、quote、classification 和 preview_token，保留旧精确重试身份。改变内容或范围是新请求，候选事实还需通过[来源撤销检查](#memory-provenance-contract)，不新建确认数据库。

0.1.60 规则事实预览由 [candidate_tokens.py](../runtime/node-host/jarvis_core/candidate_tokens.py)签名，purpose 为 `rule-candidates-v1`，绑定来源、摘要、候选与全库修订水位；生成前后检查水位，有效期 20 分钟，重启失效。规则与语义服务分别持有进程内密钥；未结事项不增加事实 token。旧 confirm 缺少/过期 token 时只允许返回已存在的精确回执，新写入在原事务内返回 `candidate_review_required`（HTTP 409）；不会借兼容性复活遗忘记录。新确认默认个人偏好、主人主体、仅日常/本地使用；旧无分类记录不回填。改变分类改用 rule-review/resolve；明确“记住”命令仍是独立的主人直接指令。

continuity.db 仍为 schema 1，source 兼容增加可选 `owner_confirmed_candidate:true`，缺省沿用控制消息校验，false 或未知字段拒绝。该标志仅由内部确认路径设置，旧显式接口不能以普通消息冒充控制消息；读取时继续验证来源资格。新 Host 可读旧记录；旧 Host 不认识新字段，会拒绝新记录，回退前必须做兼容检查。完整数据语义归[候选整理](knowledge-learning.md#personal-candidates-runtime)，不承诺双向无条件降级。

<a id="semantic-candidates-contract"></a>
### 语义事实候选接口（0.1.50）

唯一运行校验器为 [semantic_candidates.py](../runtime/node-host/jarvis_core/semantic_candidates.py)；HTTP 接线在 [candidate_routes.py](../apps/web/candidate_routes.py)，复用既有 Host/Origin、页面 nonce、核心状态、请求大小、ChatRequests 及两个聊天并发槽。0.1.50 未改原[规则候选接口](#personal-candidates-contract)，后续 0.1.60 兼容变化见该节；内部 `ChatService` 增加 `memory_candidates` purpose，禁止继承历史、人格、技能或记忆输入，浏览器不能在普通聊天 JSON 中指定内部 purpose。

| 接口 | 严格字段与结果 |
|---|---|
| `POST /api/personal-candidates/semantic` | 必须且仅有 `{source,project_id,provider,model,reasoning,request_id}`。source 沿用会话 ID/消息位置；request_id 为 32 位小写十六进制；具体 provider/model 必填，不接受 auto；reasoning 可 null 或网关支持的档位。返回 engine、source、project_id、source_digest、source_text、candidates、result、`model_used:true,committed:false`；非空合格候选另有 preview_token |
| 模型候选 | 完整 JSON 对象 `candidates` 数组，最多 3 项；每项仅 `{segment,title,content,category,subject_label}`。category 为现有类型但不含 temporary_state；同句不重复。宿主验证句位、类型/主体、项目约束和内容长度，并生成原句、candidate_id、classification；不接受模型提供的权限、ID、工具或执行指令字段 |
| `POST /api/personal-candidates/semantic-confirm` | 必须且仅有 `{preview_token,candidate_id,title,content,classification,scope}`。scope 为 current/global；classification 使用[现有分类契约](#memory-domain-contract)，不能缺省或 null。返回原 MemoryStore receipt 和显示文字；模型类别不构成写入授权，主人编辑仍须通过原分类约束 |

输入最多 800 字符、32 个非空句子，不截断后发送；句界按 `。；;\n!?！？` 划分，每句最多一个候选。标题 60、内容 1024 字符；模型原始输出最多 16,384 UTF-8 字节，拒绝重复 JSON 字段、越界句位、未知字段和不完整输出。可解包**唯一且完整**的 JSON Markdown 围栏；不从解释性文字中搜索 JSON、不补齐截断对象。输出上限云端最多 1,024 tokens、本地最多 256 tokens，受原档案更小上限约束；不保证所有模型或最高思考档位在此预算内产生合格候选。

preview_token 是当前宿主随机密钥 HMAC-SHA256 签名的规范 JSON 预览，含来源摘要和候选，最多 32,768 字符、有效 20 分钟；签名用于绑定而非加密。宿主不持久化预览、不建立全局候选缓存，重启后旧 token 无效。确认按来源身份、摘要、目的范围及编辑后文档生成稳定 UUID5，归档追加修订不改变该回执。来源正文不写入事实库；分类与正文、来源绑定、确认回执一次提交，沿用 schema 3，不增加表或改变已有行。

**2026-10-18 修订屏障增量：**语义整理开始前只读 `receipts` 中 correct/forget 的累计数量，作为内部 `review_revision`；不读取事实正文，不向提取模型发送此值，不因空库预览新建数据库。有效候选返回前复核，签名预览绑定此值，确认写入在同一个 `BEGIN IMMEDIATE` 事务内再次比较。纠正、独立确认、用途/外发许可修改及遗忘均会改变水位；仅新增事实不改变，允许同批候选逐项保存。已完成请求先回放原回执，不重复写入；既有同源撤销保护仍优先执行。请求 JSON 与 schema 3 不变，没有新增持久表。

水位变化返回 `candidate_review_changed`：提取途中发生时返回 FAILED、空候选、无 token，保留本次用量；确认时返回 HTTP 409，事实、来源绑定与确认回执均不提交。签发前无法读修订也拒绝候选并保留调用回执，不自动重试模型。当前采用全库水位，其他项目的纠正也会使待确认语义预览过期，属于可解释的保守限制；它不是多库原子快照。此屏障仅覆盖运行中的语义整理与已经签发的语义预览；规则候选仍沿用原同源保护。遗忘后另开一次整理、从新消息提取同义内容仍不具备语义等价撤销，不能把这一增量称为跨消息永久遗忘或自动冲突合并。实测见[多轮与修订屏障证据](delivery-validation.md#memory-lifecycle-evidence)。

同一提取 request_id 的重复 HTTP 提交返回 409，不再次付费调用；当前控制注册表只保留进程内有界记录，**不保证重启或记录到期后的提取去重**。停止复用 `/api/chat/cancel`；HTTP 等待超时会请求取消，但直到工作线程结束才释放槽位，远端已接收请求可能仍计费。失败返回 result 状态/用量/有界错误，不回显任意模型原始正文；`model_used:true` 表示进入模型提取路径，是否真的派发及计费以 result.dispatch_admitted/usage/billing 为准。

0.1.52 增加有限来源边界错误：`candidate_subject_conflict`（明确扮演语句被归为现实主体）、`candidate_pending_work`（明确待执行计划被提为事实）、`candidate_scope_conflict`（明确项目选型被改归其他主体）。返回 `result.status=FAILED`、空 candidates、无 preview_token，保留已有用量，不自动重试或写入其他库；条件与保守限制见[运行语义](knowledge-learning.md#semantic-candidates-runtime)。原 JSON 字段、句位、签名、存储 schema 均不变。当前资格过滤不改变 v1 规则事实的兼容来源身份。

范围、句级身份与遗忘限制见[运行语义](knowledge-learning.md#semantic-candidates-runtime)，使用见[候选面板](interaction-persona.md#personal-candidates-ui)，验证见[证据](delivery-validation.md#semantic-candidates-evidence)。这不是完整插件 MemoryExtractor 或自动记忆写入接口。

<a id="memory-candidate-review-contract"></a>
### 规则与语义事实候选的本地核对与显式处理（0.1.58—0.1.60）

**implemented / 局部 verified。** 0.1.58 接通语义入口；0.1.60 将规则事实接入同一 [memory_comparison.py](../runtime/node-host/jarvis_core/memory_comparison.py) 与 [memory_review.py](../runtime/node-host/jarvis_core/memory_review.py)，事务写入仍只在 MemoryStore。没有引入新模型、常驻进程、库依赖或数据库 schema。历史见[原核对证据](delivery-validation.md#memory-candidate-review-evidence)，新入口及部署范围见[规则入口证据](delivery-validation.md#rule-memory-review-evidence)。

| 接口 | 严格字段与结果 |
|---|---|
| `POST /api/personal-candidates/semantic-review` | 与 semantic-confirm 相同的六个字段，核对编辑后的内容与范围；返回 `matches,total_matches,truncated,source_unusable,method,model_used:false,committed:false,review_token,note`。每个 match 含旧事实 ID、修订、document、provenance、relation、reason；最多五条 |
| `POST /api/personal-candidates/semantic-resolve` | 必须且仅有 `{review_token,decision,target_id}`。decision 为 new / keep / replace；new 的 target_id 必须 null，其他只能选择本次 token 列出的 ID。返回原事实回执及文字，不接受客户端附加正文或权限 |
| `POST /api/personal-candidates/rule-review` / `rule-resolve` | 分别与上述 review / resolve 相同字段和结果；规则 review 的六字段为 `{preview_token,candidate_id,title,content,classification,scope}`，必须有明确分类；只接受规则服务签名，原规则候选 ID 不变化 |

比较只读目标**精确项目范围**中的记录，不自动把通用与项目合并。已分类记录须 kind、subject、subject_label 相同。`duplicate` 指正文经 NFKC、空白、末尾标点及有限主人称谓规范化后一致；不把相似度直接当等价。有限饮品/回答风格/姓名主题、同名或字符二元组重合可提示 `possible_change`、`possible_addition`、`related`，不是通用矛盾推理器。未分类记录只在原正文完全相同时提示 `unclassified`，不自动补分类。来源失效或未核查记录不作为处理目标，另报数量；有效期仍沿用旧记录，核对不自动使过期事实生效。

review_token 复用对应服务 HMAC，但 purpose 为 `memory-review-v1`，绑定编辑后文档、原来源、旧事实 ID/修订/摘要/关系及原预览的 review_revision；有效期不得超过原预览。只能用对应入口的原始预览 token 重新核对，不能借核对刷新过期或跨越纠正/遗忘水位。签名前后均校验水位；只读核对不创建空事实库，也不把已有记忆发给模型。

| 决定 | 同一事务中的效果 |
|---|---|
| new | 保存新的本地默认事实和来源；若核对后又出现同范围、同主体的有效重复事实，返回 `candidate_duplicate`，防止比较与提交之间的重复写入；同名冲突仍拒绝，另存应使用不同名称 |
| keep | 仅允许 duplicate / unclassified；不改原事实正文、修订、来源、用途或接入方许可。将新候选来源绑定到原 ID，并保存幂等回执，后续纠正/遗忘能抑制这一来源；不声称增加了完整多来源证据图 |
| replace | 仅允许同类型、同主体且并非重复/未分类的目标；替换内容及当前来源，保留原 ID、名称、分类、用途、有效期和 providers。增加修订、抑制原候选绑定；旧正文不复制进修订回执，依赖旧修订的历史依原机制失效 |

提交在原 `BEGIN IMMEDIATE` 内重新检查来源、全库纠正/遗忘水位、目标修订/摘要和旧来源可用性；失败不提交事实、来源绑定或回执。`candidate_target_changed`、`candidate_duplicate` 与 `candidate_review_changed` 返回 HTTP 409。resolve 精确重试先返回原已提交回执，即使之后已纠正或忘记也不再次执行；过期 token 则不能作为 resolve 重试凭据。请求身份包含编辑文档、来源、决定及旧目标快照。旧 semantic-confirm 和规则 confirm 保留有效重复检查；后者旧回执兼容例外见[规则接口](#personal-candidates-contract)。两个入口共用规则不等于通用语义去重已经完成。

另补针对实测 P24 的有限来源保护：整条消息各句均只是纠正助手猜测、没有检测到新的一人称断言时，semantic 返回成功空候选、`model_used:false` 和 notice；不发模型请求。混合消息仍可提取其他句子，但模型把被标记的纠错句做成事实时以 `candidate_correction_only` 拒绝整批并保留实际用量。此检查不修改已有错误记忆，不保证识别所有语言或混合转述，也不改变来源身份。原单条提取对照结果不因增加此检查而重新评分。

<a id="memory-provenance-contract"></a>
### 候选事实来源与数据库迁移（0.1.44）

唯一来源对象定义为 [memory-fact.schema.json](../contracts/schemas/memory-fact.schema.json) 的 candidate_source。对象只由确认路径构造并复核，不接受面板写入时伪造 source 字段。suggest 返回每项 candidate_id；confirm 将其与原规则候选比对。旧客户端缺少标识时，仅在原候选唯一或原文本精确匹配时兼容，歧义的编辑要求刷新；candidate_id 不代替原消息摘要和范围检查。

`memory.db` user_version 从 1 事务迁移到 2，原 facts、receipts、chat_commands 内容保留；增加 fact_origins 主来源元数据与 candidate_bindings 去重/撤销映射。事实、来源、绑定和新请求回执在同一事务中提交，失败一并回滚；来源会话仍在原 conversations.db，不声称跨库原子提交。绑定身份取来源会话/消息位置/来源项目及原候选标识，不使用编辑后的预览文本、目的范围或引擎版本作为原候选身份。

事实列表增加 provenance，状态为 independent / current / source_changed_or_missing / unchecked；原文只在本机管理视图有界返回。上下文和历史过滤重新核对有效来源与事实修订，模型请求不携带管理视图中的原文片段。一次来源核对最多 32 个归档，以累计序列化 8 MiB 为放行预算，单条原文展示最多 800 字符；读入当前归档后若超预算，该归档不放行且不继续读取。单份归档仍受既有 2 MiB 存储限制；解析、重序列化和最后一份越额归档会占额外瞬时内存，8 MiB 不是进程内存上限。多个事实共用同一归档读取，完整归档用后释放。

原写入接口兼容可选 `reaffirm_source:true`，仅用于已有事实；在期望修订上独立确认来源，递增修订；同内容、同请求修订的响应丢失重试不重复递增。更改事实正文/标题/范围或明确修改指令也解除旧来源依赖；仅更新 provider 不解除。来源绑定总数上限为 20,000，不自动清理撤销记录；达到上限拒绝新绑定，已有事实仍可忘记。

新 Host 可读并迁移旧库；旧 Host 只接受 schema 1，会拒绝 schema 2，不能直接回退旧二进制继续写入。发布前保存受控数据库恢复材料；后续降级必须保留新纠正和撤销记录并经过迁移验证，不能恢复旧快照使遗忘失效。未识别版本保持拒绝，不通过降低版本号绕过检查。当前补齐的是单机规则候选事实；完整 Extractor 格式、知识编纂、语义等价撤销与复制仍为 proposed。

<a id="memory-domain-contract"></a>
### 事实分类、用途与兼容接口（0.1.47）

唯一机器定义仍为 [memory-fact.schema.json](../contracts/schemas/memory-fact.schema.json)。`document.classification` 可选，包含 `kind/subject/subject_label/uses/expires_at`；允许值和长度由 schema 定义，类型与主体一致性、项目绑定、临时状态必须到期、虚构角色只保存由 [memory_policy.py](../runtime/node-host/jarvis_core/memory_policy.py)执行。`expires_at` 为 null 或合法 UTC `YYYY-MM-DDTHH:MM:SSZ`，本地界面负责时区转换。完整使用语义只在[知识章](knowledge-learning.md#memory-domain-runtime)维护。

现有 `memory_context` 增加可选 `purpose=personal_chat/work_assist`；省略时按当前/联合项目推导。返回的 memory 与 MemoryView 报告携带实际 purpose；不在客户端或模型生成的资料中读取授权。新增字段不改变 knowledge_context、continuity 或历史原文的规则。其他用途严格拒绝，不提供尚未实现的对外上下文 API。

`GET /api/memory` 返回 `schema_version=3`、`capabilities=[fact_classification,owner_facing_purpose]`；各事实返回 `usage.state=legacy/active/expired/stored_only/invalid` 和分类投影。这不是来源有效性判断，来源仍看 provenance。新界面发现旧 Host 缺少能力标记时禁止分类写入并提示重启，避免静态资源已更新而旧代码忽略用途。分类筛选在本地面板中进行，列表不因到期隐藏事实。

数据库首次打开事务升级 `user_version=3`，不改写已有行、摘要、ID、修订、墓碑或回执，不新增表/索引。schema 1/2 可迁入；旧 Host 不支持 3，应拒绝打开，不能通过调低 user_version 绕过。发布前使用 SQLite backup 保存恢复材料；发生后续修改/遗忘后，不能直接恢复旧快照。分类写入与正文同一事务/同一修订；旧编辑器漏传 classification 时服务端保留已有值，显式 null 无效。原请求幂等、冲突、遗忘与来源限制继续生效；详细验证见[验收](delivery-validation.md#memory-domain-evidence)。

<a id="work-continuity-contract"></a>
### 0.1.42 接续与执行账本关联

字段校验唯一维护于 [continuity.py](../runtime/node-host/jarvis_core/continuity.py)和[work_state.py](../runtime/node-host/jarvis_core/work_state.py)，不修改冻结种子。以下为上一节的兼容增量：

| 字段 / 接口 | 当前约束 |
|---|---|
| 接续 document 可选 `work_refs` | 最多 3 个 `{kind,id,conversation_id}`；kind 仅 task/growth，id 分别为 `task_32hex` / `32hex`，conversation_id 为 `32hex`；同 kind/id 不重复 |
| `POST /api/continuity/{id}` | 新增 action=`link_work`，严格接收 `{action,revision,request_id,project_id,work_refs}`；空列表解除关联。与原动作共用修订冲突、同请求幂等及事务；无法核验或越域的新关联拒绝 |
| `GET /api/continuity/{id}/work?project_id=…` | 原同源/nonce/核心检查；返回 revision、来源会话最多 30 个普通任务和 30 个成长单引用 choices，以及已关联项 observed；无 project_id 表示无项目范围。不会写账本或触发恢复 |
| 装配中的 `linked_work` | checked_at 与 items；每项有 kind/id/conversation_id、state、label、artifact_verified；可用时附 raw_status、机器 error_code、result_digest，普通任务另附 action_status |
| `history_continuity` / `continuity_refs` | 保留 id/revision；有任务关联的回答增加可选 `work_digest`，为 64 位小写 SHA-256。专用校验兼容旧引用，拒绝未知字段；整轮历史须同时匹配修订与观察摘要 |

已选接续仍最多 3 条、完整装配仍最多 4,096 字节；因此每轮最多读取 9 个关联对象。关联来源可与接续原消息来自同项目的不同会话；请求内共用归档缓存，最多 12 个不同来源会话、原始归档读取上界 24 MiB（单份 2 MiB）。通常同一来源只读一次；这不是 Python 常驻内存指标。管理候选列表只读标识，不批量检查 60 个产物；当前关联最多核对 3 项。成长库以只读 SQLite 打开，文件/侧车沿用 32 MiB 检查，单任务 JSON 上限 1 MiB；普通产物继续受原任务上限与校验控制。

存储仍为 continuity.db schema 1，可选 work_refs 不改变表结构；旧记录无需迁移。新 Host 兼容旧记录和引用；旧 Host 不认识 work_refs/work_digest 时会拒绝对应新记录/归档，因此降级需兼容检查，不能直接忽略新字段。更新接续文字保留关联，解除只改引用；完整状态与隐私语义仅维护于[关联运行语义](knowledge-learning.md#work-continuity-runtime)。

<a id="project-knowledge-contract"></a>
### 0.1.26 项目文档登记、检索和来源引用

唯一字段定义为 [project-knowledge.schema.json](../contracts/schemas/project-knowledge.schema.json)，实现为 [knowledge.py](../runtime/node-host/jarvis_core/knowledge.py)。独立于事实与会话库，不改 K0 冻结契约；沿用本机 Host/Origin、页面 nonce、严格 JSON 和核心运行检查。登记写入使用 effect guard 与乐观修订。

| 接口 | 作用 |
|---|---|
| `GET /api/knowledge?project_id=…` | 列出指定项目的有效登记元数据；不读文件正文，拒绝重复或未知查询参数 |
| `POST /api/knowledge/<id>` | `{revision,document}`；document 为 project_id/path/providers。新增 revision=0；更新只改外发范围，禁止旧 ID 改绑路径或项目。相同内容最近重试幂等，重复路径/旧修订冲突返回 409 |
| `POST /api/knowledge/<id>/delete` | `{revision}`；清路径/项目/接入方字段，留 ID tombstone；不删除原文件。迟到保存不能恢复旧 ID |
| `POST /api/knowledge/search` | `{project_id,query}`；只在本机读取登记文件并返回匹配引用、预算省略和不可用原因；不调用模型 |
| `POST /api/knowledge/read` | `{project_id,reference,start_line,end_line}`；核对登记及文件摘要后返回当前摘录。来源撤出、修订或内容改变返回过期，不返回旧缓存 |
| `POST /api/chat` 可选扩展 | `knowledge_context={enabled,project_id}` 和与 history 等长的 `history_knowledge`。引用只有 id/revision/digest；正文从当前项目登记读取。旧客户端省略时不读取项目文件 |

每项目最多 32 份有效来源，累计最多 10,000 个登记 ID；每个文件最多 256 KiB，单次快照总读取预算 4 MiB。新文件读取前预留一份最大文件的余量，可能在尚有少量预算时提前停止。读取与切分分别使用 3 秒协作期限，单文档最多处理 256 段、总计 2,048 段；不能声称这是 OS 强制文件 I/O 超时。查询前 512 字符提取至多 128 个词项；本机 search 请求本身最多 512 字符。

上下文最多 6 段、8,192 UTF-8 字节，只选完整段落，不截断为伪完整证据。每段按标题或 40 行/约 1,400 字符切分，单独的长行保留完整并可能因预算被省略。查看摘录最多 40 行、8,192 字节。输入及会话要求优先；有项目快照时事实记忆先取最多可用预算的三分之一且不超过 2,048 字节，其余用于项目摘录，最后按完整轮次补历史；没有项目快照沿用原事实预算。

`history_info.knowledge` 包含 enabled/references/citations/matches/omitted/bytes/issues/read_bytes/dropped_history_messages。citations 含标签、reference、路径、标题和起止行，0.1.33 兼容增加来源项目 ID/名称；references 为本轮与历史继承的依赖，最多 32 个。聊天归档消息新增可选 `knowledge_refs` / `knowledge_citations`，兼容旧记录，不保存额外摘录正文。记忆过滤与资料过滤的索引映射回原始 history，既有 context-report 契约不变。引用链仍是当前客户端的应用约束，不能证明同用户恶意客户端无法自行粘贴旧资料。

文件、项目、外发及旧历史失效语义归[项目文档检索](knowledge-learning.md#project-retrieval-runtime)，文件读取边界归[安全章](security-sovereignty.md#project-knowledge-boundary)，证据归[验收章](delivery-validation.md#project-knowledge-evidence)。

<a id="chat-attachments-contract"></a>
### 0.1.21 聊天附件接口

`POST /api/chat` 保留 `message/provider/history/model/reasoning`，增加可选 `attachments` 数组；不传附件的旧客户端继续有效。`history` 的 user 消息可含同名数组，assistant 不可含附件。仅接受两种严格对象：文本 `{kind: "text", name, text}`；图片 `{kind: "image", name, media_type, data}`，data 为无前缀标准 Base64，仅允许 PNG/JPEG/WebP。name 是展示名，禁止路径分隔符和控制字符；不接受文件路径、远端 URL、工具角色或任意字段。服务端复查类型、编码、文件签名及大小，不能只依赖网页校验。

聊天 JSON 体上限 12 MiB；其他控制接口保留原有 128 KiB（文本导出与[会话归档](#conversation-archive-contract)各有独立上限）。每条最多 8 个附件，文本单个最多 48 KiB UTF-8；正文加展开后的文本附件最多 64 KiB。传入历史最多 20 条、32 KiB 展开文本；整个请求（含历史）最多 8 张图片、8 MiB 原始图片字节，单张最多 4 MiB。核心再按所选模型预算裁剪旧轮次，不将图片 Base64 误算为文字 token，也不忽略附件正文的输入占用。

原生网关按接入方转换为 Responses input_image、Gemini inlineData、Anthropic image/source 或兼容聊天 image_url 的 data URL。能力未知或纯文本模型拒绝图片请求，自动路由跳过不兼容候选。日志仅保留完整请求摘要与数字计费信息，不保存附件正文或图片。对话的内存保存和恢复行为归[输入交互](interaction-persona.md#composer-attachments)。

<a id="chat-completion-contract"></a>
### 聊天完成状态字段（0.1.21）

`POST /api/chat` 的结果增加 `output_incomplete` 布尔值和 `completion_reason`（`complete / unspecified / length / provider_incomplete`）。`SUCCEEDED` 表示取得可显示正文，不表示正文一定完整；调用者必须同时检查 `output_incomplete`。明确无正文且未完整结束时返回 `FAILED`、`error_category=response_incomplete`；已发生的数值用量仍保留。未确定的传输结果继续使用 UNKNOWN。字段未给出时旧客户端兼容行为不变；当前网页保存和浏览器执行采用[完整性规则](models-offline.md#runtime-chat-context)。

宿主能力说明由 ChatService 构造，不开放客户端 `instructions` / system 历史字段；计入实际提供商文本输入预算。此字段不是长期记忆或工具授权接口。

<a id="chat-cancel-contract"></a>
### 0.1.12 单次聊天取消接口

0.1.12 的网页 `POST /api/chat` 采用文本 JSON（0.1.21 的扩展见[附件契约](#chat-attachments-contract)），新增可选头 `X-Jarvis-Request`（32 位小写十六进制随机 ID）；旧客户端不传该头仍可聊天。`POST /api/chat/cancel` 严格接受 `{request_id}`，要求原 Host、Origin、nonce 校验；只设置该 ID 的取消信号，不能提交全局停止、恢复或浏览器任务参数。取消接口不依赖核心仍处于运行状态。

返回 `CANCEL_REQUESTED` 仅证明服务收到信号，`FINISHED` 表示该请求处理已结束；两者都不能证明远端已撤销计费。取消先于聊天 POST 到达时保留取消标记，随后同 ID 不调用模型；重复聊天 ID 返回 409，不自动创建第二次生成。进程内最多保存 256 个控制句柄；未开始/已结束记录 10 分钟后可回收，正在处理的记录不淘汰。服务重启即失效，没有增加持久会话或另一套 Task 账本。

传输层将事件交给 ChatService 与模型网关，取消后屏蔽回复；调用槽位要等真实处理线程退出才释放。前端用每次生成独立的 AbortController 和运行标识隔离迟到回调；停止等待不等于撤销已发送的文件写入。协议实现见 [server.py](../apps/web/server.py)，网关状态及认证/远端限制归[模型调用边界](models-offline.md#section-896f72aed9a9)。

<a id="resource-usage-contract"></a>
### 设置总览资源快照接口（2026-10-16 增量）

`GET /api/resources` 为固定、只读的本机接口，无查询参数。遵循现有 Host/Origin 校验并要求页面 `X-Jarvis-Nonce`，不引入用户密码或额外登录。返回 `scope: "machine"`、UTC `sampled_at`、`refreshing`、`stale`、`age_seconds`、`cpu_percent`、`gpu_percent`、`memory` 与 `adapters`；未知值为 `null`，适配器未知时为空数组。`memory` 包含 `used_bytes/total_bytes/percent`；适配器记录包含 LUID `id`、`name`、`dedicated_total_bytes/shared_total_bytes`、可用时的 `dedicated_used_bytes/shared_used_bytes`。容量以字节传输，前端转换 GiB。此接口不枚举进程清单、不返回命令行、凭据或对话；0.1.34 的已知进程计数扩展见[并行指标](#parallel-runtime-contract)。

调用立即返回已有缓存或初始未知值，并按需触发单次采样；`refreshing` 只表示采样在途，不是助手正在执行用户任务。`sampled_at` 为空或 `stale` 为真时界面不得展示缓存百分比为当前值。口径与缓存生命周期唯一规则见[整机资源统计](health-maintenance.md#machine-resource-usage)。

<a id="parallel-runtime-contract"></a>
### 并行运行指标接口（0.1.34）

沿用 `GET /api/resources` 的固定路径、nonce/Origin 与只读边界。兼容增加 processes[] 和 runtime，不接受 URL 指定进程、采样命令或指标写入，不返回 PID/命令行。processes 只有本次采到的 host/local_model；每项 name/status/cpu_percent/working_set_bytes/private_bytes，失败数值为 null。它们与 machine 的 sampled_at/stale 共用有效性口径。

runtime 含 scope=host_lifetime、started_at/uptime_seconds、sample_capacity=200、overlap_seconds、counters、lanes、limits、queue。limits 为 chat_slots=2/task_slots=1；lanes.chat/task 含 active、oldest_active_ms、duration/queue_wait（samples/p50_ms/p95_ms/max_ms）及窗口内 outcomes。counters 的 chat_started/chat_finished/task_started/task_finished/chat_busy/http_wait_timeout/chat_thread_failed 是本次启动累计值，未发生的键可省略。没有样本的分位值为 null，不能当作 0ms。

queue 为原队列的 paused/owned/waiting/capacity/error/resources，加 running 数量及 unreviewed_unknown 布尔；模块未接入时为 null，读取失败为 unavailable=true。`GET /api/tasks` 的 queue 兼容增加 unreviewed_unknown，不改变动作状态或恢复权限。runtime 不持久化，也不承担任务真相或模型答案验收。计时、采样范围、CPU 分母与重启语义唯一维护于[观测规则](health-maintenance.md#parallel-runtime-monitoring)。

<a id="deterministic-calculation-contract"></a>
### 精确计算聊天回执（0.1.37）

沿用 `POST /api/chat` 与既有输入白名单、Origin/nonce、请求槽和取消机制；不增加调用者可写的计算标志、表达式字段或工具权限。命中[计算分流规则](models-offline.md#deterministic-calculation-runtime)时，成功响应含 `provider="builtin"`、`model="exact-rational-v1"`、`attempts=[]`、`outcome_uncertain=false` 及可选 `calculation`，不记供应商用量。普通模型响应不要求此字段。

`calculation` 的唯一机器定义为 [calculation.schema.json](../contracts/schemas/calculation.schema.json)：版本、引擎、规范化表达式、精确分子/分母字符串、显示值、保留位数/舍入方式、运算次数、`model_used=false` 和规范 JSON 的 SHA-256。摘要不包含 digest 自身，不是签名。`history_info.calculation` 说明引擎、未调用模型及未使用历史；页面据此呈现来源与上下文说明。当前会话归档保存正文和已有展示元数据，不另建计算日志，也不宣称已持久保存完整机器回执。

失败采用原 `FAILED` 响应：`error_category=calculation_failed`，`error` 区分除零、预算或格式等原因，条件冲突的 `error=calculation_context_conflict`；不会回退调用模型。HTTP 处理通道生成成功计算结果时，使本次宿主 `runtime.counters.calculation_completed` 加一，模块卡片复用它；计数不代表客户端已签收。直接 Python/CLI 调用不进入该计数，重启清零。算式限制和错误含义只在模型章维护。

<a id="model-admin-contract"></a>
### 模型后台配置与统计接口（0.1.19）

当前本机 HTTP 接口的配置请求机器定义为 [model-admin.schema.json](../contracts/schemas/model-admin.schema.json)，版本 `1.0.0`；[Registry](../adapters/models/provider-native/jarvis_models/registry.py) 强制 schema、按操作字段白名单、关联 ID 与有效模型档案验证。测试的正反请求见 [test_model_admin.py](../tests/test_model_admin.py)，不改变 K0 冻结契约。

| 接口 | 作用与边界 |
|---|---|
| `GET /api/admin/config` | revision、连接、模型、价格和脱敏 Key 元数据；不解密后回传完整 Key |
| `POST /api/admin/config` | 带 revision 的 `add_connection/connection/add_key/key/model` 命令；旧版本冲突不写入，凭据异常不覆盖原配置 |
| `GET /api/admin/usage` | `start/end/provider/model/key_id/offset`；拒绝重复或未知查询字段，同一快照聚合与 50 条分页 |
| `POST /api/admin/balance` | 只接受 connection；仅 Eachlabs 显式账户余额读取，无自动重试，不作每 Key 余额相加 |

读写后台 API 都要求当前页面 nonce；写入另要求同源 Origin。复用 loopback Host 校验、严格 JSON、131072 字节边界和无请求内容日志，不增加登录密码。错误只回传本地可展示的校验文案，远端错误体与凭据不透出。浏览器任务支持 `connection::model` 明确选择同名模型的线路；原有唯一模型 ID 仍兼容。计费快照与未知结果的语义由[模型章](models-offline.md#model-admin-config)唯一维护。

<a id="application-network-contract"></a>
### 0.1.63 应用网络控制接口

`GET /api/network` 返回 `offline/revision/updated_at/valid/scope/process_guard` 与当前允许/阻止能力摘要。`POST /api/network` 只接受 `{ "offline": true|false, "revision": 非负整数 }`；成功返回提交后的同一快照。字段、类型及修订校验由 [NetworkPolicy](../runtime/node-host/jarvis_core/network_policy.py) 唯一执行，测试见 [test_network_policy.py](../tests/test_network_policy.py)。读写要求当前页面 nonce，写入要求同源 Origin，沿用本机 Host 和停止状态检查。

错误语义：无效输入 400 `network_request_invalid`；陈旧修订 409 `network_conflict`；开启时存在活动作业 409 `network_busy`；不可读/损坏策略 503 `network_policy_unavailable`。读取异常时快照为 `offline=true, valid=false, revision=null`，界面禁用修改并保留刷新入口；不以默认在线覆盖损坏配置。网络请求分发另用 `network_offline/network_policy_changed` 标识阻断，不视作供应商故障、不触发云端备选。

浏览器超时不能判断写入是否完成，必须 GET 核对，不自动重复 POST。持久范围、子进程限制、本地例外与回退兼容唯一规则见[模型与离线章](models-offline.md#application-offline-control)。

<a id="module-monitor-contract"></a>
### 0.1.22 模块观察与维护接口

[modules.py](../runtime/node-host/jarvis_core/modules.py)拥有观察快照与维护回执；[运行槽位契约](#runtime-slots-contract)继续独占候选内容、验证结果及选择事务。观察器当前对明确的宿主账本表作只读投影，不另建任务或模型状态真源；后续表结构变更必须同步投影测试。它不是未来完整模块注册/热替换协议的实现。

| 入口 | 输入与结果 |
|---|---|
| `GET /api/modules` | 无参数；返回缓存，不等待采集完成 |
| `POST /api/modules/refresh` | 只接受 `{}`；请求后台刷新，仍立即返回缓存 |
| `POST /api/modules/maintenance` | 202 表示已受理，结果以维护记录为准；严格拒绝未知字段 |

三者均要求本机 Host 与本实例 `X-Jarvis-Nonce`；POST 另要求一致 Origin 和 JSON，维护还检查核心未停止。观察不授予执行权限，也不清除停止状态。

快照字段：`version/observed_at/refreshing/stale/poll_seconds`；`modules[]` 包含 `id/name/installed/enabled/health/activity/active/recent_uses/last_used/version/message/update_mode`。安装/启用可为 null（未知），次数可为 null（不适用）；`health` 为 ready/unavailable/offline/unknown/not_implemented，`activity` 为 running/busy/standby/unused/on_demand/service_online/offline/not_integrated/unknown，`update_mode` 为 bundled/configuration/external/planned。`releases` 只投影最近 40 个候选的 id/version/state/created_at 和 active/previous，不返回包内文件、健康 stdout 或凭据。active 指下次运行包启动选择，不代表当前源码进程。

0.1.28 在原快照中增量增加 `catalog`：状态 ready/unavailable、运行版本、种子版本、来源/摘要、knowledge/rules/capabilities/skills、privacy=local_only、chat_callable=false 和说明。首次采集中允许缺少 catalog；校验失败时正文与条目数组为空，页面依旧根据 observed_at/stale 呈现缓存时效。能力状态为 available/conditional/internal/planned/unavailable，分别表示本机状态入口、执行前需检查、宿主内部能力、未实现以及当前核心不可用；不能直接作为派发许可。规则字段只是历史基线说明，`rules_enforced_by=host_policy` 标明实际执行仍归宿主。

0.1.37 兼容增加 `count_scope`：`recent_records` 沿原有限记录计数，`host_lifetime` 为本次宿主成功计算次数，`catalog` 为目录中的完整用户技能数量。`recent_uses` 是保留的数值字段名；客户端必须按 scope 显示“次”或“项”，不能把目录容量显示为调用次数。未知/缺少 scope 的旧客户端沿原记录口径。

事实、资料、MCP 登记和技能登记条目增加 `storage_state/record_count/records_label/last_changed`；存储状态为 not_created 或 ready，读取失败沿用 health=unknown 且不返回旧数量。数量仅统计至多 1,000 条非删除记录，last_changed 是观察到的这些记录中的最近修改时间；不等同于最近调用，recent_uses 和 last_used 保持 null。观察查询不读取任何记录正文、文件路径、命令、端点或凭据。字段用途与限制见[模块页](health-maintenance.md#module-monitoring)。

运行包维护输入四种：`{action:"install",archive:<本机绝对 ZIP 路径>}`、`{action:"health",release_id:<release-24位小写十六进制>}`、`{action:"select",release_id:...}`、`{action:"rollback"}`。0.1.32 增加 `{action:"local-start"}` 和 `{action:"local-stop"}`，不接受模型路径、命令、参数、强制停止或下载开关；仍共用严格校验、nonce/Origin、核心检查与单项维护通道。local-llm 条目可包含 runtime={owned,state,pid}，state 为 stopped/starting/running/failed，pid 仅在本实例持有进程时出现。该状态来自进程句柄，不把其他端口服务当成本实例拥有。回执含 id/action/status/started_at/finished_at/release_id/message，状态 RUNNING/SUCCEEDED/FAILED/UNKNOWN；`maintenance_busy` 表示独立维护通道占用。失败不暴露原始异常正文；本地生命周期错误只显示宿主定义的说明。`module-maintenance.json` 仅保留最近 20 项，不记录 ZIP 路径或 Key；回执不确定时核对槽位登记，绝不自动重复外部动作。

<a id="cosyvoice3-contract"></a>
### 独立 CosyVoice3 文件语音接口

实现归 [speech.py](../runtime/node-host/jarvis_core/speech.py)，输入校验归 [speech_contract.py](../runtime/node-host/jarvis_core/speech_contract.py)。这是局部文件 TTS，不是实时语音/身份认证协议；模型选择和安装只在[组件运行页](models-offline.md#cosyvoice3-runtime)维护。

| 入口 | 输入与结果 |
|---|---|
| `GET /api/speech` | 不加载模型；返回 installed/state/owned/pid/device/threads/memory/load/busy/job/uses 等本实例状态 |
| `POST /api/speech` | `{action:"start"}`、`{action:"stop"}`，或受限合成请求；202 表示操作受理，最终结果看 job；不接受源代码、模型路径、命令、下载或云端开关 |
| `GET /api/speech/audio/{id}` | id 为 32 位小写十六进制，只读取组件音频目录中的对应 WAV；不存在或超过大小限制时拒绝 |

均复用本机 Host 和本实例 `X-Jarvis-Nonce`；POST 还检查 Origin、JSON 和核心运行状态。加载和合成各自进入同一条语音通道，一次一项；停止可打断该通道。聊天与原任务队列不占该通道。语音回执状态为 RUNNING/SUCCEEDED/FAILED/CANCELLED，进程状态为 stopped/loading/ready/busy/failed；状态和最近一次回执仅在本次宿主内存中维护，重启不恢复或自动重放。

合成字段为 `action=synthesize`、`text`、`mode`、`emotion`、可选 `reference_audio` 和 `reference_text`，拒绝未知字段。文字 1—300 字；模式 clone/instruct/cross_lingual；表达 neutral/happy/sad/angry/soft/slow/fast，非 instruct 模式只接受 neutral。参考录音为 base64 编码 PCM16 WAV，单/双声道、8—48kHz、1—15 秒、至多 3,000,000 字节，完整 JSON 请求至多 4,010,000 字节；参考文字至多 500 字，上传自定义声音并选择 clone 时必填。未上传时使用固定发布方演示参考音频，不自动采集麦克风、登记身份或读取任意路径。参考录音本身的授权来源由使用者选择，不把“可上传”当作声音权利核验。

输出为 24kHz PCM16 WAV，单次至多 60 秒；生成超过边界或 300 秒请求超时会失败并回收本次受管语音进程。Windows Job 只持有本实例创建的进程；停止递增内部代次，丢弃旧代次的迟到回执。操作进行时检查核心控制状态；核心停止或宿主退出触发组件回收，不清除停止锁存。成功合成的 uses 是本次启动计数，不是长期账本；没有以此宣称无限并发或硬实时停止上界。

上传参考音频仅保存为本机随机临时文件，操作结束清理；清理异常在回执中给出 cleanup_notice，不悄悄写入长期声纹库。生成 WAV 保留在本机组件输出目录，由有 nonce 的请求取得；浏览器通过受检请求转为 blob 播放/下载，不把 nonce 放进 URL。进程工作集、峰值工作集、私有提交和峰值提交分列；读不到时为 null，不能按零处理。first_internal_chunk_seconds 是后端第一块音频产生时间，不是浏览器首播时延。

<a id="qwen-tts-contract"></a>
### 独立主力 Qwen 语音接口

实现为 [QwenSpeechService](../runtime/node-host/jarvis_core/qwen_speech.py)、[原生协议读取](../runtime/node-host/jarvis_core/qwen_protocol.py)和[组件 Worker](../adapters/speech/qwen/worker.py)。复用[语音生命周期、同源 nonce 与回执语义](#cosyvoice3-contract)，使用独立操作通道、音频目录与使用次数；`GET/POST /api/speech/primary`，`GET /api/speech/primary/audio/{id}`。音频编号不能跨组件读文件。

start/stop 只接受 action；synthesize 接受 action、text 和可选 voice（默认 serena）、emotion（neutral）、language（zh）、direction（空，最多 120 字的表达提示）。预设枚举以[输入契约](../runtime/node-host/jarvis_core/qwen_speech_contract.py)为唯一来源，由 GET capabilities 提供给界面。文本 1–180 字；不接受内部 instructions 字段、路径、设备切换或参考音频。角色 primary、auto_start=false；不会自动启动备用或云端。当前交付方式 complete_wav。

整段表达提示、可组合标签、分段预览与合成规则只在[分层表达接口](#speech-expression-score)维护。`emotion` 保留为初始表达选项；结果字段的第一段 emotion 只表示其情绪维度，完整次序以 expression 与 segments 为准。

启动前核验 GGUF 与运行库大小/摘要，至少 4 GiB 可用 RAM/提交余量；固定原生协议 3。独立 Python broker 与原生推理子进程均归本次 Windows Job 所有，ready 分别核对 broker PID 和原生 inference_pid 的 Job 成员身份；停止、超时或失败回收本次 Job，不杀同名外部进程。ready 后仍检查原生进程归属；原生异常退出令 broker 退出。重启不复用旧健康回执或重放取消请求。Job 是生命周期边界，不是网络/推理安全沙箱。

原生 JSONL 分片必须同一 id、连续 seq、有效 PCM16；输出最多 20 秒、24kHz 单声道。终止必须 stop=complete 且样本数吻合，截断、超限或损坏不交付成功 WAV。请求 60 秒、启动 120 秒上限；临时音频原子发布。first_pcm_seconds 是原生第一分片，页面仍收到完整 WAV，不能标作扬声器首声。

GET 的 pid/memory 指原生推理进程，broker_pid/broker_memory 另列。gpu_memory 是同一原生 PID 的 Windows PDH 专用/共享分配，没有读数为 null/状态原因；不是设备容量、硬上限或物理总和。只对本次 Job PID 采样，停机关闭计数器。主力面板可见且忙时约 150ms、已加载待命时约 2 秒、未加载时约 8 秒观察，离开页面停止。使用归[组件运行](models-offline.md#qwen-tts-runtime)，证据归[验收](delivery-validation.md#qwen-tts-integration-evidence)。

<a id="speech-expression-score"></a>
#### 分层表达、分段预览与语音合成

**0.1.43 工作树增量，替代此前“只能一个句首标签”的限制。** 模型仍为同一份 Qwen CustomVoice；新增纯文本表达计划和 PCM 组合，不新增模型、依赖或常驻服务。自然语言提示依赖原生 instructions，分段标签是 Jarvis 语法，并非模型原生特殊 token。[S217](references.md#s217)、[S218](references.md#s218)

| 控制 | 当前规则 |
|---|---|
| 默认表达 emotion | 初始化情绪、说话方式或语速中的对应维度；界面称“默认表达”，不再把整段锁死为单一控制 |
| 表达提示 direction | 最多 120 字，不朗读；整段或所有分段均传给模型，可描述重音、起伏、前后语气变化。保持整句合成通常更连贯，不保证模型逐词严格服从 |
| 情绪标签 | `[开心]`、`[悲伤]`、`[生气]` 等更新情绪维度，持续至下一次修改 |
| 说话方式/语速 | `[轻声]` 与 `[慢速]`/`[快速]` 分别更新说话方式和语速，能够叠加；如默认慢速再加 `[轻声]` 会同时保留两者 |
| 重置 | `[语速正常]` 仅恢复语速；`[正常语气]` 仅移除轻声；`[自然]` 清除三维控制并恢复自然语气/正常语速，保留全局 direction |
| 显式停顿 | `[停顿350ms]` 或 `[pause=350ms]` 插入对应长度的 PCM 静音，不朗读，不清除当前表达；单次 50–1000ms，总计最多 3000ms |
| 分段与限额 | 全部原始 text 含标签合计最多 180 字，最多 8 个有声片段；连续相同控制会合并，避免无谓推理。总音频仍最多 20 秒，包含静音 |

中英文别名的完整集合以[输入契约](../runtime/node-host/jarvis_core/qwen_speech_contract.py)的 EMOTION_TAGS 为唯一来源，由 capabilities 暴露；方括号和中文括号保留为语法。未知/不完整标签、无正文的末尾控制、无效停顿或超限返回 400，不派发推理、不停止已就绪组件。仍不支持 SSML 或 `[laugh]`/`[cry]` 等非语言事件。建议在标点后切换；在词语中间切分会给预览警告，但不冒充自动断句或通用韵律分析。

**预览：**同一端点 POST action=preview，其他字段同 synthesize，返回 200 与 preview；无须已安装或加载模型，不创建语音目录、不调用 LLM。仍需同源 nonce 与运行态控制，不放大权限。preview 含分段文本、三维状态、表达标签、总停顿及警告，不含内部 instructions。界面显示“预览表达分段”，编辑后失效；迟到的预览不覆盖新草稿。

**执行：**同一原生 Worker 串行合成各有声片段，保持所选 voice/language 与每段 seed=42；每段使用独立协议编号，仍核对连续分片与完整终止。相同配置不能当作音色一致或采样结果逐字/逐位相同的保证。显式静音精确插入；多段连接仅对每段两端各 5ms 做淡入淡出，不自动裁剪音节、强行时间拉伸或承诺无缝。表达提示与标签对应固定指令按顺序组合；应用保证请求状态，不能保证模型的声学表达严格满足全部描述。

所有片段共用一次 60 秒请求期限和 20 秒音频预算，预留后续静音，不能每段各占完整上限。全部片段成功后才原子发布一份 WAV；任何后段失败、超限或取消都不交付部分成功，不重放任务。使用同一份模型驻留，分段越多可能增加合成耗时和边界感。

结果 segments 返回每个语音/停顿的 start_sample/end_sample 与秒数、已应用控制和正文；speech_segments、pause_ms、direction、warnings 与按次序保留的 expression 辅助核对。界面称“应用表达”，不是由声学识别器证明的实际情绪。播放仍等待完整 WAV；首 PCM、文件可用、扬声器起音和完整语音聊天延迟分开。真实 A/B/C、听感偏好和未验证项见[分层表达证据](delivery-validation.md#speech-expression-evidence)。

<a id="chat-readout-contract"></a>
#### 聊天回复的有界朗读通道

**0.1.45 工作树增量。** [readout.py](../runtime/node-host/jarvis_core/readout.py) 对现有 Qwen 组件增加一个短期朗读占用，不复制模型、人格、记忆、后台任务队列或常驻服务。页面、状态、音频及写入沿已有同源 nonce 边界；重新连接后使用更新的页面 nonce。输入准备只解析文字，不执行代码、不抓取链接、不调用云端模型。

| 接口/操作 | 规则 |
|---|---|
| `POST /api/speech/readout`，`action=start` | 客户端预先生成 32 位小写十六进制 `id`，附 text、voice、emotion、language、direction；仅显式开始才加载主力模型。相同编号与准备后相同内容返回原回执；内容冲突、已结束编号或其他占用拒绝，不重新推理 |
| 同端点，`action=next` | 附 id 与从 0 开始的整数 index；依序启动一个短段，重复 index 只返回原回执。模型加载中返回状态，不能跳号或并行合成 |
| `GET /api/speech/readout/{id}` | 返回 active、model_state、total 和已派发 items；成功项沿原主力音频路由提供完整 WAV。网络结果不确定时先查原编号，不换编号重放 |
| `action=finish` | 只有全部短段合成成功且组件空闲时释放占用，保留已就绪模型 |
| `action=stop` | 只取消相同 id 的朗读；迟到的旧 stop 不停止新朗读。stop 先于迟到 start 到达时记录取消回执，阻止该 start 复活。加载/合成中回收所属组件，空闲时保留模型 |

原始回复最多 16,000 字；清洗后含标签最多 1,800 字，最多 24 个请求。跳过围栏代码和网址，保留链接说明、图片替代文字与已知表达标签；未知方括号注释转为普通文字。复用[表达计划](#speech-expression-score)，最多 8 个表达片段，正文按标点/空白优先拆成每段最多 80 字，传递情绪、轻声、语速、停顿、固定音色和全局提示。每个实际合成请求仍遵守原 180 字、60 秒请求和 20 秒音频上限；过长、过多或模型失败明确报错，不交付虚构完成。

浏览器最多保留当前段加下一段两份 WAV blob，逐段合成、真实 Audio 播放并在结束/停止时释放 blob。不是原生 PCM 到扬声器的流式协议，也不承诺段间完全无缝。暂停保留播放位置，生成最多预取下一段；快速重复重新朗读采用最新请求，切换会话丢弃迟到音频。朗读租期为最近有效操作后的 180 秒，后续观察/操作懒检查过期；没有额外定时守护进程。页面关闭的停止请求是尽力送达，未送达时由期限与原有合成上限收敛，没有自动恢复播放。

占用期间拒绝设置页的加载/合成等变更，但纯表达预览继续可用；设置页显式全局停止会取消占用。原有设置合成正在执行时，朗读不得抢占。保留最近 8 个结束编号的小型回执；模型重启不恢复朗读。ZipVoice 与 CosyVoice3 不因此启动，也不静默转云端。文字归档不新增朗读字段；已生成的 WAV 沿本机原有音频目录保留，包括临时会话，尚无新增自动回收策略。交互见[回复朗读](interaction-persona.md#chat-readout-ui)，证据见[联测](delivery-validation.md#chat-readout-evidence)。

<a id="fast-speech-contract"></a>
### 独立快速本地语音接口

实现为 [fast_speech.py](../runtime/node-host/jarvis_core/fast_speech.py) 与 [ZipVoice worker](../adapters/speech/zipvoice/worker.py)，复用[已有语音生命周期与鉴权语义](#cosyvoice3-contract)，但使用独立进程、音频目录、操作通道和使用次数。接口为 `GET/POST /api/speech/fast` 和 `GET /api/speech/fast/audio/{id}`；读取另一组件相同编号不会跨目录返回音频，缺失音频返回 404。

合成字段沿用前节，**只接受 mode=clone、emotion=neutral、文字 1—180 字**，默认发布方参考声音；自选参考仍需准确文字并沿 PCM16 边界。固定 4 步、CPU 推理，接口不接受改变步数、任意模型路径、情绪指令或云端路由参数。请求时限为 30 秒，超时回收本次快速组件，不转慢速模型、不重放聊天或后台动作；输出仍为最多 60 秒的 24kHz PCM16 WAV。更换模型不代表已经接通麦克风或聊天自动播报。

当前角色为 fallback，auto_start=false；只在手动请求时加载，不因打开页面或聊天自动启动。界面仅快速组件操作进行且页面可见时约 150ms 读取完成状态，待命约 8 秒、离开页面停止；CosyVoice3 操作仍用其较低频率。click_to_blob_seconds 只计生成按钮到浏览器取得可播放文件，既不是扬声器首声也不是全链路会话延迟。选型与安装在[组件运行页](models-offline.md#fast-speech-runtime)，结果在[验收页](delivery-validation.md#fast-speech-evidence)维护。

<a id="memory-provider-contracts"></a>
## 记忆组件的替换契约（proposed）

下表定义边界，不是已实现的 API；K2 实施时在 `contracts/schemas/` 固定机器定义，避免各框架的私有对象成为跨模块格式。内容语义由[记忆设计](knowledge-learning.md#memory-selection-design)维护，复制语义由[共同体页](federation.md#memory-replication)维护。

| 组件 | 输入与输出 | 不可越过的边界 |
|---|---|---|
| MemoryStore | 原始资料引用、候选事实、修订/撤销关系；返回持久 ID、提交版本和证据 | 唯一事实写入入口；验证来源、作用域、授权及幂等；不让 Worker 或向量库直接决定有效事实 |
| MemoryExtractor | 已授权片段、角色与任务域；返回带来源片段定位的候选事实/摘要 | 模型推断和助手陈述必须标出；无来源、结构错误或不确定输出可拒绝，不能默认晋升 |
| Retriever | 查询、不可放宽的身份/域/版本/时间过滤、预算；返回证据引用、分数类型、索引水位和缺失范围 | 支持关键词、向量、图等实现；返回前重新检查有效性，过期索引不能绕过遗忘或撤权 |
| EmbeddingProvider | 固定模型配置、query/document 用途、文本批次；返回向量及空间标识 | 拒绝维度或空间不匹配；云端处理另行遵循既有数据授权，不能在离线失败后静默外发 |
| SyncTransport | 已授权且版本兼容的事件/对象及缺失范围；返回持久接收游标 | 传输不裁决事实真伪，不授予动作执行权；断线重放须幂等 |
| MemoryViewResolver | 主人、任务与已授权资源范围；返回本次允许的记忆视图 | 应用侧计算范围；模型提出的 project / persona / world ID 不是授权依据 |
| KnowledgeCompiler | 指定项目、源版本、变更集合和资源预算；返回来源明确的候选知识/文档 patch | 不直接修改 MemoryStore、规则或任务表；生成完成不等于知识真实或文档已发布 |

共同记录至少需要：稳定对象 ID、来源与内容摘要、节点及节点实例代次、事件序号与因果前驱、事实有效时间与系统记录时间、修订/撤销关系、现实或模拟域、主体/分享范围、保留策略与证据状态。时间字段不能替代因果关系；来源签名证明发送方，不证明内容真实。

索引版本由源资料修订、切片器/分词器版本、嵌入模型与权重修订、维度、归一化、池化、query/document 前缀和量化配置共同标识。相同维度不代表相同向量空间。检索回执还需标明事实提交水位、已索引水位及结果覆盖范围，不能只返回一段没有来源的自然语言。

记忆事件及其 outbox 在记忆存储的同一事务中持久化，接收端 inbox 去重与事实应用同样原子提交。它们与 `control.db` 的任务/动作事务彼此独立，跨域靠稳定引用与对账；不声称跨数据库的普通写入天然原子。接口升级需提供导出、导入、重放、拒绝不兼容版本和删除传播的兼容证据。

<a id="memory-extractor-adapter"></a>
### 开源提取器、编纂器与路由的适配要求（proposed）

用于 LangMem、Mem0 或其他候选实现；以下完整插件契约仍是拟定语义要求。0.1.50 先实现了独立的[最小语义提取基线](#semantic-candidates-contract)，不等于已安装这些框架；既有[规则候选契约](#personal-candidates-contract)继续工作，插件不能绕过主人确认和事实库校验。

2026-10-18 新增 **实验工具范围的 LangMem 适配子集**：[父进程适配器](../tools/memory_lab/langmem_bridge.py)调用独立环境的[单次 Worker](../tools/memory_lab/langmem_worker.py)。输入仍先经过本人消息、临时会话、来源版本和不保存/凭据排除检查；输出重新经过原 `SemanticCandidates` 的句位、类别、主体、项目范围校验。框架只接收分句内容和 `has_project`，不接收库路径、密钥、项目真实标识、已有全库事实或确认权限。适配器真实运行 `create_memory_manager`，使用候选批次 schema，关闭更新/删除、存储、embedding 与追踪；`max_steps=1`、Trustcall `max_attempts=1`，父进程另限制每例最多一次网关请求、60 秒模型期限和 90 秒协作期限。取消和异常退出回收实验进程，已发生的用量及 UNKNOWN 保留。

框架实际产生的消息和工具 schema 经管道交回父进程，再通过现有模型网关与核心准入检查发送；当前网关用**文本 JSON 模拟工具回执**，没有新增 SDK 直连或复制上游私有函数。这是受 Jarvis 规则约束的提取实验，不是完整 LangMem 默认配置，也未实现下表全部插件语义。子进程清除继承的供应商/代理/追踪环境变量，安装 Python 网络和子进程审计拒绝；这只能防误用，**不是操作系统安全沙箱**。依赖固定文件、运行测量和复跑方式见[影子对照证据](delivery-validation.md#memory-langmem-shadow-evidence)。生产启动不导入此模块，当前工作台也不把它列为可选提取器。

同日新增 **Mem0 2.2.1 实验子集**：[适配器](../tools/memory_lab/mem0_bridge.py)与[独立 Worker](../tools/memory_lab/mem0_worker.py)使用公开 `Memory.from_config`、`add(infer=True)`、`get_all`、`update`、`delete`、`history`，不复制私有提取函数。每例独立 Qdrant 本地目录与 SQLite 历史；结束后先回收进程再删除临时库。`candidate` 模式让原生 `memory[].text` 承载候选 JSON，再经原来源、分类、项目和修订屏障校验；`sequence` 模式仅用于合成多轮行为观察，其显式更新/删除无权改变 Jarvis 正式事实。二者均不是生产自动建档入口。

Mem0 配置使用受支持的 OpenAI 兼容接口，实际 SDK 只连接 Worker 自己的临时回环端口，使用随机本地令牌；模型消息经管道、序列化文本传输和原网关发送，真实供应商凭据不进入 Worker。原生长提示不通过放宽正式网关的指令上限接入。每个 `add` 至多一次实际模型调用，SDK HTTP 重试关闭；单例候选最多一次、序列最多六次，取消/超时/UNKNOWN 不自动补发；错误 JSON 必须报告失败，不能让 SDK 的宽松解析把错误计为成功弃答。嵌入是本地 256 维字符 n-gram 哈希向量，只用于空库候选和每域不超过十条事实的穷举式小场景，**不作为语义检索质量证据**。遥测关闭，数值库线程限制为一；Python 审计只允许该回环端口，其他网络及子进程拒绝，仍不是 OS 权限隔离。安装、费用、资源与实际边界见[Mem0 实验记录](delivery-validation.md#memory-mem0-shadow-evidence)。

| 边界 | 适配器必须提供什么 |
|---|---|
| 输入快照 | 稳定作业与输入版本、允许的来源集合、说话者/来源类型、作用域、允许的目的 provider、已有相关事实修订、调用/字节/时间预算；只给相关片段，不默认导出全库 |
| 候选结果 | 候选类别、内容、原文或工具回执定位、派生依赖、有效时间、保留理由、冲突/替代建议及提取实现版本；找不到来源或无法确定时返回不足，不能伪造定位 |
| 写入校验 | 应用重新验证作用域、来源是否仍在当前版本及删除/纠正状态；模型输出的 ID、置信度和建议动作不能直接授权写入；向量相似度不作为真实性概率 |
| 幂等与失效 | 区分同一请求重试与更换算法后重新分析；候选必须关联输入修订与提取代次。确认、忽略、撤销和过期结果可对账；被遗忘来源的旧作业不得重新生效 |
| 完成回执 | 分别报告已接受、待确认、忽略、冲突、失效、失败以及实际模型用量；模型生成完毕不等于持久提交成功，失败不能静默丢失待处理输入 |
| 退出和替换 | 可取消，有超时；导出通用候选及来源，不把上游私有对象作为唯一格式。关闭插件后明确事实与既有资料读取仍可运行，实验数据可按其作用域清理 |

提取和知识编纂共用既有模型网关，按任务设置首选、备选、档位与费用预算；每次备选切换重新检查输入外发范围。规则过滤、事实读取和词法检索无需 LLM；语义检索单独经过 EmbeddingProvider。**LLM 任务路由与 embedding 空间管理分工，不新增两个互相绕过策略的云网关。** embedding 不可用时退回词法或等待；换模型须建新索引代次，不能把新模型向量写进旧空间。已准备的离线模型可用则本地处理，否则保留待整理状态，不为完成后台任务自动上传私人内容。

Wiki patch 还需包含所依据的源版本和目标章节版本；发布时源或目标已变化则重新分析/合并，不覆盖用户新修改。插件的自动提示优化、技能生成、联网学习和调度功能默认不由“接入记忆”一并启用；涉及这些能力时仍使用对应模块的既有契约。

<a id="memory-view-runtime-contract"></a>
### 联合知识视图运行契约（0.1.33）

既有 memory_context / knowledge_context 保留必填 enabled/project_id，增加可选 project_ids，机器定义见 [memory-fact schema](../contracts/schemas/memory-fact.schema.json) 与 [project-knowledge schema](../contracts/schemas/project-knowledge.schema.json)。省略时仍只取当前项目；提供时最多 4 个唯一、已登记 ID，非空当前 project_id 必须在集合内。两个来源开关分别生效，页面将相同项目集合交给两者；通用事实独立于项目存在。不接受 all_projects、模型自定域或正文权限断言。

新增 `POST /api/knowledge/view`：严格输入 `{project_id,project_ids,query,memory_enabled}`，采用既有 nonce/Origin/核心状态检查。仅本机预览，返回 view/memory/knowledge/facts，不调用模型。query 最多 512 字符，预览上下文预算 14,336 UTF-8 字节；facts 只含本次选中的当前记录。聊天则在 `history_info.memory_view` 返回 schema_version=1、实际 provider、两类 project_ids、bytes/max_bytes、retrieval=lexical、snapshot_atomic=false 和逐项目 coverage；coverage.status 为 matched/partial/no_evidence，表示本次文档摘录覆盖，不代表事实完整性或语义正确性。

所有项目共用原[检索预算](#project-knowledge-contract)，不按项目倍增：快照最多 32 份成功读取的文档；跨项目轮流读取，合计最多 4 MiB、2,048 段，读取与切分各有 3 秒协作期限。最终仍最多 6 段/8,192 字节；事实预算和必要输入优先顺序保持原规则。整条事实/段落装不下时省略并报告，不截断正文。事实候选在 SQL 读取层按项目和 provider 过滤；文档在打开文件前按目的地过滤，读取后再次检查登记修订与撤出。

citation 兼容增加 project_id/project_name；新引用与会话归档保留原项目定位，旧引用缺字段时继续用会话项目。refs 的 ID/revision/digest 格式不变。每次实际模型尝试都重建视图和历史资格，上一供应商允许的摘录不自动传给下一供应商。语义与非原子边界只在[联合视图运行规则](knowledge-learning.md#memory-view-runtime)维护；下节完整生产契约仍为 proposed。

<a id="memory-view-contract"></a>
### MemoryView 与知识候选的必要语义（proposed）

这是完整生产目标；当前仅实现[0.1.33 有界联合视图](#memory-view-runtime-contract)，不能将其等同于完整域、时态与冲突契约。实施时建立独立 schema、兼容版本与正反例；字段以机器定义为准。

| 对象 | 需要携带的语义 | 失败行为 |
|---|---|---|
| ScopeContext | owner / task / session 引用、允许的 project 集合、现实或 world 域、persona 配置引用、消费 Agent/工具、查询用途、处理 provider、输出读者/渠道、策略版本 | 未知项目或域不自动扩为全库；更换消费者、用途或目的地重新解析；模型不能自行授予资格 |
| MemoryRecord | 主体 ID 与说话者、信息类别、事实内容或原件引用、适用条件、有效/记录时间、证据类型与状态、修订、分享/外部处理/输出许可引用、来源依赖 | 未知范围保持待归类；缺省不自动共享。密钥不进入普通正文，转述/假设/推断不得伪装核验事实 |
| MemoryView | 本次范围与用途、背景偏好、项目目录引用、选定证据与源修订/策略版本、冲突、事实/索引水位、覆盖范围、字节或 token 预算 | 只返回满足当前使用及输出资格的内容；不足时返回 missing / stale / conflict，不伪造完整性；输出阶段不继承另一用途的完整历史 |
| SharedProjection | 原依赖 ID/修订、分享决定与策略版本、获准的输出字段或片段、目标用途/范围、有效期、晋升状态 | 生成摘要或改标签不扩大许可；依赖变化则复核/重建，无法证明目标范围资格时不放行 |
| KnowledgeCandidate | 源资源 ID/版本、Claim 或摘要、证据类型/说话者、建议作用域、依赖列表、产物状态、编纂器版本、目标章节 | 模型不能自签 verified；源版本变化、缺证据、越域时拒绝晋升或进入待复核 |
| ProjectReference | 全局稳定项目 ID、节点本地位置映射、文档 ID/锚点、提交/工作区版本 | 路径失效只报告无法定位，不能自动扩大扫描到全盘；本机盘符不作为全局 ID |

MemoryView 只授权本次读取与装配，不授予工具执行权限。实际 provider 变化时重新计算 external_processing；将两个项目联合检索不修改它们永久的分享策略。知识候选的来源链包含派生输入，不能只留下摘要而失去限制的继承关系。具体用途与自然交互语义只在[记忆作用域](knowledge-learning.md#memory-scope-model)维护。

切片/事实中的每个来源定位都属于宿主允许的输入集合；多来源混合片段不能因为其中一句可见而返回全文。查询、出站提示、向量化、检索结果与最终产物分别执行当前用途检查。视图缓存键至少关联范围、用途、消费者/实际 provider、输出受众、策略版本及所用依赖修订；旧缓存不能沿用到另一个 Agent、项目、角色或读者。撤销/纠正先使派生视图不再合格，再执行可延后的物理清理；期间返回缺口，不从旧摘要补回内容。

上述 MemoryRecord / SharedProjection 是拟定接口语义；0.1.47 的[事实分类子集](#memory-domain-contract)、0.1.50 的[按需语义候选](#semantic-candidates-contract)和既有 fact_origins 不等于完整依赖图或此权限模型。更广的自动提取与完整受众隔离落地前，先冻结相应字段与正反例；相关组合验收归[个人与工作防串用](delivery-validation.md#memory-domain-validation)，不得只给适配器加一个 category 字段就宣布完成。

<a id="context-assembly-contract"></a>
## 上下文编排：当前装配与后续压缩

这是 `dialogue` 内 ContextAssembler 的语义边界，来自[源码对照](stack-project-layout.md#grok-context-memory-tradeoffs)发现的缺口。0.1.23 已实现下述临时聊天装配子集；任务/记忆引用、自动摘要和完整 K2 工具循环仍为 proposed。

<a id="context-assembly-current"></a>
### 0.1.23 已实现的临时聊天上下文

`POST /api/chat` 增加可选 `context_note` 文本，最多 8192 UTF-8 字节；旧客户端不传时继续使用原接口。内容是用户填写的会话要求，与本轮消息一起进入 **user 输入**，不会变成 system 规则或执行权限。每次请求重新读取字段，修改/清空从下次生效，上下文装配器不自行建立服务端会话状态；0.1.24 的[文字归档](#conversation-archive-contract)由独立服务管理。清空不删除此前回答已引用的文字。

[context_assembly.py](../runtime/node-host/jarvis_core/context_assembly.py)独立于路由策略、任务账本和持久存储。它预留宿主说明、固定要求、本轮消息及附件的全部文本字节，再按完整用户发起的轮次选最近连续历史；最多 20 条/32 KiB，沿用图片总预算。不能容纳完整最近轮次时，不拆出孤立回答，也不跳过中间大轮次后偷接更早内容。没有做模型摘要或 token 精确计数。

固定内容超限时不调用模型；有会话要求时返回 `CONTEXT_BUDGET_EXCEEDED`，未携带新字段的旧请求保留 `selected_model_input_limit` 错误码。模型回退时按实际候选预算重新装配；停止继续沿用已有 request_id 取消语义，不因装配引入新后台循环。HTTP 传输与图片字节约束不因模型上下文预算改变。

响应保留 `history_info`，增加所收历史中的 `kept_indexes`，及 `history_info.context`。后者的唯一机器定义为[context-report.schema.json](../contracts/schemas/context-report.schema.json)：算法版本、输入视图摘要、实际候选路由、字节预算、要求是否携带和历史索引；不包含要求正文。摘要是当前装配视图的内容指纹，不是持久会话修订/任务水位。`token_count=null`、`summarized=false` 明确未实现的能力。索引只针对本次 HTTP/CLI 提交的历史；页面先前已裁剪的消息不算服务器见过。表中拟定的完整 ContextView 不能与该报告混为同一接口版本。

<a id="context-assembly-future"></a>
### 后续完整 ContextAssembler 契约（proposed）

下表是后续任务、知识和摘要接入目标，新增语义须先完善唯一 schema 与兼容用例，再接入执行链。

| 接口部分 | 必要语义 | 权威与失败行为 |
|---|---|---|
| BuildContext 输入 | session/turn/task 标识与修订、目标模型 profile 和输入预算、外发目的、授权引用、会话片段/检索证据/产物引用 | 调用者先取得允许使用的资料；Assembler 再核对版本、域和外发范围，不扩大读取权限 |
| BuildContext 输出 | 版本化 ContextView：有序消息、来源与摘要映射、会话/任务水位、估算 token 与字节、保留/省略项、摘要所用模型与方法版本 | 只供规划/模型请求使用，不作为事实或执行回执；估算标明模型与方法，不能把字节数直接说成精确 token |
| 必保信息 | 当前用户目标及纠正、有效规则引用、未完成步骤、已确认产物、UNKNOWN/取消状态、文件或工具版本 | 规则由其权威模块重新注入，执行端独立校验；不得依赖模型生成摘要来恢复权限或任务状态 |
| 压缩与持久性 | 对可压缩历史生成带来源区间的派生摘要；最近交流和关键证据留原文；原记录按既有保留策略保存 | 临时会话不得因压缩偷偷持久化；保存会话的摘要失效后可重建，不能用摘要覆盖唯一原件 |
| 修订、切换与取消 | 使用前核对任务/会话水位和模型 profile；资料撤回、用户纠正、目标供应商变化使相关视图失效；取消按 turn 绑定 | 水位变化重建；旧摘要不能复活删除资料或重复动作；压缩请求计入同一预算并服从取消 |
| 无模型与超预算 | 确定性选择最近消息及关键引用；已登记本地摘要器可选 | 必保信息仍装不下时返回 `CONTEXT_BUDGET_EXCEEDED` 并等待缩小范围；不得静默丢掉约束或自动改用未授权云端 |

首期只做有界装配、必要时摘要和可解释省略；两段预测压缩、后台摘要缓存等必须证明减少延迟且不增加错误后再启用。它可以独立换实现，但始终只消费[记忆 Provider](#memory-provider-contracts)与[任务状态](#next-control-contracts)，不直接读写它们的内部数据库。外部编码器内部的压缩由其适配器负责，Jarvis 仍用自己的任务目标和回执进行最终核对。验收归 [V-OSS-01](delivery-validation.md#v-oss-01)。

<a id="interfaces"></a>
## 接口与数据契约

以下是未来扩展的概念契约示例，不是现成可运行配置。当前实现以[上述六份源 schema](#k0-contracts)为准；新增扩展须先更新正式 schema、校验器与兼容测试，再接入执行链。

<a id="interfaces-1"></a>
### 模块生命周期

```text
DescribeCapabilities() -> capabilities, versions, limits
Health()               -> readiness, liveness, degraded_reasons
PrepareUpdate(target)  -> compatibility_report
Drain(deadline)        -> pending_tasks, safe_to_stop
ExportCheckpoint(id)   -> schema, content_ref, integrity
ImportCheckpoint(ref)  -> validation_result
Start(config_version)  -> instance_id
Stop(mode)             -> final_state
```

不是每个模块都支持迁移；接口应明确返回 unsupported，发布器据此选择保留旧实例或维护窗口。

<a id="interfaces-2"></a>
### 任务与动作分离

```yaml
task:
  task_id: task_001
  goal_id: goal_001
  parent_task_id: null
  scope: local
  owner_node_id: node_workstation
  owner_epoch: 7
  workflow_version: "1.2.0"
  skill_version: "2.1.0"
  planning_policy_version: "17"
  authorization_ref: grant_001
  checkpoint_schema: "task.checkpoint.v2"
  budget:
    max_cost_units: 100
    max_runtime_seconds: 1800
    max_attempts: 3
  required_capabilities: ["filesystem.read.v1"]
  cancellation_ref: cancel_001
  status: READY

action:
  action_id: act_001
  intent_id: intent_001
  task_id: task_001
  resource_id: device_workstation_files
  host_instance_id: host_b
  host_epoch: 3
  owner_epoch: 7
  enforcement_policy_version: "18"
  arguments_digest: "sha256:..."
  idempotency_support: receiver_verified
  status: PREPARED
```

task_id 标识工作；intent_id 标识较高层意图，可包含多个具体动作；action_id 标识一个外部动作，同一动作的网络重传、跨节点交接和模型重试必须复用该编号；attempt_id 只区分尝试，不能当作动作幂等键。同一个 action_id 携带不同参数必须拒绝。

动作账本去重记录的保留期必须覆盖允许的重放与离线重连窗口；超过窗口的旧命令拒绝自动重发，先对账或重新规划。第三方去重有效期也必须记录，不能假定永久有效。

执行链：授权 → 持久记录 PREPARED → 持久记录 DISPATCHING → 发出 → 接收并持久化回执 → 对账/验证 → CONFIRMED。恢复时所有没有终态回执的 DISPATCHING 一律按 UNKNOWN 对账；实际未发出的请求也可能被保守归入 UNKNOWN。不能因为缺少“已发出”记录就假定未执行。能够校验幂等键的接收方可用原 action_id 查询或安全重试；不支持幂等的目标保持等待直至消除歧义。[S06](references.md#s06)

<a id="interfaces-3"></a>
### 事件信封

```json
{
  "event_id": "evt_unique",
  "event_type": "task.checkpoint.saved",
  "schema_version": 1,
  "node_id": "node_workstation",
  "community_id": "community_owner",
  "entity_id": "task_001",
  "node_sequence": 1024,
  "causal_parents": ["evt_previous"],
  "occurred_at": "2026-10-15T00:00:00+08:00",
  "policy_version": "17",
  "trace_id": "trace_001",
  "sync_scope": "community",
  "external_processing": "deny",
  "payload_ref": "object:sha256:..."
}
```

事件按至少一次传递设计，消费者去重。消息中间件的确认语义不能替代业务动作幂等。

<a id="interfaces-4"></a>
### 技能和模块包清单

```yaml
id: jarvis.tools.design_exporter
version: "1.3.0"
artifact_digest: "sha256:..."
signature_ref: "signature:..."
platforms: ["windows-x86_64"]
runtime: python-worker
entrypoint: design_exporter.main
contracts:
  provides: ["design.export.v1"]
  requires: ["filesystem.v1"]
  protocol_range: ">=1.0 <2.0"
state:
  schema_version: 2
  migrate_from: [1]
execution:
  checkpoint_supported: true
  concurrency: 1
permissions:
  filesystem_scopes: ["project-assets"]
  network_scopes: []
resources:
  memory_mb: 512
  timeout_seconds: 120
release:
  evaluation_suite: "design-export-regression-v2"
  rollback_strategy: "new-task-switch-and-drain"
```

权限使用可解析的授权资源范围，执行端必须检查真实路径和目标；清单文字本身不能授予权限。依赖包、运行环境和模型配置都应锁定版本或内容哈希。

<a id="interfaces-5"></a>
### 接口类型选择

核心跨进程：Protobuf/gRPC 或等价强类型协议，版本兼容检测。
- UI：本机受保护的 IPC 或 HTTP/WebSocket，校验来源和会话。
- 动态工具参数：JSON Schema；输入输出都校验。
- 外部工具：MCP、HTTP 等通过适配器接入；固定经过测试的协议版本。
- 大文件：对象引用与流式传输，避免塞进事件或模型上下文。
- 新旧接口支持窗口至少覆盖正在运行的任务与受支持节点版本；超出窗口给出明确升级/隔离行为。

MCP 是工具互操作边界，不承担 Jarvis 的任务账本、身份主权或整个生命周期。规范仍在演进，应固定版本并通过适配层处理差异。[S16](references.md#s16)

<a id="skill-selection-contract"></a>
## 技能选择、策略与调用记录契约

**2026-10-17 accepted；0.1.36 已实现有界原生子集，完整通用导入仍待 K2 后续。** 本节不增加当前 `/api/extensions` 可接受字段，不修改 K0 冻结种子及固定 `sample-plan`。所有适用性和选择顺序只在[统一技能规则](tasks-agents.md#skill-selection-policy)维护，元数据与包内技能由 importer 规范化后提交同一目录，不直接执行上游 frontmatter。

| 对象 | 必需内容 | 校验与含义 |
|---|---|---|
| SkillDescriptor | `skill_id/version/source_namespace/source_revision`、有 Git 来源时的 `source_commit`、包与文件 `bundle_digest`、入口、必要引用、执行器/能力依赖、输入输出契约 | 同名按来源区分；内置/用户自建/生成技能也须有可追溯修订；完整依赖闭包绑定摘要，不能只校验 SKILL.md；包版本与单技能版本分别记录 |
| Applicability | `use_when/do_not_use_when`、任务阶段、输入类型、预期产物、必要上下文、正反例 | 每项至少两个有效正例、两个不应触发的反例；不得只有关键词或“总是调用”；缺规则不能自动准入 |
| SkillPolicy | `revision/mode`（`auto/manual/disabled`）、`scope`（全局/项目/会话/本轮）与对应 ID、用户覆盖及依赖/预算引用 | 宿主解析有效值与来源，拒绝未知模式和作用域；覆盖不改包正文，不包含秘密，不扩大任务授权 |
| Readiness | `registration/loadability/executability`、缺失依赖、适配器/运行版本、验收与准入状态 | 偏好为 auto 不代表可执行；只有原子核对当前包、依赖、策略与能力后才可派发；未验证不能填 ready |
| SkillSelectionDecision | task/turn/step 标识、候选与排除原因、选中技能/版本、匹配条件、有效策略修订、输入/产物类型、预算与能力快照引用 | 允许 `selected=[]`，表示直接处理、没有适用技能或能力缺失；“未使用”与“执行失败”分开；不复制敏感正文 |
| SkillInvocation | 原 Task/Action、技能/包摘要、实际执行器与模型、依赖调用、产物/检查回执、耗时/用量、终态与未验证项 | `loaded/selected` 不是成功；文字技能和实际工具动作分别观察；取消与 UNKNOWN 沿用任务契约 |

发布前校验包内每个技能的规则与引用，拒绝目录外资源、循环依赖或名称静默覆盖。自动选择只向规划器暴露准入后的有界候选；正文要求额外能力时重新生成选择决定并走 ActionGateway。元数据匹配和模型意图判断均可能出错，必须用正反例与真实任务验收，不能由 JSON 合法推导语义正确。

参数、上下文和输出遵守既有大小预算；SkillDescriptor 存引用，不把整包正文加入一次请求。上游正文大于当前宿主指令上限时，选择兼容执行器、短适配版或可验证的分步装配；不能伪造用户历史、提升记忆为规则或静默截断关键约束。策略修改用预期 `revision` 检查并返回有效值、来源和失败原因；恢复任务保留原版本快照，派发前复核用户最新禁止条件。

科普产物仍使用[Artifact 契约](#k0-contracts)及相应扩展：描述 HTML/SVG/图片/视频、源码与证据的独立引用、各自类型/大小/摘要、语言、教学隐喻或真实结构、数据模型/来源版本和可用交互。正式多文件清单和产物预览接口须先出 schema 与兼容验收，不把目录路径或模型自述当作整包交付回执。

0.1.36 的正式有界契约为 [native-skills.schema.json](../contracts/schemas/native-skills.schema.json) 与 [skill-report.schema.json](../contracts/schemas/skill-report.schema.json)，运行时实际校验目录和交付回执。原生目录固定来源、适用/排除规则、正反例和工作流；目录摘要绑定指导，执行配置另外绑定绘图库、模板与许可证。`extensions.db` 新增策略和选择记录表，保留原登记 schema 与 dormant 语义；选择日志只存消息摘要及原因，不保存原提示或源码。内置种子的策略不可修改。

目录的 `presentation` 描述用户能力的 category/icon/summary/output/requirements/kind/components；非内部项必须完整，组合的方法来源不单独暴露为可选技能。`inventory` 保留原 43 条的 active/merged/internal/removed/unavailable 归属及理由。快照返回 `selection_method=host_rules`，不伪称模型自主选择。九项已准入指导均有正文预算检查及 evaluation.guide_sha256 样例绑定；正文变更会使运行就绪失效，需复测更新记录，任意新 ID 不能只靠修改元数据获得执行器。撤出目录的旧 ID 拒绝选择，合并项提示完整能力 ID；旧策略行和历史回执保留。

文本报告允许无参考文件的五项文本流程；四项编程分析仍由请求校验和报告 schema 要求至少一份来源。参考资料保持最多八项、每项 16 KiB、总量 32 KiB，交付前重验摘要。是否有源码不改变报告“未执行代码/测试”的语义。

| 已实现接口 | 有界语义 |
|---|---|
| `GET /api/skills`、`/api/skills/decisions` | nonce/同源/核心检查；可同时带 project_id/conversation_id，返回 readiness、有效策略/来源及最近 30 次决定 |
| `POST /api/skills/policy` | skill_id、scope、scope_id、预期 revision 和 mode（null 恢复继承）；原子修订，过期拒绝 |
| `POST /api/skills/select` | message、context 和 chat/task 用途；试配只选择，不调用模型或执行器 |
| `POST /api/conversation-tasks/{conversation_id}` | mode=skill、稳定 request_id、所选项目、prompt、可选 skill_id/model/paths/ratio/theme/output_path/target_path/focus/explain；编程分支另见[限定字段](#bounded-coding-contract)；复用原账本和队列 |
| `POST /api/skills/preview` | 已确认且属于当前会话的 Anatomy task_id；重验交付文件，返回 10 分钟随机预览引用 |
| `GET /api/skill-previews/{token}` | 不包含业务 nonce；每次重验回执/文件；CSP 固定脚本摘要、禁止连接，sandbox allow-scripts 且无 allow-same-origin |

0.1.47 的 `rea.software-analysis` 复用同一技能任务接口：`target_path` 为项目内相对目录或 `.asar` 文件，空串表示项目根目录；`paths` 必须为空。可选 `focus` 是不含控制字符、最多 256 UTF-8 字节的字面标识符；显式值优先，否则从 prompt 提取有界的引号标识符、通道名或 JS 文件名。`analysis.focus` 记录 query/source/method、匹配数量和有界摘要；没有匹配保留未知，不是模型解释。回执采用 `skill-report.schema.json` 的 REA 分支，要求 `text,analysis,input_manifest,runtime` 及独立证据引用 `evidence_ref={path,digest,size_bytes,media_type,evidence_id}`；兼容读取 0.1.45 的内嵌 `evidence`，两者只允许其一。`skill_id` 固定为 REA；回执继续受 2 MiB 上限与 Artifact 摘要约束。`runtime.evidence_digest` 是无末尾换行的规范化 Evidence JSON 摘要；`evidence_ref.digest` 绑定实际独立文件字节（含末尾换行）；原 stdout 摘要另存，不可混淆。

`GET /api/skills/evidence/{conversation_id}/{task_id}` 提供经会话、确认回执及完整文件摘要核对的 `{evidence,analysis,input_manifest,runtime,checks}`，不通过另一次解析重新生成。带 `section=links/components/files/omitted` 时返回分页 `{evidence_id,section,offset,total,items,next_offset,query,total_before_filter,static_only,coverage_note}`；offset 非负，limit 为 1—50、默认 20。可选 query 与 focus 同样限制，按不区分大小写的字面标识符边界匹配，空值显示全部；total 为筛选后条数，total_before_filter 为筛选前条数。items 携带当前集合（有筛选时为筛选集合）中的索引，超过 8 KiB 的单条显示带 `truncated` 标记的摘录，完整字段仍在下载文件中；每页条目总预算 64 KiB。nonce、同源和核心状态检查沿用技能接口。`input_manifest.format` 为 directory/asar，`parser_input_format` 固定为 directory；ASAR 增加 container 的 path/digest/bytes，以及每文件 origin 的 container/member/byte_offset/unpacked/declared_hash_checked。保留原包来源不等于把全部原包交给解析器。UI 使用纯文本预览及分页，不执行目标文本中的 HTML/脚本。格式、输入预算与进程限制见[REA 执行边界](security-sovereignty.md#rea-static-boundary)。

`skill.report.v1` 保留原 Task/Action/Artifact 生命周期，单任务 120 秒，源码任务最多一次模型路由；科普任务零模型请求。模型报告的“检查通过”只指来源/交付流程，不代表源码建议已被测试验证。固定 HTML 组装受原 Python LPAC/Job 限制，浏览器使用私有上下文、进程 Job 与 Chromium sandbox；页面错误、外部资源或交互不符均阻止交付。HTML 上限 768 KiB，当前仍是单文件模板；通用多文件清单、导入引用图和视频契约未实现。

REA 任务增加可选布尔 `explain`（默认 false）。true 时只接受明确的 `provider::model`，模型计数预算为 1；false 时为 0。回执可增加 `explanation`：status 为 SUCCEEDED / INSUFFICIENT_EVIDENCE，包含 findings、unknowns、sources、coverage、model_calls、citations_verified=true、semantics_verified=false。有实际调用时另存模型/用量/请求编号、请求资料摘要与字节数、原输入摘要和 evidence_id。每个来源的 E 编号由宿主生成，绑定原 edge_id、relation、properties、location；模型只返回文字、类别与编号。1.3.1 增量把 handles 注册关系纳入关键关系、focus 和分页，优先显示 IPC 关系；来源同时保留 evidence_state、confidence 与 limitations。若模型将引用 inferred 关系的结论标为 observation，宿主降为 inference，保存 classification_adjustments；这只校正证据等级，不验证句子语义。格式与引用核验拒绝额外字段、重复键和未知编号。预算和失败语义只在[REA 执行边界](security-sovereignty.md#rea-static-boundary)维护。

模型入口使用内部 purpose=rea_explanation 的固定指导，拒绝混入历史、附件、记忆或其他技能上下文；不新增公共任意指令字段或工具权限。设置中的会话选择使用既有 `/api/conversations` 名称列表，并把选中会话所属 project_id 一同用于有效策略查询，使“会话继承项目”与任务执行保持一致。


<a id="bounded-coding-contract"></a>
### 编程副本与验证状态字段（0.1.69）

**改进单交接字段（0.1.68）。** 复用 `POST /api/conversation-growth/{conversation_id}`；编码请求为 `request_id`、`prompt`、`coding`。coding 必含 paths、cases、heldout_cases、model、coding_provider、build_recipe，可含 entrypoint；项目身份从已保存会话读取。源码包改进单也必须有独立案例。创建、查询、开始、取消和重新分析继续使用已有路由及 nonce/Origin 保护。

Host 保存 `frozen`（规范化参数、源码快照、项目根目录、实现/技能绑定、预算），并返回 `proposal.binding`、文件摘要和待开始状态；源码正文不在改进单列表中重复返回。Host 写入任务参数 `coding_demand={id,digest}`，受理和运行都核对保存内容，客户端不能凭一个引用替换目标或验收条件。`web-{改进单 id}` 为唯一任务请求键；关联与队列入账同事务提交。最多保留 1,000 项改进单。

`result` 包含 verified、task_id、artifact_digest、cases_digest、cases、model_calls、build_recipe、delivery、automatically_applied。delivery 为 verified_candidate 或 diagnostic_only；automatically_applied 固定 false。独立案例失败可对应“任务 CONFIRMED、改进单 FAILED”，二者含义不同。状态及结果投影可从原任务/产物重建，损坏产物不能保留“已核验”展示；重新分析只允许终态，保持 previous_job 来源链。当前交接流程见[任务规则](tasks-agents.md#bounded-coding-workflow)。

0.1.67 的静态失败回执可含 `static_reason`，说明受限环境缺少的内置名称；该诊断不来自留出案例正文。候选生成提示包含实际内置函数清单，构建配方与允许执行能力不变。

技能请求沿用 `coding:boolean` 与 `cases:[{input,expected}]`；新增 `heldout_cases`、`entrypoint`、`coding_provider=gateway|codex`（默认 gateway）；`build_recipe=python-source-v1|python-zipapp-v1|python-jmespath-v1`，API 缺省保持原源码配方，当前 UI 默认可运行工具包。每组案例 2—24 项、总计最多 16 KiB；每项仅含 input/expected，预期为最多 4 KiB 字符串。独立输入不得与公开输入重复。多文件或可运行工具包必须有 heldout_cases；旧单文件请求兼容，但不宣称已做独立检查。paths 为 1—4 个同目录 `.py` 文件，模块名普通英文字母开头，可含数字和下划线；入口默认第一份且必须在清单中。原始/候选每文件最多 16 KiB、合计 32 KiB。四项工程技能之一必须明确指定，不能并用 output_path 或 REA explain。

gateway 使用明确 `provider::model`，Codex 使用[编码协作设置](evolution-release.md#external-coding-executor)中的模型。入队时宿主写入 `coding_executor_binding`，绑定设置修订和内容；排队及调用期间变化即停止旧任务。任务执行截止时间读取账本预算，编码任务 240 秒；最多两次完整候选生成，网关每次 55 秒，Codex 每次 90 秒；不是自动重发未知请求。

回执沿用 `jarvis.skill-report`，包含 text、source_references、coding；[报告 schema](../contracts/schemas/skill-report.schema.json)维护字段约束。原有 original/candidate 保持单文件兼容，多文件增加 originals/candidates/entrypoint；validation 分 public/heldout 并标 independent_checks。build 绑定所选配方的 ZIP/PYZ、manifest、字节数和 SHA256；每个源文件与冻结案例摘要都进入清单。PYZ 增加 launcher_sha256、Python 版本范围；回执增加 build_recipe、build_validation（实际归档入口与案例）和 source_build（原无依赖配方的配套源码包）。依赖配方增加 dependencies（名称/版本/来源/许可证/原 wheel 摘要与公开接口），manifest 增加 dependency_files；具体锁定规则归[离线依赖配方](toolchains.md#bounded-python-dependencies)。文件名只接受 candidate-python.zip / candidate-python.pyz。静态失败基线的 executed=false、diagnostics 含文件及语法行号；不执行原始损坏源码。构建复验失败使 coding.passed=false；仅 coding.passed=true 可应用；CONFIRMED 只表示报告交付完成，失败诊断也可为 CONFIRMED。

`POST /api/skills/coding-apply`、`coding-rollback` 仍仅接收 conversation_id/task_id，从核验回执取源文件组，不接受客户端另传路径或代码。保留 nonce、Origin、会话归属、项目身份和内容冲突保护。部分多文件写入返回 coding_partial，允许在同一回执上继续/恢复；恢复日志不是自动回放命令。

`GET/POST /api/coding` 为独立编码设置：revision、enabled、model、reasoning（low/medium/high/xhigh），写入比较修订号；不接受任意命令、可执行路径或 Key。GET 同时返回已固定 CLI 的可用性、离线状态、认证与费用边界，不进行付费探测。`coding-settings.db` schema 1 只在明确保存时创建，不新增常驻服务；新数据不交给不理解它的旧运行包接管。

`GET /api/skills` 的 validation 继续分别呈现 evidence 与 latest_success。指导、执行器或报告 schema 改变使旧质量证据 stale，不将旧任务搬成新验证，也不由一次成功报告宣称所有技能已复验。

<a id="extensions-3"></a>
## 资源租约、本地组件与安全事件契约

```yaml
resource_lease:
  lease_id: resource_001
  root_task_id: task_001
  holder_agent_id: agent_001
  node_id: node_home
  cpu_limit: measured_profile
  memory_limit_mb: 1024
  model_concurrency: 1
  spend_reservation: 10
  budget_account_ref: task_budget
  expiry_ref: lease_expiry
  reclaim_policy: checkpoint_then_sleep
  security_epoch: 12

local_component:
  component_id: speech.stt.local
  kind: stt
  version: "validated-1"
  artifact_hashes: ["sha256:..."]
  source_ref: trusted_registry_entry
  platform_arch: windows-x86_64
  runtime_abi_ref: onnx_compatible_profile
  languages: ["zh"]
  quality_eval_ref: owner_voice_commands_v1
  resource_profile_ref: cpu_survival
  fallback_ref: speech.stt.previous
  offline_verified_at: "2026-10-15"
  status: ready

security_stop_event:
  event_id: stop_unique
  community_id: community_owner
  incident_id: incident_unique
  issuer_node_id: node_home
  issuer_sequence: 1024
  scope: community_business
  reason_code: ROOT_PRINCIPLE_VIOLATION
  evidence_ref: protected_evidence_hash
  signature_ref: supervisor_signature
```

上述额度、日期和编号均为示例，不是已完成验证的记录。真正运行时使用签名来源、实际评估和有效租约。

<a id="project-resources-contract"></a>
## 项目资源与工程文件契约（0.1.27）

`ProjectFiles` 使用现有 `workspace.db` 项目身份；不复制所有文件，不另设目录事实库。下面均为同源 loopback POST，沿用 Host/Origin、页面 nonce、核心运行检查。请求拒绝未知字段；路径限所选项目内相对路径，工程打开动作例外接收用户明确输入的完整路径。

| API | 请求字段 | 结果与边界 |
|---|---|---|
| `/api/project-files/tree` | `project_id,path,exclude?` | `path` 可为空表示根目录；返回本层 `entries` 的 name/path/kind/editable/size_bytes，以及 excluded/truncated；不读文件正文 |
| `/api/project-files/read` | `project_id,path` | `content,digest,size_bytes,bom,path`；digest 为原始字节 SHA-256，UTF-8/BOM 解码，非文本拒绝 |
| `/api/project-files/write` | `project_id,path,content,digest,bom` | digest 为读入版本，新文件用 null；内容相同的重试可回现有结果，不同旧版本返回 409；成功重新读盘核验摘要 |
| `/api/project-files/save-project` | `project_id,path,document,digest` | 在项目根目录创建或按预期摘要更新 `.jarvis-workspace`，复用文本写入 |
| `/api/project-files/open-project` | `path` | 校验工程后登记其父目录，返回 project/document/path/digest；不从工程执行命令、安装扩展或取得云端许可 |

工程 JSON v1 的唯一格式如下；未知版本、重复字段、额外字段、多根列表、活动文件不在标签列表时拒绝。`folders` 当前必须恰为 `[{"path":"."}]`，避免导入工程时隐式挂载其他位置。

```json
{
  "schema_version": 1,
  "folders": [{"path": "."}],
  "view": {
    "open_files": ["src/main.py"],
    "active_file": "src/main.py",
    "exclude": ["logs", "*.log"]
  }
}
```

容量：每次目录列举最多 500 个显示条目、5000 个检查项、协作式 2 秒截止；超过返回 truncated，不宣称目录完整。文本最多 1 MiB，浏览器跨项目合计最多 8 个编辑缓冲；工程最多 8 个打开路径、32 个排除模式，每个模式 160 字符。编辑写请求体最多 6 MiB + 64 KiB 以容纳 JSON 转义，解码后仍受 1 MiB 文件限制；其他请求使用现有 128 KiB 限制。行号展示最多 10000 行，正文不因此截断。协作式截止不是阻塞磁盘调用的硬超时。

支持的文本类型由 [project_files.py](../runtime/node-host/jarvis_core/project_files.py) 的 `TEXT_TYPES` 与固定无扩展名集合实现，包含常用代码/脚本、Markdown、JSON、YAML/TOML、文本和工程文件。树中其他普通文件可见但禁用编辑；不渲染 SVG/HTML 内容。额外排除模式按相对路径、文件名或目录前缀匹配，仅约束文件树；已经打开的标签仍可访问，不将它当成授权撤销。当前不解析 `.gitignore` 的完整语义。

修改在宿主内串行，替换已有文件前复核目录身份、原摘要并使用同目录临时文件加 `os.replace`；创建使用独占创建。进程内冲突检查不等于 OS 原子 compare-and-swap，完整限制归[编辑边界](security-sovereignty.md#project-editor-boundary)。失败不改存其他路径；首次创建的 I/O 中断可能留下不完整新文件，页面保留草稿并要求核对。未来批量模型修改继续走任务/动作与差异审阅，不能复用此手动编辑入口当作隐式自主许可。

<a id="extension-catalog-contract"></a>
## MCP 与技能登记契约（0.1.27；0.1.37 管理增量）

`ExtensionCatalog` 在当前实例数据目录维护 `extensions.db`，独立于模型、记忆、任务与项目库。登记本身为全局个人配置，选用偏好作用域见下文；登记统一 `status=registered,runtime_available=false`。登记不是模型可调用工具清单。

| API | 字段与行为 |
|---|---|
| `GET /api/extensions` | 同源/nonce/核心检查；返回 entries 与 runtime_available |
| `POST /api/extensions/{id}` | 32 位小写 hex ID；`{revision,document}`。新建 revision=0，修订为整数；相同上一版请求可幂等回执，过期写或重用删除 ID 返回 409 |
| `POST /api/extensions/{id}/inspect` | 空对象；MCP 返回配置格式检查结果，技能读取当前 SKILL.md 并对比摘要，返回 unchanged/changed 与纯文本；缺失/异常显示错误 |
| `POST /api/extensions/{id}/delete` | `{revision}`；清除登记正文并留删除标记，不操作原技能文件或外部服务 |

`document={kind,name,config}`，name 为 1—80 字符；kind 仅 mcp/skill。0.1.37 可为 MCP 增加 `catalog_id`，必须属于当前固定目录；旧文档无需迁移，其他类型不能附带此字段。MCP config 的 transport 为 stdio 时保存 command、可选 args 字符串数组；为 streamable-http 时保存 url。credential_ref 为可选引用名称，尚未绑定真实凭据。参数数组最多 32 项、每项 1024 字符；只将数组存为数据，不拼接 shell。HTTP 端点登记接受 HTTPS 或本机 HTTP，拒绝用户信息、query、fragment 与非法端口；登记操作不请求该 URL。参照的传输规范见 [S164](references.md#s164)。

`McpManager` 读取 [mcp-catalog.schema.json](../contracts/schemas/mcp-catalog.schema.json) 校验的固定目录，将同 catalog_id 的登记归到一个能力；未关联登记保留为 `custom.{32位id}`。`GET /api/mcp/catalog` 返回 entries、来源审阅版本、使用条件、registrations、policy、overrides、组合建议与暂不推荐项；`POST /api/mcp/view` 接受可选 project_id/conversation_id 返回对应有效偏好。当前仅唯一匹配官方无凭据 HTTP 配置的 Context7 可返回 `runtime_available=true`，且规则非 disabled 时 `callable=true,status=available`；其余仍为 false。`selection_method=explicit_documentation_task`。可选 `last_validation` 投影最近真实账本任务的状态、时间、连接修订与错误；它是历史记录，不是连通探测。来源验证不生成可调用工具。

`POST /api/mcp/policy` 接受 `{mcp_id,scope,scope_id?,revision,mode?}`，scope 为 global/project/conversation，非全局 scope_id 为既有 32 位标识格式；模式为 auto/manual/disabled 或 null 恢复继承。偏好存于同 extensions.db 的独立 mcp_policies 表，不覆盖 skill_policies 或 entries。全局不能携带非空 scope_id；必须以当前修订写入，过期写返回 409 `mcp_policy_conflict`，恢复继承也递增修订。以上 API 复用同源、nonce、核心停止和请求大小检查；没有任意 MCP call 或进程启动入口；受限 Context7 调用仅通过下述任务契约。管理 UI 只使用固定 `/mcp_manager.js`，无请求派生静态路径。

技能 config 保存本地目录绝对 path 与服务器计算的 SKILL.md digest；文件必须是非空、最多 128 KiB 的 UTF-8 文本。未解析全部 frontmatter，不声称完全兼容 [Agent Skills 规范 S165](references.md#s165)。单库累计标识最多 1000；只存配置与摘要，不复制技能包，不下载依赖，不建立额外调度权威。

未来适配器需通过能力注册接口暴露经过检查的工具/技能；握手、可用性与一次调用分别有状态，工具输入输出按契约校验，调用受现有 Task/Action、取消、预算与范围约束。当前不会让工程文件携带 MCP 自动启动设置、技能自动执行规则或明文凭据。模块边界见[架构章](architecture.md#project-extension-modules)。

<a id="mcp-documentation-task-contract"></a>
### Context7 只读文档任务（0.1.55）

复用 `POST /api/conversation-tasks/{conversation_id}`，参数为 `{mode:"mcp",request_id,prompt,library,project_id?}`。请求编号仍为 `web-` 加 32 位 hex；prompt 为非空单行、最多 2,048 UTF-8 字节，library 最多 160 字节；以 `/` 开始时必须为 `/组织/项目` 或 `/组织/项目/版本`。宿主附加会话与准入时连接/策略快照，不允许客户端提供该内部快照。项目字段用于策略，不读取项目文件。

候选检查复用本机 nonce、Origin 和就绪检查：`POST /api/conversation-tasks/{conversation_id}/documentation-candidate` 接受 `{candidate:{library,query},text,project_id?}`。text 最多 16 KiB；library/query 必须通过以上参数限制且逐字出现在 text 中，库名不允许截取另一个英文库名的一部分。只读返回 `{kind:"mcp.documentation",eligible,auto_eligible,automatic_execution:false,next_action,reason_code,reason,policy}`；通过时另有核对后的 library/query/context/connection/data_scope，`next_action="review_draft"`。eligible 表示允许准备草稿；auto_eligible 仅表示当前规则允许成为自动候选，均不授权执行。不接收 request_id、execute、model 或额外工具参数；无模型和 MCP 请求、无 Task/Action。真实发送仍经原准入接口检查。会话归属从 ConversationStore 读取：保存的项目优先，传入不符则拒绝，删除墓碑阻止旧会话；未归档临时会话沿用明确传入作用域。连接快照带入实际 scope，等待时归属变化不交付旧结果。

`mcp.documentation.v1` 使用现有 FIFO、Task/Action/Artifact 和取消语义，90 秒总预算、每个协议请求最多 25 秒、一次工具调用、零模型请求；128 MiB 为调度估计而非 OS 隔离限额。队列绑定适配器源码摘要；派发和等待检查连接修订与策略，变更后不交付旧结果。同 request_id 查询或重提不重放已派发任务。只准入 `catalog_id=context7` 的唯一登记，config 必须精确为官方 `streamable-http` 端点且不带凭据引用。

0.1.57 宿主受理器可向同一个 `enqueue_mcp` 传内部 automatic 来源，公开 HTTP 参数仍不接受 automatic、`_origin` 或 `_connection`。来源只含 kind/turn_id/decision_id/text_digest/rule；自动查询的连接快照另带 automation_digest，等待与返回前重检 `config/mcp/automation.json`、连接、策略和真实会话归属。成功报告附原来源，原文输入不写入 MCP 报告。准入条件由[统一意图识别](tasks-agents.md#conversation-intent-routing)唯一维护，回复回执字段归[意图契约](#dialogue-intent-shadow-contract)。

协议子集为初始化、initialized 通知、tools/list 和 tools/call；支持 JSON 与 SSE 响应、协商的 2025-03-26 / 2025-06-18 / 2025-11-25、会话头和最佳努力关闭/取消。无重定向、自动重连或流续传。工具目录最多 32 项；发现分页、反向请求、版本或必填参数变更时拒绝。库名调用 resolve-library-id，明确 ID 调用 query-docs，不凭第一候选猜库。只读性质由宿主固定白名单决定，不信任 readOnlyHint。

每个解压后响应最多 256 KiB，文档文本最多 192 KiB，工具结果仅接收非空文本；超限、协议错误、工具 isError 不截断为成功。鉴权/额度错误明确失败；已派发工具的网络超时、断流或 HTTP 结果不明标 UNKNOWN，取消标 CANCELLED。请求被取消不代表远端已撤销。成功回执 `kind=jarvis.mcp-report` 保存端点、协商版本、tool/library/query、原文、候选 ID、请求轨迹、规则和连接修订；Artifact 仍受摘要及会话归属核对。原文不是模型回答或已验证事实，也不自动写入长期记忆。完整通用 MCP、OAuth/凭据、stdio 和模型自主选工具未实现。

<a id="evolution-runtime-contract"></a>
## 限定成长运行接口

**0.1.37 建立接口；0.1.64 增量见[三能力契约](#growth-center-contract)，implemented。** 行为权威见[限定成长闭环](evolution-release.md#bounded-evolution-loop)。所有接口仅绑定本机回环，复用 Host / Origin、页面 nonce 和核心就绪检查；请求 JSON 字段严格匹配，查询尾缀不扩张文件访问范围。

| 接口 | 输入 / 输出 |
|---|---|
| `GET /api/evolution` | 设置、活动/前一版本与代际、最近任务、包状态、限额、已支持配方；不返回凭据 |
| `GET /api/evolution/jobs/{32hex}` | 完整改进阶段、模型调用引用、候选验收、回退、错误和执行结果 |
| `GET /api/evolution/packages/{64hex}` | 重新核对摘要后返回固定三个包文件及元数据；不接受任意文件路径 |
| `POST /api/evolution/policy` | 当前字段和旧三字段适配见[三能力契约](#growth-center-contract)；只允许登记模型及合法档位，任务运行时不改设置 |
| `POST /api/evolution/jobs` | `{action, request_id}`；`ensure` 另需 `target_revision`，`execute` 另需 `input`，`check` / `analyze` / `heal` / `rollback` 无其他参数；返回 202 与任务编号 |
| `POST /api/evolution/cancel` | `{job_id}`；停止当前对应任务，已完成任务幂等返回 |

`request_id` 为 8—80 个字母/数字/下划线/短横线；同编号同内容返回原任务，内容不同为 409。单维护通道最多一个运行中任务，其他新请求为 409；聊天使用独立通道。任务状态为 `QUEUED/RUNNING/OBSERVING/SUCCEEDED/FAILED/UNKNOWN/CANCELLED/INTERRUPTED`。`SUCCEEDED` 表示该动作完成，`check.result.healthy=false` 仍需处理；不能只看 HTTP 200/202 判断修复完成。

工具输入为 `{format,entries:[{path,size}]}`；最多 100 条 / 65,536 UTF-8 字节，path 为 1—256 字符文本且不含 NUL，size 为 0—10¹² 的整数（布尔值无效）。v1 格式为 csv/markdown，v2 另支持 tsv。path 只是输入数据，不被打开为文件；返回文本按路径稳定排序，具体兼容与期望值归受控配方。CSV 不自动打开或执行，文件名原文中的公式前缀不被当成动作。

生成包的 manifest 绑定技能 ID、revision、contract、独立 build ID、执行器、依赖、权限、显式调用模式、正反例和验收摘要；内容摘要涵盖全部三个文件。候选不能修改宿主规则、验收阈值、编码模型配置或自己的权限。持久化 schema 当前为 1，不兼容未来版本拒绝打开而非降级覆盖。

<a id="growth-demand-contract"></a>
### 会话需求适配接口（0.1.41）

以下严格字段描述原目录报告格式分支。0.1.68 在相同路由加入编码改进单，其独立参数、状态投影和产物语义只维护在[编码交接契约](#bounded-coding-contract)；开始动作进入共享编码队列，不进入报告发布通道。两种请求不能复用同一会话请求编号。

复用上述同源、nonce、核心状态与请求大小约束。`cid`、`job_id`、`request_id` 均为 32 位小写 hex；只有本机已有的普通会话可创建提案。所有会话接口复核来源会话及其当前项目归属，跨会话或归属变化返回未找到。

| 接口 | 严格字段与返回 |
|---|---|
| `POST /api/conversation-growth/{cid}` | `{request_id,prompt}`；最多 1,024 UTF-8 字节的完整导出要求，返回持久 `PROPOSED` 单；同编号不同要求返回 409 |
| `GET /api/conversation-growth/{cid}` | 返回当前范围最近 30 单，待开始/运行中优先；全量审计仍在原账本 |
| `GET /api/conversation-growth/{cid}/{job_id}` | 返回该单原请求、提案、事件、尝试、错误及实际结果 |
| `GET /api/conversation-growth/{cid}/requests/{request_id}` | 按原请求编号找回回执；不存在时不重发 |
| `POST /api/conversation-growth/{cid}/{job_id}/start` | 仅 `{}`；复核基线并进入原成长通道；重复开始不重复执行 |
| `POST /api/conversation-growth/{cid}/{job_id}/cancel` | 仅 `{}`；未启动单直接取消，运行单协作式取消 |
| `POST /api/conversation-growth/{cid}/{job_id}/reanalyse` | 0.1.43 新增 `{request_id}`；仅 FAILED / INTERRUPTED / UNKNOWN / CANCELLED 原单可用。同范围重新核对最新成功报告与能力基线，建立新的 PROPOSED 单，不启动编码或交付；同编号同来源重传返回原新单 |
| `GET /api/conversation-growth/{cid}/{job_id}/artifact` | 仅完成且结果摘要与 Host 期望值再次一致时返回 UTF-8 纯文本；无任意路径参数 |

内部请求为 `{action:"fulfill",request_id:"growth-{cid}-{request_id}",target_revision,input,origin}`；`origin` 必须包含 `conversation_id,project_id,goal,source_task,source_digest`，0.1.43 可选 `previous_job` 指向原单的 32 位标识，除此之外字段拒绝。`project_id` 可为 null，来源任务为 `task_32hex`，摘要为 `sha256:64hex`。`target_revision` 由格式确定：TSV 为 2，其余为 1；输入继续受上节 100 条/64 KiB 限制，超出拒绝而非截断。公开的旧 `/api/evolution/jobs` 不接受 `fulfill` 或外来 origin/input 的组合。新旧请求编号不混用；重传还核对 previous_job，不能把普通提案编号复用于重新分析。旧 Host 不认识该来源字段，回退前需检查兼容性。

`proposal` 保存 selection、route、baseline_revision、issue、decision、max_coding_attempts、acceptance_digest、input_digest；`decision` 为 reuse/create/upgrade/repair。在原 jobs 表新增 `PROPOSED` 状态，不更改数据库 schema 版本。开始后沿用原状态集合；`result` 增加 `growth` 与 `benefit={format,entries,source_digest,verified_on_user_input}`。UI 的成功说明只取真实终态，HTTP 成功不表示执行成功。

会话归档消息可选 `growth_ref` / `growth_request_id`，均为 32 位标识且必须搭配 `personal_control:true`；仅恢复回执链接，不加入模型历史。不认识新字段的旧宿主会拒绝该新归档而非静默丢字段，回退前需检查归档格式兼容。完整行为、数据保留与重启语义只维护于[需求成长](evolution-release.md#demand-growth-runtime)。

<a id="growth-center-contract"></a>
## 三能力消息与旧接口迁移

**0.1.64 已实现既有 `/api/evolution` 的增量契约；没有建立第二组调度 API。** 当前字段的机器校验位于 [settings.py](../runtime/node-host/jarvis_core/evolution/settings.py) 和 [manager.py](../runtime/node-host/jarvis_core/evolution/manager.py)；正反例见 [test_evolution.py](../tests/test_evolution.py)。后续通用消息仍需按[公共契约规范](#next-control-contracts)扩展，不能认为下表每个目标字段均已实现。

当前 `POST /api/evolution/policy` 接收 `{revision, enabled, interval_seconds, auto_heal, target_revision, models}`；`models` 必须恰含 `inspect/heal/evolve`，每项 `{primary, fallback}`，模型选择为 `{route: "provider::model", reasoning: 原生档位或null}`，fallback 可为 null。保存时 revision 比较并递增，忙时拒绝。旧三字段请求只更新自检开关、目标和进化主模型，不开启自动自愈、不清除其他用途。GET 继续带兼容 `route` 别名及 `schema_version:2`。

动作新增 `analyze/heal`，均无额外参数；`check` 改为纯完整性检查，执行包和候选均不改变。新任务持久记录 `purpose/policy_revision/policy`；观察报告含检查时间、范围、选择代际、实际/目标 revision、classification 与 fault；自动 heal 的 cause 引用原检查单。主/备调用共享两次上限，回执与切换规则见[用途路由](models-offline.md#growth-model-policy)。旧 `PROPOSED` 单没有新策略修订时须重新分析，不静默套用新策略启动。

| 对象 | 必须明确的语义 |
|---|---|
| InspectionReport | 检查对象/范围、基线与验收器版本、检查/缓存时间、新鲜度、已覆盖/未覆盖、证据、结论；正常/异常/未知/过期不能混同 |
| Incident | 故障签名、来源报告、原能力契约、实际影响、去重次数、修复负责人/租约、暂停与观察状态 |
| EvolutionProposal | 主人目标来源、作用域、当前能力基线、期望变化、冻结验收、收益假设、预算与自动研发/发布范围 |
| GrowthJob | inspect/heal/evolve 的明确类型，父事件/提案、请求幂等键、固定策略代际、尝试与真实回执；不能以旧 check 动作猜测类别 |
| PurposeProfile | 首选与有序备选连接、各自原生档位、阶段覆盖、故障切换类别、触发/预算引用；禁止任意 URL、凭据或可执行文本 |
| ModelAttempt | 逻辑请求、尝试序号、实际连接/模型/档位、已派发标记、确定/未知结果、切换原因、费用与用量来源 |

新 `inspect` 只产出报告；事件消费者是否提交 `heal`、提案是否提交 `evolve` 由各自策略决定。复用 Task/Action/Artifact 的幂等、取消与 UNKNOWN 语义，不复制独立执行账本。对同一对象的候选提交使用基线代际检查；设置保存使用乐观并发，旧页面不能覆盖新配置。HTTP 202 只表示受理；动作完成、检测正常、故障复测通过、实验已发布为不同字段。

迁移将成长库从 schema 1 升到 2；保留原包、指针、任务和历史混合 `check` 记录，不重写旧结果。旧 route 初始化三个独立用途，旧 enabled 只保留周期检查，新 auto_heal=false。使用同一观察器，不凭升级启用新付费诊断/修复。启动器识别 schema 2 并拒绝 0.1.63 及更旧包接管；未来格式仍明确拒绝，不覆盖降级。

旧调用者仍走相同路径，但新请求的 `check` 统一收窄为纯检查；功能变化通过 `feature=growth-purposes-v2`、schema 及本契约明确声明。历史没有 purpose 的 check 在界面标记“历史混合维护”，不可当作新自检证据。取消、重启不重放、基线比较继续复用原实现；schema 迁移不是旧运行包兼容承诺。

<a id="dialogue-turn-contract"></a>
## 统一对话受理、意图与事件契约（proposed）

2026-10-18，供[分离改造](architecture.md#dialogue-separation-design)实施；**下表的完整统一语义对象与持久事件仍为 proposed**；已分别落地[回复回执子集](#dialogue-receipt-contract)与[意图影子子集](#dialogue-intent-shadow-contract)，不宣称已经实现完整 Turn/Intent/Work 协议。保留现有 `/api/chat`、任务与朗读接口，迁移时以适配器接入同一受理服务，不同时执行旧/新两条入口。

| 对象 | 最小字段 | 语义 |
|---|---|---|
| TurnInput | schema_version、client_event_id、conversation_id、input_source、final、text、context_refs；语音另有 capture_id/utterance_id/transcript_revision | 只接受最终输入提交；部分转写不建工作；原始录音默认不落长期会话库 |
| TurnReceipt | turn_id、conversation_revision、received_at、status | 只表示已接收本轮，不等于任务已开始；同 client_event_id 同内容返回原回执，异内容冲突 |
| IntentDecision | decision_id、turn_id、revision、parser/model_version、interaction_style、intents[] | 每项含 intent_id、类型、source_span、目标、scope_refs、depends_on、候选 capability、参数及 missing_fields；置信度可选且不能授予执行权 |
| WorkReceipt | turn_id、intent_id、task_id、request_id、goal_revision、status | 已入账才发受理成功；复用既有任务状态及回执，不能只由模型声明成功 |
| DialogueEvent | event_id、conversation_id、turn_id、generation、seq、kind、payload_ref | kind 包含 accepted/text_delta/text_final/task_receipt/clarification/error；每流排序，重连按游标读取或获取快照，不重放动作 |
| SpeechSegment | turn_id、generation、segment_id、text_ref、expression、status、played_offset | 区分 planned/generated/queued/playing/played/interrupted；只有播放回执推进已播记录 |
| ScopedCancel | target_type、target_id、expected_generation、request_id | reply/speech/capture/task 分开；旧取消不影响新代际；任务取消回执不等于外部效果已撤销 |

受理的校验、会话修订和幂等登记用短事务完成；锁外进行模型、STT/TTS、检索和规划。任务登记及其 outbox 同处 Task Runtime 事务；会话库与任务库不同事务时，以稳定的 `(turn_id, intent_id, goal_revision)` 受理键查询/对账，不能假装跨库原子提交。崩溃发生在“任务创建成功、聊天未获回执”之间，恢复只查询原键，不创建新任务。

输入箱、事件队列和音频缓存有上限，满时返回可理解的局部 backpressure，保留草稿/原请求号；不得无界创建线程、HTTP 长连接或模型调用。流式输出在提供商适配器逐步支持，旧整段接口可发单个 text_final；不能把整段响应套上流式字段后宣称首字延迟已经优化。任务事件使用持久游标，音频为短期数据，二者不能共用无限重放队列。

被新输入替代的 generation 不再播放或插入当前回复，但对应模型用量和 UNKNOWN 必须保存；未最终转写的语音不得改变正式任务。澄清关联 turn/intent/候选对象与有效修订，后续“好的”仅在绑定明确时解决该澄清，不能确认另一项工作。技术实现和取消能力有差异时必须在 capability 描述中声明，不谎称请求撤回后供应商立即停止计费。

<a id="dialogue-intent-shadow-contract"></a>
### 对话意图与限定任务受理契约（0.1.56—0.1.59）

**implemented；语义正确率只按[先导证据](delivery-validation.md#dialogue-intent-shadow-evidence)评价，完整 V-DLG 仍 proposed。** 网页普通对话经同一 `invoke_reply` 入口调用现有 Dialogue 子进程；一次模型回答同时提供自然回复与候选意图，不增加串行分类调用、不另启常驻模型。明确个人命令、本地计算、后台固定规划保持原接口。协议试点名单限 `vertex::gemini-3.1-pro-preview` 与 `vertex::gemini-3.8-flash`；其他供应商、其他版本及本地模型保持原自然回复协议，返回 `state=not_evaluated`。新增路线需独立格式/退化验证，名单不代表语义验收或执行授权。

模型输出规则和确定性校验唯一实现于 `runtime/node-host/jarvis_core/intent.py`。最外层只接受 `schema_version=1 / reply / interaction_style / intents`；最多八个意图，每个只接受 `kind / quote / disposition / capability / arguments / missing_fields`。类型为 chat/question/emotion/action/control/memory/other；交流风格为 neutral/warm/empathetic/concise；用途为 requested/discussed/negated/uncertain。记忆类型包括未来偏好/人格要求，情感类别描述当前交流用途，不是诊断或身份鉴定。

宿主要求 quote 在本轮输入中恰好出现一次，并计算 Unicode 码点的 `[start,end)` 原文范围；拒绝旧历史片段、重复键、未知字段、假能力和伪造参数。当前仅为 `mcp.documentation` 接受逐字来自该片段的 library/query；其他意图 capability=null、arguments={}。这只证明来源和结构合法，不能证明模型理解正确，也不代表连接已可用。模型回复协议最多 128 KiB，原文片段最多 4,096 UTF-8 字节，missing_fields 最多八项；超限或错误不扩大预算。

成功回执增加 `intent_decision`：宿主生成 `decision_id / turn_id / revision / intent_id`，带引擎版本、实际供应商/模型、state、interaction_style、intents。识别层仍输出 `mode=shadow / automatic_execution=false / execution=not_submitted`；0.1.57 引擎为 `dialogue-intent-v2`。仅在宿主完成限定文档任务受理后，改为 `mode=bounded_documentation / automatic_execution=true / execution=submitted` 并附实际 task_id。稳定 ID 由原请求号派生；同请求查询复用原回执，不靠文本去重，也不把不同新请求合并。

JSON 不合规时，有完整 reply 就保留正文并标记识别失效；普通非 JSON 回答可继续阅读；破碎协议不作为正文/文件自动保存。取消、UNKNOWN、进程退出沿现有规则，不为修复分类再次调用模型。输入预算放不下识别协议时，在调用前回退普通回答并返回 `state=skipped_budget`，不挤掉当前输入或新增调用。完整候选随原回复回执受限保存，临时会话仍不入持久表；普通会话归档只额外保留简短识别摘要，详细可操作卡仅在本次回复或回执取回时建立，不加入后续模型历史。

文档候选的按钮仍只请求[只读能力检查与草稿准备](#mcp-documentation-task-contract)。0.1.57 另由宿主按[限定准入规则](tasks-agents.md#conversation-intent-routing)检查本轮回复及原输入，返回 `work_admission={status,capability,automatic,reason,reason_code?,task_id?,request_id?}`；submitted 必须对应已持久受理的真实任务。未通过时保留正文与原因，不重试模型。受理后回复持久化失败则返回 UNKNOWN 并保留已取得的 work_admission，任务仍可从本会话账本找回，不能自动重放。尚无通用多能力规划与多行动依赖执行；限定报告目标修订见下文。

0.1.59 增加可替换的 `WorkAdmission` 端口，保留文档规则，扩展已验范围的样例报告。新增回执 `mode=bounded_sample_report`，`work_admission.operation=create/revise/cancel`；创建/替换为 `status=submitted`，指定取消为 `status=controlled`，附 `task_status` 和实际 task_id；未执行为 not_submitted 及原因。仅实际采用的意图片段标记 submitted/controlled，同行的情绪/问答仍是 not_submitted。新任务请求键按会话/轮次派生，不向浏览器开放内部 `_origin` 或 `_replacement`。

任务账本按需增加 `report_admissions(task_id,document)` 与 `report_controls(request_id,arguments,result)`，没有第二套任务状态或队列。前者与新任务、旧任务取消同事务保存来源及替换关系；后者保存唯一取消回执。原样例任务参数和执行协议保持不变。任务详情增加 `report_control={relative_path,revision,admission}`，修订摘要绑定原行动身份/参数/所有权/策略；不是全局可变计数。旧 Host 忽略新增辅助表，但在途版本/源码绑定仍须核对，不保证带待执行任务直接回退。范围规则归[受理规则](tasks-agents.md#conversation-intent-routing)。

<a id="dialogue-receipt-contract"></a>
### 已实现的回复回执接口（0.1.48—0.1.49 / dialogue-receipt-v1）

状态 **implemented；限定验证见[运行证据](delivery-validation.md#dialogue-receipt-evidence)**。初始0.1.48接口只调用既有 `ChatService.reply`；0.1.57/0.1.59的限定任务受理见上节，既有明确个人指令仍沿原个人核心处理。旧 `/api/chat` 保留兼容，与新接口共用 `invoke_reply`，每条输入只走一条入口。

| 接口 | 字段与返回 | 边界 |
|---|---|---|
| `POST /api/dialogue/turns` | `instance_id/conversation_id/request_id/chat`；`chat` 采用既有聊天校验；202 返回回执 | 三个 ID 均为 32 位小写十六进制；当前实例内同 request_id 同内容返回原记录，异内容 409；相同会话已有执行未结束时 409，不排无限模型请求 |
| `GET /api/dialogue/turns/{request_id}?conversation_id=…&instance_id=…` | 返回 `request_id/conversation_id/instance_id/status/revision/finished/expired/cancel_requested`，完成后可含 `result` | nonce 必须匹配；不同会话 404、旧实例 409；只查询，绝不启动模型 |
| `POST /api/dialogue/cancel` | 仅三个 ID，无 `chat` | 可先取消后受理；取消只绑定该回复，核心停下后仍允许登记；不取消任务或 TTS |
| `GET /api/resources` 的 `runtime.dialogue` | active、retained_results、issued_ids、reserved_bytes、容量与 TTL | 只有数量、字节和状态，不含提示/答复；设置页面按已有可见性采样 |

状态为 `RUNNING → SUCCEEDED/FAILED/UNKNOWN`，取消时经 `CANCELLING → CANCELLED`。当前实例持有的执行在 worker 退出后才将 `finished` 置真；重启收口的旧实例请求则以 UNKNOWN 结束本地观察，不表示远端或旧实例已停止；用户发出取消不会提前归还槽。取消后迟到文本不再采用；已经提交的个人核心修改仍报告提交结果，不虚称撤销。模型异常/连接不确定返回 UNKNOWN；线程创建失败可确认未调用模型。两条入口合计最多两个实际回复线程；每个会话至多一个。任务队列仍有自己的入口与容量。

每实例最多 4096 个已发编号；正文最多保留 64 个完成结果，单结果最多 2 MiB，总预留 32 MiB（包括输入和进行中结果预算）。完成结果 600 秒后在访问/采样时可释放；已用 ID 的墓碑保留到实例结束，正文过期也不能自动重做。复用的取消句柄登记还有 256 条/600 秒保留上限；任一容量先满都明确拒绝新受理，草稿仍由前端保留。取消先于受理的短回执同样受数量上限与正文淘汰约束。

**恢复边界：**0.1.48 仅有内存回执；0.1.49 的普通已归档会话增加下述持久恢复，临时会话与未声明持久范围的兼容请求仍只在内存。POST 响应丢失时，浏览器以原 ID 查询，不再次 POST；GET 临时失败继续查询，页面等待上限仍为 125 秒，单次 HTTP 最多 8 秒。超时、回执过期或实例变化不会自动重发。既有任务账本的恢复能力不受此回执替代；新静态资源缺失时旧同步聊天仍可用，界面显示降级。


<a id="dialogue-recovery-contract"></a>
#### 普通会话的持久回复恢复（0.1.49）

`DialogueJournal` 与 `ConversationStore` 共用 `conversations.db`，新增 `dialogue_owner` 和 `dialogue_receipts` 两张表，不建立第二个任务账本。普通输入明确携带 `personal_context.temporary:false`；网页先完成用户消息归档，再提交模型请求。存储不可用时返回未受理，不静默降为不可恢复的普通调用；临时会话不写恢复表。接口未声明该字段的兼容请求继续只用内存，不能宣称可跨重启恢复。

| 操作或字段 | 规则 |
|---|---|
| `GET /api/dialogue/recover/{request_id}?conversation_id=…` | 当前页面 nonce＋精确会话 ID；仅查询，不接收模型输入。不同会话、已删除或无记录返回 404。可跨实例读取持久记录 |
| 回执新增 `durable` / `origin_instance_id` | `durable:true` 表示回复已登记到恢复表；`origin_instance_id` 是实际受理实例，`instance_id` 是当前查询实例。完成结果提交失败时显示 UNKNOWN，不把内存成功当作已经可靠保存 |
| 会话消息可选 `reply_ref` | 32 位小写十六进制；定位请求/回复，不授予读取、执行或取消权。旧会话无需迁移；旧版本不认识此字段，回退前须核对归档格式兼容 |
| 原编号再次提交 | 在记录保留期内同内容返回旧结果/UNKNOWN，异内容冲突；没有任何恢复分支自动调用模型。旧实例 POST 仍被实例边界拦截 |
| 新 Host 接管 | 旧 RUNNING/CANCELLING 原子改为 UNKNOWN，已有成功保留；旧 owner 的迟到写入不能覆盖。个人修改可能已提交，需检查原操作记录；不能把 UNKNOWN 解释为失败或已撤销 |
| 删除会话 | 同一 SQLite 事务清空关联恢复正文并标记删除，阻止迟到完成重新写回；不删除任务账本、导出文件、语音文件或外部副本 |

只额外存请求 ID、会话 ID、owner、输入摘要、状态、时间、取消标志和有限结果，不复制提示正文、历史、附件载荷或凭据。回复正文可能包含私人内容，按本机会话数据保护。最多 8192 个恢复编号、64 个结果、16 MiB 结果正文；正文默认 24 小时、编号默认 7 天，访问/新受理/启动时回收，容量先满可提前回收正文但保留编号，编号满时明确拒绝。此限额叠加已有内存和句柄上限；不是无限持久保存，文件物理分配大小也不等于正文计数。受理前取消的内存墓碑仍只保证当前实例，不扩称为已持久受理。

SQLite 写锁等待上限 150ms。受理落盘失败不调用模型；完成落盘失败释放执行槽并显示 UNKNOWN。恢复表初始化失败不拖垮整个 Host，普通持久受理报告不可用；临时文字、原任务和控制仍按各自入口工作。线程/旧 Host 故障隔离和 CPU/GPU 公平性尚未因此完成。


<a id="dialogue-process-contract"></a>
#### 对话与后台模型进程边界（0.1.54）

网页旧 `/api/chat` 与新回复回执共用 `invoke_reply`。0.1.54 将普通模型回复的上下文准备、路由和网关调用一起交给 `DialogueProcesses.reply`；个人记忆/人格指令、可直接求值的精确计算、回复回执和持久恢复仍由 Host 负责。子进程拒绝个人指令，避免被取消的进程承担个人事务。涉及附件/会话要求而需模型处理的非显式算式也走独立回复进程。

自然语言目录规划、代码/文本技能报告、REA 中文解释通过另一个单槽池调用同一固定 Worker；它不借用两个对话槽。父进程保留模型选择、任务账本、计划/来源复核和真实产物提交。按需记忆候选、成长和网页操作规划尚未迁移，不能据此宣称全部后台能力都已隔离。上下文读取仍沿用现有范围校验；允许原有数据库建表、技能选择审计及网关用量日志，不是只读 OS 沙箱。

| 边界 | 当前实现 |
|---|---|
| 生命周期 | Windows 上按请求启动；普通回复最多 2 个、已接入后台分析最多 1 个，空闲不保留；一次完整回复一个进程。使用项目依赖路径和实际 Python 解释器，避开虚拟环境启动器的额外子进程 |
| IPC | 私有 stdin/stdout JSON 行帧；请求含随机标识、经入口校验的本轮上下文引用/历史/附件、配置路径、数据目录、原授权代际与可选任务 ID；子进程按原规则筛选上下文。输入最多 24 MiB、输出累计最多 2 MiB、最多 16 帧；仅接受 context/model 阶段和单个结果，核对随机标识与顺序。不接受模型提供的程序路径/执行入口，不在参数、临时文件或监控中复制正文和密钥 |
| 资源约束 | 发送输入前加入 Windows Job；单个 Job 最多 1 个进程、提交内存上限 384 MiB，kill-on-close。上限是保护预算，不是模型权重或实测占用；进程以当前用户运行，能读取既有凭据库，并非权限沙箱 |
| 时间预算 | 每次回复总预算 110 秒；启动/上下文阶段每段 12 秒，卡住时回收，不仅依赖函数返回后才检查时间。保留网关单响应最多 60 秒及原自动路由预算；兼容 probe 子入口仍是 `min(85, max(1, response_deadline+20))` 秒。宿主约每 0.5 秒复查核心及任务检查点，取消/进程状态约 20ms 检查；这些周期不是负载下延迟保证 |
| 停止与失败 | 发送前取消可确定未调用；输入开始传递后崩溃、超时、坏包或回收保守返回 UNKNOWN。现有回复层可将明确取消映射为 CANCELLED，但保留 `outcome_uncertain:true` 与 `cancel_requested`；禁止自动重发/切供应商。回收并等待本地进程退出后才释放槽。供应商或本地模型服务中的请求可能继续 |
| 状态与授权 | 子进程沿用原核心授权代际；有任务 ID 时独立核查该任务，网络准入短事务同时核查任务取消。父进程保留超时/取消检查点，不把函数序列化给子进程。不初始化核心、不接管任务队列、不提交个人资料；取消/核心停止后不采用迟到输出 |
| 正常与异常退出 | 成功结果进入原回执/恢复流程；Host 正常关闭回收活动 Job，Host 异常退出由 Job 关闭回收。进程被终止时供应商用量日志可能停在 RESERVED/DISPATCHING，不能据此认定零费用；不重放该日志 |

不支持此后端或启动失败时，对话模型明确不可用，不静默退回 Host 执行。新请求可以重新创建进程；没有守护进程重启循环、额外队列、消息中间件或新依赖。任务规划/解释取消时先回收子进程，再让任务执行线程退出，避免下一个任务叠加尚未退出的调用。供应商配额、本地 LLM/GPU 和整机资源仍可能被不同通道共同使用，独立进程槽不等于独占推理容量。监控见[进程观察](health-maintenance.md#dialogue-runtime-monitoring)，验证见[0.1.54 证据](delivery-validation.md#conversation-lanes-evidence)。

<!-- book-footer:start -->
[返回全书目录](README.md#book-tree) · [上一章：主人利益原则、身份授权与停止控制](security-sovereignty.md) · [下一章：技术栈、源码目录与运行数据](stack-project-layout.md)
<!-- book-footer:end -->
