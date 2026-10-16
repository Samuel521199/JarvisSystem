# 研究资料与证据边界

> 状态：proposed（设计基线，尚未实现） · 更新：2026-10-15  
> [文档入口](README.md) · [维护规则](MAINTENANCE.md) · [架构图册](architecture-atlas.md)

<!-- book-nav:start -->
[全书目录](README.md#book-tree) › [第五篇 · 验证与参考](README.md#part-evidence) › 第 19 章 · 研究资料与证据边界

## 本章导航

- [19.1 研究资料与证据边界](#references)
- [19.2 论文与研究文章](#references-1)
- [19.3 官方工程资料](#references-2)
- [19.4 证据使用说明](#references-3)
- [19.5 架构评审、构建与自维护依据](#references-4)
- [19.6 0.1.0 实施选型依据（2026-10-15）](#implementation-sources)
- [19.7 0.1.1 提供商错误处理依据](#chat-error-sources)
- [19.8 0.1.2 模型目录与参数迁移依据（2026-10-15 核验）](#model-catalog-sources)
- [19.9 0.1.3 推理级别依据（2026-10-15 核验）](#reasoning-control-sources)
- [19.10 0.1.4 Google Pro 与主流型号依据（2026-10-15 核验）](#google-catalog-sources)
- [19.11 知识与记忆开源选型依据（2026-10-15 核验）](#memory-selection-sources)
- [19.12 运行预检与控制实现的官方依据（2026-10-15 核验）](#preflight-sources)
- [19.13 Codex 工作台与交互参考（2026-10-15 核验）](#codex-workbench-sources)
<!-- book-nav:end -->

<a id="references"></a>
## 研究资料与证据边界

资料核查日期：2026-10-15。论文用于支持具体机制，官方文档用于核对组件和平台约束。本设计没有将任何论文基准成绩等同于 Jarvis 的实测能力。

<a id="references-1"></a>
## 论文与研究文章

| 编号 | 来源 | 本文使用范围 |
|---|---|---|
| <a id="s01"></a>[S01](https://www.inkandswitch.com/essay/local-first/) | Kleppmann 等，Local-first software: You own your data, in spite of the cloud，2019 | 本地数据所有权、离线工作与多设备协作原则 |
| <a id="s02"></a>[S02](https://dsf.berkeley.edu/cs286/papers/crdt-tr2011.pdf) | Shapiro 等，A comprehensive study of Convergent and Commutative Replicated Data Types，2011 | 可收敛复制数据结构及其适用条件 |
| <a id="s03"></a>[S03](https://www.comp.nus.edu.sg/~gilbert/pubs/BrewersConjecture-SigAct.pdf) | Gilbert、Lynch，Brewer's Conjecture and the Feasibility of Consistent, Available, Partition-Tolerant Web Services，2002 | 网络分区时强一致与可用性的限制 |
| <a id="s04"></a>[S04](https://raft.github.io/raft.pdf) | Ongaro、Ousterhout，In Search of an Understandable Consensus Algorithm，2014，扩展版 | 领导者、日志复制和多数派 |
| <a id="s05"></a>[S05](https://static.usenix.org/events/osdi06/tech/full_papers/burrows/burrows_html/) | Burrows，The Chubby lock service for loosely-coupled distributed systems，2006 | 锁、租约和执行端 sequencer 验证 |
| <a id="s07"></a>[S07](https://arxiv.org/abs/2305.16291) | Wang 等，Voyager: An Open-Ended Embodied Agent with Large Language Models，2023 | 自动课程、代码技能库与执行反馈；限于论文环境 |
| <a id="s08"></a>[S08](https://arxiv.org/abs/2303.11366) | Shinn 等，Reflexion: Language Agents with Verbal Reinforcement Learning，2023 | 通过语言反馈与记忆改进尝试，无需权重更新 |
| <a id="s09"></a>[S09](https://arxiv.org/abs/2405.15793) | Yang 等，SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering，2024 | Agent 工具界面与软件工程任务 |
| <a id="s10"></a>[S10](https://www.anthropic.com/engineering/multi-agent-research-system) | Anthropic，How we built our multi-agent research system，2025 | 协调、分工、上下文、产物与多 Agent 成本取舍 |
| <a id="s28"></a>[S28](https://arxiv.org/abs/2304.03442) | Park 等，Generative Agents: Interactive Simulacra of Human Behavior，2023 | 角色记忆、反思、计划与小镇模拟，不能证明无限扩展 |
| <a id="s31"></a>[S31](https://arxiv.org/abs/2310.08560) | Packer 等，MemGPT: Towards LLMs as Operating Systems，2023 | 分层记忆与有限上下文管理 |
| <a id="s32"></a>[S32](https://arxiv.org/abs/2507.03724) | MemOS: A Memory OS for AI System，2025 | 记忆资源、来源、版本和生命周期的研究框架 |
| <a id="s34"></a>[S34](https://www.anthropic.com/research/prompt-injection-defenses) | Anthropic，Mitigating the risk of prompt injections in browser use，2025 | 外部内容风险、分层防御与未解决边界 |
| <a id="s36"></a>[S36](https://web.mit.edu/Saltzer/www/publications/protection/Basic.html) | Saltzer、Schroeder，The Protection of Information in Computer Systems，1975，基本原则部分 | 默认拒绝、逐次检查、最小权限等设计原则 |

<a id="references-2"></a>
## 官方工程资料

| 编号 | 来源 | 本文使用范围 |
|---|---|---|
| <a id="s06"></a>[S06](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/) | AWS Builders' Library：Making retries safe with idempotent APIs | 意图编号、参数匹配与安全重试 |
| <a id="s11"></a>[S11](https://docs.langchain.com/oss/python/langgraph/persistence) | LangGraph：Persistence | 线程检查点与长期存储区分 |
| <a id="s12"></a>[S12](https://docs.temporal.io/worker-versioning) | Temporal：Worker Versioning | 工作流版本绑定与新旧 Worker 并存 |
| <a id="s13"></a>[S13](https://protobuf.dev/programming-guides/proto3/#updating) | Protocol Buffers：Updating a Message Type | 协议演进和字段兼容规则 |
| <a id="s14"></a>[S14](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/) | Kubernetes：Deployments | 滚动更新、就绪、历史和回滚边界；不是首期必选技术 |
| <a id="s15"></a>[S15](https://docs.litellm.ai/docs/routing) | LiteLLM：Router | 路由、重试、冷却和 fallback |
| <a id="s16"></a>[S16](https://modelcontextprotocol.io/specification/2026-07-28) | MCP Specification，2026-07-28 | 工具互操作协议；实施时固定版本 |
| <a id="s17"></a>[S17](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) | llama.cpp server README | 本地模型服务能力及部署接口 |
| <a id="s18"></a>[S18](https://k2-fsa.github.io/sherpa/onnx/index.html) | sherpa-onnx 官方文档 | 本地语音能力与平台支持 |
| <a id="s19"></a>[S19](https://docs.livekit.io/agents/logic/turns/) | LiveKit：Turns overview | 轮次检测和打断机制 |
| <a id="s20"></a>[S20](https://tauri.app/concept/process-model/) | Tauri：Process Model | 桌面界面进程边界 |
| <a id="s21"></a>[S21](https://www.sqlite.org/wal.html) | SQLite：Write-Ahead Logging | 本机事务、持久性和网络文件系统限制 |
| <a id="s22"></a>[S22](https://learn.microsoft.com/en-us/windows/desktop/services/interactive-services) | Microsoft：Interactive Services | Windows 服务与交互桌面的限制 |
| <a id="s23"></a>[S23](https://developer.apple.com/documentation/backgroundtasks/choosing-background-strategies-for-your-app) | Apple：Choosing Background Strategies for Your App | 移动端后台运行约束 |
| <a id="s24"></a>[S24](https://developer.android.com/about/versions/oreo/background) | Android：Background Execution Limits | 移动端后台运行约束；具体当前版本另行实测 |
| <a id="s25"></a>[S25](https://developers.home-assistant.io/docs/api/websocket/) | Home Assistant：WebSocket API | 设备状态事件与服务调用 |
| <a id="s26"></a>[S26](https://docs.nats.io/concepts/jetstream) | NATS：JetStream | 可选持久消息基础设施 |
| <a id="s27"></a>[S27](https://opentelemetry.io/docs/what-is-opentelemetry/) | OpenTelemetry：What is OpenTelemetry? | 追踪、指标与日志互操作 |
| <a id="s29"></a>[S29](https://docs.ray.io/en/latest/ray-core/scheduling/resources.html) | Ray：Resources | 逻辑资源调度与物理隔离的区别 |
| <a id="s30"></a>[S30](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/) | Kubernetes：Horizontal Pod Autoscaling | 依据指标扩缩副本；不自动提供任务语义和预算控制 |
| <a id="s33"></a>[S33](https://microsoft.github.io/graphrag/index/overview/) | Microsoft GraphRAG：Indexing Overview | 可配置索引、实体关系与派生摘要 |
| <a id="s35"></a>[S35](https://www.openpolicyagent.org/docs) | Open Policy Agent：Documentation | 策略决策和执行分离，不构成语义安全证明 |
| <a id="s37"></a>[S37](https://design.ros2.org/articles/node_lifecycle.html) | ROS 2：Managed Nodes | 外部监督下的生命周期，不等于物理安全认证 |

<a id="references-3"></a>
## 证据使用说明

Local-first 和 CRDT 支持数据组织思路，不能证明共享记忆产生真实意识。
- 多 Agent 与自动编程论文说明特定任务中的有效机制，不能保证所有任务或任意自主代码正确。
- 框架文档说明功能接口，不能代替在目标硬件上的兼容、性能和故障测试。
- 本文关于双路径恢复、模块拆分、版本治理和阶段目标是结合这些依据形成的工程建议。
- 最终是否达标，以[验收标准与故障演练](delivery-validation.md#acceptance)规定的真实场景和故障验收为准。

<a id="references-4"></a>
## 架构评审、构建与自维护依据

<a id="s38"></a>[S38](https://c4model.com/diagrams) C4 架构视图。
- <a id="s39"></a>[S39](https://martinfowler.com/bliki/MonolithFirst.html) Martin Fowler：Monolith First。
- <a id="s40"></a>[S40](https://sei.cmu.edu/documents/196/1998_019_001_29711.pdf) CMU SEI：Architecture Tradeoff Analysis Method。
- <a id="s41"></a>[S41](https://slsa.dev/spec/v1.2/build-provenance) SLSA v1.2：Build Provenance。
- <a id="s42"></a>[S42](https://clang.llvm.org/docs/CrossCompilation.html) Clang：Cross-compilation。
- <a id="s43"></a>[S43](https://learn.microsoft.com/en-us/visualstudio/install/install-vs-inconsistent-quality-network) Microsoft：Visual Studio 离线安装布局。
- <a id="s44"></a>[S44](https://pnpm.io/cli/fetch) pnpm：fetch。
- <a id="s45"></a>[S45](https://docs.wasmtime.dev/security.html) Wasmtime：Security。
- <a id="s46"></a>[S46](https://component-model.bytecodealliance.org/language-support.html) WebAssembly Component Model：语言支持。
- <a id="s47"></a>[S47](https://learn.microsoft.com/en-us/virtualization/windowscontainers/deploy-containers/version-compatibility) Microsoft：Windows 容器版本兼容。
- <a id="s48"></a>[S48](https://developer.apple.com/xcode/system-requirements) Apple：Xcode 系统与 SDK 要求。
- <a id="s49"></a>[S49](https://doc.rust-lang.org/cargo/commands/cargo-vendor.html) Cargo：vendor。
- <a id="s50"></a>[S50](https://docs.astral.sh/uv/concepts/projects/sync/) uv：锁定与同步。
- <a id="s51"></a>[S51](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file) Microsoft：Windows Sandbox 配置。
- <a id="s52"></a>[S52](https://www.erlang.org/doc/system/sup_princ.html) Erlang/OTP：Supervisor Behaviour。
- <a id="s53"></a>[S53](https://docs.temporal.io/workflow-definition) Temporal：Workflow Definition。

- <a id="s54"></a>[S54](https://learn.chatgpt.com/docs/non-interactive-mode) OpenAI：Codex 非交互模式。
- <a id="s55"></a>[S55](https://learn.chatgpt.com/docs/codex-sdk) OpenAI：Codex SDK。
- <a id="s56"></a>[S56](https://evolutionaryarchitecture.com/precis.html) Building Evolutionary Architectures：作者概要。
- <a id="s57"></a>[S57](https://github.com/seddonym/import-linter/blob/main/docs/contract_types/layers.md) Import Linter：Layers 合约。

<a id="implementation-sources"></a>
## 0.1.0 实施选型依据（2026-10-15）

以下是本次接口与模型选型的官方依据。精确本地文件版本、许可指针、大小和 SHA-256 由 [模型清单](../config/model-profiles/local-candidates.json)维护；来源说明能力或接口，不证明本机准确率、生产隔离或所有商业使用权。

| 编号 | 来源 | 本次使用范围 |
|---|---|---|
| <a id="s58"></a>[S58](https://developers.openai.com/api/docs/guides/text) | OpenAI Text generation | Responses 接口、输出项解析 |
| <a id="s59"></a>[S59](https://developers.openai.com/api/docs/models/gpt-5.6-luna) | OpenAI gpt-5.6-luna | 成本敏感的文本探测候选；账户列表可见不等于生成已成功 |
| <a id="s60"></a>[S60](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-flash-lite) | Google Gemini 3.1 Flash-Lite | 模型 ID、global 支持、MINIMAL thinking |
| <a id="s61"></a>[S61](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope) | 阿里百炼 OpenAI 兼容 | Chat Completions、模型和区域配置；基址另见[官方说明](https://help.aliyun.com/zh/model-studio/base-url) |
| <a id="s62"></a>[S62](https://docs.x.ai/developers/rest-api-reference/inference/chat) | xAI Chat REST | 请求与响应格式 |
| <a id="s63"></a>[S63](https://x.ai/news/grok-4-1-fast) | xAI Grok 4.1 Fast | non-reasoning 模型选择 |
| <a id="s64"></a>[S64](https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/tree/23749fefcc72300e3a2ad315e1317431b06b590a) | Qwen 官方 GGUF | 0.6B Q8_0 与固定发布文件 |
| <a id="s65"></a>[S65](https://huggingface.co/FunAudioLLM/SenseVoiceSmall/tree/3847d57b6bdf2dd8875cb1508d2af43d80a16bf7) | FunAudioLLM SenseVoiceSmall | 原始模型能力、模型许可；转换版另由清单固定 |
| <a id="s66"></a>[S66](https://huggingface.co/csukuangfj/icefall-tts-aishell3-vits-low-2024-04-06/tree/57345c004e13ed640e408c4c29ab56187b18f065) | sherpa 发布者 AISHELL3 VITS low | 小型中文预置声音合成模型 |
| <a id="s67"></a>[S67](https://modelscope.cn/models/iic/speech_campplus_sv_zh-cn_16k-common) | ModelScope CAM++ 中文声纹模型 | 说话人特征；不提供主人身份授权结论 |
| <a id="s68"></a>[S68](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata) | Microsoft CryptProtectData | 当前 Windows 用户 DPAPI 加密与适用边界 |
| <a id="s69"></a>[S69](https://github.com/ggml-org/llama.cpp/releases/tag/b11617) | llama.cpp b11617 | 固定 CPU 运行包、发布摘要；不追随 latest |
| <a id="s70"></a>[S70](https://github.com/snakers4/silero-vad) | Silero VAD 官方仓库 | 语音活动检测；实际 ONNX 文件与摘要见清单 |

<a id="chat-error-sources"></a>
## 0.1.1 提供商错误处理依据

| 编号 | 来源 | 本次使用范围 |
|---|---|---|
| <a id="s71"></a>[S71](https://developers.openai.com/api/docs/guides/error-codes) | OpenAI Error codes | 区分余额/账单额度、429 限流、认证及服务错误；不能把所有 429 当余额耗尽 |
| <a id="s72"></a>[S72](https://help.aliyun.com/zh/model-studio/error-code) | 百炼错误码 | Arrearage 等账户异常与参数/限流错误 |
| <a id="s73"></a>[S73](https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/models/api-errors) | Google API errors | RESOURCE_EXHAUSTED 可表示配额或共享容量不足，响应本身不等于余额证明 |

<a id="model-catalog-sources"></a>
## 0.1.2 模型目录与参数迁移依据（2026-10-15 核验）

| 编号 | 来源 | 使用范围 |
|---|---|---|
| <a id="s74"></a>[S74](https://developers.openai.com/api/docs/models) | OpenAI API model catalog | GPT-6 Astra、6.1 Sol、6 Luna 和 6 Sol 的官方 ID；账户生成状态另看本地实测 |
| <a id="s75"></a>[S75](https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra.md#migration-quickstart) | OpenAI GPT-6 migration | Astra/6.1 Sol 不支持 none；Responses、推理参数兼容；未启用供应商内置工具 |
| <a id="s76"></a>[S76](https://docs.x.ai/developers/models/grok-4.7) | xAI Grok 4.7 | 精确 ID、low/medium/high/xhigh 推理档位 |
| <a id="s77"></a>[S77](https://help.aliyun.com/zh/model-studio/text-generation-model) | 百炼文本模型 | Qwen3.8 Max/Flash、Qwen3.7 Plus、思考开关；区域和账户状态需实测 |
| <a id="s78"></a>[S78](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-3-8-flash) | Google Gemini 3.8 Flash 迁移 | global、LOW/MEDIUM/HIGH、移除 candidateCount 与 MINIMAL |
| <a id="s79"></a>[S79](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/4-argon) | Google Gemini 4 Argon | 模型 ID、global 和思考档位；本原型只接文字能力 |

<a id="reasoning-control-sources"></a>
## 0.1.3 推理级别依据（2026-10-15 核验）

| 编号 | 来源 | 使用范围 |
|---|---|---|
| <a id="s80"></a>[S80](https://help.aliyun.com/zh/model-studio/deep-thinking) | 百炼深度思考 | Qwen 混合思考的 enable_thinking 开关；商业模型支持非流式，输出与 reasoning_content 区分 |
| <a id="s81"></a>[S81](https://developers.openai.com/api/docs/models/gpt-6-astra) | OpenAI 模型页 | Astra 的 low 至 max；另核对 [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol)、[GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol)、[GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) 的各自枚举；GPT-5.6 Luna 见 S59 |

<a id="google-catalog-sources"></a>
## 0.1.4 Google Pro 与主流型号依据（2026-10-15 核验）

| 编号 | 来源 | 使用范围 |
|---|---|---|
| <a id="s82"></a>[S82](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-pro) | Gemini 3.1 Pro | 精确 preview ID、global、发布阶段和中等思考档位 |
| <a id="s83"></a>[S83](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite) | Gemini 3.5 Flash-Lite | 当前 Lite 选型、模型 ID、GA、四个 thinking 档位 |
| <a id="s84"></a>[S84](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/migrate) | Google 当前模型迁移表 | Argon、Pro、各 Flash 分支的阶段和能力比较，不是本机质量测试 |
| <a id="s85"></a>[S85](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions) | Google Cloud 模型生命周期 | Vertex 的 2.5 系列及 3.6/3.7 Flash 退役时间；不混用 Developer API 日期 |
| <a id="s86"></a>[S86](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/thinking) | Google Thinking | 按模型支持的级别与 thought signature 限制；当前仅验证纯文字聊天 |

<a id="memory-selection-sources"></a>
## 知识与记忆开源选型依据（2026-10-15 核验）

本组依据官方仓库、文档和模型卡；主分支和许可证会变化，表中是本次网页核验，不是已安装的版本锁。正式接入前固定 tag/commit、依赖与模型 revision；选型结论是本项目工程判断，不是这些项目对 Jarvis 的背书。未采用商业托管成绩作为开源实现或本机效果证据。

| 来源 | 核验范围 | 使用限制 |
|---|---|---|
| <a id="s87"></a>[S87](https://www.sqlite.org/fts5.html) | SQLite FTS5 的 unicode61、trigram、MATCH 与 LIKE/GLOB 限制 | 用于解释本地中文探测；不是中文语义召回基准 |
| <a id="s88"></a>[S88](https://github.com/asg017/sqlite-vec) | C 扩展、向量类型、部署形式、MIT/Apache-2.0、pre-v1 提示 | 不推断未测索引能力、吞吐或跨节点复制 |
| <a id="s89"></a>[S89](https://github.com/lancedb/lancedb) | LanceDB OSS 嵌入式检索、Lance 数据层、Apache-2.0 | 区分 OSS、Cloud 与 Enterprise，不把数据版本当多主语义 |
| <a id="s90"></a>[S90](https://qdrant.tech/documentation/distributed_deployment/) | Qdrant 分片/复制、集群元数据与读写语义；另见[安装约束](https://qdrant.tech/documentation/installation/)和[许可](https://github.com/qdrant/qdrant/blob/master/LICENSE) | 稳定集群不等于经常离线的个人设备网络 |
| <a id="s91"></a>[S91](https://github.com/pgvector/pgvector) | pgvector 精确/近似检索、过滤与迭代扫描、PostgreSQL License | 需测过滤后的召回和服务运维成本 |
| <a id="s92"></a>[S92](https://github.com/chroma-core/chroma) | Chroma OSS 本地/服务端接口与 Apache-2.0 | collection 接口本身不提供主人事实的修订和同步规则 |
| <a id="s93"></a>[S93](https://github.com/mem0ai/mem0) | Mem0 记忆库、自托管与托管区分、默认模型配置、Apache-2.0 | README 将部分新基准归于托管专有优化；不移植其成绩 |
| <a id="s94"></a>[S94](https://github.com/getzep/graphiti) | 时态关系、图后端要求、Kuzu 弃用、小模型结构输出限制、Apache-2.0 | 图关系提取仍需核验；不提供事实真伪保证 |
| <a id="s95"></a>[S95](https://github.com/letta-ai/letta) | Letta V1 server 归档与[Letta Code](https://github.com/letta-ai/letta-code) 当前路径、记忆块/文件系统与本地后端、Apache-2.0 | 不沿用旧服务端架构假设，不把 Cloud 多机等同离线共同体 |
| <a id="s96"></a>[S96](https://github.com/topoteretes/cognee) | Cognee 文档/代码/对话知识处理、本地模型路线、Apache-2.0 | 本地运行声明不证明本机中文效果或多主复制 |
| <a id="s97"></a>[S97](https://github.com/MemTensor/MemOS) | MemOS 自托管、Cloud 和 Agent 本地插件的不同入口、Apache-2.0 | 资源比较需选同一部署形态；插件不等于通用 Jarvis 模块 |
| <a id="s98"></a>[S98](https://github.com/volcengine/OpenViking) | 目录式上下文、L0/L1/L2、[当前主许可](https://github.com/volcengine/OpenViking/blob/main/LICENSE) AGPLv3 与 README 的分组件/改写说明 | 不作许可效力判断；选用前核对具体版本与组件，不能沿用旧 Apache-only 假设 |
| <a id="s99"></a>[S99](https://automerge.org/docs/hello/) | Automerge 离线合并与同步；[代码库](https://github.com/automerge/automerge)为 MIT | CRDT 收敛不替代权限、独占行动或矛盾事实判断 |
| <a id="s100"></a>[S100](https://www.sqlite.org/wal.html) | SQLite WAL 的同主机共享内存限制；[Public Domain 声明](https://www.sqlite.org/copyright.html) | 不支持把活跃 WAL 文件直接交由云盘多机同步 |
| <a id="s101"></a>[S101](https://docs.couchdb.org/en/stable/replication/conflicts.html) | CouchDB 复制冲突、winning revision 与应用解决冲突责任 | 可见修订不是事实裁决；没有免除应用冲突处理 |
| <a id="s102"></a>[S102](https://huggingface.co/BAAI/bge-small-zh-v1.5) | BGE 中文小嵌入模型、参数/维度、MIT | 官方模型卡不是量化后本机中文/代码测试 |
| <a id="s103"></a>[S103](https://huggingface.co/intfloat/multilingual-e5-small) | E5 多语言小模型、384 维、512 token、用途前缀、MIT；核验[原始模型卡](https://huggingface.co/intfloat/multilingual-e5-small/raw/main/README.md) | 运行包和分词/截断配置需另行固定 |
| <a id="s104"></a>[S104](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) | Qwen 嵌入模型维度可调、上下文、多语言、Apache-2.0 | 输出降维不等于权重按比例缩小；不是当前聊天模型 |
| <a id="s105"></a>[S105](https://github.com/xiaowu0162/LongMemEval) | LongMemEval 长期记忆问答评估；[论文](https://arxiv.org/abs/2410.10813) | 不能代替中文、权限、离线复制与故障注入测试 |
| <a id="s106"></a>[S106](https://github.com/snap-research/locomo) | LoCoMo 长对话记忆数据和任务；[论文](https://arxiv.org/abs/2402.17753) | 不将单轮公开成绩或模型裁判评分当整个系统可靠性 |

<a id="preflight-sources"></a>
## 运行预检与控制实现的官方依据（2026-10-15 核验）

| 来源 | 核验范围 | 使用限制 |
|---|---|---|
| <a id="s107"></a>[S107](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls) | `icacls` 显示 DACL 与授权操作 | 预检只读；0.1.7 Worker 仅对自己创建的运行包/暂存授予只读执行权限，不改用户输入目录 ACL |
| <a id="s108"></a>[S108](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/whoami) | `whoami /user` 的当前账户及 SID 查询 | 只代表调用进程身份，不推断其他服务或 Worker 身份 |
| <a id="s109"></a>[S109](https://cryptography.io/en/46.0.4/hazmat/primitives/asymmetric/ed25519/) | Ed25519 生成、签名、验证和密钥序列化 API | 0.1.6 历史恢复实现参考；0.1.14 已移除恢复密钥/签名流程。依赖仍由模型认证组件使用，不能据此声称当前有恢复认证 |
| <a id="s110"></a>[S110](https://www.sqlite.org/lang_attach.html) | ATTACH 多库事务在 WAL 模式下的原子性边界 | 当前控制库独立提交，业务注释允许随后对账；不声称两个 WAL 数据库有跨库原子提交 |
| <a id="s111"></a>[S111](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer) | LPAC 创建、profile、能力与注册表初始化要求 | 原生机制依据，不替代本机有效权限试验或完整沙箱审计 |
| <a id="s112"></a>[S112](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) | Job 进程组和关闭终止；[限额定义](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information) | 本机 CPU 自动终止没有得到预期证据，改用 Host 主动计时；Job 不保护 Host 自身 |
| <a id="s113"></a>[S113](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes) | Windows 进程 user/kernel CPU 计时 | 主动轮询需要 Host 响应，不是独立实时监督 |
| <a id="s114"></a>[S114](https://developers.openai.com/api/docs/guides/tools-computer-use) | OpenAI Computer Use：模型、结构化动作、代码工具、截图反馈与应用负责执行 | 官方接法不证明 Jarvis 已接入；Codex 产品内部实现不由此推断 |
| <a id="s115"></a>[S115](https://ai.google.dev/gemini-api/docs/computer-use) | Gemini 3.8 Flash 的 Computer Use 与浏览器/桌面接口 | Gemini API 示例不等于已有 Vertex 服务账号已验证可用 |
| <a id="s116"></a>[S116](https://github.com/QwenLM/Qwen3-VL) | Qwen3-VL 模型规格与 GUI agent/computer-use 示例 | 小型离线候选尚未下载和在本机验收 |
| <a id="s117"></a>[S117](https://github.com/QwenLM/open-computer-use/blob/main/README.md) | 开源 MCP 电脑操作服务与 Windows UI Automation 实现 | 可借鉴的适配器，不是 Jarvis 的权限边界或已安装功能 |
| <a id="s118"></a>[S118](https://playwright.dev/python/docs/browsers) | Playwright 系统 Edge channel、浏览器 sandbox；[网络路由](https://playwright.dev/python/docs/network)、[Route API](https://playwright.dev/python/docs/api/class-route) 的重定向行为 | 本项目锁定 1.64.0；路由不是 OS 防火墙，重定向拒绝和生命周期仍须真实测试 |
| <a id="s128"></a>[S128](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/ns-sysinfoapi-memorystatusex) | Windows 物理可用内存和当前进程提交余量；[读取 API](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-globalmemorystatusex)、[进程计数](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters_ex) | 快照易变；不能视为实际预留、浏览器限额或其他进程峰值 |
| <a id="s129"></a>[S129](https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule?view=windowsserver2022-ps) | Windows 防火墙 Program、Outbound、Block 与配置文件范围 | 本机探测只为临时包的 4 个可执行文件设规则，实测阻断并清理；不是整机断网或 Host 安全隔离 |
| <a id="s130"></a>[S130](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/start-process?view=powershell-5.1) | Start-Process 的 RunAs、WindowStyle 与参数传递 | 通过正常 UAC 提权固定防火墙脚本；不能根据桌面应用身份推定工具子进程已有管理员权限 |

<a id="codex-workbench-sources"></a>
## Codex 工作台与交互参考（2026-10-15 核验）

本组用于[Jarvis 工作台设计](interaction-persona.md#desktop-workbench)。已搜索并阅读官方原页；界面布局同时参考用户本轮提供的 Windows Codex 新会话截图，截图只支持对可见区域的描述。表中资料不能证明 Jarvis 已实现这些能力，也不证明用户安装的 Codex 已启用官方列出的每项功能。官网包含 ChatGPT 桌面、Codex、Work、网页、CLI 等不同 surface，引用时按原页适用范围解释。

| 编号 | 官方资料 | 使用范围与限制 |
|---|---|---|
| <a id="s119"></a>[S119](https://learn.chatgpt.com/docs/projects) | Projects and chats | 本地文件夹、主目录、附属目录、会话组织和搜索；项目同步不等于完整目录上传 |
| <a id="s120"></a>[S120](https://learn.chatgpt.com/docs/environments/git-worktrees) | Worktrees | 新会话工作树、分支与交接；以已有 Git 为条件，不推导为打开普通文件夹必须初始化 Git |
| <a id="s121"></a>[S121](https://learn.chatgpt.com/docs/features) | Features | 发现插件、语音、浏览器、长任务、计划任务和 dots 等能力范围；目录存在不等于全部可在本机使用 |
| <a id="s122"></a>[S122](https://learn.chatgpt.com/docs/reference/settings) | Settings | 发送键、跟进方式、外观、快捷键、通知、隐私入口与记忆；不据此推断未公开的内部实现 |
| <a id="s123"></a>[S123](https://learn.chatgpt.com/docs/reference/commands) | Commands | Windows 打开文件夹、新聊天、文件树/搜索、模型、终端与布局快捷入口；部分命令要求对应功能可用 |
| <a id="s124"></a>[S124](https://learn.chatgpt.com/docs/reference/slash-commands) | Slash commands | 输入区命令发现与技能入口；Jarvis 的候选命令须由自己的能力注册决定 |
| <a id="s125"></a>[S125](https://learn.chatgpt.com/docs/artifacts-viewer) | Work with files | 文件产物预览、标注和修订；格式支持与宿主有关 |
| <a id="s126"></a>[S126](https://learn.chatgpt.com/docs/code-review) | Code review | PR 的描述、差异、检查和评审流程；查看评审不等于已经发布评论或合并 |
| <a id="s127"></a>[S127](https://learn.chatgpt.com/docs/browser) | Browser | 内置浏览器、标签分屏、批注、配置与网站权限；浏览器访问不等于网页内容可信 |

Jarvis 专属入口来自本项目的需求和领域设计，不通过缺少竞品文档来证明竞品没有相应功能。后续实施前应重新核对官方页面和实际安装行为；本组是调研时点的参考，不能作为永久功能清单。

<!-- book-footer:start -->
[返回全书目录](README.md#book-tree) · [上一章：架构与流程图册](architecture-atlas.md) · [下一章：文档维护规范](MAINTENANCE.md)
<!-- book-footer:end -->
