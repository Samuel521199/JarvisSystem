# Jarvis 文档首页

这里是 Jarvis 文档的总入口。目标是类钢铁侠贾维斯的高级个人 AI 助手与伙伴：能长期相处、了解主人、自然交流、记住适用信息、延续共同经历、主动协助，并自主学习和进化。围绕这个核心按需扩展项目工作台、编程、设备控制、多 Agent 等能力。

**部署方向：以普通 PC/笔记本为主，先 Windows，再按需求跨平台；能力按需扩展，默认安装保持轻量。** 具体约束见[普通 PC 优先规则](stack-project-layout.md#technology-selection-4)。

**第一次阅读，先看 [个人助手与伙伴的核心是什么](product-requirements.md#personal-companion-core)，再看 [完成后能带来哪些体验与能力](product-requirements.md#capability-boundaries)。**

> **在 Cursor 中打开链接：**打开整个 `Jarvis` 文件夹。若页面顶部有 `Preview / Markdown`，先选 `Markdown`，再按 `Ctrl+Shift+V` 打开内置预览（标签名为 `Preview README.md`），单击链接阅读对应文件。VS Code 也可使用此快捷键；源码视图使用 `Ctrl+单击`。更多说明见[阅读与链接规范](MAINTENANCE.md#stable-identifiers)。

[后续方向指南](development-guide.md#direction-start) · [选择阅读入口](#start-here) · [查看当前进度](#project-status) · [查找专题](#quick-topics) · [完整文档目录](#book-tree) · [维护文档](#for-maintainers)

---

<a id="start-here"></a>
## 你现在想做什么？

| 目的 | 从这里开始 | 接着看 |
|---|---|---|
| **了解 Jarvis 的个人助手与伙伴定位** | [核心定义与体验判据](product-requirements.md#personal-companion-core) | [个人交流与工作台](interaction-persona.md#desktop-workbench) → [核心如何起步](core-bootstrap.md#bootstrap-1) |
| **启动并使用现有原型** | [启动方法与聊天入口](core-bootstrap.md#current-implementation) | [可选模型与切换方式](models-offline.md#configured-models) |
| **使用本地主力语音与备用组件** | [Qwen 主力语音](models-offline.md#qwen-tts-runtime) | [接入、速度与内存证据](delivery-validation.md#qwen-tts-integration-evidence) · [主备选型](models-offline.md#voice-local-candidates) · [ZipVoice 备用](models-offline.md#fast-speech-runtime) |
| **判断现在能否使用、智能有多强** | [v0.1.62 的实现、实测与剩余验收](delivery-validation.md#k2-completion-evidence) | [当前能力和完整性规则](models-offline.md#runtime-chat-context) |
| **查看个人核心的使用与验证** | [聊天记忆与交流设置](interaction-persona.md#personal-core-ui) → [跨会话继续话题](interaction-persona.md#continuity-ui) | [当前 K2 验收结果与范围](delivery-validation.md#k2-completion-evidence) |
| **从聊天提出改进并取回成果** | [改进与成长进度](interaction-persona.md#growth-demand-ui) | [0.1.41 需求成长验证](delivery-validation.md#growth-demand-evidence) |
| **查看本轮修复与验收** | [K4 体检、对照与归档](delivery-validation.md#k4-quality-storage-evidence) | [原始基础验收](delivery-validation.md#foundation-repair-evidence) |
| **查看当前实现离个人助手目标还有多远** | [个人核心评价与工程审计](decisions-review.md#personal-core-assessment) | [助手核心架构图](architecture.md#pc-runtime-convergence) → [既有测试证据](delivery-validation.md#current-audit-evidence) |
| **用自然语言执行首条任务** | [聊天任务入口](core-bootstrap.md#conversation-task-entry) | [执行边界与记录](tasks-agents.md#sample-task-runtime) |
| **查看模块运行和准备升级** | [设置模块入口](core-bootstrap.md#module-monitor-entry) | [监控与维护边界](health-maintenance.md#module-monitoring) |
| **看后续优化、缺口与原方案下一步** | [后续方向指南：16项工作清单](development-guide.md#direction-start) | [当前推进队列](core-bootstrap.md#near-term-work-queue) → [对应验收](development-guide.md#direction-evidence) |
| **继续设计或开发** | [下一步具体工作](core-bootstrap.md#next-implementation) | [技术栈与代码结构](stack-project-layout.md#technology-selection) → [下一阶段验收](delivery-validation.md#next-k1-acceptance) |

<a id="project-status"></a>
## 目前做到哪里了？

**本次升级 · 0.1.76：**新增[契约体检与旧版本归档](evolution-release.md#project-tool-quality-storage)：显示已观察的案例边界和待审阅问题；无引用退役包校验归档后释放在线名额，载回仍退役。三类实用任务的对照与部署状态见[本轮证据](delivery-validation.md#k4-quality-storage-evidence)。不宣称通用语义正确或磁盘空间释放。

**上一升级 · 0.1.75：**候选先审阅进入灰度，稳定工具继续服务；新输入核验与用途证据达标后再明确启用，支持可恢复退役。见[流程与边界](evolution-release.md#project-tool-lifecycle)、[界面](interaction-persona.md#project-tool-ui)和[验收/部署状态](delivery-validation.md#k4-lifecycle-evidence)。仍不能自主证明任意业务验收正确。

**上一修复 · 0.1.74：**网页和桌面均可通过本机服务创建项目/子文件夹；Argon 真实连接已通过，新增[可玩的坦克游戏原型](tasks-agents.md#tank-game-runtime)，[结果与限制](delivery-validation.md#assistant-game-evidence)。

**上一升级 · 0.1.73：K4 验收草案与审阅。** 能力缺口可生成输入/输出和公开案例草案，明确审阅并补充独立留出案例后交给原 K3 编码；[使用方式](interaction-persona.md#project-tool-ui)及[实际模型与隔离执行验证](delivery-validation.md#k4-contract-evidence)。完整 K4 仍在推进，通用语义裁决与无人审阅自动发布仍未完成；本轮退役子集见上方 0.1.75。

**上一版本 · 0.1.70：K3 编码协作已闭环。** 支持从会话改进单生成候选代码，经独立检查、实际构建和隔离运行，再审阅、应用或恢复；新增 Python 子目录包/新文件与 JavaScript 交互场景。五类真实任务的有/无技能指引对照均通过，未观察到成功率增益；范围与局限见[K3 最终验收](delivery-validation.md#k3-closure-matrix)。下一步进入[当前推进队列中的 K4](core-bootstrap.md#near-term-work-queue)，把候选接入受控工具启用与实际调用。

**0.1.66 已有基础：** K3 增加可运行 Python 工具包、产物入口独立复验、离线重建与语法损坏修复；三类真实 Codex 任务通过，结果见[本轮证据](delivery-validation.md#k3-build-evidence)。使用与限制仍归[编程工作流](tasks-agents.md#bounded-coding-workflow)。

**0.1.65 已有基础：** 已完成本轮限定 K3 编码协作：候选副本、独立公开/留出案例检查、1—4 个 Python 模块、源码构建包、文件组应用与恢复，以及外部 Codex。入口为[设置 → 编码协作](http://127.0.0.1:18181/settings#coding)；[使用规则](tasks-agents.md#bounded-coding-workflow)与[实测证据](delivery-validation.md#k3-coding-evidence)集中维护。v0.1.64 基线已上传 GitHub。当时完整 K3 尚未收口；当前结果见上方 0.1.70，不将限定配方写成任意仓库自主开发。

**0.1.64 已有基础：** 设置 → 成长中心已接通自检、自愈、进化三标签及独立模型/备选/档位；[增量证据](delivery-validation.md#growth-purposes-evidence)。按主人要求停止重复验收，继续[后续开发](core-bootstrap.md#near-term-work-queue)。 已增加[仅此软件离线开关](models-offline.md#application-offline-control)，入口为设置 → 网络与离线；[本轮测试](delivery-validation.md#application-offline-evidence)与整机断网分别记录。 新增称呼与交流设置、带来源的话题推荐、相关事实选择和三库查询；取消/存储争用已修复。本轮本机实现与独立验证已收口，结果和剩余条件集中于 [K2 本轮收口](delivery-validation.md#k2-completion-evidence)。完整 K2 尚未签收：物理低配机、整机断网及主人体验仍须如实验收。

**0.1.61 已有基础：**[多轮记忆最终回答先导](delivery-validation.md#memory-final-answer-evidence)已运行；修正自动记忆承诺与聊天任务的过时能力说明。16 次真实回答复验、24 条报告校准及69项针对回归通过各自判据，仍保留少量措辞模糊等局限。

**0.1.60 已有基础：**[规则与语义候选统一核对](delivery-validation.md#rule-memory-review-evidence)已部署：旧记忆比较、纠正/遗忘屏障、本机重新整理；211 项回归与三组 UI 探针通过，核对的 11 个业务表未变化。后续扩大到人物、时序、资料和保留历史的多轮回答验证。

**0.1.59 已有基础：**普通已保存会话选择 Google Flash，可边聊天边生成样例报告，并指定取消或修改尚未开始的报告；[使用方法](interaction-persona.md#mixed-report-ui)与[实测限制](delivery-validation.md#mixed-report-admission-evidence)。该范围继续保留，完整通用任务调度仍未验收。

**0.1.58 已有基础：增加限定编程闭环和技能验证状态。** 四项工程指导可组合处理一个 Python 转换函数，真实运行提供的案例，交付差异，并支持明确应用和恢复。九项文字技能已增加 Google / Sol 共 108 次配对回答，设置页显示各模型的覆盖及问题、验证版本和最近成功任务。使用见[技能入口](core-bootstrap.md#native-skills-entry)，实际部署、测试和资源边界见[本轮证据](delivery-validation.md#skills-completion-evidence)。[记忆重复与差异核对](delivery-validation.md#memory-candidate-review-evidence)同期部署。

**限定文档查询继续可用。** 在普通已保存会话选择 Google Flash，输入“查询 Electron 文档中的 ipcMain.handle 示例”，满足规则时自动生成只读 Context7 任务；其他请求保留草稿。条件见[文档任务入口](interaction-persona.md#dialogue-intent-shadow-ui)，先前 40 条校准＋160 条留出与真实调用见[0.1.57 证据](delivery-validation.md#dialogue-intent-shadow-evidence)。完整 V-DLG 和通用自动执行仍未验收。

**同期修复：**[候选记忆增加修订屏障](delivery-validation.md#memory-lifecycle-evidence)，纠正/遗忘之后的旧预览不能迟到覆盖新事实，编辑仍保留；[Context7 草稿检查](delivery-validation.md#mcp-runtime-evidence)遵守真实项目策略、保护已有输入，显式文档查询可在未连接聊天模型时使用。

**记忆实验新增：**LangMem 和 Mem0 均已有独立进程实验适配；正式助手继续使用轻量提取器，记忆权威仍由 Jarvis 管理。先看[选型结论与借鉴内容](stack-project-layout.md#memory-recommended-plan)，再看 [Mem0 的质量、费用、纠正/遗忘实测](delivery-validation.md#memory-mem0-shadow-evidence)与 [LangMem 对照](delivery-validation.md#memory-langmem-shadow-evidence)。

**记忆方向 0.1.52：**已补规则疑问/单次要求过滤、明确模拟主体与项目范围检查，并固定 30 条提取先导样例。结果、漏记代价与未验证项见[先导评测和修复](delivery-validation.md#memory-extraction-pilot-evidence)。

**记忆方向新增：0.1.50 按需语义事实候选。** 在本人消息下点击“整理为记忆…”，选择模型提取候选，核对原句、主体和用途后保存；普通聊天不增加后台提取调用。沿用原 SQLite 和模型网关，未向正式运行环境安装新的记忆框架。见[使用方法](interaction-persona.md#personal-candidates-ui)和[验证证据](delivery-validation.md#semantic-candidates-evidence)。

| 状态 | 当前情况 |
|---|---|
| **已有可运行原型 · 0.1.76** | 新增[轻量事实分类与日常/工作用途](knowledge-learning.md#memory-domain-runtime)；新增 [REA 软件结构与行为解析](tasks-agents.md#rea-skill-policy)及[发布目录与证据分页改进](delivery-validation.md#rea-improvement-evidence)、[ASAR 与关注项](delivery-validation.md#rea-asar-focus-evidence)； 新增[候选事实来源与遗忘保护](knowledge-learning.md#candidate-fact-provenance)； 新增[候选记忆与未结事项](interaction-persona.md#personal-candidates-ui)、[中断重新分析](interaction-persona.md#growth-demand-ui)；新增[真实任务状态接续](interaction-persona.md#work-continuity-ui)； 新增[会话需求成长与真实交付](interaction-persona.md#growth-demand-ui)； 新增[有来源的话题接续](interaction-persona.md#continuity-ui)；保留[个人记忆指令与基础交流设置](interaction-persona.md#personal-core-ui)； 已修复[基础启动隔离与响应预算](delivery-validation.md#foundation-repair-evidence)；保留[限定代码与技能成长闭环](core-bootstrap.md#evolution-loop-entry)；新增[本地精确计算](core-bootstrap.md#calculator-entry)；新增[原生技能、源码报告与齿轮科普闭环](core-bootstrap.md#native-skills-entry)；新增[并行资源与延迟监控](core-bootstrap.md#parallel-runtime-entry)；保留[跨项目联合知识查询](core-bootstrap.md#memory-view-entry)；保留[本地模型启停与离线报告](core-bootstrap.md#offline-task-entry)；保留[会话关联任务与真实报告下载](core-bootstrap.md#conversation-task-entry)；保留[自然语言目录报告与产物核验](core-bootstrap.md#sample-task-entry)；保留[可缩放导航与右侧文件工作区](interaction-persona.md#workbench-layout)；保留[记忆/扩展真实状态](health-maintenance.md#module-monitoring)与[已校验种子入口](knowledge-learning.md#seed-runtime-entry)；保留[项目资源与工程文件](interaction-persona.md#project-resource-workbench)、[MCP / 技能管理入口](interaction-persona.md#extension-management-ui)，保留[项目资料检索与来源预览](interaction-persona.md#project-knowledge-ui)，保留[明确事实记忆](interaction-persona.md#explicit-memory-ui)，保留[本机会话自动保存与紧凑导出](interaction-persona.md#conversation-archive-ui)，保留[本会话要求与上下文编排](interaction-persona.md#composer-context-note)，保留[设置模块监控与升级](core-bootstrap.md#module-monitor-entry)，保留[拖拽附件与图片输入](interaction-persona.md#composer-attachments)，保留[页面配色](interaction-persona.md#workbench-appearance)，保留[模型与费用后台](core-bootstrap.md#model-admin-entry)、Eachlabs Claude、托盘、任务恢复、项目根目录和会话停止；验证见[分版本证据](delivery-validation.md#versioned-evidence)。 |
| **当前交付重点** | v0.1.70 已完成 K3 并发布 GitHub；当前实施 K4 项目工具成长，顺序见[当前推进队列](core-bootstrap.md#near-term-work-queue)。K2 已有结果和未验项见[K2 收口](delivery-validation.md#k2-completion-evidence)，保留门槛而不重复验收。原需求去向见[后续方向指南](development-guide.md#direction-requirements)。 |
| **仍属设计目标** | 完整多形态人格、通用语义经历召回、完整主动跟进、自动正式记忆建档、完整知识检索、多设备共同体、任意源码自主编程发布、完整语音和 NPC 世界尚未实现。已有词法相关推荐与按需记忆候选不等于这些完整能力。 |

以[当前实现说明](core-bootstrap.md#current-implementation)和[分版本验证记录](delivery-validation.md#versioned-evidence)为准。文档中的设计方案不代表功能已经上线。

**记忆增量已随 0.1.58 部署（2026-10-19）：**[本地重复/差异核对与显式更新](delivery-validation.md#memory-candidate-review-evidence)已通过临时核心和界面验证，统一部署时另核对线上脚本摘要；未使用主人正式记忆做写入测试。使用方式见[候选窗口](interaction-persona.md#personal-candidates-ui)。

**当前设计重心：**按主人要求将类贾维斯个人助手与伙伴放在核心，沿[K2 路线](core-bootstrap.md#next-implementation)补齐个人记忆、基础人格、交流接续和[最小自主进化](core-bootstrap.md#k2-growth-core)，按[V-PAL](delivery-validation.md#personal-companion-validation)验证。既有[成长中心三能力方案](evolution-release.md#growth-governance)、[动画交互预览](prototypes/growth-center/index.html)及[独立模型与备选](models-offline.md#growth-model-policy)继续保留；预览不替换正式工作台。

<a id="quick-topics"></a>
## 直接查找你关心的内容

| 关注的问题 | 直接阅读 |
|---|---|
| **让模型操作网页、以后控制电脑？** | [网页任务面板](core-bootstrap.md#web-computer-console) · [模块架构](architecture.md#computer-use-design) · [实际验证](delivery-validation.md#k1-progress-evidence) |
| **Grok Build 哪些代码值得借鉴？** | [源码对照与模块归属](stack-project-layout.md#grok-build-comparison) · [K 阶段落点](core-bootstrap.md#grok-adoption-stage-map) · [验收要求](delivery-validation.md#open-source-adoption-validation) |
| **什么时候用技能，怎样禁用或只手动使用？** | [统一选择规则与全部候选场景](tasks-agents.md#skill-selection-policy) · [管理设置设计](interaction-persona.md#skill-policy-management-ui) · [V-SKL 验收](delivery-validation.md#skill-selection-validation) |
| **科普动画、机械拆解和编程技能怎样接入？** | [Anatomy 方案](stack-project-layout.md#anatomy-integration-choice) · [Matt Pocock 编程包](stack-project-layout.md#matt-pocock-skills-evaluation) · [既有阶段归属](core-bootstrap.md#skills-adoption-stage-map) |
| **LLM Wiki、Mem0、记忆宫殿，哪种适合 Jarvis？** | [先看综合推荐与选择条件](stack-project-layout.md#memory-recommended-plan) → [完整横向比较](stack-project-layout.md#memory-candidate-identities) → [模块落点](stack-project-layout.md#memory-module-adoption) · [本机资源预算](delivery-validation.md#memory-resource-envelope) |
| **已有记忆怎么改造，下一步先做什么？** | [现状与缺口](knowledge-learning.md#memory-current-gap) · [交流到长期记忆的流程](knowledge-learning.md#memory-operating-cycle) · [K2 实施顺序](core-bootstrap.md#next-implementation) · [静态调研与未测项](delivery-validation.md#memory-review-evidence) |
| **私人聊天、画像、工作结果怎样共用而不串用？** | [分类与保存](knowledge-learning.md#memory-domain-catalog) → [共用方式](knowledge-learning.md#memory-sharing-bridges) → [使用与输出边界](knowledge-learning.md#memory-use-boundary) · [架构图](architecture-atlas.md#personal-work-memory) |
| **怎样记住我，同时理解不同项目？** | [当前项目资料](interaction-persona.md#project-knowledge-ui) · [当前记忆面板](interaction-persona.md#explicit-memory-ui) · [个人与项目记忆的共享范围](knowledge-learning.md#memory-scope-model) · [项目知识增量更新](knowledge-learning.md#project-knowledge-compilation) · [小型嵌入模型](models-offline.md#embedding-candidates) |
| **单机如何变成多设备 Jarvis？** | [离线与联网模式](federation.md#offline-federation) · [记忆同步与冲突](federation.md#memory-replication) |
| **现在能完整对话吗，怎样边聊边做事？** | [当前能力与缺口](architecture.md#dialogue-separation-audit) → [混合意图分流](tasks-agents.md#conversation-intent-routing) → [文字/语音体验](interaction-persona.md#unified-conversation-experience) → [改造顺序](core-bootstrap.md#dialogue-upgrade-order) |
| **怎样避免聊天、语音和工作互相堵塞？** | [资源保留与公平调度](tasks-agents.md#conversation-resource-isolation) · [代码落点与框架取舍](stack-project-layout.md#dialogue-runtime-adoption) · [并行验收目标](delivery-validation.md#conversation-separation-validation) |
| **怎么组织更多 Agent 完成任务？** | [对话与任务并行图](tasks-agents.md#end-to-end-flows-1) · [Agent 生成与分工](tasks-agents.md#agent-factory) |
| **怎么自检、自愈、进化，又避免越改越差？** | [三种能力与成长原则](evolution-release.md#growth-governance) · [三标签交互预览](prototypes/growth-center/index.html) · [当前可运行闭环](core-bootstrap.md#evolution-loop-entry) · [独立模型与备选](models-offline.md#growth-model-policy) |
| **本地语音选谁、资源不够怎样用便宜云候补？** | [声纹 / STT / 克隆 TTS 主备](models-offline.md#voice-model-selection) · [回复朗读](interaction-persona.md#chat-readout-ui) · [接入计划](interaction-persona.md#voice-chat-plan) · [本地复测与未验证项](delivery-validation.md#voice-selection-evidence) |
| **人格、语音、NPC 和控制边界在哪里？** | [人格与交流](interaction-persona.md#persona-embodiment) · [NPC 世界](simulation.md#npc-world) · [权限与停止](security-sovereignty.md#identity-authorization) |
| **怎样编辑、置顶、分区或整理项目？** | [项目“…”菜单与恢复规则](interaction-persona.md#project-management-ui) |
| **打开文件夹后怎样保存内容？** | [当前使用方法](core-bootstrap.md#project-workspace-entry) · [根目录与输出规则](interaction-persona.md#project-root-output) |
| **日常交流与需要工作时的界面如何组织？** | [个人会话与按需工作台](interaction-persona.md#desktop-workbench) · [打开文件夹](interaction-persona.md#workspace-folder-flow) · [输入区](interaction-persona.md#composer-design) · [设置与专属能力](interaction-persona.md#jarvis-distinctive-controls) · [图标候选](interaction-persona.md#jarvis-brand-icon) |

---

<!-- book-tree:start -->
<a id="book-tree"></a>
## 按主题查阅完整文档

点击章节名打开正文，正文顶部可跳转到具体小节。下面的编号是阅读顺序；开发顺序以核心章中的 K0—K6 为准。

<a id="part-product"></a>
### 第一篇 · 产品与体验

| 章 | 文档 | 这章回答什么 |
|---|---|---|
| 01 | [产品定义、需求与能力边界](product-requirements.md) | 个人助手与伙伴的核心是什么，如何围绕主人扩展能力？ |
| 02 | [个人助手体验、工作台与人格形态](interaction-persona.md) | 怎样自然交流、延续人格，并在需要时展开工作台？ |
| 03 | [NPC 小镇与虚拟世界](simulation.md) | 怎样运行 NPC 小镇，并隔离虚拟与现实？ |

<a id="part-foundation"></a>
### 第二篇 · 核心与工程基础

| 章 | 文档 | 这章回答什么 |
|---|---|---|
| 04 | [最小核心、初始资产与开发路线](core-bootstrap.md) | 个人助手与自主成长核心从哪里开始，怎样沿 K0—K6 扩展？ |
| 05 | [后续方向指南：现状、缺口与优化工作清单](development-guide.md) | 当前版本还缺什么、先优化哪里，原方案的后续工作怎样落到代码与验收？ |
| 06 | [系统架构、运行边界与模块职责](architecture.md) | 个人助手核心如何连接记忆、模型、任务与可替换能力？ |
| 07 | [主人利益原则、身份授权与停止控制](security-sovereignty.md) | 当前个人使用边界是什么，哪些监督与认证设计已延期？ |
| 08 | [公共接口与数据契约](contracts.md) | 模块之间怎样交换任务、事件和记忆数据？ |
| 09 | [技术栈、源码目录与运行数据](stack-project-layout.md) | 选哪些技术，代码放哪里，开源组件如何取舍？ |

<a id="part-runtime"></a>
### 第三篇 · 智能运行与多设备协同

| 章 | 文档 | 这章回答什么 |
|---|---|---|
| 10 | [模型路由、本地模型与离线生存](models-offline.md) | 用哪些云端和本地模型，怎样切换与离线降级？ |
| 11 | [记忆、知识库与持续学习](knowledge-learning.md) | 记住什么，怎样检索、纠正、遗忘和持续学习？ |
| 12 | [任务、动作、多 Agent 与资源调度](tasks-agents.md) | 怎样一边交流一边执行任务，如何组织多 Agent？ |
| 13 | [离线自治、多设备共同体与重连](federation.md) | 断网怎样独立工作，重连怎样共享记忆与协同？ |

<a id="part-evolution"></a>
### 第四篇 · 自主成长与维护

| 章 | 文档 | 这章回答什么 |
|---|---|---|
| 14 | [自主进化、外部编码协作与版本发布](evolution-release.md) | 怎样自编工具、改进模块，并验证和回退？ |
| 15 | [开发环境、多语言工具链与构建](toolchains.md) | 怎样准备编译环境，构建和测试不同语言的程序？ |
| 16 | [系统健康、防退化与自愈](health-maintenance.md) | 怎样发现故障与结构退化，清理和修复隐患？ |

<a id="part-evidence"></a>
### 第五篇 · 验证与参考

| 章 | 文档 | 这章回答什么 |
|---|---|---|
| 17 | [能力验收、故障演练与评估证据](delivery-validation.md) | 哪些能力测过，证据在哪里，下一阶段怎样验收？ |
| 18 | [架构决策、批判性评审与评分](decisions-review.md) | 当前实现离伙伴核心有多远，工程评分和架构取舍依据是什么？ |
| 19 | [架构与流程图册](architecture-atlas.md) | 在哪里集中查看架构图和流程图？ |
| 20 | [研究资料与证据边界](references.md) | 设计和选型参考了哪些论文与官方资料？ |
| 21 | [文档维护规范](MAINTENANCE.md) | 以后怎样归类、更新、检查和清理文档？ |
<!-- book-tree:end -->

---

<a id="for-maintainers"></a>
## 文档维护者入口

修改文档前读[章节组织与维护规则](MAINTENANCE.md#book-organization)。查实现文件位置请看[源码与运行数据结构](stack-project-layout.md#project-structure)；查文档登记请看 [manifest.json](manifest.json)。

<details>
<summary>维护资料：文件职责、文档结构与检查命令</summary>

### 文件职责地图

完整规则放在下面指定的页面；其他页面用链接引用。公共契约页负责跨域格式，各领域页仍拥有其专用语义，避免把同一规则复制成多份。

| 当前文件 | 负责的内容 |
|---|---|
| [product-requirements.md](product-requirements.md) | 产品文案、作用、R/N 需求与能力上限 |
| [core-bootstrap.md](core-bootstrap.md) | 当前启动、聊天、预检与独立控制操作、迁移、SeedBundle、知识/规则/技能种子、K0—K6 与阶段内工作包及技能接入归属、首个演示 |
| [development-guide.md](development-guide.md) | 当前版本跨主题差距与优化工作项、原需求去向、未验项目及滚动维护；不另定K路线或验收门 |
| [architecture.md](architecture.md) | 总体视图、部署、信任边界、数据所有权、唯一控制权威 |
| [security-sovereignty.md](security-sovereignty.md) | G0、权限、委派、安全代际、锁存、离线解锁 |
| [federation.md](federation.md) | 单机/局域网/外网模式、统一意志的一致性边界、所有权、租约、记忆复制协议、同步选型与冲突 |
| [interaction-persona.md](interaction-persona.md) | 桌面工作台、项目文件夹与会话交互、输入区、功能入口与技能策略设置、品牌图标规范；语音通道、个性、性别表达、关系设定与形态 |
| [tasks-agents.md](tasks-agents.md) | 任务状态、动作账本、后台任务与有限工具循环、所有技能的使用/不使用与选择规则、Agent 工厂、团队、预算与资源租约 |
| [models-offline.md](models-offline.md) | 当前模型目录/提供商参数/用量策略与有限路由；嵌入模型候选、生产路由、恢复入口、模型生命周期、LP 降级与网络诊断 |
| [knowledge-learning.md](knowledge-learning.md) | 首期运行时知识与会话边界、个人/项目/人格记忆作用域、项目知识编纂、事实与派生索引分层、纠错/遗忘、学习晋升与防污染 |
| [evolution-release.md](evolution-release.md) | CodingProvider、改进事务、技能准入与升级退役、兼容、版本并存、灰度与回退 |
| [toolchains.md](toolchains.md) | 开发能力、构建配方、依赖闭包、目标验证与隔离 |
| [contracts.md](contracts.md) | 跨域契约、K1/K2 最小接口面、技能选择/策略/调用字段、记忆组件与 MemoryView/知识编纂契约、上下文编排、模块生命周期和公共事件 |
| [stack-project-layout.md](stack-project-layout.md) | 技术取舍、普通 PC 默认部署、开源记忆/OpenWiki/Grok Build 对照、Matt Pocock 编程包与 Anatomy 科普选型、模块化集成、源码树与依赖规则 |
| [health-maintenance.md](health-maintenance.md) | 观测、结构约束、文档/代码健康、退役清理、分级自愈 |
| [simulation.md](simulation.md) | 世界事实、角色、时间、精度、分支及现实效果隔离 |
| [delivery-validation.md](delivery-validation.md) | M 验收门、R/N 追踪、阶段出口验收、B/H/V-MEM/V-PC/V-UI/V-OSS/V-SKL/V-ANI 测试、记忆资源预算、选型与故障证据 |
| [decisions-review.md](decisions-review.md) | ADR、历史设计评分、EV 证据等级、取舍与待验证假设 |
| [references.md](references.md) | 稳定 S 系列来源、使用范围与论据限制 |
| [architecture-atlas.md](architecture-atlas.md) | 架构图的导航、图源和渲染说明 |
| [MAINTENANCE.md](MAINTENANCE.md) | 文档权威、章节树与技术文档归类、状态、增删改、检查、删除与历史规则 |

### 文档与资产结构

```text
Jarvis/
├── README.md                       # 简短项目入口
├── AGENTS.md                       # AI 维护约定
├── docs/
│   ├── README.md                   # 本页，完整导航和权威地图
│   ├── <topic>.md                  # 按 manifest 登记的当前主题页
│   ├── manifest.json              # 登记、图源/图片摘要、迁移依据
│   ├── assets/                   # 品牌设计等非架构图资产，由 manifest 登记
│   └── diagrams/
│       ├── <diagram>.mmd          # 唯一可编辑图源
│       ├── <diagram>.png / .svg   # 生成展示文件
│       └── render-validation.json # 图表解析与导出检查记录
└── tools/
    ├── check_docs.py              # 标准库文档检查
    ├── sync_doc_navigation.py     # 全书章节树与章内导航生成/核对
    ├── render_docs.cjs            # 图表导出
    └── package.json               # 仅文档渲染依赖
```

上面仅列文档工程；已经落地的源码、外置模型和运行数据与完整规划统一见 [源码与数据结构](stack-project-layout.md#project-structure)。不用第二套“总设计.md”重复拼装全部正文，不再在当前树保存旧版全文或 archive 文档。

### 修改后的检查

篇章归属和一句话导读在 manifest 中维护，小节导航由正文标题生成。修改后在仓库根目录执行：

```text
python tools/sync_doc_navigation.py --root .
python tools/check_docs.py --root .
```

改图另按[图册维护说明](architecture-atlas.md#rendering)渲染和核对。文档检查不替代软件功能、性能或安全测试。

### 状态与历史

整体设计状态仍为 proposed；accepted、implemented、verified 的区别见[状态与证据口径](MAINTENANCE.md#status-and-evidence)。K0—K6 是唯一实施顺序，M0—M6 是能力验收门。

各版本的历史证据与当前发布验证分别保留在[验收章](delivery-validation.md#versioned-evidence)；历史设计评分见[评审章](decisions-review.md#critical-review)，不能当作当前产品成绩。原文档迁移依据保存在 manifest 的 migration 字段。

已按主人 2026-10-16 的明确要求建立 Git，并关联 [Samuel521199/JarvisSystem](https://github.com/Samuel521199/JarvisSystem)；后续历史按[受控历史与退役规则](MAINTENANCE.md#retirement-and-history)管理。既有版本报告仍保留原时点的文件摘要，不补造历史提交。现已增加显式启用的限定工具成长观察器，范围见[进化章](evolution-release.md#bounded-evolution-loop)；启动与运行边界见[核心章](core-bootstrap.md#current-implementation)。

</details>
