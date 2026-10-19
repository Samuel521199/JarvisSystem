# 技术栈、源码目录与运行数据

> 状态：完整目录与架构 proposed；0.1.20 当前实现与历史基线分开记录 · 更新：2026-10-16
> [文档入口](README.md) · [维护规则](MAINTENANCE.md) · [架构图册](architecture-atlas.md)

<!-- book-nav:start -->
[全书目录](README.md#book-tree) › [第二篇 · 核心与工程基础](README.md#part-foundation) › 第 09 章 · 技术栈、源码目录与运行数据

## 本章导航

- [9.1 技术栈与选型理由](#technology-selection)
  - [9.1.1 先给结论：协议开放，初期实现收敛](#technology-selection-1)
  - [9.1.2 首期参考栈与可替代方案](#technology-selection-2)
  - [9.1.3 类 Codex 工作台的宿主与复用选择](#workbench-host-choice)
  - [9.1.4 语言与运行形态怎样选择](#technology-selection-3)
  - [9.1.5 普通 PC 优先：默认部署与组件准入](#technology-selection-4)
  - [9.1.6 自有任务状态机、LangGraph 与 Temporal 的取舍](#technology-selection-5)
  - [9.1.7 替换与隔离规则](#technology-selection-6)
  - [9.1.8 选型冻结条件](#technology-selection-7)
- [9.2 知识与记忆的开源选型（2026-10-18 复核，proposed）](#memory-open-source)
  - [9.2.1 名称、短长期记忆与比较边界](#memory-candidate-identities)
  - [9.2.2 存储和检索层：不同项目解决不同问题](#section-ee5f9aae063b)
  - [9.2.3 记忆框架：复用算法和接口，不交出数据所有权](#section-31d166a591e4)
  - [9.2.4 整库接入、复用部件还是自己实现](#memory-integration-choice)
    - [9.2.4.1 综合比较后的推荐方案与替换条件](#memory-recommended-plan)
    - [9.2.4.2 个人与工作资料怎样分区，为什么这样选](#memory-storage-partition-choice)
  - [9.2.5 推荐组合如何落到独立模块](#memory-module-adoption)
  - [9.2.6 OpenWiki：适合项目知识，不取代整套记忆](#openwiki-adoption)
  - [9.2.7 已核查的依赖负担与默认部署](#memory-dependency-audit)
  - [9.2.8 冻结选型的依据与成本](#section-9f65cb73fb32)
- [9.3 Grok Build 源码对照与模块化借鉴（2026-10-16，proposed）](#grok-build-comparison)
  - [9.3.1 核验对象、源码证据与限制](#grok-audit-scope)
  - [9.3.2 能力对照：我们涉及了什么，哪里应采用更好的做法](#grok-feature-comparison)
  - [9.3.3 借鉴后仍然独立的模块边界](#grok-module-adoption)
  - [9.3.4 三个需要改造的具体设计](#grok-context-memory-tradeoffs)
  - [9.3.5 复用方式、维护成本与本轮决定](#grok-reuse-decision)
- [9.4 常用 MCP 选型与集成（2026-10-17）](#mcp-integration-choice)
  - [9.4.1 REA 软件解析：技能优先的集成评估与首期适配](#rea-integration-choice)
    - [9.4.1.1 接入后的实际价值与改进优先级（2026-10-18）](#rea-effectiveness-improvement)
- [9.5 Matt Pocock 编码技能选型（2026-10-17，accepted）](#matt-pocock-skills-evaluation)
  - [9.5.1 固定来源与实际内容](#matt-pocock-skills-scope)
  - [9.5.2 当前缺口与最小接入方式](#matt-pocock-skills-integration)
- [9.6 Anatomy 科普动画与机械拆解选型（2026-10-17，accepted）](#anatomy-integration-choice)
  - [9.6.1 固定来源、可复用代码与能力边界](#anatomy-source-scope)
  - [9.6.2 Jarvis 适配层与产物交付](#anatomy-adapter-boundaries)
- [9.7 统一对话与语音的轻量接入选型（2026-10-18）](#dialogue-stack-choice)
  - [9.7.1 复用现有实现，按边界拆分](#dialogue-runtime-adoption)
- [9.8 项目文件结构与依赖规则](#project-structure)
  - [9.8.1 当前实际落地范围（0.1.18）](#implemented-layout)
  - [9.8.2 推荐源码结构](#project-structure-1)
  - [9.8.3 单个模块模板](#project-structure-2)
  - [9.8.4 运行数据结构](#project-structure-3)
  - [9.8.5 依赖规则](#project-structure-4)
- [9.9 领域目录与受保护状态](#extensions-2)
- [9.10 构建模块的目录与复用边界](#development-platform-11)
<!-- book-nav:end -->

<a id="technology-selection"></a>
## 技术栈与选型理由



<a id="technology-selection-1"></a>
### 先给结论：协议开放，初期实现收敛

**建议采用“小型受保护底座 + 模块化业务宿主 + 隔离 Worker + 版本化能力包”，将 Rust/Python/TypeScript 作为可调整的参考实现，不作为系统永远只允许的三种语言。**

**已采纳的产品部署约束：普通个人 PC/笔记本是主要运行设备，先完成 Windows 本机版本，再按需求验证其他平台。** 默认部署与组件准入统一遵守[普通 PC 优先规则](#technology-selection-4)。跨平台、多设备、自主编程能力通过现有边界逐项加入，不以安装集群基础设施为前置条件。

当前已检测开发机：Windows、AMD RYZEN AI MAX+ 395（16 核/32 线程）、约 123.6 GiB 内存、Radeon 8060S 集成显卡。尚无实际外围设备清单，也没有证据证明唯一最佳栈。首期个人或小团队维护，优化目标依次为：控制边界可验证、形成可用闭环、易调试与恢复、满足离线体验，再考虑吞吐。v0.2 把较多业务模块预设为 Rust，没有足够理由证明这种投入能优先改善用户体验；本版缩小这项承诺。

开发机配置不是最低要求，也不能据此默认让模型、语音、索引和编译环境全部常驻。普通设备的资源验收口径见[PC 开销验收](delivery-validation.md#pc-footprint)；尚未测得通用最低配置。

稳定的是 `Task / Action / Capability / Artifact / Module / Build` 的语义，以及授权、检查点和数据所有权；语言、框架、数据库驱动、推理引擎属于实现选择。跨语言通过进程协议或适用的 WASI 接口接入，不把任意语言的对象、异常或内存布局当作跨模块契约。

<a id="technology-selection-2"></a>
### 首期参考栈与可替代方案

| 层 | 首期参考选择 | 替代条件与代价 |
|---|---|---|
| 独立监督与恢复 | 小型 Rust 程序，分别权限隔离 | Go 或 .NET 也可实现；替换需重跑锁存、进程控制、离线恢复与资源上限测试。语言本身不能证明忠诚 |
| node-host 业务宿主 | 现有 Python + JSON Schema；任务/预算/动作控制逻辑确定性实现 | 严格类型检查按需补充；有重复校验成本时再评估类型建模库，不并行维护第二套契约。其他语言仅在明确平台需求或实测收益下替换 |
| 任务与研发 Worker | 隔离 Python 环境起步；能力包允许其他语言 | 优先复用领域生态；生成程序不得以可信 Host 权限运行 |
| 界面 | 沿用现有本地网页，逐步加入任务/告警面板 | 需要系统托盘、桌面集成等能力时再评估桌面壳，例如 Tauri [S20](references.md#s20)；不为换外观同时维护两套 UI。UI 关闭不结束后台任务 |
| Agent 规划 | 自有薄 Reasoner 接口；先直接模型调用，必要时接 LangGraph [S11](references.md#s11) | LangGraph 可管理推理内部检查点；不可成为第二个外部动作调度权威 |
| 持久任务 | 有限任务状态机 + SQLite 本地事务 | 只实现明确状态、取消、重试、检查点和动作日志；复杂工作流按 [框架替换边界](#technology-selection-5) 处理 |
| 模型适配 | 沿用单一 ModelGateway 和已实现的原生适配 | 多供应商共用目录与调度；实测维护成本需要时再比较 LiteLLM [S15](references.md#s15)，不额外常驻第二个模型代理 |
| 本地推理 | 独立 llama.cpp 服务作为候选 [S17](references.md#s17) | 其他引擎可替换；按真实硬件、中文、工具调用、内存和许可证测试 |
| 本地语音 | sherpa-onnx 适配器起步 [S18](references.md#s18) | ASR/VAD/TTS 分别选择；多设备实时音频需要时再引入 LiveKit/WebRTC [S19](references.md#s19) |
| 本地存储 | SQLite WAL、本地对象文件、全文搜索、可重建向量索引 [S21](references.md#s21) | 热状态先保留本地；并发或检索实测证明必要后再增加服务端数据库 |
| 本机 IPC | 受保护 Named Pipe / Unix Socket，加版本化消息 | 首期少量受控接口可用 JSON Schema；强类型、多语言或跨节点接口采用 Protobuf/gRPC [S13](references.md#s13) |
| 跨节点 | 配对身份、双向 TLS、outbox/inbox、任务对账 | 不把“接入消息队列”当成已经完成分布式一致性 |
| Windows 桌面 | API/CLI 优先，独立用户会话 UI Automation 助手 [S22](references.md#s22) | 不绕过锁屏、UAC 或权限；Linux/macOS 各自实现适配器 |
| 浏览器操作 | 已采用可选 Playwright 1.64.0 + 系统 Edge，DOM 观察与固定元素动作 [S118](references.md#s118) | 不额外下载浏览器；需要视觉定位时另验模型/截图适配，不能把现有文本路由当成原生 Computer Use API |
| 家居/硬件 | Home Assistant、MQTT、串口等按需适配 [S25](references.md#s25) | 控制能力取决于设备回执、幂等与安全停止支持 |
| 观察与发布 | 结构化日志，逐步接 OpenTelemetry；不可变包、A/B 槽 [S27](references.md#s27) | 首期不建设大型可观测平台；日志与凭据分离 |
| 自带开发环境 | 按任务安装一个受支持生态的版本化开发包 | 默认运行包不附带全套编译器；本机/远端构建、目标验证和发布分开，详见[开发环境](toolchains.md#development-platform) |

同一 API 只能指定一种权威契约，禁止手工维护两套会漂移的 JSON 和 Protobuf 业务定义。JSON Schema 用于动态清单/工具参数；需要两种传输映射的固定接口，必须生成并做一致性测试。首期无必要在本机每个函数调用上都套一层 gRPC。

<a id="workbench-host-choice"></a>
### 类 Codex 工作台的宿主与复用选择

界面目标见[工作台设计](interaction-persona.md#desktop-workbench)，优先在已有 `apps/web/index.html`、`apps/web/computer.js` 与 `apps/web/server.py` 上增量实现。首次提供文件夹入口时，浏览器附件选择、项目目录挂载与系统目录选择器必须分别表达；纯网页页面不能仅凭一个路径字符串获得操作系统授权。

| 选择 | 适用范围 | 采用条件 |
|---|---|---|
| 现有本地网页＋本机服务 | 侧栏、项目/会话、输入区、任务、模型选择与文件/产物视图 | 首选；复用当前 ModelGateway、任务账本和安全入口；输入框切换模式不新增执行权威 |
| 本机服务＋轻量 Windows 托盘 | 0.1.18 已实现通知区域状态、打开网页和明确退出当前实例 | 使用系统 Windows Forms/PowerShell，测量实际进程开销；不引入第二套前端或 Tauri 安装依赖，范围见[托盘使用](core-bootstrap.md#windows-tray-entry) |
| 同一前端＋可选桌面壳 | 原生目录选择、托盘、窗口管理、快捷键和系统集成 | 有实际需求后评估 Tauri 等现有候选 [S20](references.md#s20)，记录安装与内存差值；壳不嵌入模型权重、不替代独立监督 |
| 单独重写“Codex 克隆”再接后端 | 会形成两套界面和状态接入 | 当前不采用；可复用公开交互模式，源码和资产复用必须另核许可，不能推定 Codex 桌面壳公开 |

项目根目录和会话索引由本机服务管理；根目录绑定与用户产物落点遵守[项目根目录与默认输出位置](interaction-persona.md#project-root-output)。UI 只持有查询结果和草稿，不把浏览器本地存储当作任务账本。真实目录访问、外发和动作校验继续经过既有权威边界。多个前端共享会话时要有修订/冲突处理；跨节点挂载不能以“本机同路径”代替节点身份。

品牌候选资产位于 `docs/assets/`，由 manifest 的 `design_assets` 登记、由[交互章](interaction-persona.md#jarvis-brand-icon)定义用途；不是 `docs/diagrams/` 中的架构图源，也不自动打包进运行 UI。当前仍未引入桌面壳或第二套前端依赖。

<a id="technology-selection-3"></a>
### 语言与运行形态怎样选择

| 方案 | 更适合的部分 | 需要承担的成本或限制 | 当前判断 |
|---|---|---|---|
| Rust | 小型长期驻留底座、原生桥、性能热点 | 编译链、所有权学习、异步与 FFI 调试；内存安全不等于业务正确 | 保留，缩小首期范围 |
| Python | 推理、工具、评估、迭代快的业务宿主 | 依赖/解释器封装、原生扩展、资源隔离；不能把所有任务塞进一个事件循环 | 首期主业务参考 |
| Go | 服务进程、联网、进程管理 | cgo/原生 SDK 仍增加构建与发布复杂度；AI 生态适配成本需估算 | 底座的有效替代 |
| C# / .NET | Windows 服务、桌面集成、熟悉该生态的团队 | 自包含与 AOT 有不同兼容约束；跨平台能力要按依赖逐项确认 | Windows 优先的有效替代 |
| TypeScript | Web/桌面交互、部分软件集成 | Node 依赖与构建供应链；不承担所有本地模型工作 | UI 和适配器按需引入 |
| C/C++、CUDA 等 | 驱动、既有高性能库与特定设备 | 内存/ABI/驱动兼容风险，编译与硬件验证成本 | 通过受限进程封装复用 |
| WASI 组件 | 可表达为受限接口的轻量工具 | 语言、宿主 API、线程/设备支持需逐项确认 | 可选能力载体，不是全系统唯一底座 |
| JVM、Swift、其他语言 | 领域库或目标平台明确要求的模块 | 增加运行时、缓存、测试矩阵和维护责任 | 按收益准入，不预装所有生态 |

这是定性选型表，不是语言性能排名。对替换需求应比较“完成同一任务的端到端质量、延迟、常驻资源、构建时间、恢复成本、维护负担”。如果 Rust 改成 Go 并未改善这些指标，仅重写代码不计作进化成果。

<a id="technology-selection-4"></a>
### 普通 PC 优先：默认部署与组件准入

此约束按主人 2026-10-15 的要求采纳，适用于 K0—K6 的个人设备产品；不是“第一版轻量、后期必然集群化”。完整功能可以逐步增加，默认安装和常驻开销必须保持受控。以下是后续实现规则，不表示加载、卸载与资源管理均已实现。

| 范围 | 默认实现方向 | 按需扩展边界 |
|---|---|---|
| 主运行形态 | 本机应用：受保护控制底座、一个模块化业务宿主、受限 Worker；先复用 Python、SQLite 和本地网页 | 按权限与故障隔离拆进程，不按文档中每个模块拆服务；不因支持跨平台而立刻重写内核 |
| 持久任务 | 现有账本与有界本机队列，一个后台 Worker 起步 | 按实测资源增加并发；不默认增加 Redis、Celery、Temporal 或消息服务器 |
| 模型与 Agent | 一个路由权威，共用按需启动的推理后端；Agent 是上下文和任务状态 | 不给每个 Agent 单独部署模型、数据库或服务；只有任务确需时生成角色，限制活跃并发 |
| 记忆与检索 | SQLite/FTS5 起步，最多选定一个当前向量后端 | 对照候选用于实验，不能把所有记忆框架和数据库一同装入默认包 |
| 语音、视觉与研发 | 能力包按需安装、加载和释放；编译环境与生产运行分离 | 未启用语音时不常驻 STT/TTS；未使用的模型、SDK 和构建器不自动下载，退役按既有保留规则处理 |
| 多设备 | 完整节点各自能运行，配对后同步领域事件、分配任务 | 加第二台 PC 不要求建立集群、共享数据库或常驻中心服务；协调节点可由现有完整节点承担 |
| 平台支持 | 当前先完成 Windows；平台特权集中在适配器 | 有实际目标设备和测试条件后再支持 Linux/macOS 等；不提前实现所有 OS、GPU 后端、语言和硬件协议 |

**默认安装、启动与升级链路均不引入 Kubernetes、服务网格、Ray 集群、Kafka/NATS 集群或分布式训练基础设施，也不依赖 Docker/WSL 环境。** 隔离需要何种原生机制或按需虚拟机，按实际执行能力验证；不能为了减小体积而允许不可信代码以宿主权限运行。确有服务器规模需求时才独立评估重型适配器，例如耐久消息服务 [S26](references.md#s26)，它不能反过来成为普通 PC 的启动条件。

新增第三方组件或长期支持一个后端前，须记录：当前任务缺口；用标准库/已有组件能否解决；相同任务的收益；下载/安装体积、空闲和峰值资源、常驻进程、更新与许可证成本；失效与卸载路径。只为未来可能使用而增加兼容层，不构成准入理由。同一能力默认只维护一个已验证实现；对照试验和明确使用中的提供商适配除外，统一走原有接口。

较多服务会增加部署、契约版本和分布式故障成本。保留必要权限隔离，其余业务模块先同宿主，再按真实瓶颈拆分；这借鉴模块化起步的工程经验 [S39](references.md#s39)，不是用进程数替代隔离验收。控制循环掌握授权和生命周期，LLM 不能改变组件准入规则或自行扩大资源预算。正式资源目标与检查方法只维护在[验收页](delivery-validation.md#pc-footprint)。

<a id="technology-selection-5"></a>
### 自有任务状态机、LangGraph 与 Temporal 的取舍

**首期只允许一份权威任务账本、一位外部动作调度者。** LangGraph 若启用，只持有推理过程检查点，工具节点向 Task Runtime 提交意图；历史检查点重放不得直接执行现实动作。LangGraph 的执行便利性不转移 Jarvis 的授权责任。

先验证自有有限状态机是否足够。若出现大量跨周定时、信号、复杂补偿或人工步骤，再比较继续维护的成本与引入成熟工作流引擎的成本。Temporal 是后期共同体工作流候选，不是必须采用的升级目标；采用后仍不要求完整离线节点依赖远端 Temporal 在线。[S12](references.md#s12)

引入另一引擎优先接新任务；既有任务完成或在明确检查点转交唯一所有权。必须记录能力差异与迁移代价，不能只替换 SDK 就宣称工作流语义等价。

<a id="technology-selection-6"></a>
### 替换与隔离规则

模型、语言、数据库和 UI 的替换都通过相同模块生命周期：候选注册 → 契约验证 → 独立评估 → 新任务灰度 → 排空或迁移 → 保留可恢复版本。长任务固定版本，执行时仍检查当前授权。

独立虚拟环境解决依赖冲突，不解决恶意代码隔离。生成代码的构建、测试和执行必须使用适当的受限账户、进程控制、文件/网络白名单，必要时使用虚拟机或适当隔离模式的容器；WSL、容器或子进程名称本身不是安全结论。生产目录和发布凭据不对候选环境开放。

<a id="technology-selection-7"></a>
### 选型冻结条件

K0—K1 在同一目标硬件上比较不超过两个底座候选，先验证确定性停止/恢复、离线准备、账本与资源预留，选定一个首期栈并锁定版本。K2—K4 逐步补齐本地智能、工具构建和版本回退证据；早期用文本与模拟交互负载测资源竞争，真实语音并发在 M2 验收时补齐。持续记录开发维护成本，不同时实现所有替代方案。

只有当一个候选实现通过相同契约和验收，且收益高于迁移/维护成本时，才发起语言或框架迁移。编程语言开放是新增实现的能力，不是允许 Jarvis 因个人偏好不断重写自己。

<a id="memory-open-source"></a>
## 知识与记忆的开源选型（2026-10-18 复核，proposed）

结论是采用 **Jarvis 自有记忆语义与数据接口 + 成熟可替换组件**：本地事实存储、项目知识编纂、选择性长期记忆、检索和同步分别负责。每个完整节点都能独立读取必需资料；稳定主机可以提供更强检索，但不能成为其他完整节点的唯一记忆来源。语义设计见[知识页](knowledge-learning.md#memory-selection-design)，同步取舍见[共同体记忆协议](federation.md#memory-replication)。以下是根据官方代码库与文档作出的工程判断，不是性能跑分；未安装这些候选，也没有把公开基准成绩记为 Jarvis 的成绩。

本轮补充 LLM Wiki、MemPalace、LangMem、LightMem、A-MEM 和 EverOS，复读 11 个项目的固定源码快照。**当前最合适的是分工组合，不是挑一个“最强记忆库”替换全部系统。** 日常伙伴需要记住偏好与共同经历，工作时需要准确资料和真实进度；这几类信息的更新、纠正和保留方式不同。推荐落点见[模块映射](#memory-module-adoption)，当前代码缺口见[渐进改造](knowledge-learning.md#memory-current-gap)。

<a id="memory-candidate-identities"></a>
### 名称、短长期记忆与比较边界

| 名称 | 本次比较对象 | 不能混淆的地方 |
|---|---|---|
| LLM Wiki | Karpathy 的 [LLM Wiki 思路稿 S219](references.md#s219) | 是“原始材料 → 持续编纂的关联页面 → 查询与维护”的方法，不是一个已有统一 API、同步协议和性能保证的数据库产品 |
| OpenWiki | 用户先前指定的 `langchain-ai/openwiki` | 是具体工具实现；可借鉴 Claims、来源版本和分节读取，不等同于所有名为 LLM Wiki 的仓库 |
| 记忆宫殿 | 本轮采用 `MemPalace/mempalace` 为具体样本 [S220](references.md#s220) | “记忆宫殿”也是一种组织隐喻，网上存在同名实现；这里的结论不泛指其他项目，也不假定空间隐喻必然提高准确率 |
| LightMem | `zjunlp/LightMem` [S222](references.md#s222) | 比较的是记忆增强研究框架，不是同名 KV cache 项目；节省模型调用不等于安装包或常驻内存小 |
| A-MEM / AgeMem | A-MEM 是动态关联笔记方法 [S223](references.md#s223)；AgeMem 是学习长短期记忆管理策略的研究 [S227](references.md#s227) | 不因名称相近视作同一库；训练策略的论文不能当作接上任意 API 就获得相同表现的插件 |
| EverMemOS / EverOS | 当前官方仓库为 EverOS [S224](references.md#s224) | 本轮看到的是 Markdown + SQLite + LanceDB 的本地路线；旧论文、旧服务栈和新代码的成绩、依赖不可互相套用 |

短期记忆是本轮上下文、近期交流和任务工作状态；长期记忆包括情景经历、可纠正事实与知识、经验证的方法。短期不等于只能放 RAM，长期也不等于一律放向量库。上下文窗口、KV cache、向量检索、知识 Wiki、事件日志各自只解决部分问题；先按[数据职责](knowledge-learning.md#memory-operating-cycle)比较，再按同条件测试选实现。GitHub 星数、项目自报准确率和某个英文数据集总分不构成 Jarvis 的适配评分。

<a id="section-ee5f9aae063b"></a>
### 存储和检索层：不同项目解决不同问题

| 候选与主项目许可 | 已核实的能力 | 对本项目的判断与代价 |
|---|---|---|
| SQLite + FTS5（Public Domain）[S87](references.md#s87)、[S100](references.md#s100) | 本地事务、关系元数据、全文检索；WAL 不是多机器共享数据库协议 | **首期事实与元数据底座。** 延续现有栈；必须补中文检索、事件同步与权限过滤，不能直接同步活跃 DB/WAL 文件 |
| sqlite-vec（MIT / Apache-2.0）[S88](references.md#s88) | C 扩展、Windows 等平台、float/int8/binary 向量；官方仍标 pre-v1 | **轻量向量候选，先试验。** 适合少依赖节点；只放派生索引，固定版本并验证重建/过滤；不把未验证 ANN 能力或演示速度当作规模承诺 |
| LanceDB OSS（Apache-2.0）[S89](references.md#s89) | 嵌入式检索、向量/全文/多模态数据，Lance 格式与版本能力 | **本地向量第二候选。** 在检索规模或多模态需求超过轻量方案时比较；增加原生包和第二种存储格式；数据版本不等于离线多主冲突解决 |
| Qdrant（Apache-2.0）[S90](references.md#s90) | 服务端向量、分片、复制、读写一致性选项；集群元数据使用 Raft | **稳定主机的可选检索服务。** 不让常休眠设备都变成集群节点；官方安装要求和目标 OS/文件系统需验证。分布式索引不替代记忆语义和删除对账 |
| PostgreSQL + pgvector（PostgreSQL License）[S91](references.md#s91) | SQL 与向量，精确/近似搜索、过滤和迭代扫描 | **已有常驻数据库或复杂服务端查询时再采用。** 每台轻节点部署的运维收益不足；近似索引加过滤可能不足 top-k，必须测授权过滤后的召回 |
| Chroma OSS（Apache-2.0）[S92](references.md#s92) | 简单 collection API、本地/服务端模式、文档/向量元数据 | **快速 RAG 对照候选。** 接入容易，但不因此获得事实溯源、离线合并或 Jarvis 的恢复协议；Cloud 功能不能默认算进 OSS |

本轮不为全套候选创建运行依赖。K2 首轮使用 SQLite/FTS5 基线，向量试验只比较 sqlite-vec 与 LanceDB 两个后端，并使用相同嵌入与输入，避免把模型差异误算成数据库优势。暂定 sqlite-vec 为资源较小节点的试验首选；如果版本兼容、权限过滤或规模测试不过，选择 LanceDB，不改变原始资料与事实接口。Qdrant/pgvector 是后续集中检索选项，不能要求完整节点在线才能查自己的记忆。

<a id="section-31d166a591e4"></a>
### 记忆框架：复用算法和接口，不交出数据所有权

| 候选与本次核验状态 | 值得复用的部分 | 准入判断 |
|---|---|---|
| Mem0，Apache-2.0 [S93](references.md#s93) | 记忆提取、个性化召回、混合检索，库/自托管/托管多种形式 | **记忆提取器的优先对照项。** 默认云端 LLM/embedding 必须显式替换或授权；README 明确部分新基准含托管专有优化。其新增记忆与 Agent 陈述处理不能替代我们的证据等级、纠正和遗忘规则 |
| MemOS，Apache-2.0 [S97](references.md#s97) | 本地插件的 SQLite/FTS5、经验整理及独立 core / 宿主 adapters | **备用对照，不进入首批默认安装。** 不要求为 Jarvis 先安装 OpenClaw，但现成插件不能直接视为 Python 模块；Node 与原生依赖需另计。自托管栈与本地插件是不同部署路线 |
| Graphiti，Apache-2.0 [S94](references.md#s94) | 时态实体关系、事实有效期和来源追踪 | **关系/时间问题出现明确收益后接入。** 需要图后端和可靠结构化提取；官方提示小模型可能导致入库失败，并已弃用 Kuzu 后端。图只作可重建关系视图，抽取冲突不能直接裁决主人事实 |
| Cognee，Apache-2.0 [S96](references.md#s96) | 文档、代码与会话转成可检索知识图；当前文档提供本地小模型路径 | **文档理解流水线的备选。** “本地可运行”不等于本机中文准确、依赖已备齐或具备离线复制；单独测解析、图构建和资源成本 |
| Letta / Letta Code，Apache-2.0 [S95](references.md#s95) | 有状态 Agent、记忆块、上下文管理和 MemFS | **借鉴或作为外部工作者，不接管核心。** 原 Letta V1 server 已归档，当前代码在 letta-code；Cloud 默认和 local 后端须区分，不能把云端多机运行当作我们的离线多主共同体 |
| OpenViking，主项目 AGPLv3，部分组件 Apache-2.0 [S98](references.md#s98) | 目录化上下文、L0/L1/L2 分层读取、记忆/资源/技能组织 | **架构参考与后续独立适配候选。** 当前 README 另含整体重写/语言转换限制说明，应核对拟采用版本条款；本轮不将其整库纳入可任意自改底座，也不作许可效力判断 |
| Hindsight，MIT [S157](references.md#s157) | retain / recall / reflect、按 bank 组织记忆、经历与反思检索 | **稳定主机上的完整记忆服务备选。** 当前 PostgreSQL / pg0 路线与大量服务依赖不适合作为每台普通 PC 的默认包；嵌入式 PostgreSQL 不等于无数据库成本，也不是换 SQLite 就能运行 |
| OpenWiki，MIT [S160](references.md#s160) | 有来源的代码知识、Markdown 页面、跨仓库 workspace、按章节检索 | **项目知识模块的优先参考，与 Mem0 互补。** 不能用 Wiki 代替个人情景记忆、任务账本或设备复制协议；具体复用与限制见[OpenWiki 分析](#openwiki-adoption) |
| LangMem，MIT [S221](references.md#s221) | 可接自有存储的提取接口、用户画像、情景记忆与后台整理；`create_memory_manager` 可返回提取结果 | **与 Mem0 同批比较，接口适配优先看它。** 功能边界较适合候选提取，但包依赖仍带 LangChain/LangGraph、模型 SDK 和 LangSmith；不为此迁移主循环或默认开追踪 |
| MemPalace，MIT [S220](references.md#s220) | 保留原文，按人物/项目/主题组织检索；后端可替换 | **借鉴情景档案和检索组织；完整实现作为独立对照。** 默认 Chroma；已有 SQLite exact 等选项，不能因此认为安装依赖已去掉 Chroma。层级不是授权机制，检索命中不等于事实已纠正 |
| LightMem，MIT [S222](references.md#s222) | 分段、短期整理、离开交互关键路径的长期整合 | **借鉴节省重复加工的方法。** 当前研究实现依赖 Torch、Transformers、压缩和 embedding 模型，不整体放进轻量默认包；“sleep-time”指异步整合，不代表计算或费用为零 |
| A-MEM，MIT [S223](references.md#s223) | 类卡片笔记的关联、上下文补充和关联更新 | **关联推荐的后续算法候选。** 模型生成的链接可撤回、可重建；不允许关联传播重写原始证据或主人确认事实，避免错误沿笔记扩散 |
| EverOS，Apache-2.0 [S224](references.md#s224) | 可编辑 Markdown、派生 SQLite/LanceDB 索引、个人/Agent/知识分域与后台整理 | **值得保留的完整系统对照。** 已不应按旧重服务印象排除；但需要 Python ≥ 3.12、Arrow/LanceDB 及多个算法包，与现有事务事实库的权威模型不同，直接替换代价较大 |

这些框架的“记忆”常包含各自的 Agent、模型配置、存储或后台处理。候选必须通过本项目适配器：输出待核验事实/摘要及来源；写入权仍由 MemoryStore 控制。先在同一数据上测增益，允许直接采用通过测试的开源实现，避免重复开发已有算法；但不能因一个库接入成功就同时启用其自动学习、网络连接或技能发布。

<a id="memory-integration-choice"></a>
### 整库接入、复用部件还是自己实现

| 方式 | 得到什么 | 真实代价 | Jarvis 的选择 |
|---|---|---|---|
| 完整框架接管记忆 | 最快获得框架自身的写入、提取、检索闭环 | 双重存储/路由、作用域和删除语义适配；升级可能影响整个闭环 | 保留为隔离对照或稳定主机选项，不作为默认核心 |
| 官方 API / 独立 Worker 适配 | 保留上游升级通道，故障和依赖可隔离 | 要做版本、预算、导入导出及回执映射；服务持有的数据仍需撤回 | **优先复用方式**；按任务启动，仅交付该任务允许的资料 |
| 小范围代码复用或算法借鉴 | 可只引入确有收益的部件，继续共用 Jarvis 路由和存储 | 复制代码后需维护补丁与许可声明；上游私有函数未必是稳定组件 | 用于证据定位、切片、排序等边界清楚的部分；维护来源 SHA 和差异 |
| 全部自己实现 | 完整控制 | 需重新解决解析、检索、性能、迁移和大量边界问题 | 只自持必要语义和协调逻辑，不自造通用数据库、向量算法或密码协议 |

**具体推荐：**保留 SQLite 与当前词法检索，补齐中文 FTS5 基线后按需对照 sqlite-vec / LanceDB；LangMem 与 Mem0 比较候选提取；LLM Wiki 的增量编纂方法结合 OpenWiki 的证据追踪；MemPalace 的情景组织和 LightMem 的异步整合按需借鉴。EverOS 保留为完整系统对照，Hindsight、Graphiti、Cognee 留在扩展层。尚无同条件实验能证明这套组合的召回更好；它优先降低当前部署和数据锁定风险，代价是 Jarvis 必须自己做好作用域、纠正和复制测试。首轮只启用一个提取实现和一个 embedding 后端。

Mem0 的 `Memory` 对象本身包含模型、embedding、向量后端和历史管理，并非现成的纯 Extractor。第一轮可让完整 SDK 在独立测试存储中输出结果，再转换为候选；若生产仅需提取，优先选择稳定扩展点或小范围实现，不依赖其私有函数。其 user / agent / run 过滤字段可作输入，不能直接等同 Jarvis 的主人、项目、人格和模拟域权限。[S154](references.md#s154)

LangMem 的函数式接口减少了存储接管，但不保证结果天然具有 Jarvis 要求的原文定位、否定语义和撤销关系，仍需外层适配与校验。其示例的 `InMemoryStore` 重启会丢失，不作为持久方案；选择功能接口也不能把整个依赖树称为“零依赖”。两者先在相同已授权片段上输出候选，比较质量、调用数和改造成本；接入任一库都不能同时启用另一套自动写入和后台调度。[S221](references.md#s221)

<a id="memory-recommended-plan"></a>
#### 综合比较后的推荐方案与替换条件

**2026-10-18：推荐路线已明确，算法胜者尚未实测冻结。** 对当前 Jarvis，优先选择“自有记忆管理规则与 SQLite 事实权威 + 可替换提取器 + 按需知识编纂 + 本地可重建索引 + 后续应用事件同步”。这是按普通 PC、个人伙伴、可纠正记忆和离线共同体要求作出的适配判断，不是宣称自研系统的问答准确率已经高于所有开源项目。最新核对继续采用 [LangMem 功能接口 S221](references.md#s221)、[Mem0 OSS S93](references.md#s93)、[OpenWiki S160](references.md#s160)、[MemPalace S220](references.md#s220)和[EverOS S224](references.md#s224)的维护方资料；固定源码与依赖证据见[静态调研记录](delivery-validation.md#memory-review-evidence)。

| 整体路线 | 最有价值的地方 | 对当前 Jarvis 的主要代价 | 结论 |
|---|---|---|---|
| 自研全部存储、提取、检索、同步算法 | 控制直接，能精确表达产品规则 | 重复建设、个人维护成本高，算法质量未必更好 | 只自持产品语义、事务写入和协调，不自造通用数据库/向量算法 |
| Mem0 整体接管 | 提取、更新和检索流程较快接通，适合从零做记忆应用 | 要处理已有来源/撤销、任务账本、路由与第二份存储的映射；完整 SDK 不是纯提取函数 | 作为完整流程对照；通过统一契约后可接入，暂不替换事实权威 |
| EverOS 整体接管 | 当前本地 Markdown、SQLite、LanceDB 路线兼顾可读资料与记忆组织 | 本项目事务事实与其 Markdown 权威模型不同；转换、冲突和遗忘需重新证明 | 是值得认真比较的完整替代路线，不能仅凭旧重服务印象排除；现阶段迁移收益未证实 |
| 自有规则与数据权威 + 开源部件 | 延续现有来源保护；提取、检索和编纂可单独改进，默认部署可较小 | 适配器、迁移和跨组件验收仍由 Jarvis 维护；接口过多也会增加复杂度 | **当前首选**：生产每类只保留一个启用实现，备用实现按需加载 |
| 多个完整框架同时作为权威 | 功能列表看似丰富 | 同一事实被多套写入、遗忘及后台机制处理；费用、依赖和故障来源难以解释 | 不采用；实验对照不等于生产同时常驻 |

**提取器的具体优先级：**已有复用现有模型路由、返回约定 JSON 候选的最小结构化提取基线；已增加 [LangMem `create_memory_manager` 隔离影子实验](delivery-validation.md#memory-langmem-shadow-evidence)与 [Mem0 公开 SDK 隔离适配](delivery-validation.md#memory-mem0-shadow-evidence)。两者均可在固定公开样例上复跑，完整独立样本及生产准入仍待验收。LangMem 可由调用者保留存储与更新控制，但这不等于依赖更少或质量已经获胜。Mem0 的默认配置包含 LLM、embedding、Qdrant 本地数据和 SQLite 历史；可替换这些组件，不能把默认本地 Qdrant 模式说成必须部署 Qdrant 服务。[S221](references.md#s221) [S154](references.md#s154)

若最小基线达到同等质量与撤销要求，就保留它，避免为少量能力引入整套依赖。若 LangMem 在模糊表达、合并或纠正样例上有稳定收益，启用其适配器；若 Mem0 的实测收益更高，优先使用其公开扩展接口或独立 Worker，而不是复制其私有函数。候选模型仍复用 Jarvis 的任务路由、备选和预算，不能由 SDK 另开不受管理的供应商配置。准入与质量/成本的判定方式归[比较验收](delivery-validation.md#memory-comparison-tracks)。

**本次实施决定：保留最小提取器为默认，LangMem 与 Mem0 保留为隔离实验适配器。** 单条候选没有必要额外维护一份永久向量库和消息历史；比较结果、费用及局限分别在 [LangMem 证据](delivery-validation.md#memory-langmem-shadow-evidence)和 [Mem0 证据](delivery-validation.md#memory-mem0-shadow-evidence)维护。Mem0 当前原生 ADD-only 策略适合追加观察，但不能直接充当主人当前偏好、纠正和遗忘的裁决器；这不是它的完整系统质量排名。[S154](references.md#s154)

**具体借鉴落点：**采用公开接口与组件可替换的思路，将“本次有来源的新消息 + 宿主允许的相关旧事实”作为提取输入；借鉴单次模型整理和明确过滤条件，不复制整段原生提示或私有函数。正式当前事实、来源修订、用途/接入方许可、纠正与遗忘仍只由 Jarvis 的事实权威管理，跨项目共用继续通过 MemoryView 产生当次允许的视图。当前工作树已落地[本地重复与差异核对子集](contracts.md#memory-candidate-review-contract)，提供显式沿用、替代或另存，绑定编辑后候选、旧事实和来源版本；没有照搬框架私有函数，也不能因相似度高就自行覆盖。Mem0 自带消息历史不作为第二份正式主人档案，`delete` 的成功也不作为全链路遗忘回执。该语义比较仍需后续独立样例，暂未进入自动写入。

**知识与检索的具体选择：**OpenWiki/LLM Wiki 用于有反复复用价值的项目资料、学习资料和主题知识；先接小范围编纂，保留原来源。OpenWiki 当前有个人知识入口，但源码 Claims 的版本核对保证不能自动套给所有个人连接器。MemPalace 借鉴原文、人物/主题和时间组织；LightMem 借鉴批次整理；它们不是额外两套常驻记忆库。检索先完善中文词项基线，语义改写确有缺口再试一个小型多语 embedding 与 sqlite-vec；LanceDB 作为兼容性或规模不满足时的替代。关系查询先评估现有 SQLite 关系表和有界链接是否足够，再决定是否需要 Graphiti 一类图模块。准确的组件职责归下节，数据流和域归[记忆流程](knowledge-learning.md#memory-operating-cycle)。

**必须承担的自研成本：**事实冲突和时间语义、派生内容撤销、事件复制、备份恢复、中文召回和长期资源表现不会因这套组合自动解决。维护中应允许完整替代方案胜出：若它通过相同隔离/纠正/遗忘/导出测试，并在真实工作负载上明显减少适配和维护成本，就重新评估 ADR-026；不因已有代码而拒绝更好的实现。完整共同体仍由[同步与任务所有权](federation.md#unified-intent-memory)承担，任何库宣称跨设备可用都不能直接证明离线多主冲突和现实任务唯一执行。

<a id="memory-storage-partition-choice"></a>
#### 个人与工作资料怎样分区，为什么这样选

组件选型之外，还要选择数据的组织方式。以下是对当前普通 PC 与个人伙伴目标的工程判断，不是不同数据库的性能跑分；信息分类与完整共享规则只在[知识章](knowledge-learning.md#memory-scope-model)维护。

| 组织方式 | 好处 | 主要问题 | 取舍 |
|---|---|---|---|
| 所有原文和记忆放一个全局向量集合，依靠提示区分 | 原型接入快，跨内容相似搜索直接 | 相似不代表允许使用；主人、客户、NPC、计划与已完成结果容易混淆，提示不能代替过滤 | 不作为权威数据模型 |
| 每个项目一套完全独立的记忆 | 项目隔离直观 | 主人通用习惯反复学习，跨项目统筹困难；复制偏好后纠正和遗忘难以收敛 | 用于确需隔离的敏感项目，不作为所有项目的默认方式 |
| 个人、工作、知识、Agent 各自引入一整套框架 | 各模块可快速使用专用能力 | 重复提取、索引与模型配置，多个写入权威和后台调度增加维护成本 | 保留实验对照，不全部常驻 |
| 单份整体画像文档直接覆盖，再附项目标签 | 画像易读，提示装配简单 | 局部纠正容易误改其他属性，情境例外和出处容易丢失 | 只把画像文档作为派生阅读视图，不作为唯一事实原件 |
| **统一接口，按主体/用途/项目/世界分域；共享用引用与晋升；敏感域可物理隔离** | 保留同一助手的连续性；局部可纠正、可迁移；适合单机与后续事件复制 | 必须实现严格的用途视图、依赖撤销和后端过滤契约；逻辑分域不能替代操作系统隔离 | **推荐**：延续原件、事实、账本、配置的现有物理落点，增量补语义，不要求合成一个巨型 DB |

首期仍由原 Python Host 管理 SQLite 与原件引用，MemoryStore 管事实，MemoryViewResolver 管一次使用资格；不是每种记忆各起一个服务。FTS/向量/关系索引只存派生数据，同一 embedding 执行后端供多个获准任务复用，但不得跨域混装提示、缓存或检索结果。真正敏感的资料可单独库、目录和受限进程；普通域共享连接/缓存不等于共享读取权限。

这种选择保持[原文—事实—知识—经验的流程](knowledge-learning.md#memory-operating-cycle)，以及[先回复后整理、按需召回、独立节点与升级](#memory-recommended-plan)。实现前先固定用途字段和混合消息正反例，再对比提取器；若产品规则尚未表达清楚，换更强的提取库也只能更快地产生难以纠正的数据。资源上限继续使用[既有预算](delivery-validation.md#memory-resource-envelope)，没有为每个域额外分配一份模型或进程预算。

<a id="memory-module-adoption"></a>
### 推荐组合如何落到独立模块

下表是实现归属，不创建同名常驻进程或新的开发阶段。现有文件可先通过接口分离职责；只有依赖或故障隔离需要时才增加 Worker。

| 职责与现有落点 | 推荐方式 | 不由该模块决定 |
|---|---|---|
| 短期工作记忆：`context_assembly.py`、`assistant_context.py` | 继续有界装配近期对话；借鉴 MemGPT/Letta 的分层上下文，摘要带来源，可回查原文 | 不把摘要当唯一原件，不通过压缩删除任务账本中的未结事项 |
| 情景原件：`conversations.py`、`continuity.py` | 借鉴 MemPalace 的可定位原文和人物/主题组织；首先补有界、允许范围内的经历检索 | 不自动扫描全部软件历史；“房间”名称不是权限 |
| 候选整理：`personal_candidates.py` 与 `semantic_candidates.py` 后的 MemoryExtractor 适配层 | 0.1.50 实现按需结构化 LLM 基线，保留确定性规则；`tools/memory_lab` 已有 LangMem 与 Mem0 公共 SDK 的隔离实验适配 | 仅实验、不写正式事实、不更换主循环；[LangMem 对照](delivery-validation.md#memory-langmem-shadow-evidence)、[Mem0 对照](delivery-validation.md#memory-mem0-shadow-evidence)与[当前产品范围](knowledge-learning.md#semantic-candidates-runtime) |
| 本地比较与决定：`memory_comparison.py`、`memory_review.py` | 2026-10-19 工作树已实现[有限关系提示与显式处理](contracts.md#memory-candidate-review-contract)，比较算法可替换，签名/事务保护复用宿主 | 不使用相似度自动改写画像，不把旧记忆发送给提取模型；正式发布见[验收状态](delivery-validation.md#memory-candidate-review-evidence) |
| 长期事实：`memory.py`、`memory_sources.py` | 保留唯一写入入口；0.1.44 已补新候选来源、失效及纠正/遗忘保护，时间语义和完整派生关系继续增量实现 | 数据有效性不交给向量库或 Wiki 文件覆盖规则 |
| 知识编纂：`knowledge.py` 前的 KnowledgeCompiler | 借鉴 LLM Wiki 的摄取/查询/维护循环与 OpenWiki 的 Claims、增量章节 patch | 不新建竞争总设计，不重写全部聊天为一册 Wiki，不自动发布技能 |
| 检索视图：`memory_view.py` | 词法优先；向量是可关的召回补充，合并后重验范围与来源；同一模型由节点共用 | 不因相似度高绕过项目、人格、现实/NPC 域和供应商限制 |
| 后台整合：现有任务队列 | 借鉴 LightMem 的分组批处理；A-MEM 关联作为可重建候选，空闲且有预算才做 | 不每五分钟无条件调模型，不因待整理积压阻塞聊天 |
| 多设备复制：SyncTransport | 继续[应用事件复制方案](federation.md#memory-sync-options)，索引按各节点资源重建 | 库的多用户字段、云服务或复制向量不等于“统一意志”；不接管任务唯一执行 |

**Wiki 与事实库的权威边界：**项目已有的正式文档仍由对应仓库的 manifest/章节维护；Jarvis 生成的知识说明、个人记忆阅读页是带来源的派生视图。主人编辑个人阅读页应转换成可检查的修订请求，不能让 Markdown 和 SQLite 同时独立裁决同一事实。EverOS 的 Markdown 权威路线有可移植优点，但本项目保留已有事务事实权威以减少迁移风险；可以吸收可读导出与重建能力，不必复制它的全部存储模型。

LLM Wiki 适合把反复使用的资料整理成有引用的主题页，原件和版本仍保留；小规模可直接按目录/标题读，大规模再索引。它不保证知识正确、维护免费或适合高频任务状态。生成摘要若遗漏否定、日期或少见细节，要能退回原件查证。OpenWiki 负责具体证据机制的参考，概念稿本身不提供可直接继承的软件许可或可用性保证。[S219](references.md#s219)

MemPalace 的上游 R@5 是检索指标，不能和另一框架的最终问答正确率直接排序；其无 LLM 的原文检索路径仍有 embedding、索引和磁盘成本。它适合验证“少总结、多保留证据”是否减少遗漏，但全量原文会增加存储与误召回，默认模型的中文能力、纠正后旧经历的读取和跨域过滤必须另测。[S220](references.md#s220)

<a id="openwiki-adoption"></a>
### OpenWiki：适合项目知识，不取代整套记忆

核验对象是用户指定的 `langchain-ai/openwiki`，固定到 `7c469e59584bfac3f97f5c32a67604de46805999`（package 0.7.2）。本次静态读码未执行它的安装、生成、插件注册或定时任务。与个人记忆框架相比，它更直接覆盖“Jarvis 理解多个项目、代码变化后知识不过时”。

| 已核查机制 | 借鉴到哪个独立模块 | 必须调整的边界 |
|---|---|---|
| Claim 的稳定 ID、来源 resource/version、增补/确认/修订/撤回；代码行范围哈希定位 [S161](references.md#s161) | 项目知识的 EvidenceResolver / KnowledgeCompiler | 版本匹配只说明来源未变，不能证明模型理解正确；增加 proposed/implemented/verified 状态与测试回执，不能把设计说明当现有能力 |
| 先给紧凑搜索结果，再按页面/章节读取；多 Wiki 保留来源身份 [S162](references.md#s162) | ProjectCatalog 与 Retriever 的分节读取 | 由 Jarvis 提供已允许的项目集合；workspace 关联是组织功能，不等于访问授权；不能默认带入所有私人项目 |
| 每页保存进度、保留未变化的 Claims、处理中断可续接 [S160](references.md#s160) | 可取消、可恢复的知识编纂任务 | 复用 Jarvis 任务账本和模型网关，不增加第二个后台调度器；更新按来源增量触发，不每轮聊天重写全书 |
| Markdown / 可视化知识图 | 知识浏览与可读导出 | 阅读视图和派生解释可以重建；权威文档仍按本仓库 manifest / 章节树维护，不额外生成一个竞争的 `openwiki/` 总设计 |

**两个实质限制：**当前 `searchWiki` 读取所选 Wiki 页面，`rankSearchUnits` 每次建立内存 SQLite FTS5，再使用 `porter unicode61` 排序；这避免持久索引陈旧，但工作量随所选页面增长。代码中的 camelCase / 路径拆词不等于中文分词，不能直接保证中文两字词召回。Jarvis 大量、多项目的日常查询应复用有源版本水位的持久增量索引，并对中文进行独立验证。[S162](references.md#s162)

现成 CLI 需要 Node ≥ 22.22.0，包含 DeepAgents / LangChain、多个供应商 SDK、MCP 等依赖；检索实现使用 `node:sqlite`，但完整依赖链仍涉及 checkpoint SQLite 原生组件。Windows 安装遇到无匹配二进制时可能需要构建工具，不能把“Markdown 文件”误认为零运行环境。生成/更新会用模型；只读 search/read 自身不调用模型。宿主集成当前支持代码 Wiki，不能把独立 CLI 的 personal brain 能力全算进宿主集成。[S160](references.md#s160)

首期采用它的边界和机制，不整体复制运行时。如果后续希望直接使用完整 OpenWiki，通过可选 KnowledgeCompiler Worker 在受限临时输出目录运行，产出**带来源的候选 patch**，经 Jarvis 文档检查后更新对应权威章节；兼容现有章节格式和目录的改造成本必须纳入对照。集成不能自动修改本仓库 AGENTS、安装全局插件、注册 cron 或启用自动合并。

2026-10-18 又读取了快照 `6c14bff27830034bfd70c15bde46825d7686ec60` 的 README、package 和检索文件 [S226](references.md#s226)。上文机制分析明确基于 10 月 16 日固定版本，不把新 HEAD 当成已完成兼容审计的升级包；正式适配前应对所选发布版本重新核对 Claims 路径、依赖和章节 patch 行为。

<a id="memory-dependency-audit"></a>
### 已核查的依赖负担与默认部署

以下是 2026-10-16 固定源码的直接依赖声明，**不是完整依赖闭包、安装体积或内存跑分**；不同语言/拆包方式的数量不能直接排序。快照、文件摘要和解析结果见[静态证据](delivery-validation.md#memory-source-evidence)。

| 候选 | 静态核查结果 | 对普通 PC 的影响 |
|---|---|---|
| Mem0 Python | 8 项基础声明，含 qdrant-client、SQLAlchemy、模型 SDK 与 PostHog；Qdrant adapter 支持本地 path [S154](references.md#s154) | 无需因此强制 Docker / Qdrant 服务；仍需模型/embedding 和依赖适配。默认遥测需显式关闭并验证网络行为 |
| MemOS local plugin | 8 项 JS 声明，Node ≥ 20，含 better-sqlite3、Transformers.js [S155](references.md#s155) | 增加 Node / 原生轮子 / 可选推理资源；不要与其完整服务部署混算 |
| Graphiti | 7 项基础声明，含 Neo4j driver、NumPy、模型 SDK；另有 FalkorDBLite 等 extras [S156](references.md#s156) | 不能笼统称“必须远端图服务”；嵌入式选项也需要单独验证 Windows、资源回收和图维护成本 |
| Hindsight API slim | 53 项基础声明；上层 API 依赖 slim[all]，extras 可带入本地 ML、ONNX、pg0 [S157](references.md#s157) | `slim` 名称不代表适合轻节点；先作为稳定主机服务评估。pg0 仍是 PostgreSQL 方案 |
| Cognee | 55 项基础声明，含 LanceDB、图后端、FastEmbed/ONNX、文档解析及服务组件 [S158](references.md#s158) | 文档处理能力完整，但不应为少量偏好记忆默认安装整套；按具体解析缺口评估 |
| OpenWiki | 27 项 JS 运行依赖声明；Node ≥ 22.22.0，独立生成与只读检索有不同成本 [S160](references.md#s160) | 适合按需编纂工具；可借鉴机制而不增加常驻 Node / 第二模型配置面 |
| Letta Code | Node ≥ 22.19、另声明 Bun 工具链，含终端/Agent 运行组件 [S159](references.md#s159) | 属于编码工作者，不因记忆需求引入第二个完整 Agent 主循环 |

2026-10-18 补充读取下列固定源码声明，完整 URL 与文件摘要见[本轮静态复核](delivery-validation.md#memory-review-evidence)。这是部署取舍依据，尚未测安装后的依赖闭包、内存、速度或中文质量。

| 新增候选 | 本轮静态观察 | 本地部署判断 |
|---|---|---|
| LangMem [S221](references.md#s221) | Python ≥ 3.10；基础依赖包含 LangChain、LangGraph、模型 SDK、Trustcall、LangSmith | 接口便于适配不等于包小；先在独立环境调用函数式提取，核查追踪/网络配置 |
| MemPalace [S220](references.md#s220) | Python ≥ 3.9；默认依赖 Chroma、NumPy、tokenizers、Hugging Face Hub；另有 GPU、DirectML、多模态等 extras | 首次 embedding 可能下载模型；离线前要备齐。选 SQLite 后端不自动移除默认包依赖，extras 不全装 |
| LightMem [S222](references.md#s222) | 当前声明 Python ≥ 3.10 且 < 3.12；固定 Torch、Transformers、sentence-transformers、LLMLingua、Qdrant client 等版本 | 研究复现环境独立；不把默认依赖合并进 Jarvis 基础环境，借鉴批处理可不引入整个训练/推理栈 |
| A-MEM [S223](references.md#s223) | sentence-transformers、Chroma、scikit-learn、LiteLLM 等 | 先验证关联是否有收益；已有 embedding 和网关应复用，避免再常驻一套模型 |
| EverOS [S224](references.md#s224) | Python ≥ 3.12；LanceDB/Arrow、SQLite、Web 服务组件及多个 everalgo 包；可选多模态 | 与 LightMem 的当前 Python 约束不能直接共用一个解析环境；本地无外部数据库不代表无运行时、模型或后台开销 |

Graphiti、Hindsight、MemOS 与 OpenViking 的本轮 README/依赖快照记录于 [S225](references.md#s225)，用于核查候选仍在变化；这里保留旧版数量的日期，不把旧直接依赖数写成当前安装体积。OpenViking 当前仍有分组件许可与 README 附加说明，实际复用须按固定文件核对，不能据名称推断所有代码都可无条件改写再分发。

默认运行仍使用已有 Python + SQLite，不新增 Postgres、Redis、Neo4j、Docker、WSL、K8s 或常驻 Node。已存在的文档渲染 Node 是开发工具，不因此变成终端用户的运行依赖。语义检索启用后只选择一个 embedding 执行后端；不同时引入 PyTorch、ONNX、Transformers.js 三条推理栈。多个 Agent、项目和人格共用模型进程，不各加载一套权重。

候选运行实验中，Mem0 使用 `MEM0_TELEMETRY=false`，OpenWiki 使用 `OPENWIKI_TELEMETRY_DISABLED=1`（或其支持的 `DO_NOT_TRACK=1`），并另核对网络行为；不能把关闭遥测等同禁止业务模型调用，也不能仅凭文档说明证明没有其他网络请求。最初静态调研未安装这些框架；后续 Mem0 的独立环境与回环限制已在[实验记录](delivery-validation.md#memory-mem0-shadow-evidence)单列，正式运行环境仍不安装 Mem0，OpenWiki 未因此进入运行流程。[S154](references.md#s154)、[S160](references.md#s160)

后台提取、索引和知识编纂走现有有界队列；默认一个后台作业、批量合并变更、互动优先、取消可恢复。小库先按需更新，后续若启用维护也只处理 dirty sources；不做无限网上学习、每次对话全量反思或重复嵌入。冷启动、空闲/峰值内存、安装和退役预算统一见[资源设计与验收](delivery-validation.md#memory-resource-envelope)。

<a id="section-9f65cb73fb32"></a>
### 冻结选型的依据与成本

先过硬门：本机离线、可导出原件和事件、纠正/遗忘完整、权限与模拟域隔离、兼容恢复、无未声明外发、许可和依赖可固定；任何一项失败不能靠高召回抵消。再比较中文召回与时间问答、错误记忆率、延迟/CPU/RAM/磁盘、后台入库的模型费用、同步字节量和迁移工作量。未测项目写“未知”，不填主观 95 分。

依赖成本包含模型文件、分词器、原生轮子、运行时和可离线重建材料；不能只比较 Python 包大小。常驻服务、重排模型和图提取均按需启用。升级触发器为冻结任务集上的可重复缺口，而不是固定“超过几万条就必须换数据库”。模型候选见[嵌入模型](models-offline.md#embedding-candidates)，实验入口见[记忆选型验收](delivery-validation.md#memory-selection-evaluation)。

<a id="grok-build-comparison"></a>
## Grok Build 源码对照与模块化借鉴（2026-10-16，proposed）

**结论：优先借鉴编码 Agent 的执行机制，把完整 Grok Build 保留为可选 CodingProvider；不整体替换 Jarvis 内核，也不为了复用它而将现有 Python/Web 系统重写成 Rust。** 它在编码会话、工具执行和上下文管理上的实现明显比当前 Jarvis 原型完整；Jarvis 的共同体、数据所有权、资源和发布边界更符合本项目目标，但大部分仍是设计，不能据此宣称运行质量更高。

本节唯一维护借鉴对照、选择理由与模块归属。编码适配语义见[外部编码执行器](evolution-release.md#external-coding-executor)，上下文接口见[上下文编排契约](contracts.md#context-assembly-contract)，实施落入[既有 K 路线](core-bootstrap.md#grok-adoption-stage-map)，实测要求见[V-OSS 验收](delivery-validation.md#open-source-adoption-validation)。

<a id="grok-audit-scope"></a>
### 核验对象、源码证据与限制

- 审阅用户指定的 [Samuel521199/grok-build-fork](https://github.com/Samuel521199/grok-build-fork)，固定提交 `8adf9013a0929e5c7f1d4e849492d2387837a28d`；提交记录日期为 2026-07-16。仓库 `SOURCE_REV` 为上游 monorepo 修订 `2ec0f0c8488842da03a71eeee3c61154957ca919`，二者不是同一个版本号。不把这个快照称作上游当前最新版本。[S146](references.md#s146)
- 已下载独立研究副本，阅读实际 Rust 实现、配置、测试源码及用户指南；未运行安装脚本、编译、登录、模型请求或上游测试。以下“有实现”只表示定位到代码；性能、Windows 构建结果和完整安全性均未实测。
- 静态解析该快照：Cargo workspace 有 **79 个 member 条目**，Cargo.lock 有 **1,270 个 package 条目**，工具链固定 Rust 1.92.0。这是依赖/构建范围信号，不是运行进程数、安装体积或内存测量，不能直接证明它“太重”。README 明确 Windows 源码构建是 best-effort、未在此树测试；提供 Windows 二进制与 Windows 源码构建已验证是不同结论。[S146](references.md#s146)
- 测试源码覆盖取消、并行派发、压缩、子 Agent 孤儿回收等，但不能按测试文件数量评价可靠性。例如 `parallel_dispatch_tests.rs` 中部分用例检查模拟的顺序/分支，不能代替真实工具故障测试。[S147](references.md#s147)

<a id="grok-feature-comparison"></a>
### 能力对照：我们涉及了什么，哪里应采用更好的做法

| 能力 | 此快照中实际看到的机制 | Jarvis 当前与后续范围 | 本项目的选择 |
|---|---|---|---|
| 会话、任务与交互并行 | 每会话 `SessionActor`，命令/事件通道；提示队列、取消、插话、通知回放 [S147](references.md#s147) | 当前有两个聊天请求槽、单 Worker 持久队列和指定请求取消；通用 Agent 会话仍待 K2 | **借鉴会话独立事件循环和取消作用域**；任务状态仍由现有账本拥有，UI 不成为调度者 |
| 工具运行接口 | `Tool` 将类型化参数、描述、能力与执行分开；统一进度流，最终一个 Terminal；WorkspaceOps 执行 [S147](references.md#s147) | 当前固定目录 Worker 和浏览器动作已有真实回执，任意工具循环尚未完成 | **优先借鉴**；新增工具只注册一次，映射既有 Capability/Action/Artifact，不将外部 Tool trait 变成核心依赖 |
| 并行工具与文件编辑 | 派发前准备/检查，同批写入按参数中的路径字符串加锁，异步结果关联原调用 [S147](references.md#s147) | 当前后台执行串行；未来需多个任务与编码协作 | 学其分阶段派发，但改用经过路径解析的资源标识、读写冲突与有界并发；不同会话、大小写/相对路径别名也要互斥；未声明效果的 Shell 不自动并行 |
| 长上下文与模型切换 | token 阈值、手动/自动压缩、溢出恢复、两段压缩及历史恢复代码 [S147](references.md#s147) | 0.1.23 已抽出上下文装配模块，预留用户固定要求、按完整轮次裁剪；持久会话和通用摘要仍未实现 | **近期最值得补的缺口之一**：上下文编排与模型调用分开，先保留任务约束/来源/产物，再做可追溯摘要；首轮不照搬全部预测压缩优化 |
| 多模型接入 | Sampler 隔离模型请求配置、重试与流解码；存在 Chat Completions、Responses、Messages 三种协议 [S152](references.md#s152) | 当前已有原生供应商适配、Google Vertex 认证等；并非只接一个模型 | 保留单一 ModelGateway，借鉴统一响应、取消和错误分类；三种兼容协议不证明当前所有供应商或模型都可用，也不能替代我们的 Vertex 路径 |
| 编码工作区与回退 | 文件状态跟踪、Git/JJ、worktree、逐提示检查点；durable checkpoint 开关、原子写入和恢复缓存 [S148](references.md#s148) | 当前 WorkspaceService 主要登记项目和保存文本；运行包回退已有，代码候选工作区未完成 | K3 增量实现候选快照、补丁校验与冲突保护。**源码回退、任务恢复、运行包回退分别管理**；回退文件不能撤回已发出的网络/硬件效果 |
| Skills、插件、MCP、Hooks | 多来源技能发现；插件元数据发现与执行分离；项目 hook 信任迁往统一 folder trust；ACP/MCP 适配 [S151](references.md#s151) | 种子三库和模块清单存在；通用运行时装载、第三方插件尚待实现 | 借鉴按需发现、名称空间、版本化和执行前检查；外部格式只经 importer 转成自有清单。可信路径不能单独代替包摘要、版本与权限边界 |
| 子 Agent 与角色 | 声明式 role/persona、模型/工具覆盖、worktree、取消/恢复/用量归集；`MAX_SUBAGENT_DEPTH = 1` [S147](references.md#s147) | 动态 Agent、资源租约和角色解耦已设计，完整团队未实现 | 借鉴生命周期与角色模板；**不是无限递归 Agent 引擎**。首期有界团队，模型/推理进程共享；扩大团队以资源和质量证据为准 |
| 知识与记忆 | 实验开关控制的 Markdown 原件、SQLite/FTS5、可选 sqlite-vec、混合召回、MMR、时间衰减、dream 整理 [S149](references.md#s149) | 已选择本地事实/原件与派生索引分层；长期记忆仍待 K2，中文词项探测已有记录 | **优先借鉴算法与故障降级**；不直接接管其 MEMORY.md 为主人事实库。继续使用既有记忆接口、中文评估和删除/纠错语义 |
| 编辑器与无界面使用 | 实现 ACP Agent；headless 支持结构化输出、恢复会话、工具筛选及轮数限制 [S150](references.md#s150) | 当前 CLI/Web/托盘；CodingProvider 与编辑器连接待 K3 | 首个外部编码适配优先选一条 headless 流；有明确交互需求再验 ACP。ACP 是 Agent 与客户端协议，MCP 是工具/资源接入，二者不可混为同一模块 |
| 断网、共同体与长期自主运行 | 本机 leader/follower、多客户端、remote sandbox 与会话同步相关代码 [S153](references.md#s153) | 目标是节点断网自治、联网领域事件合并、任务所有权对账；完整共同体待 K6 | 这些实现可参考连接恢复，**未构成我们所需的多主离线共同体验证**。继续沿用 federation 契约；本机 leader 不能直接升级为“统一意识” |
| 生成代码后的自我改进 | 编码、测试工具、会话/文件回退、更新组件及记忆整理属于不同子系统 | K3 编码候选 → K4 受控发布 → K5 模块替换，仍待实现 | 不把外部 Agent 的“完成”当发布决策；继续由独立验收、发布与健康模块完成闭环 |
| Windows 与隔离 | 沙箱核心使用 Landlock/Seatbelt；非 Unix 分支不施加此沙箱，apply 仍返回 Ok；Unix 不支持/应用失败也有继续运行路径 [S148](references.md#s148) | 已有 Windows 固定 LPAC/Job Worker 子集，尚无通用生成代码隔离 | **不得直接移植该降级策略**。真实执行前检测有效隔离，缺少时保留分析/补丁生成能力并等待合适执行器；不是宣称当前 Jarvis 已安全运行任意代码 |

这里比较的是具体职责，不打一个把功能完整度、未来目标和实测性能混合的总分。编码产品完成度上 Grok Build 有更多可检查实现；普通 PC 的资源优势、长期稳定性或更高成功率，目前两者没有同条件对照，结论保留到实测。

<a id="grok-module-adoption"></a>
### 借鉴后仍然独立的模块边界

下表是逻辑职责与拟定落点，不创建空目录或常驻服务。完整源码树仍只在[项目结构](#project-structure-1)维护；首期同 Host 的模块按函数/接口隔离，需要独立权限或版本时才拆进程。

| 自有模块及落点 | 可借鉴内容 | 输入、输出与唯一所有者 |
|---|---|---|
| `dialogue` 内的 ContextAssembler | chat-state、compaction、token 预算 | 接收有修订的会话/任务/检索引用，输出模型上下文视图；不直接执行工具、写事实或改变任务状态；[唯一契约](contracts.md#context-assembly-contract) |
| `goal-task-runtime`、`agent-orchestrator` | actor/mailbox、取消、恢复、用量归集 | 前者独占 Task/Action 状态，后者只提出计划；现有 `jarvis_core/task_queue.py` 渐进承接，不能平行创建 Grok 队列 |
| `capability-registry`、`action-gateway` | typed Tool、发现与进度/终态约定 | 注册能力与验证意图；执行走受限 Worker，Tool 返回结果是待核验回执，不能自写成功状态 |
| `memory-computation` + 已有记忆 Provider 边界 | 分块、混合召回、MMR、降级与整理候选 | 原件/事实归 `memory-service`，索引可重建；检索、摘要与整理输出仍受域、来源、撤回和外发规则约束 |
| 工作区/文件系统适配器 | 文件快照、worktree、变更追踪 | 从当前 `jarvis_core/workspace.py` 的项目登记扩展；候选写入与最终产物分开，数据库和原始项目由 Jarvis 管理 |
| `adapters/coding/grok-build/`（可选） | 完整 Grok 的 headless 或 ACP | 接收既有 coding_job，返回候选 diff、产物与执行记录；按需进程，不能读写生产账本/记忆库或调用发布入口 |
| `adapters/protocols/` | MCP 工具发现、ACP 客户端/服务端映射 | 外部 ID 映射内部 ID，校验协议版本/能力；配置、认证、重连局限在适配器，不将供应商类型传播进核心 |
| 既有 `agent-factory`、`team-controller` | role/persona 模板、父子生命周期 | 生成 AgentBlueprint 并申请既有资源租约；人格不授予权限，子任务预算从父预算扣减；不为每个 Agent 部署模型/数据库 |

两条路径必须区分：**原生模块借鉴**时，每个工具意图经过 Jarvis ActionGateway；**外部完整编码器**内部自带工具循环，不能假装其每个本地动作已由 Jarvis 逐项批准。后者只有在整份 coding_job 的工作区、进程、网络和凭据范围可由外层执行器约束时才可执行；否则只作为源码参考。ACP 通知和 CLI 工具 allowlist 都不能代替 OS 边界。

<a id="grok-context-memory-tradeoffs"></a>
### 三个需要改造的具体设计

**上下文与记忆分开。** 压缩是给下一轮模型提供较小输入；长期记忆是保存经核实、可纠正、可遗忘的信息。压缩结果不能自动晋升为事实，不能压掉未完成任务、用户纠正、资料禁发限制或 UNKNOWN 动作。0.1.23 已将聊天装配独立为可测试模块，保留用户固定要求和完整近期轮次；它仍不是完整长任务记忆或自动摘要实现。契约与失败行为归[上下文编排](contracts.md#context-assembly-contract)。

**借鉴检索策略，不复制整块记忆系统。** Grok 的源文件可读、索引可重建、无向量可回退这三点很适合本项目；其 memory crate 却直接依赖 auth、config、telemetry、tools 等，并非直接摘下就能用的独立小库。工作区路径 hash 适合单机目录分组，不能作为跨设备稳定项目身份；chunk schema 也不能替代 Jarvis 的事实修订、撤回与域语义。MMR/衰减/来源权重先逐项做消融；访问越多加分可能放大旧错误，长期偏好也不应仅因时间衰减被“忘记”。dream 应映射为 MemoryCurator 的待验证整理候选，沿用[晋升流程](knowledge-learning.md#continuous-learning-2)，不另起无限后台学习循环。[S149](references.md#s149)

**可编译拆分不等于可独立替换。** 快照中的 memory crate 有 24 个直接 dependency 条目，workspace crate 有 81 个；`acp_session.rs`、`tool_calls.rs`、`handle_request.rs` 分别为 2,054、3,013、2,015 行。行数不是质量分数，但联同依赖关系说明摘取成本不能忽略。值得学习的是无 I/O 类型层、执行适配和组合入口；不复制大量会话职责到 Jarvis 单个万能类。运行中的版本替换继续使用[模块生命周期](contracts.md#interfaces-1)和[发布单元](evolution-release.md#critical-review-7)，同进程修改不能保证无中断。

<a id="grok-reuse-decision"></a>
### 复用方式、维护成本与本轮决定

| 方式 | 收益与代价 | 决定 |
|---|---|---|
| 按自有契约实现相同机制 | 保留 Python/Web 与既有状态，依赖最少；需自己实现和测试 | **K2 首选**：上下文编排、工具运行接口、有限计划、检索降级 |
| 按需启动完整 Grok 编码进程 | 较快复用编码能力，进程边界清楚；其认证/依赖/工具策略仍须验证 | **K3 备选**：与 Codex 争取首个 CodingProvider，先选一个实测通过者，不同时铺开所有后端 |
| 摘取纯算法或小型叶子模块 | 可减少重复实现；需切断无关依赖、维护来源与兼容测试 | 按实际缺口逐项评估，首选分块/排序/流事件规范和测试场景；不因文件位于独立 crate 就直接引入 |
| 整体 fork 后充当 Jarvis 内核 | 立即获得较多编码界面，但混入第二套会话/配置/工具/更新权威，持续同步成本大 | **当前不采用**；保留自己的品牌与 Web 工作台，不移植整套 TUI |

第一方许可证为 Apache-2.0，另有工具移植、随包工具和 Mermaid 等第三方声明。若以后复制或改写派生代码，记录精确来源提交/文件、适用声明、修改说明与随包 notices；不能仅保留仓库根 LICENSE 就推定覆盖所有资产，也不复制产品名称和品牌资产。当前仅研究和设计，没有把上游源码或依赖纳入 Jarvis 发布包。[S146](references.md#s146)

上游 README 说明此树由 monorepo 定期同步；升级需要先固定候选修订、核对差异和契约，再跑适配与故障测试。外部二进制不自行替换当前已固定版本，旧进程按任务排空后退役；保留范围与卸载规则沿用[健康维护](health-maintenance.md#system-health)。本轮没有启用自动更新、后台监控或真实编码执行。

<a id="mcp-integration-choice"></a>
## 常用 MCP 选型与集成（2026-10-17）

**0.1.37 实现十项来源目录与统一管理；0.1.55 首先接通 Context7 的受限只读文档任务。**选择依据为维护方来源、具体任务收益、依赖成本和与现有能力的重叠；不以 star 数或目录收录替代有效性验证。[来源评估](../evals/reports/mcp-source-review-2026-10-17.json)保存九个仓库的精确修订、归档状态与许可元数据；没有复制上游实现或安装服务器。界面归[MCP 管理](interaction-persona.md#extension-management-ui)，选用条件唯一规则归[MCP 与技能配合](tasks-agents.md#mcp-selection-policy)。

| 来源 | 对当前项目的价值 | 接入取舍 |
|---|---|---|
| Context7、GitHub | 版本文档与远程代码/Issue/PR 证据，配合编程指导 | Context7 先接无凭据的官方 HTTP 文档查询，真实队列调用通过；GitHub 仍需凭据和权限验收。[S179](references.md#s179)、[S180](references.md#s180) |
| Playwright | 浏览器结构、真实交互和界面回归 | 已有 Jarvis 浏览器能力优先复用；新适配不能绕开现有隔离。[S181](references.md#s181) |
| Brave、Tavily | 时效检索与带来源的研究 | 同类搜索通常二选一，按账户、覆盖和成本选。[S182](references.md#s182)、[S183](references.md#s183) |
| Firecrawl、MarkItDown | 多页网页采集与文件文本提取 | 按输入类型选择；转换成功不证明原文正确或版式保真。[S184](references.md#s184)、[S185](references.md#s185) |
| Filesystem、Git | 外部 MCP 客户端的文件和版本工具 | 协议参考实现；与现有文件/Git 接口重叠，按实际缺口接入。[S186](references.md#s186) |
| Blender | 场景、三维演示与拆解素材 | 社区项目，非 Blender 官方；需插件、脚本与输出验收，不能替代专业 CAD。[S187](references.md#s187) |

官方参考仓库已归档旧 GitHub、Brave、SQLite 等实现，当前选择维护方的 GitHub/Brave，SQLite 暂不引入。Memory、Sequential Thinking、Time 暂不默认推荐，因为现有记忆、模型推理和系统时间已有职责，尚无证据支持另建一套权威。[S186](references.md#s186) 配置模板只提供登记起点；未来运行须固定安装版本、核对依赖与凭据，并进入既有 K2 工具、Task/Action、取消和预算约束。完整编码修改/测试闭环仍归 K3，不另起实施阶段。Context7 选择理由是用途明确、只读、已有官方托管端点，可先验证现有队列到工具回执的最小链路；当前不引入新依赖或常驻 MCP 进程。匿名额度可能变化，不能将本次成功解释为永久免费可用。实测见[运行证据](delivery-validation.md#mcp-runtime-evidence)。

<a id="rea-integration-choice"></a>
### REA 软件解析：技能优先的集成评估与首期适配

已确认用户提到的项目是 **morluto/rea — Reverse Engineer Anything**；本轮 GitHub API 观察为 **308,807 stars**，热度仅用于确认身份。审阅固定提交 `47d3c6b1a15c166091b47666c9cac6dbd882454c`，源码包版本与 npm 本次试跑版本均为 **6.5.0**；二者分别固定，npm 元数据没有提供 gitHead，不将版本号相同当作构建一致性证明。实测 npm 随包 SKILL 为 22,513 字节，主分支审阅文件为 23,510 字节，内容摘要不同；正式适配需按实际安装版本的工具契约加载资料。[S228](references.md#s228)

**适合集成为一个“软件结构与行为解析”技能，优先适配固定版本 CLI，后续再接同一工具后端的 MCP 会话。** REA 本身已有 `reverse-engineer-anything` 技能和六份按目标加载的参考资料。技能负责选择目标、规划调查、按证据解释与提出重建方案；解析器、反编译器和运行观察器才产生工具结果。完整源码仓库的一般阅读继续使用已有文件/代码工具；REA 主要补充发布包、ASAR、二进制、运行行为与版本差异的证据。[S229](references.md#s229) 0.1.45 已将固定 CLI 的 JavaScript 目录路径接入一个活跃技能；MCP 会话与其他格式仍未接通。

| 已审阅的实现 | 对集成的意义 | 取舍 |
|---|---|---|
| `scripts/rea.mjs` 分开 CLI/MCP；`src/cli/javascriptApplicationAnalysis.ts` 与 `src/server/registerElectronTools.ts` 调用同一应用服务 | CLI 能直接获得 Evidence JSON，无需先完成通用 MCP 客户端 | 先实现窄范围、类型化 CLI 适配；避免复制 TypeScript 解析实现进 Python |
| `JavaScriptApplicationService` 校验输入、静态重建、进度、取消和部分证据；隔离分析 worker 解析 AST | JavaScript/Electron 静态入口可形成首个真实产物 | 当前只读明确的 JavaScript 目录或 ASAR 过滤文本快照，不执行目标；原包与成员来源一并保存 |
| `domain/evidence.ts` 保存目标摘要、提供者、分析配置、位置、observed/derived/inferred、限制和证据关联 | 能接 Jarvis 的任务、文件摘要和报告来源 | 保留原始证据及解释摘要，不能把推断写成已观察事实；REA Evidence ID 不替代 Jarvis Task/Action ID |
| `SetupSkill.ts` 一起管理入口与六个参考文件；上游还有面向自身开发/CI/变更日志的技能 | 参考资料属于一个能力包，安装助手针对已有宿主配置 | 用户菜单仅一个完整入口；不把参考文件、工具或 REA 仓库维护技能逐项导入 |
| `package.json` 提供 Node CLI，含解析、MCP、浏览器、终端等依赖，Frida 为可选依赖 | 可独立运行，但不是零依赖的提示词文件 | 按需进程、固定版本与摘要，避免每个任务执行 `npx @latest` 或自动 setup/update |

REA 主仓库采用 MIT；复用代码或技能需保留对应版权与许可。Hopper、IDA、JEB 及其他可选工具各有自己的许可和安装条件，不能由 REA 的 MIT 一并覆盖。正式适配将已安装 npm 6.5.0 和 Node 24.15.0 复制到独立运行目录，保留包内许可与第三方文件；没有移植解析实现到 Jarvis Python 模块。[S231](references.md#s231)

| 接法 | 可以得到什么 | 当前判断 |
|---|---|---|
| 仅技能说明 | 根据用户已有源码、截图或分析报告组织调查、解释和规格 | 有方法价值，但不能凭文字增加反编译/抓取能力 |
| 技能＋受控 REA CLI | 静态包分析、证据报告；补相应 provider 后扩展原生分析 | **首期已实现目录路径**，复用任务账本、作用域策略与交付核验；更多格式逐项扩展 |
| 技能＋REA MCP | 保持调查会话、证据分页、连续工具追踪与更多操作 | 后续复用同一能力，接入真实 MCP transport/tools/cancel 后逐项验收 |
| 大量移植 REA 内部实现 | 深度修改解析器与协议 | 目前没有必要；内部模块不是已承诺稳定的独立 Python 库，长期升级成本高 |

Windows 本机 Node **24.15.0** 满足上游引擎范围（22.19+ 的 22 系列、24.11+ 的 24 系列或 26+）。静态 JavaScript 样例无需 Ghidra。原生 EXE/DLL 分析另需 Ghidra 12.1.x、匹配的 64 位完整 JDK 和包内 Windows 原生组件；上游 Windows Ghidra P0 仍标实验性，只覆盖文档列出的只读操作/格式，不能据此承诺所有功能跨平台一致。[S230](references.md#s230) 本次 PATH 未发现 `rea`、`java`、`javac`；这不排除用户在其他位置已有安装，原生分析依赖未验收。

**评估时 Jarvis 0.1.43 的缺口：** `skills.py` 对工作指导使用固定准入集合和 **1,800 UTF-8 字节**正文上限；上游主 SKILL 文件约 23 KB，不能整份加入当前 guide。现有 `mcp_catalog.py` 仍报告 `runtime_available=false`，登记不会运行工具。限定 Python 成长执行器也不是通用 Node/反编译进程适配器；旧科普实验出现过 Node LPAC 启动失败，应重新证明 REA 所需进程边界，不能把本次普通开发进程试跑算为 Jarvis 隔离通过。

建议只增加一个短入口，按任务加载 JavaScript、原生或运行观察参考；由宿主适配器绑定工具名称、目标路径/摘要、固定 Node 与 REA 路径、输出目录、总截止时间和进程树资源。先支持 `analyze-javascript-application`，完整 JSON 保存为任务产物，向模型提供带来源的有界摘要；需要时再分页读取。`detail: summary` 是 MCP 已保留证据的交付选项，不是此次 CLI 命令的通用旗标；CLI 先保存完整结果再派生摘要。缩小展示内容也不等于减少全量分析工作。上游默认分析器 heap 1 GiB、每个源码 300 秒，只限制对应分析器/文件，宿主还须限制整棵进程树与整个任务。[S229](references.md#s229)

0.1.45 的适配由 `rea.py` / `rea_process.py` 提供，技能入口为 [SKILL.md](../adapters/skills/rea/SKILL.md)，运行固定文件清单及摘要由 `config/skills/rea-runtime.json` 绑定。安装准备脚本只复制调用者指定的已安装固定包，不执行上游 setup 或运行时下载。完整进程/文件边界见[执行边界](security-sovereignty.md#rea-static-boundary)。

最终流程建议为：明确要理解的功能和目标 → 分类并检查所需依赖 → 最小静态调查 → 输出证据、推断与未解决问题 → 用户任务包含实现时交给编程工作流 → 用可观察行为测试独立实现。当前限定 Python 成长链不能承诺重建任意桌面软件。使用条件归[REA 选用规则](tasks-agents.md#rea-skill-policy)，阶段归[现有技能工作包](core-bootstrap.md#skills-adoption-stage-map)，试跑和待验项目归[REA 验证](delivery-validation.md#rea-review-evidence)。

REA 可以帮助理解 AI 应用的界面、客户端逻辑、可见接口和本地文件；客户端分析无法直接取得未下发的服务端实现、私有模型权重或训练数据。反编译伪代码、静态关系和有限行为一致性，都不等于恢复原始工程或证明完整等价。

<a id="rea-effectiveness-improvement"></a>
#### 接入后的实际价值与改进优先级（2026-10-18）

**当前判断：0.1.47 已形成有界 JavaScript/Electron 目录与 ASAR 文本的静态解析、字面关注项及报告闭环，适合辅助查入口、模块和 IPC 关系；尚未形成按具体问题调查真实软件、解释功能并验证重新实现的完整能力。** 后续仍保留一个完整技能，由短入口组织任务，固定工具提供证据；增加参考资料或工具操作不会增加菜单中的技能数量。

[效果补测](delivery-validation.md#rea-effectiveness-evidence)发现，清晰的字面量通道可以解析，但目录筛选和证据输出使部分微型输入也无法交付。两个同输入候选实验均由失败变为可解析，说明优先改进宿主适配具有直接价值；这只能支持这些场景的改善，不能据此给整个产品估算成功率提升百分比。0.1.47 已支持显式 focus 或从 `prompt` 提取字面标识符并定位证据，尚不驱动语义调查、追问和模型解释；即使解析成功，也不能算已回答任意用户问题。

| 优先级与既有阶段 | 改进内容 | 预期实际收益与证据强度 |
|---|---|---|
| 首先，K2/W2—W4 | 将完整证据保存为独立、有界、摘要绑定的任务产物，账本保留小回执；按页读取相关证据，并显示覆盖范围与省略项 | **同输入实验支持明显改善可交付范围**：当前 20 条通道因 stdout 上限失败，固定解析器在实验上限内获得 20 条配对。不能仅扩大 stdout 后继续把全量 JSON 塞入回执；仍需验证持久化、下载、取消和恢复 |
| 同批，K2/W1—W2 | 为解析任务提供发布目录选择，明确支持选中的 `dist` 等子树；按入口/目标选取必要源码，保持凭据、链接和越界排除；之后逐项接入 ASAR | **目录选择已有同输入实验支持**；ASAR 过滤快照已于 0.1.47 实现，并通过官方打包器生成的普通包与外置源码样例，真实应用覆盖仍待扩展。Electron 官方说明发布源文件通常使用 ASAR，覆盖该格式比只支持源码目录更贴近实际发布包。[S234](references.md#s234) 不取消所有文件数量限制，超预算时明确范围并保留未知 |
| 然后，K2/W2—W4 | 将用户问题映射到入口、模块、IPC 或某项功能；提供证据定位、关系视图和带出处的中文解释；需要时继续读取证据 | 有望明显提高报告的可读性与问题相关性，**目前尚无模型质量对照证明收益**。仅向模型发送所需内容，解释首次准入优先官方 Google；确定性解析继续零模型调用 |
| 按真实目标需要扩展 | 对无法静态确定的调用增加受控运行观察，再逐项接入原生 provider | 能增加运行事实，但成本与执行边界明显不同；不能把静态关系视为运行可达，也不能承诺仅改提示词就解决动态通道、混淆或原生代码 |
| K3 | 从证据整理行为规格，交给 CodingProvider 实现并进行独立功能对照 | 才能回答“能否借鉴并做成自己的功能”；必须验证用户可观察行为，不能用结构相似或成功生成文件代替实现正确 |

以上为 0.1.45 评估后的优先改进方案；当时的候选实验没有变更正式服务。**后续 0.1.46 已实现独立证据保存、分页读取以及发布目录纳入，并完成同输入对照和本机任务交付**，范围见[改进验证](delivery-validation.md#rea-improvement-evidence)。**0.1.47 增加 ASAR 获取和字面关注项，仍使用一个组合技能**，见[包与关注项验收](delivery-validation.md#rea-asar-focus-evidence)。对比此前只能传目录，现在可直接选择符合预算的发布包；对比此前只看全貌，现在可定位指定通道/文件证据。本轮已接入可选的带引用中文解释与右侧结果工作区，实测与修订见[专项证据](delivery-validation.md#rea-explanation-workspace-evidence)。它把结构关系转为可读说明；引用成员核验不验证推断正确，仍需按实际目标核对。真实源码对照已补充 WebTorrent Desktop 与 Motrix 的限定主进程目录，并发现和修复 IPC 处理器关系被显示层遗漏的问题；范围与限制见[真实应用证据](delivery-validation.md#rea-real-apps-evidence)。运行观察和 K3 功能复现仍待实现。详细比较指标只在[效果验收](delivery-validation.md#rea-effectiveness-evidence)维护；当前没有证据承诺总体分析精度、节省时间或功能复现成功率会提高到某个数值。

<a id="matt-pocock-skills-evaluation"></a>
## Matt Pocock 编码技能选型（2026-10-17，accepted）

**结论：适合选择性引入工程方法；Jarvis 当前需要补齐技能加载和编码执行，才能成为真正可运行的编程技能。** 现有开发宿主 Codex 可使用其技能格式；Jarvis 的扩展登记、模型 API 和 CodingProvider 是不同层次。把文件登记到设置中，不会自动创建编辑、测试或修复能力。实施仍落在既有 K2 技能入口与 K3 编码执行器，不增加另一条实施路线。固定源码、静态统计及模型观察见[本轮记录](../evals/reports/matt-pocock-skills-review-2026-10-17.json)。

本节唯一维护选型和适配取舍；模型状态与建议见[编码模型快照](models-offline.md#coding-skills-model-snapshot)，执行器契约见[CodingProvider](evolution-release.md#external-coding-executor)，待运行的质量比较见[编码技能评估方法](delivery-validation.md#coding-skills-evaluation-plan)。初次评估只审阅源码、既有证据和只读接口；后续 0.1.35 适配和真实运行另记于[技能闭环证据](delivery-validation.md#native-skills-evidence)。

**2026-10-17 后续用户决定：采纳编程工作流技能包方案，按既有 K 阶段实施，并与 Anatomy 及全部内置/第三方技能统一管理。** 首批采用排错、TDD、模块设计和代码审阅四项；其他技能逐项准入。上述静态评估记录保留原时点 proposed 状态；本次 accepted 指选型与管理要求，0.1.35 已接入四项压缩原生指导、分层策略和只读源码报告；编辑/测试/修复执行器及同模型质量收益仍未实现/未验证。0.1.36 将其中九个完整文本能力纳入活跃目录，六个来源组件合入两项组合，其余退出活跃登记；当前使用/不使用条件与逐项归属只在[技能适用场景表](tasks-agents.md#skill-applicability-catalog)维护，不让 `ask-matt` 或上游 setup 再建立独立路由权威。

<a id="matt-pocock-skills-scope"></a>
### 固定来源与实际内容

审阅 `mattpocock/skills` 提交 `49dd158d1076134a641b33efb035946536778336`。该快照共有 38 个 `SKILL.md`：engineering 20、productivity 7、misc 4、in-progress 7；插件清单版本 1.3.1，仅分发前两组的 27 项，实验目录与偶用工具不属于默认插件。MIT 许可允许改编和分发，复制实质内容时保留版权及许可声明。[S171](references.md#s171)

主要价值是需求澄清、小步实现、真实反馈与模块设计。它以 Markdown 指令及关联参考文件为主，不自带模型权重、编译器、任务执行器或保证正确性的判定器。正常使用需要宿主提供读取/修改文件、命令执行、Git、技能引用解析；部分流程还需要任务跟踪器、浏览器或子代理。不能由“支持各种模型”推导小模型也能完成同样工作。[S172](references.md#s172)

| 技能 | 对 Jarvis 的用途 | 适配方向（实现待验收） |
|---|---|---|
| `diagnosing-bugs` | 先建立能重现问题的检查，再最小化、验证假设、修复并回归 | 首批采用；脚本模板按 Windows/PowerShell 改写，用现有回执记录检查结果 |
| `tdd` | 每次实现一小段可观测行为，测试与实现逐步推进 | 首批采用；已获授权且验收范围明确时沿用范围，不逐个测试重复询问；简单可逆外观修改按实际风险决定检查 |
| `codebase-design` | 通过小接口承载实际复杂逻辑，避免无需要的抽象 | 首批采用其原则；术语服从本仓库既有定义，不强制替换接口/适配器等用语 |
| `code-review` | 分别检查需求满足程度和代码规范 | 首批改为可串行执行的双视角审阅；既有未提交修改也须纳入实际 diff，不仅检查 `<base>...HEAD` 的已提交内容；子代理作为后续可选能力 |
| `to-spec`、`to-tickets`、`domain-modeling` | 把已讨论需求转为可核对的小任务和依赖 | 复用现有需求编号、K0—K6、ADR 与权威章节；不自动生成平行 `GLOSSARY.md`、`docs/adr` 或未登记 Markdown |
| `grill-with-docs` / `grilling` | 澄清真正缺失、会改变结果的决定 | 降低默认追问强度；可从仓库查到的事实由助手查询，沿用主人已明确的要求；显式需要深度访谈时再进入完整流程 |
| `implement` | 串联实现、必要检查与审阅 | K3 编码执行接通后使用；原文自动提交到当前分支的动作改为宿主任务范围内的明确交付动作 |
| `implement-spec`、`research` | 任务图调度与后台子代理 | 首期延后；Jarvis 尚无对应通用子代理编排，不能用文字模拟并行完成 |
| `setup-matt-pocock-skills` | 生成追踪器、术语与 Agent 配置 | 用本仓库适配配置替代默认脚手架，映射已有权威页和检查命令 |
| `misc`、`in-progress` | Claude hook、TypeScript 工具及实验流程 | 按实际任务单独评估，不随首批批量引入 |

上游 `tdd` 要求预先确认测试接口，`code-review` 默认并行子代理，`implement-spec` 创建分支/工作树并合并，`setup` 会修改指导文件；这些是源码中的工作流假设。审阅它们不代表已调用该技能，也不自动授权执行这些操作。[S172](references.md#s172)

<a id="matt-pocock-skills-integration"></a>
### 当前缺口与最小接入方式

1. **K2 按需加载。** 复用 `ExtensionCatalog` 的来源与摘要，在此基础上解析名称、描述、显式/隐式调用策略和参考资源，按任务装配所需正文；初次查询的额外登记模块返回 `runtime_available=false`、登记数为 0；0.1.35 的原生目录与它分开，五项已准入能力有真实 readiness，额外登记仍 dormant。关联技能与相对参考必须一起解析，不能只复制包装入口。UI 继续显示真实登记/可加载/可执行状态，入口归设置内技能管理。
2. **上下文预算。** 现有网关单次宿主 `instructions` 上限为 4,096 UTF-8 字节；云端文本总输入为 65,536 字节，本地为 4,096 字节。去掉 frontmatter 后，`code-review` 为 6,207 字节、`diagnosing-bugs` 为 8,462 字节、`codebase-design` 为 6,135 字节，直接拼入现有 instructions 会被拒绝。38 个技能文件合计 170,800 字节，亦不能整包加入云端一次请求。采用元数据发现、正文按需读取、参考文件再按需读取，并独立分配技能与代码预算；本地路线选择短流程。Codex 的分级加载方式可作参考，不能通过伪造用户历史/system 或提升记忆为规则绕过宿主语义。[S173](references.md#s173)
3. **K3 编码执行。** 复用既定 CodingProvider，接入一个实际可用的文件/补丁/检查执行器；本机能找到 Codex CLI 启动器，外部 Codex 适配仍未接通。0.1.37 / evolution-v1 已采用现有 ModelGateway 实现限定 Python 工具的 CodingProvider 与独立验收，见[模块边界](evolution-release.md#bounded-evolution-loop)。另一条原生路线需要在现有 ModelGateway 上接通工具调用、工具结果回传、有限循环、取消和产物核验。两条路线选一条做首个闭环，避免同时搭建重复执行平台。
4. **交付与用量。** 每个编程作业记录需求/基线、技能版本、所选模型、实际 diff、检查命令/退出码、tokens/费用与未完成项。外部编码器若自行请求模型，其身份和账单单独观察；当前网页 API Key 可用并不能证明外部 CLI 使用同一线路、同一 Key 或同一费用记录。上游自动提交、任务跟踪器发布和脚本运行必须与实际作业授权匹配。

采用文本技能不会必然增加常驻服务；主要额外成本来自更长上下文、多次验证/修复请求和可选审阅。只导入文件时质量增益为零；加载后可以改善需求与审阅步骤；完整代码质量改善需要真实编译/测试反馈，幅度须由同模型对照验证，不能承诺固定提升百分比或消除错误。

<a id="anatomy-integration-choice"></a>
## Anatomy 科普动画与机械拆解选型（2026-10-17，accepted）

**按用户决定纳入可选能力：以适配后的 Skill 指导创作，配合按需绘图/检查执行器，交付可交互科普图与机械结构拆解。** 先完成 HTML/SVG、源码、缩略图和检查报告，再扩展配音、字幕和视频出口；保持普通 PC 默认安装轻量。适用/排除条件只在[统一场景表](tasks-agents.md#skill-applicability-catalog)维护，实施归[既有 K 工作包](core-bootstrap.md#skills-adoption-stage-map)，验收归[V-ANI](delivery-validation.md#anatomy-validation)。本节是组件选型与集成取舍的唯一权威，0.1.35 已将固定绘图库、参数模板与 MIT 许可纳入发布源码；齿轮交互闭环局部 verified，完整自由科普、机械建模和视频仍待实现。

<a id="anatomy-source-scope"></a>
### 固定来源、可复用代码与能力边界

审阅 `wheresryan22/anatomy` 提交 `e9488296a44211c42701ff71705b7901470ec78f`。它包含 Skill、15 个 kit 文件、44 个测试文件及完整示例；普通 ESM/HTML 路线使用 Node 内置模块，浏览器检查另需 Chromium，React 输出才需要 React。MIT 版权与许可声明须随复制的实质内容保留；不以一次源码快照替代后续版本和资产许可核对。[S176](references.md#s176)

| 组件 | 采用方式与边界 |
|---|---|
| `SKILL.md`、必要 references | 保留概念、部件、几何、交互和验证流程；按任务读取，改为中文教学与既有任务契约，不强制每个小问题堆满 40 个部件 |
| `iso-kit.mjs`、`lathe.mjs`、`tube.mjs` | 首期复用等轴测实体、曲面与管线，走现有 Web 可展示的独立 HTML/SVG；不为此迁移整套前端到 React |
| `audit.mjs` | 检查已建模形体的间距、连接与绘制顺序；记录采样/容差和跳过项，不当作机械原理、强度或真实结构的证明 |
| `turn*.mjs` | 作为可选 3D beta；凹体拆成凸形部件，复杂运动先验证预算；不默认引入未文档化的实验变体 |
| `capture.mjs`、`drive.mjs`、`turn-check.mjs` | 封装输入/输出、页面异常、超时和进程树回收后复用，不能直接作为无限范围的浏览器工具 |
| 发布、会话统计及其他附属脚本 | 不进入科普能力的必需依赖闭包；不默认接入社区发布、GitHub 凭据、其他宿主会话目录或自动更新 |

交互机器隐喻、机械剖面和真实结构复原分别标明目的。Anatomy 的 3D 依旧是自有绘制与运动体系，未提供完整 CAD 内核、STEP/STL 工程交付或受力/热力仿真；制造图、尺寸公差和工程签核由将来独立 CAD/CAE 适配器承担。[S177](references.md#s177) 对真实机械，部件关系、尺寸/单位与工作过程来自可追溯资料；公式、运动、读数、标注和旁白共享同一数据模型。几何与浏览器检查通过也不提升为科学真实性已验证。

<a id="anatomy-adapter-boundaries"></a>
### Jarvis 适配层与产物交付

同一任务内形成“明确教学目标与来源 → 部件/行为模型 → Skill 指导生成 → 受控 Node 构建 → 几何与浏览器检查 → 宿主核验产物 → 交互预览”。技能目录只管理版本、策略与依赖，任务仍归原账本/队列；Node 和 Chromium 按需启动，代码只进入任务工作区，依赖包只读，文件/网络/凭据按本次范围约束，取消或崩溃按已验证进程树规则收口。原始上游脚本不是 Windows 隔离器；不得把现有固定元数据 Worker 宣称为可执行任意生成 JS 的通用环境。

当前文件编辑器不渲染 HTML/SVG，且单文本上限 1 MiB；发动机示例重建为 1,610,584 字节。科普产物需要独立、有大小配额的加载与预览路径，不放宽普通文件编辑限制来冒充支持。预览使用隔离来源或不带同源能力的沙箱框架，单独限制脚本/资源来源，不能借用工作台 nonce、凭据或业务接口；保留键盘、减弱动效、浅深主题、窄屏与中文部件说明，完整规则和状态呈现在[交互章](interaction-persona.md#skill-policy-management-ui)。

上游截图脚本在页面抛异常时可能仅打印异常并返回退出码 0；接入检查同时核对页面异常、预期状态/交互、实际输出与回执，不只看退出码。[S178](references.md#s178) 包版本绑定完整依赖摘要，记录 Node/浏览器版本；跨环境浮点末位差异按数值容差和可视结果核查，不能以改写历史摘要伪造字节一致。

完整视频需要额外的可定位时间轴/逐帧接口、字幕、分段 TTS 和编码器，分别登记为依赖能力并验收。FFmpeg 或 Remotion 按需选一个出口，不作为所有用户的强制常驻依赖。交互 HTML 已交付不能折算为 MP4 已完成；教学与结构资料不足时保留假设和待核验项，不凭画面精致补造结论。

<a id="dialogue-stack-choice"></a>
## 统一对话与语音的轻量接入选型（2026-10-18）

<a id="dialogue-runtime-adoption"></a>
### 复用现有实现，按边界拆分

**完整方案 proposed；0.1.48 的回复回执子集已落地，未安装新依赖。** 不因语音接入整体替换 Python Host、原生 JS 界面、SQLite 或已有模型网关。下表区分已实现与拟新增落点，不是所有文件均已存在的目录树；完整目录权威仍在[项目结构](#project-structure)。

| 落点 | 保留与改造 | 选择理由 |
|---|---|---|
| `jarvis_core/chat.py`、已新增 `turns.py` / 拟新增语义 `dialogue.py` | 保留现有个人上下文和模型答复；抽出 Turn 受理、会话代际、回应编排 | 防止继续把意图识别、执行和语音都塞入 ChatService；先定义接口，再移动代码 |
| 拟新增 `intent.py` | 复用确定性命令解析；一般输入使用有界结构化模型输出并校验 | 通用语义不是堆关键词；不默认常驻另一个大模型，也不每轮启动多 Agent 投票 |
| `task_queue.py`、`conversation_tasks.py`、技能/成长服务 | 共用 WorkAdmission 适配器，保留唯一账本与幂等键 | 不建立与原队列平行的新任务系统，逐项迁移旧前端拦截 |
| `resources.py`、`runtime_metrics.py` 与模型网关 | 由内存准入扩展到用途额度、等待原因、预算与公平调度 | 用现有监控和生命周期，不先引入 Redis、Celery 或集群调度 |
| 拟新增 STT 适配器＋现有 `speech.py`/Qwen | sherpa-onnx 的 SenseVoice int8＋已验证 VAD 起步；Qwen 短段合成 | 本地优先；精确模型/内存和云候补仍由[模型章](models-offline.md#voice-model-selection)维护；不把非流式切段识别包装为原生流式 |
| `server.py`＋已新增 `dialogue_routes.py` / 拟新增语音输入路由 | 先异步受理＋有界事件查询，按需加 SSE；连续 PCM 再加一个可关闭 WebSocket 适配层 | 保留现有 HTTP 边界和正常启动，不为长连接创建无限线程；跨协议共用 nonce/origin/实例与取消校验 |
| `index.html`、`dialogue.js`、`conversations.js`、`readout.js` 与拟新增语音输入模块 | 抽出发送状态机，任务卡不占全局 busy；AudioWorklet/Web Audio 负责有界采集与播放调度 | 麦克风接入/撤销、重采样、缓冲和断线分别验证；保留可访问图标及 J 品牌 |

0.1.48 文件职责：`runtime/node-host/jarvis_core/turns.py` 管短期受理/结果/取消，`apps/web/dialogue_routes.py` 管 HTTP 边界，`apps/web/dialogue.js` 管页面待发与回执查询，`server.py` 只接线并共享旧聊天槽。验证入口为 `tests/test_dialogue_turns.py`、`tools/probe_dialogue_ui.py`、`tools/probe_dialogue_deployment.py`。0.1.49 新增 `jarvis_core/dialogue_journal.py`，共用 `conversations.db`，由 `tests/test_dialogue_recovery.py` 与两项 `probe_dialogue_recovery_*` 验证恢复与删除。尚未加入通用持久事件流、独立 Dialogue 进程、意图解析和新第三方依赖。

0.1.51 新增的 `jarvis_core/dialogue_process.py` / `dialogue_worker.py` 在 0.1.54 扩为完整模型回复和阶段帧；相同实现用于独立的后台单槽池。`sample_tasks.py`、`skill_tasks.py`、`rea_explanation.py` 接线到该池，保留原计划校验、任务检查点和产物提交，不另造任务队列。个人事务留在 Host。继续用 Python 标准库与既有 Windows Job/HTTPX，无新依赖、额外数据库或空闲服务。契约见[进程边界](contracts.md#dialogue-process-contract)；回归入口为 `tools/check_conversation_lanes.py`，浏览器联测为 `tools/probe_dialogue_process_ui.py`。完整 R07 故障域仍未验收。

Pipecat 的帧处理、优先控制和中断机制可作实现参考；LiveKit 的轮次/插话及播放历史处理可作语音质量对照。**当前推荐借鉴机制、保持适配端口，不直接整体引入两套框架。** 后续确需 WebRTC、多端实时音视频或更多供应商插件时，在独立试验中比较 Pipecat 和 LiveKit 的依赖、空闲 RAM、冷启动、CPU、取消能力与维护成本，再决定是否替换媒体适配层。官方介绍不证明其在本机更轻或更快。[来源](references.md#conversation-isolation-sources)

Python I/O 使用有界线程/异步任务，原生推理/重 CPU 工作保持独立进程；浏览器采集开启 AEC/降噪是请求，硬件/浏览器是否生效需要实测。必要协议先通过小适配层接入，不为使用 WebSocket 将全应用立即改写为另一套 Web 框架。以延迟、可靠性和资源数据决定下一步，不以语言或框架偏好替代评估。

<a id="project-structure"></a>
## 项目文件结构与依赖规则

本页是源码和运行数据目录的唯一权威；所有领域、工具链与健康维护目录已合并。完整树是实现的放置规范，当前已落地以下种子原型、聊天/模型选择、预检、独立控制、固定 Worker 及 网页浏览器队列及 0.1.11 项目文本保存子集，其余目录按阶段创建。

<a id="implemented-layout"></a>
### 当前实际落地范围（0.1.18）

模型协议由 `jarvis_models/gateway.py` 实现；新增 `jarvis_models/catalog.py` 管理同提供商多模型及受限参数档案，初始目录来自 `config/model-profiles/providers.json`，后台建立后本机 `model-admin.db` 成为唯一有效配置，规则见[模型后台](models-offline.md#model-admin-config)。

| 现有路径 | 内容与依赖边界 |
|---|---|
| `pyproject.toml`、`uv.lock`、`jarvis.ps1` | Python 3.13 开发环境与锁定依赖；启动器不含凭据 |
| `contracts/schemas/` | K0 六类业务 JSON Schema，以及只读预检、旧版停止状态兼容消息 schema；唯一机器字段定义 |
| `seed/{knowledge,rules,skills,system-manifest}/` | 三库初始数据与 22 资产摘要，不是运行时学习库 |
| `runtime/node-host/jarvis_core/sample_tasks.py`、`contracts/schemas/sample-plan.schema.json` | 0.1.30 固定自然语言报告组合、严格候选计划；复用原 FIFO/账本与 Worker，不引入新任务框架 |
| `runtime/node-host/jarvis_core/` | `policy.py` 范围/资源限制、`ledger.py` 持久状态、`service.py` 确定性任务；`chat.py` 的 ChatService 负责文字会话和有限路由，模型不授予动作权限 |
| `runtime/sovereignty-supervisor/jarvis_safety/` | 保留旧版控制库、事件和代际；无认证的显式兼容迁移，正常会话停止不触发全局锁存；仍以同一 OS 用户运行 |
| `runtime/recovery-cli/main.py`、`jarvis-control.ps1` | 只保留 status 和 migrate-local；无全局 stop、密钥、密码或登记入口 |
| `runtime/node-host/jarvis_core/control.py` | 业务对独立控制库的薄接入，旧宿主与旧任务代际失效；业务库迁移由 `upgrade-control` 显式执行 |
| `runtime/node-host/jarvis_core/worker.py` | 固定元数据 broker、每次派发校验运行包、输入/回复绑定；Host 仍持有枚举与提交权 |
| `runtime/worker-host/worker.py`、`runtime/worker-host/jarvis_worker/` | 固定计算入口与 ctypes Windows LPAC/Job 适配；不接收模型脚本，不新增第三方依赖 |
| `config/worker-profile.json`、`tools/prepare_worker.py` | 本机小型 Python 包固定摘要与离线组装；版本变更须复核 profile，不自动接受新运行包 |
| `runtime/node-host/jarvis_core/worker_recovery.py`、`tests/test_worker_recovery.py` | 固定暂存根的登记、OS 锁、进程退出核验和定点残留回收；真实 Host 崩溃探测，不扫描未知资料 |
| `tests/test_worker.py`、`tools/worker_probe.py` | 真实 OS 合成拒绝/资源/进程故障测试，以及三次临时任务开销观察；不接触真实凭据内容 |
| `tests/test_control.py`、`tools/control_probe.py` | 旧版数据兼容、一致性、并发及真实子进程中断测试；探测只使用临时实例，不生成密钥 |
| `apps/cli/main.py` | 任务 CLI、`models/chat` 与 `preflight`；预检独立于业务状态读取和模型入口 |
| `apps/computer-use/main.py`、`jarvis-computer.ps1` | 可选独立浏览器 CLI：demo/run/status/cancel；复用现有任务库 |
| `adapters/computer-use/jarvis_computer/` | `protocol.py` 校验、`planner.py` 模型/显式测试规划器、`browser.py` Edge 与私有进程 Job、`service.py` 控制循环；模型可替换，驱动变更需重验 |
| `config/computer-use/demo-task.json`、`apps/computer-use/demo.html` | 明确的合成任务范围与内部演示页，不是业务网站 |
| `contracts/schemas/computer-{task,action}.schema.json`、`tests/test_computer.py` | 可选扩展契约与真实浏览器故障测试；不修改 K0 冻结资产 |
| `runtime/node-host/jarvis_core/preflight.py`、`config/runtime-boundaries.json` | 只读诊断实现与当前角色/资源访问声明；声明不授予权限，也不是监督器部署证据 |
| `tests/test_preflight.py`、`tests/fixtures/preflight/` | 诊断故障、只读性、版本与正反例测试；独立于 K0 冻结的 22 项资产 |
| `apps/web/server.py`、`apps/web/index.html`、`apps/web/computer.js` | loopback 聊天与目录/浏览器后台任务面板；聊天文字通过独立归档模块恢复，附件/草稿仅页面内存，任务从主账本恢复 |
| `apps/tray/companion.py`、`launch.py`、`tray.ps1`、`TrayApplication.cs` | Windows 托盘：Python 管理本实例命名事件，系统 Windows Forms 显示图标与菜单，异步读取本机状态；桌面退出不写全局锁存，不启动模型 |
| `apps/tray/assets/`、`tools/export_tray_icons.ps1` | 从 TrayApplication.cs 的 DrawIcon 生成 ICO 与预览；完整运行包包含 C#、PowerShell、Python 和 ICO |
| `tests/test_tray.py`、`tools/probe_tray_package.py`、`evals/reports/tray-baseline.json`、`evals/reports/tray-idle-resources.json` | 真实托盘进程/HTTP 状态/退出隔离、完整运行包与加入托盘后的待命资源证据；包探测结果保存在 tray-package.json |
| `apps/web/workspace.js`、`apps/web/workspace.css` | 项目侧栏、页面会话/草稿、输出位置、保存操作与回执；不维护后台任务状态 |
| `apps/web/admin.html`、`admin.css`、`admin.js` | 模型与费用的四页本机后台；复用 server.py 同源接纳，不创建第二个服务 |
| `jarvis_models/registry.py`、`jarvis_models/billing.py` | 本机连接/Key 版本管理、价格快照与用量聚合；完整路径位于 adapters/models/provider-native/ |
| `contracts/schemas/model-admin.schema.json`、`tests/test_model_admin.py`、`tools/serve_model_admin_fixture.py` | 配置命令契约、版本/计价/HTTP 回归与不使用真实凭据的合成界面验收 |
| `runtime/node-host/jarvis_core/conversations.py`、`apps/web/conversations.js` | 本机会话文字归档与串行保存客户端；独立 SQLite、版本冲突与删除标记，不调用模型或新增依赖；接口见[归档契约](contracts.md#conversation-archive-contract) |
| `runtime/node-host/jarvis_core/memory.py`、`contracts/schemas/memory-fact.schema.json`、`apps/web/memory.js` / `memory.css` | 0.1.25 明确事实的独立存储/运行装配与面板，复用现有依赖；ChatService 逐路由过滤记忆与历史引用。接口见[记忆契约](contracts.md#explicit-memory-contract)，不包含自动提取或共同体同步 |
| `runtime/node-host/jarvis_core/knowledge.py`、`contracts/schemas/project-knowledge.schema.json`、`apps/web/knowledge.js` / `knowledge.css` | 0.1.26 独立项目文档登记、按需有界读取、词法检索、来源预览和历史引用；只存登记元数据，无新增第三方依赖或索引服务。见[运行范围](knowledge-learning.md#project-retrieval-runtime) |
| `runtime/node-host/jarvis_core/continuity.py`、`apps/web/continuity.js` / `continuity_routes.py`、`tests/test_continuity.py`、`tools/probe_continuity_ui.py` | 0.1.40 有来源的明确话题接续、独立 SQLite、逐记录范围与许可、修订依赖过滤；面板复用记忆入口，无新增运行依赖。见[接续契约](contracts.md#continuity-contract) |
| `tools/probe_companion_journey.py` | 0.1.42 个人核心联合验收：临时数据、真实 Edge/归档/LPAC/下载、服务重建与跨范围请求；默认模型替身，`--live` 增加一次真实对照。范围与证据见[联合验收](delivery-validation.md#companion-journey-evidence) |
| `runtime/node-host/jarvis_core/personal_candidates.py`、`apps/web/personal_candidates.js`、`tests/test_personal_candidates.py`、`tools/probe_recovery_candidates.py` | 0.1.43 按需中文候选、原句核对、确认去重与来源失效；复用原记忆/接续库。探针同时验证成长重新分析与丢响应恢复，见[候选契约](contracts.md#personal-candidates-contract) |
| `runtime/node-host/jarvis_core/semantic_candidates.py`、`apps/web/candidate_routes.py`、`tests/test_semantic_candidates.py`、`tools/probe_semantic_candidates_ui.py`、`tools/probe_semantic_candidates_live.py` | 0.1.50 最小语义事实提取、签名预览、分类确认及共用并发/取消；复用原网关和 MemoryStore，无新增框架或常驻进程。见[语义候选契约](contracts.md#semantic-candidates-contract) |
| `evals/cases/memory-extraction-pilot.json`、`tools/eval_memory_extraction.py`、`tests/test_memory_extraction_eval.py` | 离线规则/可选真实模型的固定提取先导评测；临时数据、分开核对内容和主体、不确认记忆。范围及结果见[提取评测证据](delivery-validation.md#memory-extraction-pilot-evidence)，不作为生产后台进程 |
| `runtime/node-host/jarvis_core/memory_policy.py`、`tests/test_memory_domains.py`、`tools/probe_memory_domains_ui.py` / `probe_memory_domains_resources.py` | 0.1.47 确定性事实分类、到期与主人日常/工作用途；沿原 SQLite，无新依赖/服务。语义、兼容及性能分别归[运行范围](knowledge-learning.md#memory-domain-runtime)、[契约](contracts.md#memory-domain-contract)、[验收](delivery-validation.md#memory-domain-evidence) |
| `runtime/node-host/jarvis_core/memory_sources.py`、`tests/test_memory_sources.py`、`tools/probe_memory_sources.py` | 0.1.44 候选来源标识、有界原文核对及真实页面验收；源关联和抑制状态由原 MemoryStore 同库事务维护，无新数据库、运行依赖或后台扫描，见[来源契约](contracts.md#memory-provenance-contract) |
| [REA 技能说明](../adapters/skills/rea/skill.md) | 软件结构解析技能的调用与证据阅读说明；正文不代替运行目录的实际能力状态或验收记录 |
| `runtime/node-host/jarvis_core/work_state.py`、`tests/test_work_continuity.py`、`tools/probe_work_continuity.py` | 0.1.42 任务/成长账本的只读、有界状态视图，接续保存引用并在请求时核验，状态摘要使派生历史失效；没有新数据库、执行器或后台服务。见[关联契约](contracts.md#work-continuity-contract) |
| `runtime/node-host/jarvis_core/personal.py` / `persona.py`、`tests/test_personal_core.py`、`tools/probe_personal_core_ui.py` | 0.1.39 当前输入的显式个人指令分流与独立持久表达；事实仍由原 MemoryStore 写入，Host 负责装配，UI 只负责显示/归档回执；没有新增运行依赖。接口见[个人核心契约](contracts.md#personal-core-contract) |
| `runtime/node-host/jarvis_core/evolution/settings.py`、`apps/web/evolution.js` / `evolution.css` | 0.1.64 三用途策略、兼容迁移和真实成长中心；行为只在[成长运行](evolution-release.md#bounded-evolution-loop)维护 |
| `runtime/node-host/jarvis_core/evolution/demand.py`、`apps/web/growth_routes.py` / `growth.js` / `growth.css`、`tests/test_growth_demand.py`、`tools/probe_growth_demand.py` / `probe_growth_demand_ui.py` | 0.1.41 会话需求适配与实际成果交付；复用既有成长账本、单 Worker、LPAC 和能力包，不增加服务、数据库、模型或依赖。见[需求契约](contracts.md#growth-demand-contract) |
| `runtime/node-host/jarvis_core/memory_view.py` | 0.1.33 协调事实与登记文档的请求级联合视图，不另建存储或后台进程；范围和预算见[运行契约](contracts.md#memory-view-runtime-contract) |
| `runtime/node-host/jarvis_core/calculator.py`、`contracts/schemas/calculation.schema.json` | 0.1.37 纯标准库的精确算术能力与回执；`ChatService` 先匹配当前纯算式，再沿原模型路由。不新增表达式执行服务，见[分流规则](models-offline.md#deterministic-calculation-runtime) |
| `runtime/node-host/jarvis_core/runtime_metrics.py` / `process_usage.py`、`apps/web/resources.js` | 0.1.34 请求级有界耗时观察与已知进程资源读取，复用原采样；不新增持久数据库/服务。见[观测口径](health-maintenance.md#parallel-runtime-monitoring) |
| `runtime/node-host/jarvis_core/project_files.py`、`apps/web/explorer.js` / `explorer.css` | 0.1.27 本机文件树、UTF-8 文本编辑、摘要冲突检查和单根工程文件；复用项目身份、标准库文件 I/O，无后台监听/索引/编辑器框架依赖。见[资源模块](architecture.md#project-extension-modules) |
| `runtime/node-host/jarvis_core/extensions.py`、`apps/web/extensions.js` / `extensions.css` | 0.1.27 MCP / 本地技能登记管理与来源检查；独立 extensions.db，无运行适配器、安装器或新常驻进程 |
| `tests/test_project_resources.py`、`tools/probe_project_resources_ui.py` | 文件/工程/扩展故障与实际 Edge 交互测试；临时项目，不写用户源码/配置夹具 |
| `runtime/node-host/jarvis_core/workspace.py` | 项目目录身份登记、明确文本导出、独占写入与摘要核验；标准库 SQLite/Tk，不新增第三方依赖 |
| `tests/test_workspace.py`、`tools/probe_workspace_ui.py` | 临时目录/HTTP 故障回归与 Edge 端到端验证；合成模型响应，无付费调用 |
| `adapters/computer-use/jarvis_computer/web.py` | 有界网页接纳层、任务查询与 PNG 校验，不增加持久调度队列 |
| `runtime/node-host/jarvis_core/task_queue.py`、`adapters/computer-use/jarvis_computer/task_queue.py` | 目录/浏览器共用 FIFO 调度与浏览器兼容包装，保留旧附表；版本/宿主与 UNKNOWN 检查，执行语义归[任务章](tasks-agents.md#browser-durable-queue) |
| `tests/test_computer_queue.py`、`tests/test_computer_web.py`、`tools/probe_computer_ui.py` | 队列崩溃/交接、HTTP 权限/并行/取消与真实 Edge 网页、窄屏验证；不调用模型 |
| `adapters/models/provider-native/jarvis_models/` | DPAPI vault、原生提供商适配、调用历史与数值用量；不再按累计调用次数拒绝请求，模型输出无执行权 |
| `config/model-profiles/` | 提供商配置与固定本地模型清单；没有明文密钥 |
| `tests/`、`tests/fixtures/` | 契约、核心、模型、诊断、聊天路由与网页 API 回归；故障测试使用临时目录，测试覆盖以验收记录为准 |
| `tools/check_seed.py`、`manage_models.py`、`model_probe.py`、`local_llm.py`、`speech_probe.py` | 校验、下载与受限诊断命令；没有注册后台服务 |
| `tools/release_bundle.py`、`tools/probe_release_bundle.py`、`tests/test_release_bundle.py` | 固定运行依赖候选归档、新槽解压及同版本恢复探测；候选放 `artifacts/releases/`，不激活服务、不打包凭据/现用账本 |
| `tests/test_runtime_start.py`、`tools/probe_runtime_start.py` | 启动前故障回退、两版本不可用、事务失败与数据保持验证；生产实现复用 releases.py |
| `tools/probe_task_faults.py`、`tests/test_task_faults.py`、`evals/reports/task-fault-matrix.json` | 固定目录任务 7 个真实进程退出点、2 类产物损坏的临时实例探测与回归 |
| `tools/probe_network_recovery.py`、`tools/network_probe_firewall.ps1`、`evals/reports/network-recovery.json` | 两个临时运行包的 Windows 程序出站阻断、启动恢复与规则清理；UAC 只用于防火墙辅助进程，不影响现用实例 |
| `evals/reports/k1-fault-network-baseline.json` | 本轮故障/网络验收的回归、文档检查与源码摘要；保留既有版本报告 |
| `runtime/node-host/jarvis_core/resources.py`、`config/resource-profile.json`、`tests/test_resources.py` | 后台队列物理/可提交内存准入、迟滞与冷却；不冒充 OS 硬资源预留 |
| `runtime/node-host/jarvis_core/browser_recovery.py`、`tests/test_browser_recovery.py` | 浏览器使用锁、登记目录与退出后回收；真实崩溃测试复用 test_computer.py |
| `runtime/node-host/jarvis_core/releases.py`、`tools/runtime_releases.py`、`tests/test_runtime_releases.py` | 本机运行包安装/健康检查/选择/回退/启动，私有 releases.db 与历史记录 |
| `tools/probe_runtime_releases.py`、`tools/probe_task_responsiveness.py`、`evals/reports/runtime-continuity-baseline.json` | 跨代码版本保留数据演练与后台工作期间前台响应的本机证据 |
| `tests/test_task_queue.py`、`tools/serve_task_queue_fixture.py`、`evals/reports/k1-progress-baseline.json` | 0.1.13 混合队列与界面、登记回收、候选运行包和历史回归证据 |
| `tests/test_web.py`、`tests/test_control.py`、`evals/reports/personal-lifecycle-baseline.json` | 0.1.14 会话取消隔离、待命与免恢复认证验证 |
| `tools/verify_baseline.py` | 汇总本地检查、源码摘要和已有诊断；不发出付费模型请求 |
| `tools/probe_memory_fts.py`、`evals/reports/memory-fts-probe.json` | 文档选型的中文 FTS5 合成探测与结果；独立于 0.1.4 运行能力验收，不代表已实现记忆服务 |
| `tools/sync_doc_navigation.py`、`tools/check_docs.py`、`tests/test_doc_navigation.py` | 文档维护工具：从 manifest 篇章归属与正文标题生成导航，核查遗漏、重复归类、过期导航与标题层级；不属于 Jarvis 0.1.4 运行功能 |
| `.vscode/settings.json` | Cursor / VS Code 工作区阅读配置：在内置 Markdown 预览中继续阅读链接目标；不改变全局设置或 Jarvis 运行行为 |
| `tools/probe_idle_resources.py`、`tests/test_idle_resources.py` | V-PC-02 的独立五分钟待命探测与证据计算检查；使用临时数据和独立进程，不终止正在使用的助手 |
| `.gitignore`、`.gitattributes` | 排除本机运行资料与可重建包；保持文件字节，避免 Git 换行转换破坏登记摘要 |
| `evals/reports/k0-baseline.json` | 0.1.0 历史验收基线与源文件摘要，保持原版本，不冒充本轮验证 |
| `evals/reports/computer-console-baseline.json` | 0.1.9 历史任务面板与部署基线，保持原版 |
| `tools/serve_chat_stop_fixture.py`、`evals/reports/chat-stop-baseline.json` | 0.1.12 取消按钮的临时网页夹具、请求/路由/传输测试及验证证据；不调用真实模型 |
| `evals/reports/project-workspace-baseline.json` | 0.1.11 项目文本保存的源码、回归与界面证据，见[本轮验收](delivery-validation.md#project-workspace-evidence) |
| `evals/reports/computer-queue-baseline.json` | 0.1.10 历史队列源码、检查与本机部署，见[队列验收](delivery-validation.md#computer-queue-evidence) |
| `evals/reports/computer-use-baseline.json` | 0.1.8 历史源码、浏览器/核心回归与已有模型实测，见[浏览器验收](delivery-validation.md#computer-evidence) |
| `evals/reports/k1-worker-baseline.json` | 0.1.7 固定 Worker 历史源码、隔离/资源测试、回归与默认实例探测，见[Worker 验收](delivery-validation.md#worker-evidence) |
| `evals/reports/k1-control-baseline.json` | 0.1.6 历史源码、控制故障探测、回归与默认实例迁移证据，见[控制验收](delivery-validation.md#control-evidence) |
| `evals/reports/k1-preflight-baseline.json` | 0.1.5 只读预检的历史源码摘要与回归证据，见[预检验收](delivery-validation.md#preflight-evidence) |
| `evals/reports/google-models-baseline.json` | 0.1.4 Google Pro/Lite 目录、实际调用及当时检查，见[Google 验收](delivery-validation.md#google-models-evidence) |
| `evals/reports/web-workspace-baseline.json` | 0.1.3 统一模型菜单和推理级别的历史证据 |
| `evals/reports/model-catalog-baseline.json` | 0.1.2 模型目录与参数迁移的历史证据 |
| `evals/reports/chat-baseline.json` | 0.1.1 聊天实现的独立证据；历史完成状态与范围以[聊天验收](delivery-validation.md#chat-evidence)为准 |
| `docs/`、文档工具 | 23 份有效 Markdown 和 19 张已登记图维护于 manifest，不创建平行说明全文 |

当前 Python 模块用明确 Host/adapter 包边界解耦，便于验证契约后换成其他语言或独立进程。首期选择 Python + SQLite + JSON Schema + HTTPX，是为快速验证持久性和提供商差异；没有因此把 Python 当作最终安全隔离边界。`jsonschema/httpx/google-auth/cryptography` 为核心开发依赖，其中 `cryptography==50.0.2` 继续满足模型供应商认证依赖；助手恢复密钥/密码流程已移除，本机状态及旧版状态迁移不导入密码库。`sherpa-onnx/sherpa-onnx-core/numpy` 为可选语音依赖，具体精确版本以 `uv.lock` 为准。网页原型采用 Python 本地 HTTP 服务与原生 HTML/CSS/JavaScript，没有因此引入 Tauri、React 或第二套模型路由；这些仍是按需替代方案。

| 仓库外实际位置 | 用途 |
|---|---|
| `H:\JarvisData\envs\dev` | uv 开发虚拟环境；可重建，不是完整离线编译包 |
| `H:\JarvisData\models` | 模型、许可、固定 llama.cpp 压缩包及受校验解压目录 |
| `%USERPROFILE%\.jarvis\worker-runtimes\worker-python-3.13.0-v1` | 本机 Windows Python 3.13 小包，约 22 MiB；要求支持持久 ACL，固定 manifest + 文件摘要，不在 H: exFAT 上部署 |
| `%USERPROFILE%\.jarvis\worker-staging\job-*` | 单任务只读元数据与入口副本；正常退出清理，Host 崩溃残留按[限制](security-sovereignty.md#worker-isolation)处理 |
| `%LOCALAPPDATA%\Jarvis\runtime` | 已安装运行槽位、选择记录和历史；不存业务账本，按核心章入口显式管理 |
| `%USERPROFILE%\.jarvis\browser-staging` | 仅 Jarvis 创建的每任务浏览器 profile、下载暂存与登记；不等于用户浏览器目录 |
| `%LOCALAPPDATA%\Jarvis\private` | DPAPI 凭据封装；[保护边界](security-sovereignty.md#prototype-security) |
| `%LOCALAPPDATA%\Jarvis\data` | 业务 control.db、独立 safety/control.db 与 safety/pending、model-probes.db 调用及价格快照、model-admin.db 有效模型配置（不含明文凭据）、workspace.db 项目/导出回执、conversations.db 会话文字及删除标记、memory.db 明确事实、project-sources.db 项目资料登记、extensions.db 扩展登记、任务产物和 diagnostics；清空聊天不删除这些记录 |

`.gitignore` 排除凭据、数据库、虚拟环境、模型、构建缓存及 `artifacts/releases/*.zip`；源码、文档、图源与生成图、测试和验证报告纳入 Git。主人指定的项目仓库及历史规则见[受控历史](MAINTENANCE.md#retirement-and-history)，忽略规则不是访问控制。本次未下载全套 C++/Rust 编译器，也没有宣称能断网重建所有依赖。未来按[工具链能力](toolchains.md#development-platform)补离线依赖闭包，不能把下载推理引擎等同于拥有自主编译平台。

<a id="project-structure-1"></a>
### 推荐源码结构

按领域与契约组织，语言可以替换。大括号为压缩表达，不是字面目录名；目录出现不代表已开发。此树给出被选中实现的归属位置，不是全量安装或全部后端的支持清单；尤其是语言、数据库、Agent 框架与部署适配器，仅为经过组件准入的实际需求创建相应目录。

```text
Jarvis/
├── README.md / AGENTS.md
├── Cargo.toml / Cargo.lock                    # 启用原生底座后创建
├── pyproject.toml / uv.lock                   # 已有Python原型
├── package.json / pnpm-lock.yaml              # 需要前端构建工具时创建
├── contracts/
│   ├── proto/{identity,tasks,actions,memory,models,federation,lifecycle,build,
│   │          sovereignty,agents,resources,worlds,local-components}/v1/
│   ├── schemas/                              # 包、技能、人格、蓝图、世界、知识、
│   │                                        # 租约、组件、停机、健康、修复、退役、
│   │                                        # 发布、构建、工具链、运行、provenance
│   └── {compatibility,codegen}/
├── apps/
│   ├── cli/main.py                           # 已有任务与文字聊天CLI
│   ├── web/{server.py,index.html}             # 0.1.1 loopback文字网页
│   └── {desktop,mobile}/                      # 后续按需
├── runtime/
│   ├── {bootstrap,sovereignty-supervisor,safety-alert-host,supervisor}/
│   ├── {node-host,worker-host,session-host,desktop-session-agent}/
│   └── {build-runner,verification-runner,recovery-cli}/
├── modules/
│   ├── core/
│   │   ├── {identity-policy,root-policy-enforcement,persona-config}/
│   │   ├── {goal-task-runtime,memory-service,artifact-service,action-gateway}/
│   │   ├── {output-delegation-gateway,capability-registry,capability-observer}/
│   │   ├── {resource-governor,agent-registry,world-runtime,local-component-manager}/
│   │   ├── {release-controller,topology-manager}/
│   │   ├── {toolchain-registry,build-coordinator,dependency-resolver,artifact-provenance}/
│   │   ├── {health-controller,architecture-guard,retirement-manager}/
│   │   └── federation/{membership,sync,reconciliation,coordination}/
│   └── intelligence/
│       └── {dialogue,agent-orchestrator,model-gateway,memory-computation,
│            evolution-lab,evaluation-service,persona-compiler,agent-factory,
│            team-controller,simulation-cognition,learning-planner,
│            technology-watch,knowledge-evolution,memory-curator}/
├── adapters/
│   ├── models/{provider-native,litellm,llamacpp,recovery-direct}/
│   ├── coding/{codex,grok-build,local}/           # 实际只创建已选中的适配器
│   ├── speech/{sherpa,realtime-provider,livekit}/
│   ├── agents/{langgraph,temporal}/            # 可选
│   ├── storage/{sqlite,postgres,vector-index}/
│   ├── computer/{windows,browser,filesystem}/
│   ├── hardware/{home-assistant,mqtt,serial}/
│   ├── embodiments/{desktop,avatar,game,robot}/
│   ├── network/{windows,linux}/
│   ├── protocols/{mcp,http-tools}/
│   ├── transport/{local-ipc,direct-tls,relay}/
│   ├── toolchains/{rust,python,node,cpp,dotnet,go,jvm,generic}/
│   ├── runtimes/{local,native,python,node,dotnet,jvm,wasi,oci,ray}/
│   └── build-environments/{windows-vm,linux-vm,oci,remote}/
├── sdk/{rust,python,typescript}/
├── seed/{knowledge,rules,skills,system-manifest}/
├── skills/{builtin,templates,examples}/
├── toolchains/{profiles,recipes,compatibility,bootstrap}/
├── config/
│   └── {defaults,policies,root-principles,personas,model-profiles,topologies,
│        agent-blueprints,world-templates,learning-sources,local-profiles,
│        architecture-rules,health-profiles,retention-policies}/
├── evals/
│   └── {tasks,interaction,memory,evolution,protected-holdout,owner-interest,
│        persona-continuity,dynamic-teams,simulation-boundary,knowledge-migrations,
│        offline-survival,shutdown-latch,architecture,regression,knowledge-hygiene,recovery}/
├── tests/
│   └── {contract,integration,end-to-end,offline,federation,upgrades,fault-injection,
│        offline-build,cross-target,toolchain-upgrade,build-isolation,evolution-loop}/
├── packaging/
│   └── {windows,linux,manifests,migration-tools,recovery,offline-packs,trusted-control-updates}/
├── tools/                                    # 已有文档、种子、模型与诊断工具
│   ├── check_docs.py / render_docs.cjs / package.json
│   └── {dev,codegen,benchmark,release}/        # 未来按需
└── docs/
    ├── README.md / MAINTENANCE.md
    ├── manifest.json                         # 当前文档与图表登记
    ├── <topic>.md                            # 名单以docs/README和manifest为准
    └── diagrams/{*.mmd,*.svg,*.png,render-validation.json}
```

自动产生的 Agent、NPC、人格、世界和知识候选进入运行注册表，不为每个实例创建源码模块。薄 SDK 不复制根规则；adapters 按需启用。

<a id="project-structure-2"></a>
### 单个模块模板

```text
module-name/
├── module.yaml          # 身份、版本、权限、依赖、生命周期
├── README.md            # 作用、边界、启动与运行说明
├── CHANGELOG.md
├── src/                 # 该模块唯一实现
├── tests/               # 单元、契约、回归
├── migrations/          # 自有状态的迁移
├── compatibility/       # 与相邻版本协作的用例
├── evals/               # 可公开的模块测试
└── release/             # 构建和恢复描述
```

共享协议来自 contracts，不在每个模块复制一份。SDK 可生成薄封装，不允许在多个语言 SDK 中复制核心业务规则。

初期同一个 node-host 内可承载多个业务模块，当前参考实现以 Python 为主；这些模块源码独立，但生产环境不可变，更新以整个 node-host 包为单位。需要独立发布频率或故障隔离时，再移到独立进程，沿用相同契约。不得把“代码分目录”宣传为已经具备全部运行时热替换能力。

<a id="project-structure-3"></a>
### 运行数据结构

运行数据与源码、安装包分离。实际路径在安装时配置；Windows 系统服务数据和用户会话数据使用对应账户的合适目录与 ACL。

```text
JarvisData/
├── identity/                    # 身份元数据；私钥仅保存密钥库引用
├── config/
│   ├── active/
│   ├── last-known-good/
│   └── proposals/
├── state/
│   ├── control.db               # 首期任务、预算、动作、outbox 同一事务
│   ├── task-payloads/            # 大型输入/检查点引用，不是第二任务账本
│   ├── memory/
│   ├── federation/
│   └── releases/
├── events/                      # 日志分段或对应快照引用
├── artifacts/objects/           # 内部产物对象/证据存储；不替代项目交付路径
├── indexes/                     # 可重建索引
├── models/                      # 模型、许可和哈希
├── packages/<module>/<version>/
├── releases/
│   ├── slot-a/
│   ├── slot-b/
│   └── manifests/
├── checkpoints/
├── experiments/                 # 自编程序和评估工作区
├── backups/
├── quarantine/                  # 不兼容或未通过验证的包
├── {personas,agent-blueprints,agent-instances,worlds,knowledge-migrations,local-components}/
├── toolchains/<id>/<version>/
├── dependency-store/<digest>/
├── build-images/<digest>/
├── builds/<build-id>/
├── provenance/<artifact-digest>/
├── {health,repair-journal,retirement,debug}/
├── documentation/              # 运行版本绑定文档；非源码docs副本
│   ├── active/                 # 当前已发布版本的文档包
│   └── retained/               # 仅支持窗口/恢复仍需要的包
└── logs/
```

系统运行时个人数据、模型权重、凭据、日志和内部产物对象默认不进入 Jarvis 自身源码仓库。面向用户的项目交付物按[项目根目录与默认输出位置](interaction-persona.md#project-root-output)保存；即使用户打开的是代码仓库，也不能因此把交付物静默转存 JarvisData。内部对象存储可以保留必要的证据或索引引用，但不是默认交付目录；0.1.11 的项目文本交付已按用户所选目录落盘，原有内部任务产物布局仍按其类型解释。系统自主进化的候选代码仍先进入 experiments，再经版本管理与发布进入 packages；用户指定项目中的普通代码创作不等于系统自我发布。


SafetyState 使用独立受保护存储与 ACL，承载锁存、安全事件和监督凭据引用；普通业务进程没有清除与回退权限。JarvisData 中的备份、retained 文档包与旧运行包按引用、支持期限和恢复策略退役；本次删除旧设计稿不等于取消这些运行时恢复要求。

<a id="project-structure-4"></a>
### 依赖规则

1. contracts 只定义协议与数据结构，不依赖业务实现。
2. modules 仅通过公开接口依赖其他模块。
3. adapters 依赖端口与 SDK；领域模块不导入适配器内部。
4. runtime 组合模块并管理生命周期，不承载全部业务逻辑。
5. apps 通过 API 操作系统，不能直接修改任务数据库。
6. 恢复代码不依赖 Python 智能框架或云模型。
7. 部分智能模块可自主生成，但受同样的接口、测试和发布约束。
8. 编译依赖和强制启动依赖不得成环；跨模块写表、生产运行中直接覆盖源码属于架构违规，CI 检查。运行时反馈循环按超时、去重与预算约束处理。

<a id="extensions-2"></a>
## 领域目录与受保护状态

扩展目录已纳入 [完整源码树](stack-project-layout.md#project-structure-1) 与 [运行数据树](stack-project-layout.md#project-structure-3)。安全锁存、监督凭据与事件独立于普通 JarvisData，权限、备份与防回退策略单独管理；路径分开本身不是隔离。

<a id="development-platform-11"></a>
## 构建模块的目录与复用边界

具体目录见 [统一源码与数据结构](stack-project-layout.md#project-structure)。这些逻辑模块初期可以由业务宿主与按需构建 Worker 提供。Build Coordinator 复用 Task Runtime 的调度与预算，工具链 Registry 复用不可变包存储，provenance 复用 Artifact；避免再建第二套任务、资源与包管理平台。

<!-- book-footer:start -->
[返回全书目录](README.md#book-tree) · [上一章：公共接口与数据契约](contracts.md) · [下一章：模型路由、本地模型与离线生存](models-offline.md)
<!-- book-footer:end -->
