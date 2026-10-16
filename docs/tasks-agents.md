# 任务、动作、多 Agent 与资源调度

> 状态：完整调度与 Agent 设计 proposed；0.1.16 增加共用队列内存准入，后台通用规划与团队尚未实现 · 更新：2026-10-16  
> [文档入口](README.md) · [维护规则](MAINTENANCE.md) · [架构图册](architecture-atlas.md)

<!-- book-nav:start -->
[全书目录](README.md#book-tree) › [第三篇 · 智能运行与多设备协同](README.md#part-runtime) › 第 11 章 · 任务、动作、多 Agent 与资源调度

## 本章导航

- [11.1 任务状态机](#interaction-tasks-3)
- [11.2 首期后台任务与有限工具循环](#initial-task-loop)
  - [11.2.1 0.1.13 本机持久队列（含浏览器）](#browser-durable-queue)
  - [11.2.2 0.1.16 后台任务内存准入](#queue-resource-admission)
  - [11.2.3 从一句需求到可检查的结果](#section-4586f8e644b1)
  - [11.2.4 把失败收口在正确的位置](#section-51878ee61b73)
- [11.3 多 Agent 组织](#interaction-tasks-4)
- [11.4 冲突与调度](#interaction-tasks-5)
- [11.5 核心端到端流程](#end-to-end-flows)
  - [11.5.1 聊天同时完成任务](#end-to-end-flows-1)
  - [11.5.2 未知外部动作结果](#end-to-end-flows-3)
- [11.6 Agent 自主生成、部署、分工与回收](#agent-factory)
  - [11.6.1 Agent 数量与类型不写死](#agent-factory-1)
  - [11.6.2 自主组队流程](#agent-factory-2)
  - [11.6.3 工厂和团队控制器](#agent-factory-3)
  - [11.6.4 委派不会扩大权限](#agent-factory-4)
  - [11.6.5 生命周期](#agent-factory-5)
  - [11.6.6 关键契约](#agent-factory-6)
- [11.7 Agent、模型与模块的统一资源自调度](#resource-scheduling)
  - [11.7.1 所有工作使用同一资源账本](#resource-scheduling-1)
  - [11.7.2 优先级](#resource-scheduling-2)
  - [11.7.3 自适应决策](#resource-scheduling-3)
  - [11.7.4 能力快照与重新规划](#resource-scheduling-4)
  - [11.7.5 从小到大的实测扩展](#resource-scheduling-5)
- [11.8 补足预算与委派协议](#critical-review-6)
<!-- book-nav:end -->

<a id="interaction-tasks-3"></a>
## 任务状态机

![task-lifecycle](diagrams/task-lifecycle.png)

[矢量图](diagrams/task-lifecycle.svg) · [可编辑图源](diagrams/task-lifecycle.mmd)


取消是有状态操作。已经发送的消息、完成的支付、发生的机械运动不能通过取消任务自动撤销。Unknown 不是失败，也不允许盲目重试。

<a id="initial-task-loop"></a>
## 首期后台任务与有限工具循环

本节总体是 K1/K2 的 proposed 执行语义，实施顺序由[核心路线](core-bootstrap.md#next-implementation)维护；已实现的浏览器子集单列在下节。`CoreService.inventory` 仍在调用路径内执行，`ChatService` 只生成文字；聊天请求槽、浏览器队列和多 Agent 是不同能力。

K1 先把固定能力放入独立 Worker，K2 再加入规划。完整闭环采用现有[聊天与任务时序图](#end-to-end-flows-1)，首期只运行一个后台任务 Worker，并为前台交互及确定性状态/停止请求保留处理能力。排队、任务持续运行和云端并发额度分别展示；后台不能占满所有前台请求槽。

<a id="browser-durable-queue"></a>
### 0.1.13 本机持久队列（含浏览器）

此节是当前目录/浏览器共用队列的执行语义权威；[使用入口](core-bootstrap.md#web-computer-console)、[HTTP 接口](contracts.md#task-queue-contract)和[验证证据](delivery-validation.md#k1-progress-evidence)分别维护操作、字段与测试结果。调度实现位于核心 `task_queue.py`，浏览器适配器保留兼容包装；语音、Agent 与任意代码尚未接入。

- **受理与排序：**校验固定目录或明确范围的浏览器任务后，在一个 SQLite 事务中写入原 Task/Action 及 `computer_queue` 附属登记。保留旧表名以兼容已有任务，没有新增第二个队列。HTTP 返回前已持久保存；附表只保存 FIFO 次序、代码版本、绑定摘要和 UNKNOWN 检查标记，不复制任务状态。`demo_digest` 历史列对目录任务存固定执行源码/profile 摘要，对浏览器演示存内容摘要。最多 20 个等待任务、1 个执行任务，满队列事务整体回滚；重复请求不占新位置，同 ID 改参数被拒。
- **执行与资源：**一个网页进程内的队列线程复用原全局执行锁；领取时在 `begin_dispatch` 的事务内再次检查当前队列宿主、暂停标志、排序、版本与待核对结果，再由原执行器检查安全代际/取消。聊天仍有独立两个请求槽。空队列使用事件等待；外部执行锁暂忙时仅重新检查准入，不重复模型或页面动作。未增加常驻浏览器、模型、消息代理或集群依赖。
- **暂停与取消：**暂停只阻止下一个任务开始，已派发任务继续收口；取消指定等待任务直接变为 CANCELLED，未产生页面动作。取消在途任务沿用 CANCELLING 与已有副作用核对规则。核心停止与队列暂停是不同状态，继续队列不能清除安全锁存或授予新代际。
- **关闭与重启：**关闭网页页签不会取消任务。正常关闭服务暂停队列、请求取消在途任务并保留等待项。进程崩溃后先依靠执行锁判断原 Worker 是否仍存在；无回执的 DISPATCHING 变为 UNKNOWN，PREPARED 保留。存在等待/在途项或原暂停状态时，新服务默认暂停，用户检查后点击继续。旧版、演示内容变化或旧安全代际任务不能默默换版本执行；需核对、取消后明确新建。
- **服务交接与未知结果：**新网页服务用持久宿主令牌阻断旧调度器继续领取，执行锁保证原在途任务与新任务不重叠。出现新的 UNKNOWN 会暂停后续派发；点击继续只标记当时已存在的 UNKNOWN 已被用户检查，不把其改成成功或重放。若旧宿主的在途任务在点击继续后才成为 UNKNOWN，新宿主仍再次暂停。
- **历史与人工继续：**终态记录继续保留；UNKNOWN、FAILED、CANCELLED、CONFIRMED 的同请求 ID 不自动重做。`unknown_reviewed` 只记录“允许继续后续任务”，不代表未知效果已被证实。网页展示最多 30 条，未完成优先，完整账本不因列表截断而删除。CLI 可查询已排队任务，但不能绕过队列暂停直接派发同一任务。

目录任务只枚举实例初始化时绑定的样例根，不能通过提交参数改为任意项目目录；仍由固定 LPAC Worker 返回元数据，Host 验证摘要并提交产物。取消、停止、版本不符或失败时不伪造产物成功。网页队列启动时尝试回收已登记 Worker 残留，完整删除边界归[安全章](security-sovereignty.md#worker-isolation)。

本版仍是同用户 Host 的受限单机实现，不是系统服务、高可用调度器或任意代码沙箱；任务版本绑定不等于防止恶意同用户修改源码。队列不能撤回已发出的云端请求或外部副作用，也不承诺服务关闭后继续工作。未提供定时触发、优先级抢占、依赖图或自动故障重试。

<a id="queue-resource-admission"></a>
### 0.1.16 后台任务内存准入

当前 [resources.py](../runtime/node-host/jarvis_core/resources.py)在共用队列领取前及 PREPARED → DISPATCHING 事务内各检查一次内存。阈值唯一配置为 [resource-profile.json](../config/resource-profile.json)：为前台保留 1024 MiB，目录任务估算 256 MiB，浏览器任务估算 1024 MiB。可用物理内存与当前 Host 的可提交内存均须达到“前台余量 + 任务估算”；数据来自 Windows [S128](references.md#s128)。这些数字是启动准入估算，不是 OS 实际预留或浏览器硬配额。

不足或读取失败时，任务仍是已持久受理的 PREPARED，不创建派发意图、不调用模型，队列显示等待资源；每 2 秒重查。恢复须再留 256 MiB 余量，并经至少 2 秒、两次健康观察，避免临界值反复启停。状态查询只读取最近快照，不推动恢复计时。未知能力、无效配置拒绝启用，不静默取消检查。

等待不占聊天请求槽，也不影响状态、取消或继续提问。取消等待任务不会执行它；资源恢复不解除人工暂停、重启核对或 UNKNOWN，也不改变 FIFO。当前在途任务沿原预算收口，不因新的内存读数被全局终止。界面关闭和进程重启仍沿用原队列语义。源配置修改在下一次创建队列时生效，暂未提供设置界面。

此增量只覆盖通过共享队列提交的目录/浏览器任务；直接 CLI、模型进程、GPU、跨进程全局租约、优先级抢占及实际 OOM 恢复尚未纳入。一次 OS 快照也不能保证派发后其他软件不再分配内存；已有固定 Worker 限额保留。测试和真实短时负载证据见[资源准入验收](delivery-validation.md#resource-admission-evidence)，不能据此关闭完整普通 PC 验收。

<a id="section-4586f8e644b1"></a>
### 从一句需求到可检查的结果

1. 会话入口识别聊天、查询状态或任务请求。任务目标与授权范围持久受理后返回任务号；缺必要输入时显示等待，不虚构已启动。
2. 检索有效知识和已发布技能，只向模型提供所需上下文。规划器输出[结构化候选计划](contracts.md#next-control-contracts)，不能提交未经登记的工具或扩张文件/网络范围。
3. Host 先校验完整计划的依赖、契约、授权和资源，再派发当前一步；每一步执行前重新核验当前门禁和撤销状态，不能把计划通过当作永久授权。
4. Worker 返回可检查产物与回执，Host 验证后更新账本。后续步骤只引用已确认、摘要一致的产物，不能把模型说“成功”当作回执。
5. 任务运行时据结果决定下一步、结束或等待。模型修正次数、动作数、时间和资源受本次任务策略约束，耗尽时保留检查点；不新增账户累计调用次数上限。
6. 会话展示状态和结果链接；失败、被取消、等待和 UNKNOWN 保持各自含义。没有能力时返回缺口，K3 后才可将缺口转成研发任务。

<a id="section-51878ee61b73"></a>
### 把失败收口在正确的位置

| 情况 | 首期处理 |
|---|---|
| 结构化输出无效或含未知能力 | 不执行；在当前任务范围内有限修正，仍无效则说明原因并结束或等待 |
| 模型切换、上下文压缩或规划重试 | 不重新执行已确认动作；使用账本结果重新规划，保留原动作身份和产物引用 |
| Worker 崩溃或回执丢失 | 先按动作账本进入 UNKNOWN 并对账；“只读”或“看起来可重试”不构成自动重放的充分证据 |
| 网页刷新、断连或重新打开 | 通过任务 ID/请求 ID 读取快照；任务归 Host 所有，不依赖页面存活；关闭会话不隐式取消已受理任务 |
| 主人改目标 | 创建目标修订；新步骤基于新修订，已发出的动作保留实际状态，不伪装成从未发生 |
| 取消与执行竞态 | 停止派发后续动作，核对在途回执；未确认停止的部分显示待确认，不能提前报取消完成 |
| 工具结果或文件中出现指令 | 作为带来源的数据处理，不改变根规则、授权或调用范围；需要执行的新意图仍经过正常准入 |

Worker 的暂存文件不直接成为正式产物。由产物入口核对路径、大小、类型和摘要，再登记回执；成功但未登记的文件按可查证证据对账，不靠文件存在猜测整个任务完成。首期不引入第二个通用工作流引擎，团队工厂留待已有单任务链路经验证后扩展。

<a id="interaction-tasks-4"></a>
## 多 Agent 组织

以下是可复用角色示例，不是类型或数量上限。系统可按能力与任务生成新蓝图、重组团队，见[Agent 自主生成、部署、分工与回收](tasks-agents.md#agent-factory)；简单任务不全部启用：

| 角色 | 责任 |
|---|---|
| Planner | 目标分解、依赖和验收设计 |
| Researcher | 查询资料、整理来源与冲突 |
| Designer | 设计方案与可编辑产物 |
| Builder | 编写代码、脚本与工具 |
| Executor | 在获授权环境执行具体步骤 |
| Verifier | 检查产物、运行测试、读取真实状态 |
| Coordinator | 汇总、资源分配、去重与沟通 |

Agent 是带模型、工具、状态和任务契约的工作者。共享的是明确的任务上下文与产物引用，不把全部私人记忆复制给每个 Agent。

每个委派包含：目标、输入、输出格式、可用工具、不可改动范围、预算、截止时间、父任务、验收标准。多个 Agent 的一致意见不能替代可检查的结果。[S10](references.md#s10)

<a id="interaction-tasks-5"></a>
## 冲突与调度

桌面 GUI 同时只能有一个有控制权的操作者；其他任务优先走 API 或排队。
- 同一文件使用版本/写锁；代码 Agent 采用独立分支或工作目录再合并。
- 设备网关维护资源代际，不由 Agent 自行抢占。
- 主人交互可提高优先级，但不可强行打断必须完成的设备安全步骤。
- 用户更新目标时创建目标修订，保留旧产物与进行中的动作状态。

<a id="end-to-end-flows"></a>
## 核心端到端流程

以下业务流程均以安全状态有效且未锁存为前提；[主人利益最高原则、独立监督与锁存关停](security-sovereignty.md#sovereignty-shutdown)停止控制可以中断任何流程。

<a id="end-to-end-flows-1"></a>
### 聊天同时完成任务

![parallel-dialogue-task](diagrams/parallel-dialogue-task.png)

[矢量图](diagrams/parallel-dialogue-task.svg) · [可编辑图源](diagrams/parallel-dialogue-task.mmd)

<a id="end-to-end-flows-3"></a>
### 未知外部动作结果

```text
请求发出 → 网络断开/进程崩溃 → 结果 UNKNOWN
    → 查询外部系统 / 读取设备状态 / 使用同一幂等标识查询
    → 已完成：登记回执并验证
    → 明确未执行且允许重试：重试原意图
    → 无法确认：保持等待，必要时由主人选择
```

不得在“无法确认”分支默认重试，更不能将日志重放解释为再次执行命令。

<a id="agent-factory"></a>
## Agent 自主生成、部署、分工与回收



<a id="agent-factory-1"></a>
### Agent 数量与类型不写死

Jarvis 根据任务、环境、已连接设备和资源状况，自主判断应该使用普通程序、单 Agent、固定工作流还是动态团队。角色名称与数量不是预置名单的上限；新领域可以产生新的蓝图。

“可持续扩展”意味着接口和存储没有人为固定的角色数量上限，可以随资源增加扩容；每次部署仍有明确的资源、预算、委派深度、时间与终止条件。有限机器和预算不支持字面意义的无限活跃实例。

| 对象 | 含义 |
|---|---|
| AgentBlueprint | 可复用的角色、能力、工具、输入输出和验证配置 |
| AgentInstance | 带唯一 ID、任务、记忆范围和生命周期的逻辑身份 |
| Worker | 真正执行程序或模型请求的进程/容器 |
| ModelDeployment | 提供推理的模型服务，可被多个 Worker 共享 |
| TeamPlan | 一次任务的角色、依赖、分工、预算和部署方案 |

这些对象不是一一对应。许多逻辑角色可以休眠或共享少量 Worker；一个复杂任务也可以使用多个工作者。生成 Agent 通常先生成配置与工作流，只有确实缺少能力才研发新代码。

<a id="agent-factory-2"></a>
### 自主组队流程

![agent-team-lifecycle](diagrams/agent-team-lifecycle.png)

[矢量图](diagrams/agent-team-lifecycle.svg) · [可编辑图源](diagrams/agent-team-lifecycle.mmd)


新设备接入后先认证与能力探测，再在必要时生成对应 Agent；不因发现设备就自动取得控制权。设备离线后撤销对应可用能力，持有该设备任务的 Agent 保存状态并重新规划。

<a id="agent-factory-3"></a>
### 工厂和团队控制器

Agent Factory：寻找已有蓝图、生成候选蓝图、验证工具与契约，登记不可变版本。
- Team Controller：观察任务结果，决定重分工、拆分合并和扩缩，不自行增加总预算。
- Capability Observer：维护带时间戳的设备与模型能力快照；执行前重新验证关键能力。
- Deployment Scheduler：选择节点、申请资源、部署 Worker，并处理失败和迁移。
- Agent Registry：维护身份、版本、父任务、租约、状态和产物。
- Resource Governor：统一管理 Agent 与普通模块的配额，不按 Agent 名字分配特权。

这些是逻辑模块，初期可组合到现有工作者和 node-host 中。

<a id="agent-factory-4"></a>
### 委派不会扩大权限

子任务继承主人目标与 G0，权限是父任务可委派权限的子集。预算先从父额度预留，再授予子 Agent；不能所有子 Agent 都把父任务的剩余金额当作各自预算。

子 Agent 可以提出进一步分解，但必须经过工厂和准入。所有后代绑定 root_task_id、delegation_chain 和 security_epoch；不能通过生成新身份、调用外部 Agent 或请第三方做事脱离约束。

外部 Agent 和第三方服务必须有明确能力、数据范围、预算、超时与取消契约。不支持可靠取消或幂等的服务，不能被包装成“可完全控制”的本地工作者；出现停机时必须如实报告未确认部分。

<a id="agent-factory-5"></a>
### 生命周期

```text
proposed → validated → admitted → deployed → running
    → draining → checkpointed → sleeping / retired
    → failed / quarantined / terminated_by_security
```

退休时撤销能力凭据、停止模型订阅、释放资源和设备占用；需保存的经验经过知识晋升。security terminated 状态不能自动被“任务恢复”转换为 running。

<a id="agent-factory-6"></a>
### 关键契约

```yaml
agent_blueprint:
  id: research.dynamic_materials
  version: "1"
  purpose_ref: goal_materials
  capabilities: ["research.read", "artifact.write"]
  tools: ["approved_search", "document_builder"]
  input_schema: task.materials.v1
  output_schema: report.materials.v1
  memory_namespace: project/materials
  model_policy_ref: research_balanced
  evaluation_ref: materials_report_checks
  termination_conditions: ["accepted", "budget_exhausted", "cancelled"]

agent_instance:
  id: agent_unique
  blueprint_ref: research.dynamic_materials@1
  parent_instance_id: agent_coordinator
  root_task_id: task_materials
  deployment_node: node_home
  permission_lease_ref: permission_subset_01
  resource_lease_ref: resource_reserved_01
  root_principle_ref: G0
  security_epoch: 12
  status: admitted
```

多 Agent 仍需结果证据，不能通过多数投票决定事实或放宽 G0。默认使用本机有界调度和共享模型端口，不为每个角色创建常驻服务。Ray 等框架只作为已有集群需求时的对照材料，逻辑资源声明不等于操作系统硬隔离。[S29](references.md#s29) 组件选择受[普通 PC 准入规则](stack-project-layout.md#technology-selection-4)约束。

<a id="resource-scheduling"></a>
## Agent、模型与模块的统一资源自调度



<a id="resource-scheduling-1"></a>
### 所有工作使用同一资源账本

CPU、内存、显存、模型请求槽、Token 额度、费用、存储、网络、电量、温度约束、设备独占权和用户等待目标都纳入调度。普通程序、索引重建、语音模型、NPC 和 Agent 不能各自绕过全局资源额度。

资源租约应包含 node_id、scope、reserved、limit、deadline、priority、reclaim_policy、parent_budget_ref 与 security_epoch。额度发放与回收需要去重，失联节点的额度不能在未确认或未到期前被重复发放。

<a id="resource-scheduling-2"></a>
### 优先级

1. 独立监督、告警、停止和实体设备安全控制：有专用保留，业务调度不能收回。
2. 主人实时交流和明确优先任务。
3. 正式后台任务与已承诺的截止任务。
4. 自主学习、进化实验、知识重建和虚拟世界扩展。

主人可调整业务优先级和资源预算；不能把监督资源分配给模型。学习或模拟若是主人的当前主要任务，可提升其业务优先级，但仍不能覆盖 G0 或停止控制。

<a id="resource-scheduling-3"></a>
### 自适应决策

每次新增 Agent 或扩大模型并发，比较预期收益、协调成本、资源代价和等待时间。无收益或资源不足时可以排队、批处理、减少上下文、换模型、降低世界刷新频率、迁移任务、休眠或缩小范围。

采用迟滞与冷却，避免资源稍有变化就频繁装卸模型和迁移 Agent。监测实际内存与 GPU 使用；仅在调度器里声明“使用 1 个 CPU”并不会强制物理隔离。[S29](references.md#s29)

个人设备版本的扩展优先采用有界 Worker、模型复用与已配对节点间的任务分配。Kubernetes 扩缩容资料 [S30](references.md#s30)仅供明确服务器集群需求时参考，不列为后续必经升级；增加 Agent、运行 NPC 小镇或连接第二台 PC 都不自动构成引入它的理由。具体组件准入统一归[技术栈规则](stack-project-layout.md#technology-selection-4)。

<a id="resource-scheduling-4"></a>
### 能力快照与重新规划

快照包括设备能力、已安装模型、可用工具、协议版本、信任域、连接状态、资源和时间戳。调度计划使用快照；真正行动前再次校验关键资源。

摄像头失联时，对依赖视觉的任务暂停或降级；GPU 失效时减少后台推理并切到已验证 CPU 路径；共同体节点离线时，不擅自复制尚未对账的现实动作。

<a id="resource-scheduling-5"></a>
### 从小到大的实测扩展

规模测试按阶梯增加身份数量与活跃任务，记录吞吐、互动延迟、事件积压、成本、内存、错误率和角色一致性。达到预算或质量门槛后停止扩容，不能只用“成功创建了很多 Agent 对象”证明可用规模。

<a id="critical-review-6"></a>
## 补足预算与委派协议

这些状态在首期由 Task Runtime 通过 control.db 维护；跨节点通过有身份、代际和幂等键的消息投影，不能多个数据库同时自称权威。

**预算预留：** `requested → reserved → consumed / released / uncertain`。

- 幂等键是 `parent_budget_id + allocation_id`，重复申请返回同一结果。
- 受理任务、为其预留额度、登记动作意图和 outbox 在同一事务提交；未提交不发出执行许可。
- Worker 启动失败且有证据未消耗时释放；费用或外部效果未知时转 uncertain，仍占额度，不因超时自动退款。
- 回执以唯一 receipt_id 去重，记录已消费和可证明未使用的余额；迁移只能转移剩余授权，不能在目标重领全额。
- 子预算总额不超过父预算。外部服务不能严格限制最终收费时，使用预留余量、上限接口或拒绝不符合硬上限要求的动作，不能声称本地账本能控制所有供应商计费。

**任务委派：** `proposed → granted → accepted → active → revoked / closed`。

- 协调者写入 granted 和 outbox，绑定 assignment_id、owner_epoch、目标节点、资源范围、预算和期限。
- 目标节点幂等接受并回执；ACK 丢失通过查询同一 assignment_id 恢复，不另创建重复委派。
- 只有有效授权、代际和租约均通过执行端检查才 active；accepted 本身不意味着外部动作已执行。
- 撤销时保存已知/未知效果并对账。重新分配遵循[离线自治与联网共同体](federation.md#offline-federation)唯一权威和 fencing；不能仅靠原节点心跳超时推断其没有执行。
- 委派结束不删除动作回执和预算证据，保留到重试、离线和审计窗口结束。

这些状态说明了最小语义；完整 schema、数据库约束和形式化模型仍列为 M0 交付，不能把本节当成已验证协议。

<!-- book-footer:start -->
[返回全书目录](README.md#book-tree) · [上一章：记忆、知识库与持续学习](knowledge-learning.md) · [下一章：离线自治、多设备共同体与重连](federation.md)
<!-- book-footer:end -->
