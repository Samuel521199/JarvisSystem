# 公共接口与数据契约

> 状态：proposed（总体设计）；局部 implemented（K0 六类契约、预检、主人恢复、固定 Worker、浏览器消息、网页队列、项目导出与 0.1.12 单次聊天取消） · 更新：2026-10-15  
> [文档入口](README.md) · [维护规则](MAINTENANCE.md) · [架构图册](architecture-atlas.md)

<!-- book-nav:start -->
[全书目录](README.md#book-tree) › [第二篇 · 核心与工程基础](README.md#part-foundation) › 第 07 章 · 公共接口与数据契约

## 本章导航

- [7.1 K0 当前实现与验证](#k0-contracts)
- [7.2 K1/K2 下一轮最小接口面](#next-control-contracts)
  - [7.2.1 0.1.5 已实现的只读预检报告](#preflight-contract)
  - [7.2.2 0.1.7 已实现的固定 Worker 消息](#worker-contract)
  - [7.2.3 0.1.8 浏览器任务与动作契约](#computer-contract)
    - [7.2.3.1 0.1.10 网页任务与队列接口](#computer-web-contract)
  - [7.2.4 0.1.13 共用后台任务接口](#task-queue-contract)
  - [7.2.5 0.1.15 本机运行版本与临时目录契约](#runtime-slots-contract)
  - [7.2.6 0.1.14 旧版停止状态兼容消息](#recovery-contract)
  - [7.2.7 0.1.11 项目与文本导出接口](#project-workspace-contract)
  - [7.2.8 0.1.21 聊天附件接口](#chat-attachments-contract)
  - [7.2.9 0.1.12 单次聊天取消接口](#chat-cancel-contract)
  - [7.2.10 设置总览资源快照接口（2026-10-16 增量）](#resource-usage-contract)
  - [7.2.11 模型后台配置与统计接口（0.1.19）](#model-admin-contract)
- [7.3 记忆组件的替换契约（proposed）](#memory-provider-contracts)
- [7.4 接口与数据契约](#interfaces)
  - [7.4.1 模块生命周期](#interfaces-1)
  - [7.4.2 任务与动作分离](#interfaces-2)
  - [7.4.3 事件信封](#interfaces-3)
  - [7.4.4 技能和模块包清单](#interfaces-4)
  - [7.4.5 接口类型选择](#interfaces-5)
- [7.5 资源租约、本地组件与安全事件契约](#extensions-3)
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

<a id="chat-attachments-contract"></a>
### 0.1.21 聊天附件接口

`POST /api/chat` 保留 `message/provider/history/model/reasoning`，增加可选 `attachments` 数组；不传附件的旧客户端继续有效。`history` 的 user 消息可含同名数组，assistant 不可含附件。仅接受两种严格对象：文本 `{kind: "text", name, text}`；图片 `{kind: "image", name, media_type, data}`，data 为无前缀标准 Base64，仅允许 PNG/JPEG/WebP。name 是展示名，禁止路径分隔符和控制字符；不接受文件路径、远端 URL、工具角色或任意字段。服务端复查类型、编码、文件签名及大小，不能只依赖网页校验。

聊天 JSON 体上限 12 MiB；其他控制接口保留原有 128 KiB。每条最多 8 个附件，文本单个最多 48 KiB UTF-8；正文加展开后的文本附件最多 64 KiB。传入历史最多 20 条、32 KiB 展开文本；整个请求（含历史）最多 8 张图片、8 MiB 原始图片字节，单张最多 4 MiB。核心再按所选模型预算裁剪旧轮次，不将图片 Base64 误算为文字 token，也不忽略附件正文的输入占用。

原生网关按接入方转换为 Responses input_image、Gemini inlineData、Anthropic image/source 或兼容聊天 image_url 的 data URL。能力未知或纯文本模型拒绝图片请求，自动路由跳过不兼容候选。日志仅保留完整请求摘要与数字计费信息，不保存附件正文或图片。对话的内存保存和恢复行为归[输入交互](interaction-persona.md#composer-attachments)。

<a id="chat-cancel-contract"></a>
### 0.1.12 单次聊天取消接口

0.1.12 的网页 `POST /api/chat` 采用文本 JSON（0.1.21 的扩展见[附件契约](#chat-attachments-contract)），新增可选头 `X-Jarvis-Request`（32 位小写十六进制随机 ID）；旧客户端不传该头仍可聊天。`POST /api/chat/cancel` 严格接受 `{request_id}`，要求原 Host、Origin、nonce 校验；只设置该 ID 的取消信号，不能提交全局停止、恢复或浏览器任务参数。取消接口不依赖核心仍处于运行状态。

返回 `CANCEL_REQUESTED` 仅证明服务收到信号，`FINISHED` 表示该请求处理已结束；两者都不能证明远端已撤销计费。取消先于聊天 POST 到达时保留取消标记，随后同 ID 不调用模型；重复聊天 ID 返回 409，不自动创建第二次生成。进程内最多保存 256 个控制句柄；未开始/已结束记录 10 分钟后可回收，正在处理的记录不淘汰。服务重启即失效，没有增加持久会话或另一套 Task 账本。

传输层将事件交给 ChatService 与模型网关，取消后屏蔽回复；调用槽位要等真实处理线程退出才释放。前端用每次生成独立的 AbortController 和运行标识隔离迟到回调；停止等待不等于撤销已发送的文件写入。协议实现见 [server.py](../apps/web/server.py)，网关状态及认证/远端限制归[模型调用边界](models-offline.md#section-896f72aed9a9)。

<a id="resource-usage-contract"></a>
### 设置总览资源快照接口（2026-10-16 增量）

`GET /api/resources` 为固定、只读的本机接口，无查询参数。遵循现有 Host/Origin 校验并要求页面 `X-Jarvis-Nonce`，不引入用户密码或额外登录。返回 `scope: "machine"`、UTC `sampled_at`、`refreshing`、`stale`、`age_seconds`、`cpu_percent`、`gpu_percent`、`memory` 与 `adapters`；未知值为 `null`，适配器未知时为空数组。`memory` 包含 `used_bytes/total_bytes/percent`；适配器记录包含 LUID `id`、`name`、`dedicated_total_bytes/shared_total_bytes`、可用时的 `dedicated_used_bytes/shared_used_bytes`。容量以字节传输，前端转换 GiB。此接口不返回进程清单、命令行、凭据或对话。

调用立即返回已有缓存或初始未知值，并按需触发单次采样；`refreshing` 只表示采样在途，不是助手正在执行用户任务。`sampled_at` 为空或 `stale` 为真时界面不得展示缓存百分比为当前值。口径与缓存生命周期唯一规则见[整机资源统计](health-maintenance.md#machine-resource-usage)。

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

共同记录至少需要：稳定对象 ID、来源与内容摘要、节点及节点实例代次、事件序号与因果前驱、事实有效时间与系统记录时间、修订/撤销关系、现实或模拟域、主体/分享范围、保留策略与证据状态。时间字段不能替代因果关系；来源签名证明发送方，不证明内容真实。

索引版本由源资料修订、切片器/分词器版本、嵌入模型与权重修订、维度、归一化、池化、query/document 前缀和量化配置共同标识。相同维度不代表相同向量空间。检索回执还需标明事实提交水位、已索引水位及结果覆盖范围，不能只返回一段没有来源的自然语言。

记忆事件及其 outbox 在记忆存储的同一事务中持久化，接收端 inbox 去重与事实应用同样原子提交。它们与 `control.db` 的任务/动作事务彼此独立，跨域靠稳定引用与对账；不声称跨数据库的普通写入天然原子。接口升级需提供导出、导入、重放、拒绝不兼容版本和删除传播的兼容证据。

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

<!-- book-footer:start -->
[返回全书目录](README.md#book-tree) · [上一章：主人利益原则、身份授权与停止控制](security-sovereignty.md) · [下一章：技术栈、源码目录与运行数据](stack-project-layout.md)
<!-- book-footer:end -->
