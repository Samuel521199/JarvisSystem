# 技术栈、源码目录与运行数据

> 状态：完整目录与架构 proposed；0.1.17 当前实现与历史基线分开记录 · 更新：2026-10-16  
> [文档入口](README.md) · [维护规则](MAINTENANCE.md) · [架构图册](architecture-atlas.md)

<!-- book-nav:start -->
[全书目录](README.md#book-tree) › [第二篇 · 核心与工程基础](README.md#part-foundation) › 第 08 章 · 技术栈、源码目录与运行数据

## 本章导航

- [8.1 技术栈与选型理由](#technology-selection)
  - [8.1.1 先给结论：协议开放，初期实现收敛](#technology-selection-1)
  - [8.1.2 首期参考栈与可替代方案](#technology-selection-2)
  - [8.1.3 类 Codex 工作台的宿主与复用选择](#workbench-host-choice)
  - [8.1.4 语言与运行形态怎样选择](#technology-selection-3)
  - [8.1.5 普通 PC 优先：默认部署与组件准入](#technology-selection-4)
  - [8.1.6 自有任务状态机、LangGraph 与 Temporal 的取舍](#technology-selection-5)
  - [8.1.7 替换与隔离规则](#technology-selection-6)
  - [8.1.8 选型冻结条件](#technology-selection-7)
- [8.2 知识与记忆的开源选型（2026-10-15 调研，proposed）](#memory-open-source)
  - [8.2.1 存储和检索层：不同项目解决不同问题](#section-ee5f9aae063b)
  - [8.2.2 记忆框架：复用算法和接口，不交出数据所有权](#section-31d166a591e4)
  - [8.2.3 冻结选型的依据与成本](#section-9f65cb73fb32)
- [8.3 项目文件结构与依赖规则](#project-structure)
  - [8.3.1 当前实际落地范围（0.1.17）](#implemented-layout)
  - [8.3.2 推荐源码结构](#project-structure-1)
  - [8.3.3 单个模块模板](#project-structure-2)
  - [8.3.4 运行数据结构](#project-structure-3)
  - [8.3.5 依赖规则](#project-structure-4)
- [8.4 领域目录与受保护状态](#extensions-2)
- [8.5 构建模块的目录与复用边界](#development-platform-11)
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
## 知识与记忆的开源选型（2026-10-15 调研，proposed）

结论是采用 **节点本地事实存储 + 可替换检索索引 + 受控记忆提取 + 应用层同步**。每个完整节点都能独立读取必需资料；稳定主机可以提供更强检索，但不能成为其他完整节点的唯一记忆来源。语义设计见[知识页](knowledge-learning.md#memory-selection-design)，同步取舍见[共同体记忆协议](federation.md#memory-replication)。以下是根据官方代码库与文档作出的工程判断，不是性能跑分；未安装这些候选，也没有把公开基准成绩记为 Jarvis 的成绩。

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
| MemOS，Apache-2.0 [S97](references.md#s97) | 本地插件已有 SQLite/FTS5 + 向量思路；经验、任务摘要与技能复用 | **与 Mem0 二选一进入首轮算法对照。** 本地插件绑定特定 Agent 生态，不能直接视为 Jarvis 插件；自托管栈的 Neo4j/Qdrant 与本地插件是不同部署路线，不混报资源需求 |
| Graphiti，Apache-2.0 [S94](references.md#s94) | 时态实体关系、事实有效期和来源追踪 | **关系/时间问题出现明确收益后接入。** 需要图后端和可靠结构化提取；官方提示小模型可能导致入库失败，并已弃用 Kuzu 后端。图只作可重建关系视图，抽取冲突不能直接裁决主人事实 |
| Cognee，Apache-2.0 [S96](references.md#s96) | 文档、代码与会话转成可检索知识图；当前文档提供本地小模型路径 | **文档理解流水线的备选。** “本地可运行”不等于本机中文准确、依赖已备齐或具备离线复制；单独测解析、图构建和资源成本 |
| Letta / Letta Code，Apache-2.0 [S95](references.md#s95) | 有状态 Agent、记忆块、上下文管理和 MemFS | **借鉴或作为外部工作者，不接管核心。** 原 Letta V1 server 已归档，当前代码在 letta-code；Cloud 默认和 local 后端须区分，不能把云端多机运行当作我们的离线多主共同体 |
| OpenViking，主项目 AGPLv3，部分组件 Apache-2.0 [S98](references.md#s98) | 目录化上下文、L0/L1/L2 分层读取、记忆/资源/技能组织 | **架构参考与后续独立适配候选。** 当前 README 另含整体重写/语言转换限制说明，应核对拟采用版本条款；本轮不将其整库纳入可任意自改底座，也不作许可效力判断 |

这些框架的“记忆”常包含各自的 Agent、模型配置、存储或后台处理。候选必须通过本项目适配器：输出待核验事实/摘要及来源；写入权仍由 MemoryStore 控制。先在同一数据上测增益，允许直接采用通过测试的开源实现，避免重复开发已有算法；但不能因一个库接入成功就同时启用其自动学习、网络连接或技能发布。

<a id="section-9f65cb73fb32"></a>
### 冻结选型的依据与成本

先过硬门：本机离线、可导出原件和事件、纠正/遗忘完整、权限与模拟域隔离、兼容恢复、无未声明外发、许可和依赖可固定；任何一项失败不能靠高召回抵消。再比较中文召回与时间问答、错误记忆率、延迟/CPU/RAM/磁盘、后台入库的模型费用、同步字节量和迁移工作量。未测项目写“未知”，不填主观 95 分。

依赖成本包含模型文件、分词器、原生轮子、运行时和可离线重建材料；不能只比较 Python 包大小。常驻服务、重排模型和图提取均按需启用。升级触发器为冻结任务集上的可重复缺口，而不是固定“超过几万条就必须换数据库”。模型候选见[嵌入模型](models-offline.md#embedding-candidates)，实验入口见[记忆选型验收](delivery-validation.md#memory-selection-evaluation)。

<a id="project-structure"></a>
## 项目文件结构与依赖规则

本页是源码和运行数据目录的唯一权威；所有领域、工具链与健康维护目录已合并。完整树是实现的放置规范，当前已落地以下种子原型、聊天/模型选择、预检、独立控制、固定 Worker 及 网页浏览器队列及 0.1.11 项目文本保存子集，其余目录按阶段创建。

<a id="implemented-layout"></a>
### 当前实际落地范围（0.1.17）

模型协议由 `jarvis_models/gateway.py` 实现；新增 `jarvis_models/catalog.py` 管理同提供商多模型及受限参数档案，目录数据只在 `config/model-profiles/providers.json` 维护。

| 现有路径 | 内容与依赖边界 |
|---|---|
| `pyproject.toml`、`uv.lock`、`jarvis.ps1` | Python 3.13 开发环境与锁定依赖；启动器不含凭据 |
| `contracts/schemas/` | K0 六类业务 JSON Schema，以及只读预检、旧版停止状态兼容消息 schema；唯一机器字段定义 |
| `seed/{knowledge,rules,skills,system-manifest}/` | 三库初始数据与 22 资产摘要，不是运行时学习库 |
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
| `apps/web/server.py`、`apps/web/index.html`、`apps/web/computer.js` | loopback 聊天与目录/浏览器后台任务面板；聊天 history 仅在页面内存，任务从主账本恢复 |
| `apps/web/workspace.js`、`apps/web/workspace.css` | 项目侧栏、页面会话/草稿、输出位置、保存操作与回执；不维护后台任务状态 |
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
| `%LOCALAPPDATA%\Jarvis\data` | 业务 control.db、独立 safety/control.db 与 safety/pending、model-probes.db 调用历史、workspace.db 项目/导出回执、任务产物和 diagnostics；清空聊天不删除这些记录 |

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
│   ├── coding/{codex,local}/
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
