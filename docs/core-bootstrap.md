# 最小核心、初始资产与开发路线

> 状态：整体 proposed；当前源码版本 0.1.87；部署状态见[本轮记录](delivery-validation.md#k6-scoped-sharing-evidence)；K4 工具与需求增量已验证，见[契约审阅证据](delivery-validation.md#k4-contract-evidence)，K3 开发协作通过，证据见[K3 收口](delivery-validation.md#k3-closure-matrix)，新增[K3 编码协作](delivery-validation.md#k3-coding-evidence)，保留[应用离线控制](models-offline.md#application-offline-control)；范围、验证与阻塞见[K2 本轮收口](delivery-validation.md#k2-completion-evidence)；完整 K1/K2 仍待原验收条件。跨主题差距见[后续方向指南](development-guide.md#direction-start)，实施次序见[当前推进队列](#near-term-work-queue) · 更新：2026-10-20
> [文档入口](README.md) · [维护规则](MAINTENANCE.md) · [架构图册](architecture-atlas.md)

<!-- book-nav:start -->
[全书目录](README.md#book-tree) › [第二篇 · 核心与工程基础](README.md#part-foundation) › 第 04 章 · 最小核心、初始资产与开发路线

## 本章导航

- [4.1 当前实现、启动与下一步](#current-implementation)
  - [4.1.1 在当前机器运行](#section-6a93004233bf)
    - [4.1.1.1 Windows 托盘与无控制台启动（0.1.18）](#windows-tray-entry)
  - [4.1.2 文字聊天与本地网页](#section-b3e262fa3ec1)
  - [4.1.3 使用自然语言目录报告（0.1.30）](#sample-task-entry)
  - [4.1.4 无需模型的本地精确计算（0.1.37）](#calculator-entry)
  - [4.1.5 查看聊天与任务的并行运行（0.1.34）](#parallel-runtime-entry)
  - [4.1.6 联合查询事实记忆与多个项目（0.1.33）](#memory-view-entry)
  - [4.1.7 使用本地模型和离线目录报告（0.1.32）](#offline-task-entry)
  - [4.1.8 从聊天发起和管理任务（0.1.31）](#conversation-task-entry)
  - [4.1.9 K3—K4 下一步：从混合成长循环拆为三种能力](#growth-center-next)
  - [4.1.10 从现在开始运行成长闭环](#evolution-loop-entry)
  - [4.1.11 模块观察与维护入口（0.1.28）](#module-monitor-entry)
  - [4.1.12 模型与费用后台（0.1.19）](#model-admin-entry)
  - [4.1.13 项目文件夹与文本文件保存（0.1.11）](#project-workspace-entry)
  - [4.1.14 项目资源、工程与扩展管理入口（0.1.27）](#project-extension-entry)
  - [4.1.15 原生技能、编程副本与齿轮科普（0.1.58）](#native-skills-entry)
  - [4.1.16 本机状态与旧版兼容（0.1.14）](#runtime-control)
    - [4.1.16.1 恢复密钥与密码流程已取消](#owner-recovery-enrollment)
  - [4.1.17 固定元数据 Worker（0.1.7）](#runtime-worker)
  - [4.1.18 独立浏览器 Computer Use（0.1.8）](#runtime-computer)
    - [4.1.18.1 网页后台任务控制台（0.1.13）](#web-computer-console)
  - [4.1.19 运行包与本机版本选择（0.1.15）](#runtime-package)
    - [4.1.19.1 0.1.17 启动前检查与故障回退](#runtime-startup-recovery)
    - [4.1.19.2 任务故障与程序网络阻断探测](#fault-network-probes)
  - [4.1.20 浏览器任务的临时目录回收（0.1.15）](#browser-residue-recovery)
  - [4.1.21 只读运行预检（0.1.5）](#runtime-preflight)
  - [4.1.22 下一步仍从 K1 出口推进](#section-d660c77ef363)
- [4.2 种子核心与初始资产](#seed-foundations)
  - [4.2.1 核心从哪里开始](#bootstrap-1)
  - [4.2.2 最小核心必须有哪些](#bootstrap-2)
  - [4.2.3 第一版就要有三类基础库](#system-health-1)
  - [4.2.4 种子资产与可信等级](#system-health-2)
  - [4.2.5 种子核心图](#bootstrap-3)
  - [4.2.6 两个层次：哪些能长大，哪些不能自行放开](#bootstrap-4)
- [4.3 开发顺序与每一步的出口](#bootstrap-5)
- [4.4 接下来具体做什么、什么时候进入下一步](#next-implementation)
  - [4.4.1 当前推进队列（更新至 0.1.87）](#near-term-work-queue)
    - [4.4.1.1 K4/K5 已有闭环与 K6 当前工作（2026-10-20）](#k4-next-delivery)
  - [4.4.2 K2 内优先完成文字/语音对话与工作的分离](#dialogue-upgrade-order)
  - [4.4.3 K2 内的最小自主进化核心](#k2-growth-core)
  - [4.4.4 历史进度核对与优先事项（2026-10-16）](#progress-audit-2026-10-16)
  - [4.4.5 K1：先交付可控、可恢复的单机执行底座](#next-k1-work)
  - [4.4.6 K2：再把“聊天”接到“做事”](#next-k2-work)
  - [4.4.7 统一技能管理、编程包与科普能力的阶段归属](#skills-adoption-stage-map)
  - [4.4.8 Grok Build 借鉴项怎样进入既有工作包](#grok-adoption-stage-map)
  - [4.4.9 工作台设计怎样进入既有阶段](#workbench-stage-map)
  - [4.4.10 K3—K6 什么时候开始](#section-0f6c7791761e)
- [4.5 实施边界与成长演示](#bootstrap-implementation-boundaries)
  - [4.5.1 每次成长的共同约束](#system-health-3)
  - [4.5.2 第一个应该做的演示](#bootstrap-9)
  - [4.5.3 首期目录子集](#bootstrap-10)
  - [4.5.4 什么时候算“核心已经有了”](#bootstrap-11)
  - [4.5.5 第一版必须保留的扩展点](#delivery-gates-1)
  - [4.5.6 首期实施应更小，但不能删除必需边界](#critical-review-9)
  - [4.5.7 核心先行、外部协作、持续评估](#product-definition-8)
<!-- book-nav:end -->

<a id="current-implementation"></a>
## 当前实现、启动与下一步

**0.1.74 使用修复：**网页/桌面共享本机目录创建，重推理有界等待、终态恢复提示可收起；新增[固定引擎坦克小游戏](tasks-agents.md#tank-game-runtime)。实际 Argon 普通回复、关卡生成与真实玩法检查见[本轮证据](delivery-validation.md#assistant-game-evidence)。原 K4 推进队列保持。

**0.1.66 K3 完善：**可修复语法损坏的所选文件，交付可直接由 Python 运行的 PYZ，实际工具包入口单独复验，并提供严格离线重建工具。三类真实 Codex 任务、独立检查、界面应用/恢复和剩余边界见[本轮结果](delivery-validation.md#k3-build-evidence)。

**0.1.65 编码协作：**在现有技能任务中增加独立留出检查、多文件候选与源码构建包、成组应用/恢复；外部 Codex 已真实接通，设置入口为[编码协作](http://127.0.0.1:18181/settings#coding)。范围归[编程工作流](tasks-agents.md#bounded-coding-workflow)，79 项针对检查、真实调用和部署归[本轮证据](delivery-validation.md#k3-coding-evidence)。

**0.1.63 网络控制：**设置 → 网络与离线，可持久限制 Jarvis 外联并保留本机能力，其他软件正常联网；[行为与边界](models-offline.md#application-offline-control)、[本轮验证](delivery-validation.md#application-offline-evidence)分别维护。此前 0.1.62 的 K2 证据保留，未运行门槛没有改成通过。

**K2 本轮冻结证据基线：v0.1.62；当前增量为 v0.1.69。** [K2 本轮实现与验收](delivery-validation.md#k2-completion-evidence)记录三库、个人配置、相关接续、资源争用修复和完整出口状态；0.1.61 的 [最终回答先导与能力说明修正](delivery-validation.md#memory-final-answer-evidence)已部署，[0.1.61 发布汇总](../evals/reports/memory-answer-release-2026-10-19.json)记录真实对照、回归与范围。0.1.60 新增[规则/语义记忆入口一致性](delivery-validation.md#rule-memory-review-evidence)，[0.1.60 发布汇总](../evals/reports/rule-memory-release-2026-10-19.json)记录源码、211 项回归、UI 与部署；下述 0.1.59 增量继续保留。0.1.59 新增[混合报告、指定取消与未开始任务原子修订](delivery-validation.md#mixed-report-admission-evidence)；[0.1.59 发布汇总](../evals/reports/report-admission-release-2026-10-19.json)记录本次有限范围。0.1.58 已上线限定编程副本/测试/应用与恢复、技能验证状态和本地记忆重复/差异核对；普通文字回执、有限恢复、对话/后台模型分槽与 Flash 限定文档自动受理继续可用。[发布汇总](../evals/reports/skills-completion-release-2026-10-19.json)记录实际范围；[后续方向指南](development-guide.md#direction-inventory)区分已完成、缺实现与缺验证。以下带版本的小节保留当时增量说明，其“尚缺”不能覆盖后续发布证据。

**0.1.50 按需语义记忆：**普通消息 →“整理为记忆…”→ 选择模型和档位 → 整理事实 → 核对原句、主体、用途并保存。保留原规则和明确指令；没有新数据库、框架依赖、模型下载或后台提取循环。实现范围见[语义候选](knowledge-learning.md#semantic-candidates-runtime)，测试及真实模型结果见[验收证据](delivery-validation.md#semantic-candidates-evidence)。

**软件解析技能（含可选中文解释）：**选择项目 → 输入区“技能任务” → “软件结构与行为解析” → 填项目内应用目录或 ASAR 文件，可选关注通道/文件 → 提交需求。在会话任务中打开右侧报告、下载文本与完整证据。默认按条件启用且零模型调用；需要解释时勾选“生成中文解释”并明确选择模型，报告区可逐条查看引用。范围见[使用规则](tasks-agents.md#rea-skill-policy)，实测见[验收](delivery-validation.md#rea-review-evidence)。

**0.1.47 轻量记忆分类：**打开原记忆面板，可设置个人/项目/共用/他人等类型及日常/工作用途。原 SQLite、记忆标识与来源保护保留，没有新增模型或常驻依赖；范围与资源实测见[分类验收](delivery-validation.md#memory-domain-evidence)。

**0.1.44 候选事实来源：**记忆卡片可回查原文；来源变化时暂停用于回答，纠正或遗忘后阻止从同一候选换名重新写入。独立确认保留复用原权限和修订检查，无新增运行依赖或模型调用。使用见[来源管理](interaction-persona.md#personal-candidates-ui)，范围与迁移限制见[本轮验收](delivery-validation.md#memory-provenance-evidence)。

**0.1.43 恢复与候选增量：**成长失败/中断记录新增[重新分析入口](interaction-persona.md#growth-demand-ui)，保留旧回执，新单先核对再开始；本人普通消息可[整理为候选事实与未结事项](interaction-persona.md#personal-candidates-ui)，经编辑确认写入原存储。没有新增运行依赖或后台模型提取。当前机器 5 分钟待命、应用层隔离离线与完整阶段缺口分开登记于[本轮验收](delivery-validation.md#recovery-candidates-evidence)，不能把局部通过等同于完整 K2。

**0.1.42 真实任务接续：**[接续卡片](interaction-persona.md#work-continuity-ui)可关联原会话的实际目录/技能任务和需求成长单，新会话核对当前状态和交付，而不是只复述旧进展。状态变化会使对应派生历史失效；关联不自动执行工作，无新增数据库、后台扫描或依赖。验收归[本轮记录](delivery-validation.md#work-continuity-evidence)。

**0.1.41 需求成长接线：**在普通聊天输入 `/改进 把最近的目录报告导出为 TSV`，本地分析来源与已有能力；开始后复用或补齐能力、独立验收，并完成本次真实输入的导出。关闭面板可以继续聊天，`/成长进度` 查看结果。继续使用同一成长账本和发布/回退机制，无新增运行依赖；[操作说明](interaction-persona.md#growth-demand-ui)与[验证证据](delivery-validation.md#growth-demand-evidence)明确当前仅限已知目录导出配方。

**0.1.40 明确话题接续：**已实现[有来源的进展与下一步记录](interaction-persona.md#continuity-ui)，可跨会话选择继续，更新/忘记使派生历史失效；范围与接入方许可继续生效。没有自动执行下一步、自动回忆全部聊天或新增后台唤醒。验证归[接续证据](delivery-validation.md#continuity-evidence)。

**0.1.39 个人核心起步：**已接通[聊天中的记住、纠正、忘记和交流设置](interaction-persona.md#personal-core-ui)，复用事实库、引用失效与本机会话归档；持久表达配置独立成模块。新会话可以采用允许的当前事实与表达快照，不自动回读全部聊天经历。分项验证归[个人核心证据](delivery-validation.md#personal-core-evidence)，完整 K2 仍未通过。

**0.1.38 基础修复：**可选界面资产故障不再阻断聊天启动，降级状态与缺失资源可见；资源面板前端夹具补齐现有页面结构；编码模型的响应等待按调用方期限执行，取消隐藏的 45 秒读取上限，保留未知请求不自动重发。真实限定工具的生成、升级、损坏发现、回退与模型修复已重新跑通。具体范围和复验证据见[基础修复](delivery-validation.md#foundation-repair-evidence)，完整 K1/K2 仍未通过。

**0.1.37 更新：**[本地精确计算](#calculator-entry)接管完整纯算式，支持小数、分数、乘方及明确舍入；无需模型配置，不新增依赖。它解决系统的计算路径，未改变原小模型的质量结论。[MCP 管理页](interaction-persona.md#extension-management-ui)新增十项已核对来源的分类卡片、配置模板、技能配合说明和分层选用规则。当前完成目录与配置管理；协议握手、工具发现、凭据绑定及 MCP 调用仍待接入，不计为十项已可执行能力。实现继续归既有 K2 有界工具入口，完整编码循环归 K3；验证分别见[计算证据](delivery-validation.md#calculator-evidence)与[MCP 管理证据](delivery-validation.md#mcp-management-evidence)。

**0.1.55 K2 增量：**接通 Context7 只读文档任务并复用现有 FIFO/取消/回执；其他 MCP 按实际接入状态管理。REA 增加真实开源应用主进程源码对照、处理器关系显示与推断等级校正；完整范围和未验证项见[文档工具证据](delivery-validation.md#mcp-runtime-evidence)与[真实应用证据](delivery-validation.md#rea-real-apps-evidence)。当时完整 K3 编码与通用选工具仍未完成；0.1.58 已增加[限定单文件编程](#native-skills-entry)，仍不代表通用开发闭环。

**0.1.36 更新：**[原生技能入口](#native-skills-entry)将 43 条原始登记整理为十个完整用户技能，带分类卡片和分层策略；九项文本指导进入聊天和报告任务，Anatomy 固定齿轮模板形成选择、执行、检查、交付、沙箱预览与下载闭环。此增量属于 K2 子集；任意生成代码、完整编程修复循环、自由机械建模和视频出口仍待 K3 及后续验收。

**0.1.34 增量：**[并行监控](#parallel-runtime-entry)已加入设置，复用按需采样与独立聊天/任务通道；补充取消、低内存准入和四个并行崩溃点测试，并修复聊天线程启动失败后请求槽未释放。真实本地测试的运行性能与答案正确性分开登记，后者仍有失败，见[证据](delivery-validation.md#parallel-runtime-evidence)。

**0.1.33 增量：**[联合知识查询](#memory-view-entry)已接通项目范围选择、事实与段落装配、来源定位和逐目的地重算；复用现有数据库与检索模块，无新增依赖或常驻服务。

**0.1.32 增量：**设置可显式启动/停止已下载的 CPU 小模型；规划使用独立上下文，本地计划采用受约束 JSON 输出，仍经原宿主校验。[18 个真实本地样例](delivery-validation.md#offline-task-evidence)全部通过；这是应用层限制外联及引擎 offline 模式的固定流程验证，不代表整机断网与完整 K2 通过。使用见[离线任务入口](#offline-task-entry)。

**0.1.31 增量：**[会话任务入口](#conversation-task-entry)已接通明确发起、进度查询、取消、持久关联与已核验报告下载，复用原账本及后台队列；受理回执丢失可按原请求编号查询。后台执行期间可继续普通聊天，任务控制消息不进入普通模型历史。范围与证据见[本轮验收](delivery-validation.md#conversation-task-evidence)。

**0.1.30 增量：**[后台自然语言目录报告](#sample-task-entry)已接通规划、完整计划校验、固定 Worker、确定性统计与产物回执；真实 Gemini 及临时实例界面/故障证据见[本轮验收](delivery-validation.md#sample-task-evidence)。仍是复用原固定范围的实验子集，普通聊天自动派发工具、MCP/技能扩展、完整离线与通用工具执行未开放。

**0.1.29 当前增量：**[工作台布局](interaction-persona.md#workbench-layout)支持可拖动导航、独立右侧目录/编辑标签、并排/专注/收起、文字缩放和保留草稿的显式重连；无新依赖或执行权限。验证见[布局证据](delivery-validation.md#workbench-layout-evidence)。

**0.1.28 增量：**修复记忆监控的旧占位，分别观察事实记忆、项目检索、MCP/技能登记和未实现的扩展执行；增加[已校验种子查询与能力状态](knowledge-learning.md#seed-runtime-entry)。不新增依赖、模型下载或常驻服务；仍无聊天工具执行入口。默认端口 18181 已在空闲时更新至 0.1.28；任务、会话与业务登记保留，源码重启不计热升级。验证与实际部署分开记录于[0.1.28 证据](delivery-validation.md#runtime-entry-evidence)。下面保留 0.1.27 及之前的功能沿革。

2026-10-15 从 K0 开始实现 `jarvis-seed 0.1.0`，随后逐步增加文字聊天、模型目录、预检、独立控制、隔离 Worker 与浏览器适配器。**0.1.27 新增[项目资源、文件编辑与工程文件](interaction-persona.md#project-resource-workbench)和[设置中的 MCP / 技能登记管理](interaction-persona.md#extension-management-ui)**；0.1.26 已有[项目资料检索与来源预览](interaction-persona.md#project-knowledge-ui)；0.1.25 已增加[明确事实记忆面板](interaction-persona.md#explicit-memory-ui)；0.1.24 已增加[本机会话自动保存与紧凑导出菜单](interaction-persona.md#conversation-archive-ui)；0.1.23 已增加独立上下文装配和[本会话要求](interaction-persona.md#composer-context-note)；0.1.22 已增加设置中的模块观察与候选运行包维护，见[模块入口](#module-monitor-entry)；0.1.21 已增加拖拽文件、图片粘贴与多模态聊天输入，见[附件使用方法](interaction-persona.md#composer-attachments)；0.1.20 已增加浅色、深色、暖纸和系统配色，在“设置 → 外观”切换后立即生效并保留草稿，见[配色规则](interaction-persona.md#workbench-appearance)；0.1.19 已增加模型配置与费用后台及 Eachlabs Claude 文本接入，见[使用入口](#model-admin-entry)；0.1.18 已增加 Windows 托盘与明确退出入口；0.1.17 已增加启动前健康检查与备用版本恢复；0.1.16 已增加后台任务内存准入、等待提示和稳定恢复；0.1.15 已增加浏览器任务临时目录回收与本机运行版本管理；保留会话停止、助手待命、免恢复认证、共用后台队列和项目根目录保存。任务记录仍来自同一本机账本；[托盘验证](delivery-validation.md#tray-evidence)、[启动恢复证据](delivery-validation.md#runtime-start-evidence)、[故障与网络阻断实测](delivery-validation.md#task-fault-network-evidence)与[既有版本记录](delivery-validation.md#versioned-evidence)分开登记。已按主人指定地址建立 [Git 仓库](https://github.com/Samuel521199/JarvisSystem)。以下区分当前实现与验证，其余章节仍是完整设计。

| 部分 | 当前实现 | 未完成边界 |
|---|---|---|
| K0 规范和夹具 | 六类 JSON Schema、知识/规则/技能种子、系统清单、有效/无效契约夹具、摘要检查 | 没有生产自主权限；规则摘要固定不等于独立 OS 保护 |
| K1 确定性外壳子集 | Task/Action 账本、幂等与取消、历史代际兼容、崩溃 UNKNOWN、固定元数据 Worker 与样例目录产物 | Host/监督器仍属调用用户；受保护身份和全局监督延期，已实现显式运行包切换/回退；整机离线及功能验收待补，K1 不算完整通过 |
| K1/W1 预检 | 独立于账本读写的 `preflight` 命令、身份/权限元数据、精确依赖版本、端口与源码摘要、角色/资源声明 | ACL 快照不等于隔离身份的有效权限；不读取锁存状态、不恢复任务，不签发执行授权 |
| K2 前置聊天与诊断 | 本地小模型、四家官方云端和 Eachlabs 初始共 20 个模型档案、CLI 与网页文字聊天、本机会话归档、有限候选路由、用量与额度提示；不设本地累计调用次数上限 | 普通聊天未接工具循环；后台固定报告另见下行，完整 K2 未通过 |
| K2/W1 记忆与项目文档增量 | 明确事实记忆、独立项目文档登记、中文词法检索、段落引用、修订与撤回、逐接入方过滤和历史引用链，0.1.33 增加有界跨项目联合视图 | 种子正文的模型检索与通用技能绑定、完整域/版本视图、自动提取、知识编纂、语义检索及共同体同步未完成；K2/W1 和 K2 总体验收仍未通过 |
| K2/W2 固定报告实验 | 后台自然语言需求、两步固定计划、真实目录 Worker、类型统计 JSON、摘要回执及取消/恢复 | 仅样例范围；普通聊天通用自动工具派发、通用技能/MCP、完整 K2 验收及真实离线任务未完成 |
| K2/W3 会话任务关联 | 0.1.31 明确任务模式及 /任务、/进度、/取消，本会话账本投影、刷新后关联恢复与核验报告下载；不额外调用模型查询状态 | 固定目录报告子集；并行性能指标、通用工具选择与完整 K2 验收仍待完成 |
| 项目工作台子集 | 持久登记项目文件夹、按需文件树、文本/脚本编辑、冲突检查、单根工程文件、会话切换与明确文本导出 | 普通会话文字可在本机归档，草稿/附件仅页面内存；只检索明确登记的项目文本；普通会话不执行生成代码，明确启用的编程副本见[技能入口](#native-skills-entry)；不支持通用图片/Word 产物，完整桌面工作台仍待完成 |
| 回复朗读、文件语音与前置诊断 | [聊天回复朗读](interaction-persona.md#chat-readout-ui)支持短句连续播放、暂停恢复与会话切换停止；[Qwen 主力文件 TTS](models-offline.md#qwen-tts-runtime) 支持组合表达，已获有限样本听感接受；[ZipVoice 文件 TTS](models-offline.md#fast-speech-runtime) 已改为默认停止的备选；[CosyVoice3](models-offline.md#cosyvoice3-runtime) 按需增强情绪；[按键 STT](models-offline.md#speech-input-runtime) 已接入本地识别，Silero 已接识别门控，声纹向量仍为文件诊断 | 已验证按键录音/转写与新回复播报；CosyVoice3 原生 CPU 仍慢；主人登记、活体检测、全双工对话未实现；不改变 K0—K6 顺序 |
| 明确任务范围的浏览器实验 | 独立 CLI、网页任务面板、持久 FIFO 队列、DOM 规划、四种元素操作、步骤与截图、取消；聊天并行 | 无通用工作流、原生桌面、视觉定位、登录态导入或开放式网页探索；不代表完整 K2/K6 达标 |

固定目录能力当前可做的真实任务是：枚举获准样例目录的文件元数据，保存带摘要的 JSON 产物；查询持久任务状态；拒绝越界路径与重复 ID 的不同参数。任务失败或进程崩溃不能简单改成“没发生”：未确认的 DISPATCHING 进入 UNKNOWN，不自动重放。

<a id="section-6a93004233bf"></a>
### 在当前机器运行

0.1.27 部署记录：2026-10-16 默认端口 18181 更新至 0.1.27，沿用原有 Python 环境和数据目录，保留浏览器依赖。本轮源码刷新核对保留 10 项任务和 1 项会话归档，项目/资料/扩展登记未改动；项目资源与扩展入口验证见[0.1.27 记录](delivery-validation.md#project-resources-evidence)，资料检索历史见[0.1.26 记录](delivery-validation.md#project-knowledge-evidence)，明确事实证据见[0.1.25 记录](delivery-validation.md#explicit-memory-evidence)，归档历史证据见[0.1.24 记录](delivery-validation.md#conversation-archive-evidence)；实际工作台聊天已验证，见[本轮使用测试](delivery-validation.md#readiness-evidence)；托盘和先前版本部署分别见[托盘记录](delivery-validation.md#tray-evidence)、[历史部署](delivery-validation.md#local-deployment-idle-evidence)。这是源码启动，不是运行槽位激活；以后更改源码仍需显式重启后端，普通页面刷新不能替代。服务重启后旧页签 nonce 失效，先检查会话保存状态并保留未发送草稿与附件，再刷新或另开工作台；0.1.23 及更早页面的聊天尚未自动归档。

**日常使用入口：[打开 Jarvis 工作台](http://127.0.0.1:18181/)。** 当前版本与本轮入口以[文档首页](README.md#project-status)为准；设置 → 成长中心保留自检、自愈与进化入口。沿用空闲实例正常退出与源码重启，不重放旧任务；本轮变更与部署记录见[成长职责增量](delivery-validation.md#growth-purposes-evidence)。历史部署及 K2 未验条件保留于[K2 收口](delivery-validation.md#k2-completion-evidence)。

当前能否日用、各模型表现和未完成功能，先看[2026-10-16 真实模型与功能测试](delivery-validation.md#readiness-evidence)。可以从云端问答、计划、单份文件生成和限定浏览器任务开始；本地微型模型仅作简单应急应答。源码现在会传入实际能力说明，截断回答不自动保存，规则见[模型上下文与完整性](models-offline.md#runtime-chat-context)。

| 本机端口 | 用途 | 使用方式 |
|---|---|---|
| `18181` | Jarvis 工作台：项目、聊天、文件保存、后台任务 | 在浏览器打开；服务未启动时，在仓库运行 `.\jarvis.ps1 tray`，随后双击托盘图标进入 |
| `18180` | 可选的本地 Qwen 小模型推理接口 | 选择本地模型前按[本地模型启动](#section-b3e262fa3ec1)操作；云端聊天不需要它。它不是 Jarvis 工作台地址，未启动时连接被拒绝是预期状态 |

如果 18181 也打不开，先执行 `.\jarvis.ps1 tray`：已有服务会返回 `already_running`；启动失败时检查[托盘诊断日志](#windows-tray-entry)。当前没有开机自启，电脑重启或明确退出助手后需再次启动。浏览器刷新可恢复已确认归档的普通会话文字，但会清空未发送草稿与附件；临时会话不归档。

PowerShell 工作目录为 `H:\Jarvis`。当前已初始化默认数据；`init` 仅用于首次初始化，不能用来解除停止。所有路径和依赖归属见[实际落地范围](stack-project-layout.md#implemented-layout)。

```powershell
.\jarvis.ps1 status
.\jarvis.ps1 inventory --request-id my-first-inventory
.\jarvis.ps1 status
```

同一请求 ID、同一参数再次运行会返回已有结果；不同参数会被拒绝。样例输入根默认为 `tests/fixtures/workspace`，不是整块硬盘。命令的完整选项可通过 `--help` 查询；`inventory --prepare-only` 可准备后再取消，`cancel <task-id>` 取消尚未完成的任务。

首次安装或重建开发环境使用锁定依赖；当前环境已经配置完成，无需每次启动都同步：

```powershell
$env:UV_PROJECT_ENVIRONMENT = 'H:\JarvisData\envs\dev'
uv sync --locked --extra speech --extra computer
$py = 'H:\JarvisData\envs\dev\Scripts\python.exe'
& $py tools/check_seed.py
& $py tools/prepare_worker.py
.\jarvis.ps1 init
```

<a id="windows-tray-entry"></a>
#### Windows 托盘与无控制台启动（0.1.18）

**双击启动（2026-10-17 增量 implemented）：**双击仓库根目录的[启动Jarvis.bat](../启动Jarvis.bat)，会复用原托盘启动器，在后台运行助手并打开 `http://127.0.0.1:18181/`；同端口已有 Jarvis 时只打开工作台。可将此 BAT 创建为桌面快捷方式，保持源文件与项目目录在一起。启动器优先复用本机 Codex 原数据目录，其次使用 `%LOCALAPPDATA%\Jarvis\data`，找不到已有 `control.db` 时明确报错，不初始化空白实例。数据旁存在原 DPAPI 凭据存储时，仅为服务子进程选择相同应用数据根，浏览器和当前终端环境不受影响。可用 `JARVIS_PYTHON`、`JARVIS_DATA_DIR`、`JARVIS_PORT` 指定已有环境、数据和端口；BAT 也接受 `--data-dir`、`--port`、`--no-browser`。`启动Jarvis.bat --check` 只检查路径与参数，不启动服务；失败窗口保留错误和日志位置。无需管理员提权，不创建开机自启。本轮在 0.1.36 集成工作树运行 BAT 的 `--check`，验证原数据定位、无效端口拒绝及缺失数据不初始化；未实际启动服务或浏览器。

在仓库根目录执行 `.\jarvis.ps1 tray`，可在后台启动带托盘图标的助手；也可指定 `--port`、`--data-dir`、`--config`。同一端口已有新版 Jarvis 时返回 `already_running`，不会再启动一份或把传入配置应用到已有实例。直接运行 `apps/web/server.py` 的 Windows 入口也默认启用托盘；诊断或无交互桌面可用 `--no-tray`。

图标在 Windows 右下角通知区域；系统可能将新图标放入 `^` 隐藏图标区，可由用户拖到常显位置。双击图标打开默认浏览器，右键菜单可查看当前状态、最近检查时间、刷新或退出。退出结束本实例的本机服务，已有账本与项目保留；有活动时提示确认。关闭浏览器页签继续待命，输入区停止仍只取消当前回复。完整状态与生命周期规则见[私人助手生命周期](interaction-persona.md#personal-assistant-lifecycle)。

托盘依赖 Windows 自带的 Windows PowerShell 5.1、.NET Framework/Windows Forms；不增加 Python GUI 依赖或更改执行策略。助手与托盘通过本次启动专属命名事件交接退出，HTTP 只读状态含版本与实例标识；没有新增网页全局停止接口。诊断在数据目录的 `diagnostics/tray/`，只记录状态、版本和实例信息；`server.log` 与 `tray.log` 用于启动失败排查。托盘异常不会给其他进程发送终止命令，没有安装开机自启或服务看护。

<a id="section-b3e262fa3ec1"></a>
### 文字聊天与本地网页

命令行与网页共用 ChatService；聊天只产生文字回答，不会执行模型建议的命令、工具或自编程序。模型、用量与自动切换的权威规则见[当前模型配置](models-offline.md#configured-models)。

```powershell
.\jarvis.ps1 models
.\jarvis.ps1 chat --provider auto --message '请帮我列一个今天的学习计划。'
.\jarvis.ps1 chat --provider openai --model gpt-6-astra
.\jarvis.ps1 chat --provider bailian --model qwen3.8-max
.\jarvis.ps1 chat --provider vertex --model gemini-4-argon
```

不传 `--message` 时进入交互模式：`/model <provider> [model-id]` 切换提供商与模型，`/models` 查看可选项，`/clear` 清空当前内存对话，`/exit` 退出聊天。支持 `auto / vertex / bailian / openai / xai / local`；输出显示实际提供商、模型、用量、切换尝试和额度提示。切换模型会把当前输入及保留的会话历史发给所选提供商；`auto` 也可能把这些内容发给其后续候选，UNKNOWN 不会触发盲目重发。

日常优先使用上方的[托盘启动](#windows-tray-entry)。只有使用本地 Qwen 模型时才需启动推理服务；0.1.32 可在[设置中显式启停](#offline-task-entry)，以下保留前台调试方式，网页服务已运行时不必重复启动：

```powershell
$py = 'H:\JarvisData\envs\dev\Scripts\python.exe'
& $py tools/local_llm.py serve
# 另一个 PowerShell 窗口中执行：
& 'H:\JarvisData\envs\dev\Scripts\python.exe' apps/web/server.py
```

浏览器打开 `http://127.0.0.1:18181`。网页采用侧栏、中央会话和底部输入区，保留 Jarvis 的 J 标识与星形图标。点击输入区下方模型名称，在同一个可搜索列表中选择各家模型，供应商自动匹配；旁边可调整该模型支持的推理级别。`auto` 跟随各家的默认模型和参数。初始六条线路注册可选，新增或停用后以后台有效配置为准，每条消息调用当前选中的一个模型；不同页面可并发，服务器现有上限为两个在途请求。该界面不表示同一条消息自动由多个模型联合回答。级别映射与限制见[推理级别](models-offline.md#reasoning-controls)。0.1.24 起普通会话文字自动保存在本机，“新对话”保留旧会话供切换；临时会话和未发送草稿仅在页面内存。新对话不会删除持久调用记录。Eachlabs 可在[后台](#model-admin-entry)显式查询余额；已有明确事实记忆与项目资料检索，0.1.81 已接入[连续语音与按键输入](interaction-persona.md#voice-chat-plan)，物理全双工与声纹仍待验收。网页服务与本地推理服务均需显式启动；关闭网页页签只关闭界面，服务仍可工作；完整退出语义见[私人助手生命周期](interaction-persona.md#personal-assistant-lifecycle)。

**0.1.12：运行时发送箭头变为方形“停止生成”按钮。** 点击后停止接收本次回复、提交后台取消，并恢复发送；原问题会回到空输入框，已输入的新草稿保留。运行中按 Enter 不会误触停止。停止后的迟到回答不追加、不进入后续历史，也不会触发尚未开始的自动文件保存；已经进入文件落盘时显示“正在保存文件”并等待回执，不把写完的文件假装撤回。此按钮仅作用于本次聊天，其他页面、浏览器任务和核心停止锁存不受影响。远端已接收的请求仍可能产生用量；具体处理边界见[模型调用边界](models-offline.md#section-896f72aed9a9)，验证见[停止验收](delivery-validation.md#chat-stop-evidence)。

模型调试与语音验证仍使用同一核心的停止状态；诊断入口保留：

```powershell
$py = 'H:\JarvisData\envs\dev\Scripts\python.exe'
& $py tools/model_probe.py --status
& $py tools/model_probe.py --provider vertex --prompt '用一句话说明你的作用。'
& $py tools/local_llm.py smoke
& $py tools/speech_probe.py
```

`local_llm.py smoke` 启动已校验的 CPU 服务、验证后退出；`serve` 提供前台服务并监听核心停止状态，Ctrl+C 也会结束子进程。只监听 `127.0.0.1:18180`，端口被占用时拒绝接入未知服务。它尚无独立进程权限隔离，同用户程序可能绕过探测网关访问端口，不能作为生产授权边界。

**0.1.14：助手空闲时显示“待命中”，本页回答时显示“回复中”，其他会话或后台任务执行时显示“运行中”。** 停止当前回复后即可继续提问，不需要恢复或解锁，也不会停止其他会话或后台任务。当前不设置恢复密钥或密码。

<a id="sample-task-entry"></a>
### 使用自然语言目录报告（0.1.30）

1. 打开[设置 → 后台任务](http://127.0.0.1:18181/settings#tasks)，选择“自然语言 · 样例目录统计报告”。
2. 输入“列出样例目录文件，按类型统计并保存结果”，选用已登记模型；相对路径留 `.` 表示页面显示的固定样例根。当前项目选择不会改变这个范围。
3. 点击启动；若队列已暂停，先核对任务记录，再点击“继续队列”。页面显示任务编号、规划状态、实际模型与结果；可以切回普通聊天或取消任务。
4. 完成后在详情查看文件数、类型数量/字节统计及 JSON 产物完整路径。成功结果读取时再次检查回执摘要；报告位于本机运行数据的 artifacts 目录，不覆盖项目文件。

不支持的需求、越界计划或不完整模型输出会如实失败，不声称已经执行。任务、修正预算与隐私边界以[运行语义](tasks-agents.md#sample-task-runtime)为准。本机小模型服务未启动时应先按既有启动说明运行；本轮不把云端成功当作离线能力通过。

<a id="calculator-entry"></a>
### 无需模型的本地精确计算（0.1.37）

打开[工作台](http://127.0.0.1:18181/)，可直接发送 `17 加 25 等于多少？只回答计算结果。`，返回 `42`；`0.1+0.2` 返回 `0.1+0.2 = 0.3`。显式命令示例：`/计算 1/3，保留2位小数` 返回 `1/3 = 0.33`，`/calc (17+25)*2` 返回 `84` 对应的算式结果。循环小数默认显示分数，例如 `/计算 1/3`。回答详情标注“本地精确计算 / 未调用模型”。

模型目录暂不可用时，仍可输入 `/计算` 加完整算式发送；宿主必须处于就绪状态。命令只处理当前算式，网页会为本次命令跳过技能/任务模式，不修改技能偏好。请移除附件和非空“本会话要求”后使用命令；自动识别遇到这些条件或显式专业技能则沿原模型聊天。完整语法、资源限制和失败处理见[计算分流规则](models-offline.md#deterministic-calculation-runtime)。设置的[模块与升级](http://127.0.0.1:18181/settings#modules)可看到独立计算模块和本次启动的使用次数；本轮[验证范围](delivery-validation.md#calculator-evidence)不代表数学应用题或原模型算术能力已通过。

<a id="parallel-runtime-entry"></a>
### 查看聊天与任务的并行运行（0.1.34）

打开 **设置 → 模块与升级** 或 **设置总览**，查看“并行运行与延迟”：当前聊天/后台任务数、已结束请求的 P50/P95、排队年龄、请求槽满/页面超时次数，以及宿主和本实例管理的本地模型工作集、私有提交与 CPU。未采到的值显示“—”；没有结束样本时不会伪造耗时。

这些统计在本次宿主内存中累计，最多保存最近 200 个结束样本，重启清零；任务与会话的持久记录仍按原机制保留。页面可见时更新，离开监控页面停止轮询。后台暂停、等待内存或待核对会显示状态，查看指标不会解除暂停或重新派发任务。

聊天页面等待超时后，后台处理可能仍在完成，请先核对状态；取消只影响指定聊天。当前小模型在[并行测试](delivery-validation.md#parallel-runtime-evidence)中仍出现算术错误，耗时成功不等于答案正确。指标口径和未覆盖的子进程见[监控规则](health-maintenance.md#parallel-runtime-monitoring)，字段见[接口](contracts.md#parallel-runtime-contract)。

<a id="memory-view-entry"></a>
### 联合查询事实记忆与多个项目（0.1.33）

打开当前项目 → 左下角 **AI 资料范围** → 在“本会话联合查询范围”勾选其他已登记项目，然后直接提问，例如“比较甲乙项目的登录方案，负责人分别是谁”。先在各项目内将要使用的文档纳入资料；打开文件夹不会自动扫描全文。事实记忆开关仍在记忆面板，选择项目后同时限定项目事实的范围，通用偏好继续可用。

面板中的“检索资料”提供本机联合预览；正式提问会按实际模型目的地及剩余预算重新筛选。回答下方的来源按钮标明项目、文件和行号，可点击核对；“本会话要求”展开后显示实际知识视图用量。切换会话或刷新页面恢复为当前项目；归档中的跨项目来源仍能打开，旧回答不因此重新获得外发资格。

这是词法查询与明确事实装配的有限增量。范围/限额见[运行语义](knowledge-learning.md#memory-view-runtime)及[接口](contracts.md#memory-view-runtime-contract)，真实模型、界面与回归证据见[0.1.33 验收](delivery-validation.md#memory-view-evidence)。

<a id="offline-task-entry"></a>
### 使用本地模型和离线目录报告（0.1.32）

1. 打开[设置 → 模块与升级](http://127.0.0.1:18181/settings#modules)，在“本地小模型”卡片点击“启动本地模型”；维护记录确认已完成、卡片显示“本实例管理”后再使用。首次先核验已有模型与运行包摘要，不下载新模型；失败原因见维护记录。
2. 返回[聊天工作台](http://127.0.0.1:18181/)，选择 **Qwen3 0.6B 本地 CPU**。普通问题使用普通对话，目录统计使用[会话任务入口](#conversation-task-entry)。希望只在本机处理时显式选本地，不使用含云端候选的 auto 路由。
3. 如队列暂停，在[后台任务](http://127.0.0.1:18181/settings#tasks)核对后继续；完成报告按原回执核验/下载。结束后在本地模型卡片点击“停止本地模型”，释放推理进程；Jarvis 主服务继续待命。

当前 PC 已有约 610 MiB 的固定 Qwen 权重，CPU 4 线程、2048 上下文、256 输出 token、单序列。启停和内存准入边界归[本地运行语义](models-offline.md#local-model-runtime)，验证范围及失败试验归[0.1.32 记录](delivery-validation.md#offline-task-evidence)。这不是通用编码、联网自恢复或语音交互验收。

<a id="conversation-task-entry"></a>
### 从聊天发起和管理任务（0.1.31）

打开[聊天工作台](http://127.0.0.1:18181/)，在输入区上方选择“执行任务 · 目录报告”，输入统计要求；也可直接发送 `/任务 列出样例目录文件，按类型统计并保存结果`。受理后可在“本会话任务”查看进度、取消或下载核验报告，普通聊天继续使用原输入框。

任务模式、命令和临时会话提示的完整用法归[会话任务交互](interaction-persona.md#conversation-task-ui)。当前仍仅执行已绑定的样例目录报告；选中项目不会改变范围，普通聊天也不自动执行模型建议的操作。队列暂停时需在[后台任务](http://127.0.0.1:18181/settings#tasks)核对后继续，旧后台任务不会自动改绑到本会话。运行语义与失败收口归[任务章](tasks-agents.md#conversation-task-runtime)，验证和实际部署分开记录于[0.1.31 证据](delivery-validation.md#conversation-task-evidence)。

<a id="growth-center-next"></a>
### K3—K4 下一步：从混合成长循环拆为三种能力

**0.1.64 已完成第 1、2 项与第 4 项的限定对象子集。** 分开纯完整性检查、按旧契约修复、明确目标进化，三个用途有主/备模型和原生档位；真实三标签替换原混合面板。未完成的事件计划、深度检查和策略抽屉保留在原目标内，不改变 K3—K4 归属。

1. 拆开只读检查、故障恢复与能力目标：先补故障分类、配置代际和迁移验证，让“自检”不再顺带写代码或升级。
2. 接三用途模型策略：原生档位、备选链、确定回执分类、预算与真实用量；UNKNOWN 不自动重发。
3. 将固定 300 秒循环替换为事件与分层到期计划，保留已有 Worker 和独立验收；完成缓存失效、资源退让与唤醒去重。
4. 以已验证后端替换预览数据，接通三标签和阶段动画；保留取消/回退/源码证据，逐项通过 [V-GROW](delivery-validation.md#growth-center-validation) 后记录 implemented/verified。

通用仓库编码、外部 Codex、任意模型/依赖替换、宿主自更新与多设备发布仍有各自未完成的实现，不因界面改名视为已完成。

**2026-10-17 结构审计建议，尚未实施：** 上述成长工作服从[个人助手优先级](#next-implementation)，复用 K1/W6 的可选模块故障降级、K2 的个人上下文与统一能力受理，避免三个标签背后形成互不相干的任务系统。已验证工具按真实需要接入，在 K5 比较实际体验和能力收益。问题见[当前代码审计](decisions-review.md#current-code-findings)，不新增阶段编号或平行实施时间线。

<a id="evolution-loop-entry"></a>
### 从现在开始运行成长闭环

**0.1.37 / evolution-v1 已实现 K3—K4 的限定垂直子集。** 打开[本机设置 → 模块与升级](http://127.0.0.1:18181/settings#modules)，在“自主成长 · 代码与技能”中选编码模型和期望能力并保存，再运行“生成 / 升级到期望版本”。启用“自动检查并修复”后，进程内观察器维护已登记对象；“立即自检”可直接触发同一路径。

当前可从缺失状态生成文件清单导出技能，再升级版本并自动处理损坏；全过程使用真实模型候选、隔离执行和独立验收。测试与代码定位见[成长证据](delivery-validation.md#evolution-loop-evidence)，完整模块、恢复与限额只维护在[进化章](evolution-release.md#bounded-evolution-loop)。命令行替代入口为 `python tools/evolution.py status|ensure|check|execute|rollback --data-dir <数据目录>`；与同一数据目录上正在运行的维护任务互斥。

该成长通路已具备继续试验第二个独立验收工具的条件，但是否扩展先由[个人助手核心需要](#next-implementation)决定，不因可以生成代码就自动优先增加工具。外部 Codex、更多工具链及 K5 自身模块对照仍待实现；任意源码重构、第三方组件自动升级、模型替换、数据库迁移和多节点统一发布亦未实现。已存在的固定目录任务和技能执行提供此子集的前置通路；K1/K2 的个人体验、整机离线、长期资源和整体验收继续保留，不因限定成长贯通就改写为通过。

<a id="module-monitor-entry"></a>
### 模块观察与维护入口（0.1.28）

打开工作台设置，选择[模块与升级](http://127.0.0.1:18181/settings#modules)。可以查看安装、启用、当前活动、健康与版本，筛选待命/未使用或异常模块，并从可信本机 ZIP 准备候选运行包。升级规则和未支持项以[模块观察与维护](health-maintenance.md#module-monitoring)为准；证据见[本轮验证](delivery-validation.md#module-monitor-evidence)。

0.1.28 已分别显示事实记忆、项目检索及扩展登记的真实状态和记录数量；页面下方可展开“初始知识与能力清单”并搜索种子条目。已登记和可执行分别展示；本轮范围见[种子运行入口](knowledge-learning.md#seed-runtime-entry)。

[Qwen 主力语音](models-offline.md#qwen-tts-runtime) 在模块列表上方提供音色、情绪、语言、资源显示和独立启停；[ZipVoice 备用语音](models-offline.md#fast-speech-runtime) 按主人要求默认停止；CosyVoice3 独立 TTS 保留加载、停止、情绪选择、参考声音、试听和 WAV 下载入口；均属于文件语音原型。安装与运行规则见[CosyVoice3 组件](models-offline.md#cosyvoice3-runtime)，已测/未测范围见[组件验收](delivery-validation.md#cosyvoice3-evidence)，不据此宣布完整 K6/M2 语音验收通过。

<a id="model-admin-entry"></a>
### 模型与费用后台（0.1.19）

点击工作台顶部最右侧的齿轮图标“设置”，进入[设置中心](http://127.0.0.1:18181/settings)，再选择“接入方与 Key”“模型与价格”“用量总览”或“调用明细”。新标签页保留原会话草稿；旧 `/admin` 地址仍兼容。后台无需登录密码；API 凭据仍是各模型服务自身所需，不是 Jarvis 恢复认证。

1. **接入方与 Key**：查看现有官方线路与 Eachlabs；添加、替换、切换 Key，或通过模板增加另一个账户/中转。Vertex 填服务账户 JSON，其他云端模板填 API Key。新增 Key 保存后只显示尾号，不自动花费测试。
2. **模型与价格**：按线路添加模型 ID，设置默认模型、推理级别、输出上限、币种、四类 Token 单价与平台附加费。对未定价档案先填写真实价格；停用默认项前先选择另一个默认项。
3. **用量总览 / 调用明细**：按日期、接入方、模型和 Key 筛选，查看每日总量、调用时价格、未知结果，导出当前 50 条分页的 CSV。Eachlabs 账户余额在其连接卡片中显式查询。
4. 回工作台点击右上角“检查连接”，模型菜单会更新。三个 Claude 型号在 Eachlabs 分组下；默认全局路由仍保持原设置，不会因为新增中转自动消耗其余额。

配置存储、费用范围与历史处理以[模型后台规则](models-offline.md#model-admin-config)为准。此版本运行的是源码启动的本机服务；0.1.18 历史运行包仍为旧版，尚未生成 0.1.19 的完整独立运行包。

<a id="project-workspace-entry"></a>
### 项目文件夹与文本文件保存（0.1.11）

在现有网页点击侧栏“打开文件夹”，选择系统目录选择器或输入现有目录的完整路径。普通文件夹也能成为项目，不要求 Git；输入区上方显示项目和根目录，点击“新对话”继承当前项目。侧栏可切换项目与本页面中的历史会话；无项目会话可聊天，生成文件前需选择项目。

- **边生成边保存：**在输入区“文件输出”菜单勾选自动导出，输入任务后发送。输出位置留空时自动产生 `回答-<请求标识>.md`，直接保存到项目根目录；也可填 `说明.md`、`docs/说明.md` 或明确的完整绝对路径。当前不会从自然语言中猜测输出路径，需要在“输出位置”填写指向。
- **保存已有回答：**展开回答下的“···”菜单，选择“导出为文件…”，在同样的路径规则下保存。成功后显示真实完整路径、字节数，并可复制路径；“文件记录”显示最近 50 项请求。其余输出规则由[交互章](interaction-persona.md#project-root-output)维护。
- **遇到失败：**重名文件不覆盖；目录丢失、被替换或写入失败，不改存其他位置。回答正文和草稿留在页面。网络丢失回执后沿用原请求核验；结果待核对时不重复写入，确认原文件后可明确点击“改为另存…”创建新请求。

项目登记与导出回执持久化；普通会话文字自动保存在本机，临时会话、草稿与附件仅保留于页面。0.1.27 打开项目后自动列举根目录，进入[项目资源编辑区](interaction-persona.md#project-resource-workbench)，展开目录和打开文件时按需读取；不会自动全文索引、上传全部文件或修改元数据 Worker 的样例目录授权。输出服务只保存用户选定的单份 UTF-8 文本（最多 1 MiB），不执行其内容；多文件代理创作、全项目内容搜索、跨会话长期记忆提取、项目输出偏好、桌面壳和实时语音尚未实现。系统目录选择器不可用时保留完整路径输入方式；实际验证范围见[0.1.11 验收](delivery-validation.md#project-workspace-evidence)。

2026-10-17 的[项目详情与管理](interaction-persona.md#project-management-ui)增加根行“…”菜单、名称/说明编辑、置顶与分区、可恢复的聊天归档和项目移除，以及系统资源管理器打开根目录；独立元数据模块不改变既有根身份或聊天正文。实现和实际部署分别见[项目菜单证据](delivery-validation.md#project-management-evidence)。

<a id="project-extension-entry"></a>
### 项目资源、工程与扩展管理入口（0.1.27）

1. 打开工作台，点击“打开文件夹”，选择现有目录；自动显示“项目资源”，可展开文件树、查看和编辑代码/脚本。README 无需登记。
2. 使用“新建文件”或打开现有文本，点击保存 / Ctrl+S；工程设置可保存 `.jarvis-workspace`。重开时在同一个打开框输入工程文件完整路径。
3. 在“设置 → MCP 连接”添加 stdio/HTTP 配置，在“设置 → 技能管理”登记包含 SKILL.md 的本地目录。现在可维护、检查和移除登记，尚不能在聊天中执行它们。

此增量属于 K1 工作台及 K2 前置能力入口，不增加另一条开发时间线，不宣布 K1/K2/K3 完成。后续在现有 K2 能力通路补任务驱动文件读取、MCP 握手/工具发现、技能加载和统一调用证据；项目读取、记忆与扩展运行仍保持[模块边界](architecture.md#project-extension-modules)。当前验证见[0.1.27 证据](delivery-validation.md#project-resources-evidence)。

<a id="native-skills-entry"></a>
### 原生技能、编程副本与齿轮科普（0.1.58）

**implemented / 局部 verified。** 在[工作台](http://127.0.0.1:18181/)先打开项目文件夹；设置中的[技能管理](http://127.0.0.1:18181/settings#skill)按类别列出十二个完整技能，含九项独立与三项组合（0.1.74 新增固定引擎坦克游戏）。内部组件与未接通候选不再混入菜单，归属可在清理记录查看，额外本地 SKILL.md 登记仍不执行。所有使用/不用规则和作用域解释只维护在[统一规则](tasks-agents.md#skill-selection-policy)。

- **齿轮科普：**输入“制作齿轮传动交互动画，支持拆解和组装”，或选择“技能任务 · 科普/源码报告”和 Anatomy。支持传动比 1:1、2:1、3:1；宿主验证要求与参数一致，比例不支持时明确拒绝。产物保存到所选项目，“本会话任务”提供预览和 HTML 下载；播放/暂停、角度、转速、拆解/组装、减弱动效可用。使用固定教学几何，不输出制造尺寸、公差或 CAD，也不输出 MP4。
- **编程指导：**聊天可按需或显式选择排错、TDD、代码审阅、模块设计。只装配一项已适配指导，最多 1,800 UTF-8 字节，不直接注入上游整篇正文。
- **其他文本技能：**需求到任务计划、工作交接、概念讲解与练习、需求调研问卷、Agent 指令编写可在聊天中按需或显式使用；选“技能任务”可把结果保存到当前项目。参考文件可选，未提供时仅依据本次要求；不会自动读取整个会话或仓库。
- **源码报告：**选“技能任务”，选上述指导，填写项目内相对源码路径（每行一项，最多 8 个，单个 16 KiB、合计 32 KiB），使用当前模型。任务读取所选文件，以附件交给模型，交付前重新核对源码摘要，再保存 `.txt` 报告。此入口只读分析，未修改源码、运行测试或实现自动修复；报告列出模型、来源摘要和未验证结论。
- **策略与回执：**设置支持全局、项目和会话作用域、继承、自动/手动/禁用和修订冲突保护；本轮开关与显式选择在输入区。原任务账本、FIFO、取消、内存等待和 UNKNOWN 语义继续有效。工作台刷新恢复任务链接，不重放执行；服务重启后旧页面需刷新。

0.1.65 已在原入口扩展为 1—4 个同目录 Python 模块，并支持选择外部 Codex、填写独立留出案例及下载源码构建包；完整使用规则见[编程工作流](tasks-agents.md#bounded-coding-workflow)。以下保留最早单文件入口的版本说明。

0.1.58 增加**编程副本**：在四项工程技能中任选入口，明确选择模型和单个 `.py` 文件，勾选“修改副本并运行验收”，填写 JSON 输入/预期。任务完成后打开“查看差异与验收”，核对结果后应用，必要时恢复原文件。当前接口及组合限制只在[编程工作流](tasks-agents.md#bounded-coding-workflow)维护；其余源码报告仍只读。该增量是 K2 有界任务与 K3 编码适配的限定子集，不表示整个 K2/K3 已通过；最终运行证据见[补齐五项缺口](delivery-validation.md#skills-completion-evidence)。

科普任务无需模型调用。固定组装器在无网络、只读暂存的 LPAC 中运行，产物必须通过独立传动比数值检查、真实 Edge 页面/交互检查和交付摘要检查；预览位于不带同源能力的沙箱 iframe，页面拿不到工作台 nonce。包内绘图库、脚本、许可证摘要变化会使准入失效。正式入口不依赖评估时的临时上游克隆；MIT 许可证随源码和 HTML 回执保留。实际运行证据及未完成场景见[技能闭环验证](delivery-validation.md#native-skills-evidence)。

<a id="runtime-control"></a>
### 本机状态与旧版兼容（0.1.14）

日常操作直接使用输入区的停止按钮；作用域和待命规则由[交互章](interaction-persona.md#personal-assistant-lifecycle)维护。需要查询本机旧控制状态时可执行：

```powershell
.\jarvis-control.ps1 status
```

控制 CLI 只保留 `status` 与 `migrate-local`，主 CLI 和控制 CLI 都不再提供全局 `stop`。旧库中的 `stopped` 仅是历史准入状态，不能解释为助手是否正在回复；网页展示实际的待命/运行状态。

只有从旧版升级且旧数据仍显示停止时，才显式执行一次 `.\jarvis-control.ps1 migrate-local`，然后重新启动原业务服务。该操作不需要密钥或密码；保留节点、事件、审计和业务记录，递增代际，旧请求不自动重放。正常运行实例执行它只查询状态，不改动数据。没有旧锁存的当前实例无需这一步。

已有 v1 业务库仍通过 `.\jarvis.ps1 upgrade-control` 显式升级，保留节点和任务/动作/产物，不覆盖独立控制区；新建实例直接使用 v2。兼容协议见[消息契约](contracts.md#recovery-contract)，验证见[当前证据](delivery-validation.md#personal-lifecycle-evidence)。

<a id="owner-recovery-enrollment"></a>
#### 恢复密钥与密码流程已取消

2026-10-16 用户明确取消密钥和密码要求。旧版密钥创建、登记、挑战、签名和认证恢复命令均已移除，不需要准备公钥文件、私钥、密码或恢复介质。保留本锚点用于旧链接指向当前决定；历史验证记录不等于现行使用步骤。

<a id="runtime-worker"></a>
### 固定元数据 Worker（0.1.7）

`inventory` 现在经过：Host 检查授权和目录范围 → 枚举文件元数据 → 暂存只读输入 → 启动一个 Windows LPAC/Job Worker → 校验绑定回复 → Host 再检查停止/代际并提交产物。原文件内容、凭据和数据库不会暂存给 Worker。正常结束、超限或取消后进程退出；本轮不新增常驻服务。

本机已准备好小型 Python 运行包。`tools/prepare_worker.py` 使用已安装的 Windows Python 3.13 离线组装，没有联网下载；已有包只校验、不覆盖。新机器生成的包可能有不同摘要，需核对来源、更新 [固定 profile](../config/worker-profile.json) 并重跑测试后使用，工具不会自行接受新摘要。缺包、摘要错、隔离身份校验失败均拒绝任务，不能退回普通子进程。实际目录归[落地结构](stack-project-layout.md#implemented-layout)维护。

```powershell
& 'H:\JarvisData\envs\dev\Scripts\python.exe' tools/prepare_worker.py
& 'H:\JarvisData\envs\dev\Scripts\python.exe' tools/worker_probe.py
.\jarvis.ps1 inventory --request-id my-isolated-inventory
```

这一步提供可运行的隔离计算通路，仍不接受 Shell、任意脚本、模型生成程序或网络权限。完整权限边界和崩溃残留限制见[Worker 安全范围](security-sovereignty.md#worker-isolation)，协议见[固定 Worker 消息](contracts.md#worker-contract)，实测见[0.1.7 证据](delivery-validation.md#worker-evidence)。

0.1.13 在网页队列启动时回收已登记、已退出的固定 Worker 残留，也可运行 `.\jarvis.ps1 recover-workers` 显式核查。只处理固定暂存根内身份匹配的任务目录和对应 profile；未知旧目录或变动内容保留并报告，不重放任务、不解除停止。新增实测见[本轮证据](delivery-validation.md#k1-progress-evidence)。

<a id="runtime-computer"></a>
### 独立浏览器 Computer Use（0.1.8）

按本次明确要求实现可运行的早期浏览器子集，采用**现有模型网关 + 独立适配器 + 系统 Edge**。能力按需启动，不新增常驻服务，也不下载第二套浏览器或视觉模型。普通文字聊天仍不执行工具。模块拆分与替换关系见[架构](architecture.md#computer-use-design)，安全和当前限制见[浏览器边界](security-sovereignty.md#computer-boundary)。

本机依赖已安装。新环境需安装现有 Microsoft Edge，并在已配置的开发环境执行 `uv sync --locked --extra computer`；若需要保留语音依赖，同时加 `--extra speech`。演示页是程序内部提供的合成表单，不连接实际业务网站。

```powershell
# 使用已注册的模型，供应商自动匹配；四步完成表单并保存截图。
.\jarvis-computer.ps1 demo --model gpt-6-luna
# 显示本任务专用的 Edge 窗口：
.\jarvis-computer.ps1 demo --model gpt-6-luna --headed
# 无模型、无云端费用的固定动作测试；这不是离线 AI 能力证明：
.\jarvis-computer.ps1 demo --scripted
# 查看回执或取消正在进行的任务；task-id 来自主账本 status：
.\jarvis.ps1 status
.\jarvis-computer.ps1 status --task-id <task-id>
.\jarvis-computer.ps1 cancel --task-id <task-id>
```

真实任务使用 `run --task <本地JSON路径> --model <模型ID>`。任务文件需明确 URL、允许的 HTTP(S) origin、目标元素的 role/name、允许动作和值、成功文字、最多步骤与时间。以[演示任务](../config/computer-use/demo-task.json)为结构样本；`demo` 才提供内置页面，不能直接把它的虚构地址用于 `run`。完整字段由[契约页](contracts.md#computer-contract)指向唯一 schema。`--model auto` 复用现有有限候选路由；不是所有候选都已验证适合规划。

例如把已授权网站的“搜索”输入框和“查询”按钮写入任务范围后，模型可以根据当前值决定是否填写、点击；新增目标页面不需要修改浏览器底座。当前还不能仅凭一句开放目标自行探索任意网站、接管用户现有标签页或上传文件。需要登录跳转、验证码、密码、弹窗、新窗口或重定向的网站暂不支持。

任务执行流程：校验任务 → 记录 Task/Action → 新建浏览器上下文 → 观察 DOM → 模型选下一步 → 校验动作及页面是否变化 → 记录 IN_FLIGHT → 操作 → 再观察 → 核对成功文字 → 保存 JSON 和 PNG。JSON 位于既有 `artifacts` 目录，含每步模型用量与状态；PNG 留在本地。当前页面文字和允许的输入值会送给选中模型，`auto` 可能转发给候选供应商。

同一 `--request-id` 的完成或未知任务只返回记录，不重新点击。外部网站没有幂等回执，发生中断后需先核对实际结果，再明确提交新任务。停止/取消保留历史，已发出的云端请求仍可能计费。浏览器任务与目录 Worker 当前共用一个执行锁，聊天可继续；多浏览器并行、后台队列和原生桌面仍待后续验收，不另建开发时间线。

<a id="web-computer-console"></a>
#### 网页后台任务控制台（0.1.13）

打开 `http://127.0.0.1:18181/`，点击顶部最右侧齿轮图标，进入 **设置 → 后台任务**，或直接进入[任务设置页](http://127.0.0.1:18181/settings#tasks)。默认目录清单无需模型；浏览器模式的执行模型独立选择，默认 GPT-6 Luna，采用模型档案的默认推理配置，不改变聊天模型和推理级别。

1. 选择“模型演示”并启动：模型决定内置合成表单的四步操作。也可选“固定动作测试”，只验证执行通路、不调用模型。
2. 要操作自己的已授权网页，选择“自定义任务”，粘贴符合[浏览器契约](contracts.md#computer-contract)的 JSON；仍需明确 URL、目标和值，不接受任意命令或用户文件路径。
3. 右侧最多显示 30 条目录/浏览器任务，未完成任务优先。点击记录查看状态；目录任务显示清单与已核验产物路径，浏览器任务显示各步操作、实际模型用量和成功截图；失败/UNKNOWN 会保留可核对的状态。
4. 运行期间可以切回聊天；切换面板保留聊天草稿和当前页面的会话。刷新/关闭页面不会取消已接纳任务，重新打开面板可查询账本；刷新可恢复已归档文字；未发送草稿与附件仍会清空。
5. 可连续添加任务，最多 20 个等待任务加 1 个执行任务；右侧显示排队位置。“暂停队列”只暂停后续派发，不中断当前任务；“继续队列”恢复未开始任务。服务重启后先核对记录再继续，UNKNOWN 不会被重新执行。
6. 从任务详情取消执行。取消处于“正在取消”时等待执行器收口，不能解释成撤销已发生效果。核心停止后允许查看历史，但不接纳新任务；网页不提供清锁或恢复密钥接口。

默认“目录清单”无需模型，输入 `.` 或获准样例根下的相对目录即可提交。面板明确显示初始化时绑定的样例根；选择项目文件夹不会扩大这个读取范围。此处是内部任务审计产物，保存在实例产物区；用户在聊天中生成或保存的文件仍遵守[项目根目录输出规则](interaction-persona.md#project-root-output)。

网页服务一次执行一个目录或浏览器任务，其他新请求进入同一持久 FIFO 队列；同时保留原有两个聊天请求槽。任务与队列登记必须在同一事务写入主账本才返回接纳成功，同一请求 ID 重复提交不会重新执行已完成或未知任务。请求等待异常时先刷新记录；页面保留当前提交的请求 ID，可用于核对，修改输入才产生新意图。

执行器是现有网页进程中的一个后台线程，队列持久保存在原 SQLite 账本中；未新增系统服务、消息代理或第三方依赖。正常关闭服务会暂停队列并请求取消活跃任务，等待任务保留；强制退出后先对账。完整排序、交接和 UNKNOWN 处理以[队列语义](tasks-agents.md#browser-durable-queue)为准。服务启动方式沿用[本地网页](#section-b3e262fa3ec1)，仍无开机自启。

<a id="runtime-package"></a>
### 运行包与本机版本选择（0.1.15）

[打包工具](../tools/release_bundle.py)收集固定源码、配置、文本说明、核心 Python 依赖及已校验 Worker Python，不包含凭据、现用账本、模型权重、完整浏览器和可选语音依赖。0.1.62 当前运行包与独立启动/回退证据见[K2 本轮收口](delivery-validation.md#k2-completion-evidence)，交付路径为 `artifacts/releases/jarvis-0.1.62-k2-reviewed.zip`；原 `k2-runtime.zip` 保留不覆盖。0.1.13—0.1.18 包仅保留为历史测试对象，不能直接承接新增个人数据；当前包包含固定 Playwright 驱动，浏览器仍需已安装 Edge。

[版本入口](../tools/runtime_releases.py)提供安装、独立健康检查、选择、回退和启动。默认槽位目录为 `%LOCALAPPDATA%\Jarvis\runtime`，可用 `--root <完整路径>` 指定本机支持 ACL 的位置；每个运行包独占一个槽，业务数据始终放在独立的数据目录。安装不会启动服务或改变当前版本。

```powershell
$py = 'H:\JarvisData\envs\dev\Scripts\python.exe'
$installed = & $py tools/runtime_releases.py install artifacts/releases/jarvis-0.1.62-k2-runtime.zip | ConvertFrom-Json
$releaseId = $installed.id
& $py tools/runtime_releases.py health $releaseId
& $py tools/runtime_releases.py select $releaseId
& $py tools/runtime_releases.py status
& $py tools/runtime_releases.py start --data-dir "$env:LOCALAPPDATA\Jarvis\data" --mode web
# 选择上一个已验证版本，下一次显式启动时生效：
& $py tools/runtime_releases.py rollback
```

`health` 使用随包 Python 在全新临时实例执行真实 LPAC 目录任务并核验产物，不触碰现用账本；失败包不能选择。每次选择、回退和启动重新校验完整成员与内容摘要；选择记录与历史在同一事务中更新。通过该入口运行的进程持有版本使用锁，运行时拒绝切换，须先明确退出该进程；不会为了升级杀掉当前助手，也不改动独立启动的 18181 旧服务。

`run --mode status` 查询同一数据目录，`--mode inventory` 执行固定清单能力，`--mode web --port <端口>` 启动本机网页。包未包含 Playwright 时仍可聊天和运行清单，浏览器能力显示不可用。0.1.17 的启动前恢复见下节；当前没有开机自启、运行中宿主崩溃重启、宿主热更新、数据库降级迁移或受保护监督；Python 禁网钩子的健康检查不等于整机断网验收。接口和持久状态归[版本管理契约](contracts.md#runtime-slots-contract)，演进边界见[版本连续性](evolution-release.md#service-continuity-4)。

<a id="runtime-startup-recovery"></a>
#### 0.1.17 启动前检查与故障回退

安装、健康检查并选择版本后，可用 `start` 代替 `run`：

```powershell
& 'H:\JarvisData\envs\dev\Scripts\python.exe' tools/runtime_releases.py start --data-dir "$env:LOCALAPPDATA\Jarvis\data" --mode web
```

此命令明确启动一次助手：先检查数据格式和当前包，再在临时实例运行健康检查；当前包不可用时，只尝试已经登记的上一个已验证版本。启动前向标准错误流报告实际选定版本和回退原因，`status` 的 `starts` 返回最近 10 次启动记录。正常退出沿用业务进程退出码；没有可用版本时保留失败原因并退出，不重置数据。完整边界见[启动恢复规则](evolution-release.md#runtime-startup-policy)，故障与实际包证据见[本轮验收](delivery-validation.md#runtime-start-evidence)。

仍可使用 `run` 直接运行当前已验证版本，它不追加自动健康回退。两个入口都不终止现有服务；端口占用应先处理原实例，不能把新进程启动失败当作重放任务的理由。

<a id="fault-network-probes"></a>
#### 任务故障与程序网络阻断探测

在 Windows 开发环境中运行以下命令。故障探测创建独立临时数据，以真实子进程退出覆盖固定目录任务的持久化边界；不会中断现用 Jarvis。

```powershell
& 'H:\JarvisData\envs\dev\Scripts\python.exe' tools/probe_task_faults.py
& 'H:\JarvisData\envs\dev\Scripts\python.exe' tools/probe_network_recovery.py artifacts/releases/jarvis-0.1.16-runtime.zip artifacts/releases/jarvis-0.1.17-runtime.zip --elevate
```

网络探测需要两个已经准备好的不同版本完整包，包不随 Git 上传；按[运行包说明](#runtime-package)准备。`--elevate` 仅通过 Windows UAC 提权防火墙辅助进程；已在管理员终端时可省略。它核对 4 个临时可执行文件路径后设置出站阻断，结束/失败后移除自身规则，最长保留 10 分钟；不更改网卡和防火墙配置文件。当前用户对新建探测目录的结果文件保留访问权限。助手和电脑上的其他应用保持原网络状态。

默认输出为 `evals/reports/task-fault-matrix.json` 与 `network-recovery.json`；需要保留前次结果时通过 `--output <路径>` 指定新位置。只有阻断前后正向连接、阻断期间拒绝及未阻断对照、恢复演练和规则清理全部成功，网络报告才能通过；失败时保留诊断，清理未经确认时保留临时目录。完整结果与未验证范围只在[验收记录](delivery-validation.md#task-fault-network-evidence)维护。

<a id="browser-residue-recovery"></a>
### 浏览器任务的临时目录回收（0.1.15）

每个浏览器任务使用独立登记的 profile 和下载暂存目录，不复用用户浏览器配置。正常结束后清理；服务重启时核查已登记残留，或显式执行 `.\jarvis.ps1 recover-browsers`。检查和清理不调用模型，不重跑旧任务，也不停止助手或其他浏览器。

仍有使用锁、驱动/Job 存在、启动过程尚未完成登记、目录身份不符或出现链接/未知顶层内容时保留并报告。只处理固定根中的登记目录，不按名称扫除旧版 Playwright 临时目录。完整范围见[浏览器实现边界](security-sovereignty.md#computer-boundary)。

<a id="runtime-preflight"></a>
### 只读运行预检（0.1.5）

在项目根目录运行：

```powershell
.\jarvis.ps1 preflight
.\jarvis.ps1 preflight --json
```

默认输出中文摘要，`--json` 输出带版本的诊断证据；`--data-dir` 可指定临时实例。命令不会初始化目录、读取密钥、调用模型、安装服务、修改权限、清锁或恢复任务，也不会自动保存报告。它短暂绑定并释放本机 IPv4 端口以观察是否可用，不连接未知服务；已占用只表示有占用，不证明对方是 Jarvis。需要留档时由调用者显式保存 JSON。

状态分为已核对、未满足、提示、未确认。固定元数据 Worker 已实现；恢复认证在 0.1.14 按用户要求取消，报告将其记为延期提示，不再要求登记材料。受保护监督和通用隔离执行仍保留未满足记录，因此完整部署就绪状态仍为 `blocked`；它不阻止已支持的个人聊天、待命和限定任务，也不代表高级部署已通过。退出码 1 是诊断结论，退出码 2 表示未完成评估；报告不签发执行授权。JSON 契约见[预检接口](contracts.md#preflight-contract)。

权限检查读取路径类型和 ACL 元数据；不通过写测试文件或改 ACL 猜测实际权限。它只确认当前诊断进程身份，不声称发现其他进程身份。普通 `status` 会对未决任务执行恢复对账，预检为保持只读而不调用它，也不打开运行数据库，明确把锁存状态标为未评估。验证范围及未通过项目见[本轮证据](delivery-validation.md#preflight-evidence)。

<a id="section-d660c77ef363"></a>
### 下一步仍从 K1 出口推进

0.1.17 已补充当前开发机的五分钟待命采样并完成实际网页更新，见[部署与资源证据](delivery-validation.md#local-deployment-idle-evidence)；固定目录任务的进程崩溃矩阵与运行包出站阻断恢复已获得[局部实测证据](delivery-validation.md#task-fault-network-evidence)。接下来仍需选定运行包整机断网冷启动、目标普通 PC 的资源证据及跨能力故障矩阵汇总；不能将程序禁网或开发机五分钟结果扩展为完整 K1 或长期稳定性通过。

按当前个人使用范围，浏览器登记回收与显式运行版本回退已补齐；0.1.16 已增加[队列内存准入](tasks-agents.md#queue-resource-admission)和短时竞争验证，继续完成整机离线、普通 PC 长时资源与 K1 整体验收。固定目录、浏览器和版本管理仍是明确限定范围。密钥、密码、受保护监督部署和全局停止已由用户延期，不再作为个人功能开发的前置条件。K1 完整通过后，把已验证模型端口接入有限计划和技能调用；K3/K4 再引入外部 Codex、候选编程、固定构建、独立验收、灰度回退。已有限定工具代码的生成、升级和自愈，见[成长入口](#evolution-loop-entry)；当前没有自主下载或替换模型、改写宿主源码、通用自动学习、动态后台 Agent 或硬件控制；这些能力需各自的权限和验收出口，不能由一次模型回答启用。

0.1.5 已交付 [K1/W1 预检](#runtime-preflight)，0.1.6 曾交付同用户控制原型，0.1.14 按用户要求将 W2 收敛为[会话停止、待命及旧数据兼容](#runtime-control)，0.1.7 已交付 [W3 固定元数据 Worker](#runtime-worker)。余项沿用[唯一推进表](#next-implementation)，不建立第二条版本路线。

<a id="seed-foundations"></a>
## 种子核心与初始资产

<a id="bootstrap-1"></a>
### 核心从哪里开始

**产品核心是“能自然交流、记住适用信息、下次接续、主动协助，并自主学习和进化”的个人助手。** 相处、行动与成长一起构成类钢铁侠贾维斯的目标；原先仅把代码成长闭环当作起点，遗漏了[伙伴核心判据](product-requirements.md#personal-companion-core)，而把成长完全推到核心之后也不符合主人要求。K2 先贯通文本个人体验与一条受限成长闭环，后续扩大能力范围。

实现依赖仍需先打牢 K0/K1 的契约、持久状态与可恢复控制，但最小可用体验在 K2 同时接通个人会话、基础人格配置、可纠正记忆和少量可靠能力。纯聊天不创建任务；需要执行才进入任务/动作账本。第一段智能来自已有本地模型或获授权远端模型，不需要先训练基础模型，也不要求首版本机小模型已经拥有强编程能力。

建设关系：

**主人确定相处方式与需要 → 我们做出可交流、可记忆、可协助的种子版本 → Jarvis 从真实使用中识别能力缺口 → 已有技能或改进候选解决问题 → 独立验证 → 主人获得更好的协助体验。** 外部 Codex 是其中可选的编码协作者，不持有 Jarvis 的个人身份与关系记忆。

这里“自己进化”指 Jarvis 能发起、组织、验证和采用改进；复杂代码可以由外部开发 Agent 协助完成。谁写代码与谁掌握运行身份、任务、权限、评估记录和发布权是不同问题。

<a id="bootstrap-2"></a>
### 最小核心必须有哪些

以下是最小助手及其成长底座的职责，按 K0—K6 渐进接通，不要求每项成为大型服务或独立 Agent。人格和个人连续性从 K2 文本体验开始；通用成长不是首次聊天的前置条件。

| 核心职责 | 第一版具体做什么 | 为什么现在就需要 |
|---|---|---|
| 个人身份、表达与会话 | 稳定助手标识、主人设置的称呼/语气/关系配置；无需项目的文本交流 | 换模型、切换会话仍是同一个助手，不只有任务执行器 |
| 个人记忆与交流连续性 | 复用事实/归档接口，接通明确记住、纠正、忘记与有界相关召回 | 下次不必重复交代；个人偏好和项目资料各守作用域 |
| 初始知识、规则、技能与系统清单 | 随种子版本预装可信资料、有效规则、基本技能及版本/依赖信息 | 首次启动就知道自己的结构、边界与已有能力 |
| 主人控制与恢复底座 | 当前会话停止、任务取消、明确退出、最后可用版本与恢复 CLI；完整身份/锁存按当前范围延期 | 系统出错或升级失败时主人仍能控制它，不把延期认证当作当前使用前置 |
| 持久任务内核 | 接受任务、状态机、取消、预算预留、动作意图、回执与 UNKNOWN | 不能把进程中断当成任务从未发生 |
| 能力执行器 | 读限定文件、写候选产物、运行受限工具；权限和资源检查 | 模型可以建议行动，但不能直接获得整台电脑 |
| 模型与开发者端口 | 一个本地模型适配、一个可选外部编码适配 | 允许先借助强编码 Agent，再逐步提升本地能力 |
| 候选工作区与构建器 | 源码快照、固定工具链、隔离构建、产物摘要 | “写出代码”必须变成可检查、可运行的包 |
| 独立评估与发布器 | 保护基线、运行验收、灰度、回退、记录结果 | 自己说“改进了”不能自动等于允许上线 |
| 最薄进化循环 | 从失败或明确需求生成改进单，提交候选，读取评估结果 | 让已有核心能够发起下一次成长 |

三库种子与可信等级详见本页对应定义：知识保存带来源的事实，规则经受保护执行器生效，技能通过测试后注册。初期另保存任务记录、主人明确偏好、能力目录、改进记录和产物引用；无需先建立通用知识图谱。防止结构退化、代码/文档污染、误删旧版本与无限自愈的完整要求见[长期健康自愈](health-maintenance.md#system-health)。一个任务 Worker 和一个编码任务足以验证限定成长实验，却不足以证明个人伙伴核心已成立；语音、复杂化身、NPC 和大规模共同体再按需扩展。

所有正式效果仍受[G0 最高宗旨](security-sovereignty.md#product-definition-6) 约束。没有完整语义判断能力的早期版本，只开放能明确限制和验收的任务范围；不能把功能不完整解释为暂时取消监督。

<a id="system-health-1"></a>
### 第一版就要有三类基础库

**最小核心出生时就必须拥有知识库、规则库和技能库，同时具备自己的能力与版本清单。** “最小”指规模有限、来源清楚、可验证，不是只有一个模型加聊天窗口。它们是本页种子闭环的基础数据，不必各自部署大型服务。

| 基础资产 | 回答什么 | 第一版必须预装 | 初期实现 |
|---|---|---|---|
| 知识库 | 我知道什么，证据在哪里？ | 项目定义、系统结构、接口、安装与恢复说明、模型/设备能力、主人明确偏好、已验证操作经验 | 原始资料 + SQLite 元数据/全文检索；向量检索按需 |
| 规则库 | 我可以做什么，必须遵守什么？ | G0、主人身份与权限、文件/网络/设备范围、预算、停机、发布和数据外发规则 | 受保护版本化配置与确定性执行；不能只靠检索提示词 |
| 技能库 | 我如何可靠地完成一种工作？ | 查询状态、限定目录读取、产物生成、候选构建、验证、报告等基本技能 | 不可变技能清单 + 执行器 + 测试与依赖 |
| 系统清单 | 我现在由什么组成？ | 模块/接口版本、依赖关系、数据所有者、运行位置、权限、工具链、健康探针、当前/回退发布版本 | 发布清单与模块注册表；由实际安装/运行状态核对 |

模型训练中已有知识不是本项目的事实库；对话摘要不是规则；一段建议或代码也不是已可用技能。外部 Codex 可以协助编写候选内容，但没有把候选规则自动提升为根规则的权限。

主人身份、权限引用等敏感资产只保留必要元数据或密钥库引用；不因为叫“系统知识库”就把全部凭据集中进可检索文本。

<a id="system-health-2"></a>
### 种子资产与可信等级

建议随首个版本发布 SeedBundle，绑定代码/配置/文档/技能/测试摘要和版本：

- **事实与系统说明：**当前架构图、模块职责、接口契约、数据格式、安装与恢复手册、支持矩阵。
- **主人明确设置：**名称、可用设备、目标、偏好、预算、禁区、授权范围和适用期限。
- **基本技能：**查看能力和任务状态、读取获准样例目录、写入产物区、提交改进单、运行候选构建、查询评估报告。
- **基本维护：**只读健康检查、已验证组件重启/回退配方；停止与解锁属于受保护底座，不伪装成可随意重写的普通技能。
- **基线与已知限制：**初始真实任务、恢复测试、不能做什么、失败案例、待确认事项。

知识记录至少有 kind、source、version、evidence_ref、validity、scope、owner 和 privacy。区分“原始证据、已验证事实、主人偏好、待验证假设、外部未可信资料、模拟内容、已撤回记录”。互联网学习先进入待验证区；不能覆盖主人规则，也不能把 NPC 情节当成现实经验。

规则通过受保护加载路径生效，知识检索仅用于解释。知识库损坏或检索不到 G0 时，执行器仍必须执行已经验证加载的规则；规则状态无法验证则拒绝业务。技能使用前匹配当前契约、运行依赖和授权，技能描述中自称“可信”没有准入效力。

<a id="bootstrap-3"></a>
### 种子核心图

![seed-core](diagrams/seed-core.png)

[矢量图](diagrams/seed-core.svg) · [可编辑图源](diagrams/seed-core.mmd)


这不是无限循环：没有真实改进需求时等待；预算耗尽、连续失败或收益不足时结束本次实验；确认 G0 违规时按设计文档集锁存全部自主活动。系统持续运行不要求持续消耗模型调用或不停改代码。

<a id="bootstrap-4"></a>
### 两个层次：哪些能长大，哪些不能自行放开

**受保护的根控制层：**主人身份、停止状态、权限执行、发布信任根、基线评估规则和恢复入口。Jarvis 可以提出这些实现的改进方案，但不能在自身业务权限下修改、批准并激活；由主人维护入口处理。G0 宗旨不属于可修改对象。

**可演进的工作层：**技能、工具、检索策略、人格配置、编码适配器、规划器、任务策略、模型组合，以及后期获准的运行模块。这些使用版本化包替换，不直接覆盖正在执行的生产目录。

评估器可以扩展测试；候选不能删除旧测试、降低阈值或查看受保护保留集。新评估规则也要独立审查，并保留历史结果的口径。否则系统很容易通过修改自己的评分标准获得“越来越高分”。

“底座小”是控制复杂度的目标，不是声称 OS、执行网关、授权代码和发布器不属于信任基础。

<a id="bootstrap-5"></a>
## 开发顺序与每一步的出口

| 顺序 | 我们与 Codex 先实现什么 | Jarvis 能自主做什么 | 进入下一步的证据 |
|---|---|---|---|
| K0：规范和夹具 | 初始知识/规则/技能包与系统清单；Task/Action/Capability/Artifact/Module/BuildProfile 六个契约；G0 执行边界；测试数据 | 暂无生产自主行为 | 相同输入、预期产物、失败条件已明确 |
| K1：确定性外壳 | 会话/任务取消、待命、故障恢复、SQLite 账本、受限文件能力、命令行入口 | 执行预定义本地任务、报告真实状态 | 崩溃恢复、重复请求、取消、未知结果和越权拒绝通过 |
| K2：最小个人助手与成长核心 | 个人文本会话、基础人格、可纠正记忆与接续；本地模型端口、三库检索、有限工具循环；能力缺口与改进单接入既有受限候选/验证/发布通路 | 无项目也能交流和协助；按需行动，断网使用已有能力；在约定范围完成一条需求驱动的生成、验证、启用与回退闭环 | [V-PAL](delivery-validation.md#personal-companion-validation)适用子项、[K2 最小成长](#k2-growth-core)与既有 V-K2 通过；保持身份/记忆与既有能力，坏候选被拒 |
| K3：开发协作 | 候选工作区、一个离线工具链、Codex 适配器、构建任务 | 为不会做的事提交改进单，调用编码助手产出候选 | 无生产密钥泄露、失败限额、真实构建产物 |
| K4：可扩展自主成长闭环 | 将 K2 受限通路和 K3 开发协作推广为可复用外部评估、包目录、灰度/回退与改进账本 | 为不同真实需求自动生成、验证并启用低风险新工具，超出首个预定义配方 | 通过保留测试；坏版本被拒；生产不被原地改写；新增能力有真实调用与收益证据 |
| K5：首次真正修改自身模块 | 一个可替换的检索或规划模块、兼容与回退协议 | 提出并验证自己的模块改进 | 同一任务集净收益成立、旧能力未退化、可以回退 |
| K6：逐能力扩展 | 实时语音、复杂形态、多语言、第二节点、设备与 Agent 等按需接入 | 在更多场景和设备延续同一个助手，按需求组织能力 | 各能力单独满足设计文档集验收；扩展不破坏个人核心体验 |

K1 可以暂时用假模型/规则输入验证可靠性，但它还不能叫完整智能 Jarvis；K2 形成最小个人助手与受限成长核心，基础人格、交流连续性和自主成长都不能全部推迟到后期。K3/K4 扩大开发与发布通路，K5 才包含替换自己运行模块的证据，不能把 K2 的单工具闭环等同于任意自身重写。

这张表是唯一实施顺序；[M0—M6](delivery-validation.md#delivery-gates) 仅定义能力验收门：可以在语音、界面和共同体尚不完整时，先用纯文本和本地文件任务验证 K4。不能等待整个目标架构完工才开始进化，也不能在缺少评估与恢复时就开放自修改。

编码适配、凭据隔离和改进事务详见 [外部编码协作](evolution-release.md#bootstrap-6)；净收益评估详见 [证据标准](delivery-validation.md#bootstrap-8)。

<a id="next-implementation"></a>
## 接下来具体做什么、什么时候进入下一步

**截至 2026-10-20，当前版本见[首页](README.md#project-status)；K5 0.1.79 验收见[历史记录](delivery-validation.md#k5-ranking-module-evidence)。K3 已闭环，K4 三个明确任务域闭环保持；K5 首个受限检索模块已通过模型生成、独立评估、实际切换与恢复。** 本机可独立完成的 K2 实现与验证沿用既有结果；完整 K1/K2 的物理低配机、整机断网及主人实际体验仍待原条件。K3 的实际范围、质量对照与局限统一查[K3 收口记录](delivery-validation.md#k3-closure-matrix)，当前推进 K6 个人交流与共享资料生命周期，双节点基础同步已交付；已有工具成长规则见[限定成长](evolution-release.md#bounded-growth-policy)。

本节是**当前工作顺序的唯一权威位置**。下面细分既有 K 工作包；后续指南的 F 编号只是工作项索引，不建立第二套 K/M 路线。日期较早的进度段落保留为历史，不再充当下一步队列。继续复用现有单机底座，K1 可靠性收口与 K2 个人核心增量按依赖推进。

<a id="near-term-work-queue"></a>
### 当前推进队列（更新至 0.1.87）

**2026-10-19 按主人最新要求停止重复验收，恢复向下开发。** 既有 K2 收口与待验条件保留，不降低门槛也不冒称整体验收通过。F08 的限定职责拆分已随 0.1.64 完成；按主人要求先上传该版本，再在 0.1.65 完成 F07 的候选代码、独立检查、多文件任务和外部 Codex 子集。每轮只做受影响的新改动必要检查，不重跑整套 K2、付费回答评审或离线验收。

三库、人格/相关接续和限定成长的已有证据统一见[K2 收口](delivery-validation.md#k2-completion-evidence)。物理低配机、整机断网、主人真实体验仍待条件，不阻断本轮授权的可独立开发内容。0.1.64 已交付 F08 的限定对象三职责、三用途模型/备选/档位和真实界面；完整事件调度、广泛净收益及任意自我改造仍开放。0.1.65 已通过真实两模块 Codex 任务、独立留出检查、离线重建、应用和恢复。0.1.66 已增加三类实际调用和第二种可运行构建配方。0.1.67 阶段验收修复运行能力声明与诊断，限定编码子集通过。0.1.68 已补[有界改进单交接](delivery-validation.md#coding-demand-evidence)的来源/快照/验收/预算与结果绑定；0.1.69 增加[受控离线依赖配方](toolchains.md#bounded-python-dependencies)。0.1.70 已完成包/新文件与隔离 JavaScript 场景，并通过[K3 冻结收口清单](delivery-validation.md#k3-closure-matrix)的真实任务、技能对照、故障与运行包验收。下一阶段沿用 K4 成长范围、K5 自身模块改造与 K6 多设备/Agent/形态。

| 优先安排与既有归属 | 本次应先交付的增量 | 依赖、边界与退出位置 |
|---|---|---|
| 贯穿每项：K1/W4—W6、K2/W4 | [F02 资源准入](development-guide.md#direction-resources)、[F09 离线恢复](development-guide.md#direction-offline)、[F12 依赖治理](development-guide.md#direction-architecture)随受影响通道补齐 | 先保留当前可用性；不要求完成所有未来监督设计才改普通功能。每项都核对取消、UNKNOWN、源码绑定及资源，完整出口仍按原 V-K1/V-K2 |
| 已交付首个子集：K2/W1—W3 | [F01 混合样例报告、指定取消与未开始任务修订](delivery-validation.md#mixed-report-admission-evidence) | 0.1.59有限模型/能力范围已验证；更多能力/模型、模糊指代、多行动依赖及独立人工标注仍开放，不宣布完整F01通过 |
| 已交付入口子集：K2/W1 | [F03 规则/语义候选共用核对和修订屏障](delivery-validation.md#rule-memory-review-evidence) | 0.1.60 已验证并部署；复杂同义、跨来源遗忘与完整 F03 仍开放 |
| 已交付开发先导：K2/W1—W3 | [F04 八场景最终回答对照及能力说明修正](delivery-validation.md#memory-final-answer-evidence) | 0.1.61 已部署；同一窄开发集回归，不等于独立留出或框架对比，保留措辞局限 |
| 已交付 K2 子集，更广泛验证仍开放 | [F04 扩大人物/时序/项目资料/保留历史的多轮回答对照](development-guide.md#direction-memory-quality)，并逐项完善 [F06 人格/接续](development-guide.md#direction-persona) | 来源与修订规则稳定后补检索；不再以30条公开提取同分决定框架胜负，不先换事实库。按 V-MEM/V-PAL 验收 |
| 输入适配：K2/W3 | [F05 按键录音、本地转写、编辑发送和独立播报](development-guide.md#direction-voice) | 复用已稳定的文字受理；不等待完整记忆框架/所有工具建成。接口及真实设备测试可独立准备；连续语音和自动动作另过门，遵守下节③④ |
| K3 已闭环，转入 K4 | [F07 编码协作](delivery-validation.md#k3-closure-matrix)的候选、独立检查、多文件/包、新文件、离线构建与 Codex 通路已验收 | 保留支持配方边界；后续多语言工具链按各自出口扩展，不重复开放已完成的 K3 清单 |
| 已完成限定 K4：工具成长 | 已实现[项目工具发布/复用/回退](evolution-release.md#project-tool-runtime)和[有界需求选用/缺口交接](evolution-release.md#project-tool-intents)；[检查记录](delivery-validation.md#k4-tool-intent-evidence) | 已补[契约草案/明确审阅与候选链](evolution-release.md#project-tool-contract-drafts)，0.1.75 增加[受控准入、灰度收益与退役](evolution-release.md#project-tool-lifecycle)；[证据](delivery-validation.md#k4-lifecycle-evidence)。0.1.76 增加[结构体检与无引用旧版归档](evolution-release.md#project-tool-quality-storage)；[三任务对照与检查](delivery-validation.md#k4-quality-storage-evidence)。0.1.77 新增[回执与目录容量整理](evolution-release.md#growth-ledger-maintenance)。0.1.78 补齐三个领域的[按策略连续成长](evolution-release.md#bounded-growth-policy)，[C01—05 对应证据](delivery-validation.md#k4-growth-closure-evidence)已收口；不承诺域外语义、无限存储或长期表现 |
| 当前 K6 语音/协作增量，K5 持续维护 | K5 首个受限模块已闭环；0.1.81 接入连续轮次、本地 VAD/STT、播报与受限插话。0.1.82 已补单机双职责协作；后续补真实声学与交谈质量，推进双节点能力 | 逐项见[工作清单](development-guide.md#direction-work)，按[唯一 K 阶段表](#bootstrap-5)及原出口。没有需求或前置证据时保持 proposed，不预装全部组件 |

顺序表达依赖和产品重点，不是日历承诺。单个增量的范围、产物和冻结判据应在编码前明确；如果前置能力已满足可直接复用，不重新开发，也不为了“下一版”强行跳过未解决失败。当前下一项以下节为准，旧版本演示场景保留其原证据，不再充当待办。

<a id="k4-next-delivery"></a>
#### K4/K5 已有闭环与 K6 当前工作（2026-10-20）

**0.1.78 已完成下表①—⑤的三个明确领域闭环，0.1.79 已完成 K5 首个受限模块；当前推进 K6 语音与单机协作工作包。** [收口证据](delivery-validation.md#k4-growth-closure-evidence)保留范围、费用负例与历史失败；下表是已完成 K4 的交付映射，不能再作为五项待办。 0.1.77 沿用原 SQLite/本地文件，终态回执归档后原编号仍可查询，退役目录收存可释放在线名额，恢复仍退役；[实现与限制](evolution-release.md#growth-ledger-maintenance)、[验证与部署](delivery-validation.md#k4-maintenance-evidence)分别记录。总索引、归档和整理审计仍有配额，不承诺无限成长；②—⑤现已实现并通过限定范围验证，通用业务语义与长期净收益仍未获证明。

| K4 内部顺序 | 交付目标与模块边界 | 对应收口检查 |
|---|---|---|
| ① 回执与目录容量治理 | 0.1.77 已实现只读资格预览、终态完整回执校验归档、原 ID/幂等查询及退役目录收存/恢复；满在线回执时维护独立可用。保留恢复版本和在途/未知材料；总存储配额及长期表现见证据限制 | [V-K4-C01](delivery-validation.md#k4-closure-readiness) |
| ② 独立可判定的真实需求 | 选择不同类型的真实重复工作，在生成代码前固定输入/输出、歧义澄清、来源、正常基线及独立留出；复用原契约草案和 K3 编码通路，补领域验证器。新契约仍明确审阅，不能让生成者自己定义成功 | [V-K4-C02](delivery-validation.md#k4-closure-readiness) |
| ③ 实际收益与负收益处置 | 在原改进账本记录匹配任务的正确性、干预、耗时、资源、费用与失败；区分主人反馈、客观结果和未知。补观察窗口、样本不足说明、预设阈值下暂停/回退与重新审阅，不新增常驻 LLM 检查 | [V-K4-C03](delivery-validation.md#k4-closure-readiness) |
| ④ 已授权范围内的自动准入 | 在上面证据成立的明确任务域，补版本化准入策略：允许的契约/验证器、项目作用域、预算、灰度门槛与停止条件。达标可按预先授权策略启用，域外/验收不明继续澄清或审阅；模型输出不能扩大准入范围 | [V-K4-C04](delivery-validation.md#k4-closure-readiness) |
| ⑤ 一次完整闭环验收 | 普通聊天提出需求 → 复用或发现缺口 → 独立验收 → 编码候选 → 灰度 → 使用与收益 → 坏版本拒绝/回退 → 旧材料整理；同时聊天、刷新、重启与取消不乱。汇总本阶段所有已有证据和剩余条件 | [V-K4-C05](delivery-validation.md#k4-closure-readiness) |

① 的实现入口是**只读预览**，同一工作包已接通受控整理与恢复；不能把只有一个预览按钮记为容量治理完成。归档必须保留原任务身份、幂等查询和恢复引用，未知/在途任务不得按终态处理；满额时仍须保留查询、停止与维护的可用路径。在线索引、归档材料和磁盘分别设有界预算，达到总配额明确提示维护，不承诺无限保存或靠自动删除主人资料腾空间。详细状态/API 维护于原[成长契约](contracts.md#project-tool-contract)，不在路线页另定义协议。

②③ 的案例应服务个人助手的实际用途，例如资料清单整理、笔记格式转换与重复报告；不能只用植入缺陷的旧实现制造正收益。优先复用本机 SQLite、按需 Worker 和模型路由，新增评估与整理通过适配器接入，不引入重型集群或多套常驻数据库。

**阶段出口保持原定义：**按[收口差距与判定](delivery-validation.md#k4-closure-readiness)逐项补证；仅有人审阅的流程可用，不足以关闭原 K4 的自动成长目标。可以对明确任务域给出有限范围结论，无需承诺“任意业务标准都能自主判对”。本轮 K4 证据成立，K5 已选择实际检索排序模块并完成[接口与失败回退](knowledge-learning.md#retrieval-ranking-module)。0.1.79 已完成[首个受限模块闭环](delivery-validation.md#k5-ranking-module-evidence)，不能再把模型候选、持久选择和重启回退列为未实现。K5 持续维护包括：①实际使用观察与人工反馈，②候选配额下的显式整理/恢复，③更广泛语义回归及其他模块独立验收；这些不是所有 K6 工作的前置阻塞。没有自然使用证据时不声称长期收益；不自动创建后台监控。按主人本轮要求，K6 先交付[按键语音交流](interaction-persona.md#voice-chat-plan)：录音、本地识别、可编辑转写与原会话发送、新回复播报、取消/恢复和资源验证。0.1.81 已交付[连续轮次与受限插话](delivery-validation.md#k6-continuous-voice-evidence)。0.1.82 已交付[单机两职责协作](tasks-agents.md#bounded-team-runtime)，包括独立调用、检查项、预算、取消和汇总；[证据与限制](delivery-validation.md#k6-team-evidence)单列。0.1.83 已接通[双节点共享资料卡](federation.md#shared-cards-runtime)：设备身份、配对、明确资料范围、并发/删除对账与重连，完成同机双进程验证；[证据](delivery-validation.md#k6-federation-evidence)另列。0.1.84 已完成[资料导出、归档、只读恢复与聊天副本](delivery-validation.md#k6-shared-lifecycle-evidence)，不恢复旧连接权限。0.1.85 已补[本机模型用途与可失效引用](delivery-validation.md#k6-shared-access-evidence)，包含逐卡/项目/接入方限制、子进程派发前检查及派生历史排除。0.1.86 已补[只读连接诊断与原设备地址恢复](delivery-validation.md#k6-connection-recovery-evidence)，同机独立进程和浏览器验证通过。主人暂时没有第二台设备，真实 LAN/防火墙/休眠验证另行安排，不将同机测试记作跨机通过。0.1.87 已交付[对端逐项接收与选定个人/项目事实投影](delivery-validation.md#k6-scoped-sharing-evidence)，使用同机两个独立进程完成模拟；整域复制、更多记忆类型、长期对账和真实 LAN/休眠仍待验，不把有限投影视为统一全量记忆。后续按需要扩展这些独立边界；任务共同体需独立的唯一所有权协议，不直接复制全部记忆或取得远端执行权。真实声学与交谈质量另按证据补验；再按需扩展设备与形态；不同时预装全部框架。个人记忆、伙伴连续性和前台可用性始终是回归约束。原 K1/K2 外部条件保留，不在此安排重复验收。

<a id="dialogue-upgrade-order"></a>
### K2 内优先完成文字/语音对话与工作的分离

**需求 accepted；0.1.48—0.1.49 已实现并验证第①项的回复回执、页面待发、局部停止与有限持久恢复子集；0.1.51 补模型调用进程，0.1.54 扩至普通上下文及限定后台模型路径；0.1.56 补第②项的意图影子与文档候选草稿，0.1.57 补 Flash 单项只读文档自动受理，通用自动行动仍 proposed。** [现状核对](architecture.md#dialogue-separation-audit)和[技术落点](stack-project-layout.md#dialogue-runtime-adoption)确定采用渐进改造，保留现有任务账本、记忆、模型目录和 Qwen。顺序属于既有工作包的内部增量，不另建 K/M 时间线。

| 顺序与归属 | 可交付的具体结果 | 进入下一项的条件 |
|---|---|---|
| ① K2/W3＋W4：统一受理和隔离基础 | 服务端 Turn/事件/局部取消；前端移除全局忙碌封锁，仍有有界输入箱；旧任务/技能/成长入口只转交同一受理服务；接口稳定后移出 Dialogue Worker 完成 R07 进程边界 | 慢任务和慢模型下继续接收文字，能独立停止；重复请求、旧回复和重启不重做任务；仅逻辑隔离时不得宣称 R07 完成 |
| ② K2/W1＋W2：自动判断与真实受理 | 多意图结构化结果，真实能力目录校验，澄清和行动分支分离；先影子评估再启用已覆盖范围 | 否定/引述/假设不误执行，混合需求既回应又产生实际回执，任务上下文不夹带无关私人交流 |
| ③ K2/W3 的输入/输出适配 | 按键录音、本地 STT、可编辑最终转写；复用文字入口与 Qwen 短段播报 | 麦克风失败可打字，中文/英文可用；工作、朗读、输入独立取消；实测内存和首声 |
| ④ K2/W3＋W4 的连续交流增量 | 显式开启连续语音、VAD/轮次、AEC 验证、说话打断、句间情绪；CPU/GPU/配额公平调度 | 通过真实房间音频及负载测试，只有有效代际能播放，后台工作仍有进展 |

当前已有[回执/待发](delivery-validation.md#dialogue-receipt-evidence)、[普通会话持久恢复](delivery-validation.md#dialogue-recovery-evidence)和[上下文与后台模型分槽](delivery-validation.md#conversation-lanes-evidence)。第①项已补普通上下文阶段超时和目录/技能/解释规划进程；仍需核对维护与网页规划路径、完整 WorkAdmission 和压力公平性。第②项已完成[200 条新合成样例的分集评测与限定受理](delivery-validation.md#dialogue-intent-shadow-evidence)：40 条校准、160 条留出，Flash 单项只读文档查询已有真实任务闭环，0.1.59进一步完成[混合样例报告子集](delivery-validation.md#mixed-report-admission-evidence)，独立人工标注、更多工具/模型、模糊指代和多行动依赖仍待补齐。0.1.81 已验证按键与连续轮次的限定链路；整个 R07、物理全双工语音与资源公平调度仍未验收，不能把待发队列视为已经理解连续补充。

完整 M2 语音体验和 K6 多设备验收归属不变；本轮提出的单机语音增量可先沿已有 K2 入口实施，不必等 NPC、完整 Agent 工厂或共同体。按步骤验证后再默认启用相应能力，阶段性仍允许文字或按键模式。每个增量采用功能开关/适配器与故障降级；撤回新路由不影响既有已入账任务。验收统一见[分离与并行验收](delivery-validation.md#conversation-separation-validation)，不以生成文件数量、模型自评分或异步函数数量判定完成。

<a id="k2-growth-core"></a>
### K2 内的最小自主进化核心

**产品要求 accepted；0.1.41 已实现已知配方的需求接线，完整体验验证仍未通过。** 复用当前 evolution-v1 的候选生成、独立验收、不可变发布和回退机制，不另建第二套进化器；当前[会话需求适配器](evolution-release.md#demand-growth-runtime)将已核验报告、改进单和实际交付连接起来，但不等于下述完整核心已实现。

K2/W1 提供真实能力清单与既有改进经验；W2 将主人需求或已观测失败形成带范围、预算和完成条件的改进单，先判断已有能力是否可用；W3 让普通个人会话能查询成长进度、继续聊天，并在发布后调用新能力；W4 验证无网络/资源不足时保留旧能力、延期研发和可恢复状态。只在已有授权的低风险范围内自动推进，缺少信息或条件时明确说明，不制造无意义的进化任务。

首条链允许选择一个范围有限、验收可独立给出的工具或技能：需求 → 缺口 → 候选 → 测试 → 启用 → 实际调用 → 收益记录，失败拒绝或回退。当前 `inventory-export` 可用于技术接线，但因宿主已有完整答案，单凭该演示不能证明新增未知能力；仍需[V-PAL-10](delivery-validation.md#personal-companion-validation)的真实需求前后对照。三能力分工和模型路由继续遵守[成长中心](evolution-release.md#growth-governance)，K3—K5 负责扩大范围，不把完整通用自改当作 K2 的隐含承诺。

**截至 0.1.37，固定报告、会话任务关联和本地模型的封闭外联流程验证已经接通，K1 各工作包已有可运行子集，K2/W1 的事实记忆、跨项目词法联合查询与种子状态入口、W3 的会话归档也已提前实现；K1 和 K2 均未整体验收。** 按个人使用范围继续完成离线、资源与整体验收；监督身份、认证和全局停止延期，不重新作为个人功能推进的前置条件。0.1.37 已补[确定性计算](#calculator-entry)、有界原生技能与限定成长闭环，当前已补 [K3—K4 限定成长子集](#evolution-loop-entry)；剩余关键缺口为通用模型答案可靠性、普通 PC 长时资源、通用技能执行绑定、整机离线，以及更多模块的开发与发布验收。工作包编号仅细分上面的 K 阶段；不另设按版本或日期推进的路线。

<a id="progress-audit-2026-10-16"></a>
### 历史进度核对与优先事项（2026-10-16）

**历史快照，非当前队列。** 2026-10-19 的推进选择以[当前推进队列](#near-term-work-queue)为准，下述原始版本范围及先后理由保留。

本次对照权威文档、运行代码、分版本报告和本机 `/api/status`：该次核对时源码与运行实例均为 **0.1.27**，网页及核心就绪。定位是**已有记忆和项目资料的本机助手工作台，正在补齐可执行的最小智能核心**。现有能力与限制只在[当前实现表](#current-implementation)维护；K0 已有种子与夹具证据，不能由此推导 K1—K6 全部完成，也不按文档篇幅估计完成百分比。

下一轮按依赖推进，不重复开发已有文件编辑或会话保存：

1. **K1/W6 收口已有底座。** 将现有故障、取消、恢复、资源和运行包证据按[当前适用出口](delivery-validation.md#next-k1-acceptance)逐项归集，补齐目标机器的断网冷启动、故障点及并行时延缺口；对延期项明确标记延期。核对测试所对应的源码摘要和实际运行包，不能把旧版本局部测试直接算作新版本全量通过。
2. **K2/W1 接通真实能力入口。**（0.1.28 已完成种子状态与监控覆盖修复，正文检索、技能执行仍待接入。） 读取有效系统清单、种子知识与已发布技能，区分“已登记、可执行、不可用、仅规划”；修正[模块观察的记忆覆盖缺口](health-maintenance.md#module-monitoring)。MCP 已有分类登记与选用偏好，协议握手、工具发现和实际调用仍需实现；十项原生技能的有界指导/报告已接通，完整通用技能加载与任意执行仍未实现。首个闭环优先使用已有固定 Worker，不依赖接入所有扩展。
3. **K2/W2 交付一条完整自然语言任务。**（0.1.30 的固定目录报告实验已有真实云端规划、Worker 和回执证据；0.1.31 已提供明确的会话任务入口，通用调用待接入。） 使用[下述样例](#next-k2-work)，把模型候选计划、参数检查、任务账本、执行回执和产物核验接通；未知工具、越界路径、循环计划必须有限结束。验收看真实文件与确定性检查，不能只看模型回答“完成”。
4. **K2/W3—W4 验证可持续使用。** 已有会话归档和后台队列继续复用，0.1.31 已补查询/取消与产物关联；0.1.32 已取得本地小模型固定流程证据；0.1.34 已补[并行运行/资源与四点中断测试](delivery-validation.md#parallel-runtime-evidence)，0.1.37 已将完整纯算式分流至本地精确计算；继续补目标普通 PC 的长时指标、整机断网与完整失败恢复。云端切换或超时不得重复已经执行的动作；入口见[K2 出口](delivery-validation.md#next-k2-acceptance)。

K2 闭环成立后，才按[唯一阶段表](#bootstrap-5)进入 K3 候选工作区、一个离线工具链与外部 Codex 协作，再做 K4 新技能生成/验证/发布、K5 模块改进与回退。2026-10-17 主人要求现在贯通闭环，已按现有固定任务前置通路接通 [evolution-v1 限定子集](#evolution-loop-entry)：模型生成、隔离验收、工具发布、运行自检与回退。完整 K 门和外部 Codex 适配尚未通过；候选运行包准备仍不等于任意模块热升级。

完整实时语音与主人声纹认证、按任务动态生成/部署多个 Agent、跨设备离线自治与重连合并、持续学习和知识库自动重构、人格/NPC 世界、模型组件自动更换及自主自愈仍属于后续设计。现有语音诊断、双聊天并发和独立本机实例分别只是前置能力，不是上述系统的验收证据。继续遵守[普通 PC 优先](stack-project-layout.md#technology-selection-4)，本轮不因补闭环引入 K8s、集群消息系统或多个 Agent 框架。

本次验证范围见[进度核对证据](delivery-validation.md#progress-audit-evidence)；历史版本章节里的未完成项是当时快照，判断当前状态应以上述实现表和最新证据为准。

<a id="next-k1-work"></a>
### K1：先交付可控、可恢复的单机执行底座

| 工作包 | 具体交付与用户可见结果 | 依赖与验收入口 |
|---|---|---|
| K1/W1 运行边界与预检 | **0.1.5 已实现诊断增量**：本进程身份、路径/ACL 元数据、依赖/版本、端口、源码摘要与边界缺口；有效权限尚待真实 Worker 测试 | [当前使用](#runtime-preflight)、[本轮证据](delivery-validation.md#preflight-evidence)；完整 [V-K1-01](delivery-validation.md#v-k1-01) 仍待受保护部署后验收 |
| K1/W2 会话取消与旧版兼容 | **0.1.14 当前个人范围**：停止本次回复、助手待命、另一会话/后台任务继续；无恢复密钥/密码，旧停止数据显式迁移并保留审计 | [实际使用](#runtime-control)、[当前证据](delivery-validation.md#personal-lifecycle-evidence)；V-K1-02 原全局监督项延期，[V-K1-03](delivery-validation.md#v-k1-03) 按最新范围验证 |
| K1/W3 隔离执行器 | 原生 LPAC/Job、只读输入、有界管道、回复绑定、超限终止；0.1.13 增加登记元数据 Worker 崩溃回收；0.1.15 增加登记浏览器 profile 回收；受保护 Host 和通用工具范围延期/待实现 | [当前实现](#runtime-worker)、[新增验证](delivery-validation.md#k1-progress-evidence)；完整 [V-K1-04](delivery-validation.md#v-k1-04) 不因子集通过而关闭 |
| K1/W4 后台队列与真实状态 | 0.1.13 共用持久 FIFO；0.1.16 增加内存准入与等待；按用户要求在 0.1.18 提前加入轻量托盘，显示真实状态并提供明确退出；完整 CPU/GPU/模型统一调度仍待实施 | W3；复用现有账本；[V-K1-05](delivery-validation.md#v-k1-05)、[V-K1-06](delivery-validation.md#v-k1-06)、[托盘证据](delivery-validation.md#tray-evidence) |
| K1/W5 可恢复运行包 | 0.1.15 安装、健康检查、事务化版本选择、显式启动与回退；已验证跨代码版本共用 v2 数据不丢任务；0.1.17 增加显式启动时一次健康回退；整机断网、数据库迁移和运行中故障恢复待验/待实现 | [候选包使用](#runtime-package)、[状态迁移](evolution-release.md#service-continuity-4)；[V-K1-07](delivery-validation.md#v-k1-07) 尚未完整通过 |
| K1/W6 整体验收 | 交付本机权限证据、故障矩阵结果、恢复说明和一次可复现演示；界面显示真实执行阶段、产物与未知状态 | 前述工作包及既有核心回归通过；[K1 出口](delivery-validation.md#next-k1-acceptance)仍待完成；当前 K2/W2 仅复用固定范围做实验，通用调用继续以完整出口为前提 |

W1 已包含预检、角色声明和诊断报告；W2 当前采用[个人生命周期](interaction-persona.md#personal-assistant-lifecycle)。此前非提升令牌、exFAT 卷与受保护身份缺失属于延期的部署增强项，不再要求用户登记公钥或密码。继续完成离线、资源与本机任务可靠性总体验收；保留已有 Worker 执行方式和历史验证，未完成的功能不因范围修订而自动记为通过。

已有 Python/SQLite 业务代码、原生模型适配和网页继续复用。小型底座的语言按已登记候选实测冻结；不为接一个 Worker 就整体重写、不同时引入多个任务框架。状态/取消/停止路径不等待 LLM 或后台任务完成。

K1/W3—W5 按[普通 PC 优先规则](stack-project-layout.md#technology-selection-4)实施：W3 先验证一个原生受限 Worker，W4 在现有账本上实现本机队列，W5 打包当前必需依赖和恢复材料。不得为了这三项引入容器编排、消息集群或全套研发环境。隔离证据不足时保留受限能力边界，不能用“轻量”放宽权限验收；资源开销同时按[PC 验收](delivery-validation.md#pc-footprint)记录。

<a id="next-k2-work"></a>
### K2：再把“聊天”接到“做事”

| 工作包 | 具体交付与用户可见结果 | 依赖与验收入口 |
|---|---|---|
| K2/W1 三库运行入口 | **0.1.62 已补三库正文查询、版本/来源和历史种子冲突说明、损坏派生索引重建、相关事实及话题推荐**；复用已有个人记忆、项目资料、撤回/纠正和外发过滤；规则由宿主独立执行 | K1 适用基础；[首期知识与记忆范围](knowledge-learning.md#initial-runtime-memory)、[V-K2-01](delivery-validation.md#v-k2-01)；本轮证据统一见下文链接 |
| K2/W2 有限计划与技能调用 | 已接普通对话的限定文档/报告任务、真实 Worker 产物、查询/取消及已有受限成长交付；**0.1.62 复验计划拒绝、实际任务与候选启用/回退**；不支持的请求说明缺口 | W1；[任务执行闭环](tasks-agents.md#initial-task-loop)、[V-K2-02](delivery-validation.md#v-k2-02) |
| K2/W3 个人会话与任务接续 | **0.1.62 已补称呼和完整交流配置界面、来源可见的相关话题、纠正/遗忘后的回答对照，以及争用时的独立查询/取消**；保留会话归档、临时排除和真实任务接续；主人体验、普通设备仍需实际验收 | 个人交流复用 W1，任务依赖 W2；[V-PAL](delivery-validation.md#personal-companion-validation)、[V-K2-03](delivery-validation.md#v-k2-03)、[V-K2-04](delivery-validation.md#v-k2-04) |
| K2/W4 离线与失败收口 | **0.1.62 已复验应用隔离下小模型任务、无模型/资源不足降级、七个真实退出点、兼容运行包和启动回退**；已准备整机断网脚本，物理低配机不可用；未完成项保留原门槛 | W3；[V-K2-05](delivery-validation.md#v-k2-05)、[V-K2-06](delivery-validation.md#v-k2-06) |

这四个工作包属于一次完整 K2 交付，不能逐包要求主人重新发起。当前逐项结论、原始证据和外部阻塞只在 [0.1.62 K2 收口记录](delivery-validation.md#k2-completion-evidence)维护；以下较早的记忆选型记录保留来由，不作为另一条推进队列。

首个自然语言任务“列出样例目录的文件，按类型统计并保存结果”已在 0.1.30 通过云端规划与固定 Worker 的子集验证，见[当前使用](#sample-task-entry)。这个演示证明规划与执行连通，不称为自主生成新技能。资料外发、持久聊天和主人偏好分别设置范围；当前允许云端聊天不自动扩大到读取并上传整份知识库。

K2/W1 按[知识与记忆开源选型](stack-project-layout.md#memory-open-source)复用本地事实与中文检索，补个人偏好、经历和明确记忆操作，保留来源、修订、域和删除字段；向量后端是增量试验，不阻塞确定性知识入口。K2/W3 已有基础持久表达与明确话题接续，继续完善自动相关性、真实任务引用与按需协助，不以先完成项目编辑器、语音或 Agent 工厂为依赖。依据[V-PAL](delivery-validation.md#personal-companion-validation)和[V-MEM](delivery-validation.md#memory-selection-evaluation)冻结配置；K5 再验证检索替换，实际多节点同步仍在 K6，不能把预留事件字段当作共同体已经实现。

W1 内按依赖完成三个可演示增量：① 在现有会话归档旁增加事实存储，让“记住/纠正/忘记”及临时会话排除成立；② 加入项目目录、MemoryView 和中文词项检索，证明切换项目仍记得通用偏好、跨项目比较有来源且无越域；③ 补齐候选事实来源链后，用相同样例比较 LangMem / Mem0 提取和可选 embedding，仅接入有增益的组件。第一版不依赖完整知识图或另一个 Agent 运行时。① 已在 0.1.25 实现并验证，范围见[明确事实运行语义](knowledge-learning.md#explicit-memory-runtime)，不代表普通消息到事实的完整来源链已经实现；0.1.26 进一步提供②中的[单项目文档与段落来源检索](knowledge-learning.md#project-retrieval-runtime)，0.1.33 已补[有界跨项目 MemoryView](knowledge-learning.md#memory-view-runtime)。完整域/版本视图、语义检索、自动提取和源码知识编纂仍未完成。

**2026-10-18 记忆方向的下一步：**0.1.44 已补本次新候选事实的原文定位、来源失效和同源纠正/遗忘保护，范围见[来源闭环](knowledge-learning.md#candidate-fact-provenance)及[验证记录](delivery-validation.md#memory-provenance-evidence)。接下来在 K2/W1 按[综合推荐](stack-project-layout.md#memory-recommended-plan)，0.1.47 已落地[事实分类与主人日常/工作用途](knowledge-learning.md#memory-domain-runtime)及相关混合来源测试；继续补[完整输出范围与派生依赖契约](contracts.md#memory-view-contract)及其[组合防串用样例](delivery-validation.md#memory-domain-validation)，0.1.50 已接通[按需结构化 LLM 事实候选基线](knowledge-learning.md#semantic-candidates-runtime)，0.1.52 已完成[30 条公开先导样例与边界修复](delivery-validation.md#memory-extraction-pilot-evidence)，新增 [LangMem 隔离影子适配与对照](delivery-validation.md#memory-langmem-shadow-evidence)，仅在实验进程生成候选，生产仍使用现有基线。现已补[12 组多轮回放与旧语义预览修订屏障](delivery-validation.md#memory-lifecycle-evidence)，修复主人纠正/遗忘后另一来源的待确认旧预览迟到写入，并完成临时数据和界面验证；这不是语义自动合并。现已接通 [Mem0 公共 SDK 的隔离实验](delivery-validation.md#memory-mem0-shadow-evidence)，可复跑同一批公开单条样例，并观察重复、偏好变化、作用域和删除后消息历史；未接管正式事实。2026-10-19 已在工作树完成[本地重复与差异核对、显式沿用/替代](delivery-validation.md#memory-candidate-review-evidence)，补入纠正猜测反例，临时数据与真实界面验证通过，并已随 0.1.58 统一部署；提示使用有限词项，不是通用语义裁决。接下来先补独立多轮留出、复杂转述与规则入口的一致性，再按收益引入中文混合召回，进入 W3 的相关经历接续；不自动改写主人画像。LLM Wiki/OpenWiki 先用于一组明确资料的增量编纂，不要求先建全库 Wiki。MemPalace 的原文组织、LightMem 的后台批次整理和 EverOS 的可读导出仅按真实缺口逐项吸收，不在这一步整体更换存储或安装全部框架。实现归属见[模块映射](stack-project-layout.md#memory-module-adoption)，现状和迁移限制见[记忆改造](knowledge-learning.md#memory-current-gap)，验收仍使用既有 V-MEM / V-PAL。

OpenWiki 借鉴的项目知识编纂接到 K2/W1 的资料入口，并在 K3 源码/测试协作时完善增量更新；不另起一套文档树或定时任务。K5 比较和替换索引/提取/编纂实现；K6 再验证双节点、断网、纠正冲突、删除传播与任务唯一执行。模块边界见[OpenWiki 对照](stack-project-layout.md#openwiki-adoption)，出口继续使用既有 V-MEM / K 阶段验收。

<a id="skills-adoption-stage-map"></a>
### 统一技能管理、编程包与科普能力的阶段归属

**2026-10-17 accepted：先纳入正式设计和验收，按已有 K 阶段实现。** [统一技能管理](tasks-agents.md#skill-selection-policy)覆盖内置、Matt Pocock 全部候选和 [Anatomy](stack-project-layout.md#anatomy-integration-choice)，不创建独立实施时间线。0.1.36 已交付下列 K2 的原生有界子集；完整通用导入、编码执行与自由动画能力仍待后续验收，不能把来源评估写成完整实现。

- **K2/W1** 增加 SkillDescriptor、逐项适用/排除规则、auto/manual/disabled 与作用域、完整包摘要、按需加载和依赖状态；先通过 [V-SKL](delivery-validation.md#skill-selection-validation) 的选择与不误调用子集。编程包首批四项及 Anatomy 规则分别绑定同一目录，冻结种子不因导入候选而改写。
- **K2/W2—W4** 复用既有账本、预算和取消，接入已审查的固定科普模板与类型化参数执行器、隔离预览和产物核验；须先证明该执行器的真实进程/文件边界，固定 Python 组装器复用原 LPAC/Job 边界，浏览器运行已固定的绘图库；本机 Node LPAC 启动返回 DLL 初始化错误，未放宽隔离。完成交互产物对应 [V-ANI](delivery-validation.md#anatomy-validation)，缺条件保持不可执行。不能用这个增量提前开放任意生成代码。
- **K3** 接通一个 CodingProvider 或等价受控候选执行器后，完成排错/TDD/模块设计/审阅的真实编程闭环，并支持 Anatomy 新场景生成 JS 的候选构建与验证；关联[编程质量对照](delivery-validation.md#coding-skills-evaluation-plan)和原构建/隔离验收。
- **K4—K5** 新技能生成、扩大自动选择范围和包升级走统一准入、保留样本、发布与回退；科普时间轴、配音/字幕和视频编码能力具备相应执行器后单独验收 V-ANI-07，不把交互 HTML 当作视频完成。

K6 仍负责实际多节点/团队协作；`implement-spec`、实验协调技能等须待对应能力验收，不能由包内文字模拟完成。模型选择继续由[模型章](models-offline.md#coding-skills-model-snapshot)管理，本轮不改实时路由、不发起付费对照。

0.1.45 已实现 [REA 软件解析](stack-project-layout.md#rea-integration-choice)的 JavaScript 目录子集，真实浏览器样例闭环通过，完整格式覆盖与阶段出口不因此通过。其短技能入口、目标选择和依赖状态对应 K2/W1；固定版本只读 CLI、证据产物、取消与资源边界对应 K2/W2—W4，当前通过范围及剩余项见[专项准入](delivery-validation.md#rea-review-evidence)。原生 provider 按已验证格式逐项扩展，基于分析结果的任意软件重新实现仍归 K3 CodingProvider；后续 MCP 会话复用同一能力，不新增一条开发时间线。

0.1.46 已解决[效果补测](delivery-validation.md#rea-effectiveness-evidence)发现的发布目录选择与证据交付瓶颈，完成[改进验证](delivery-validation.md#rea-improvement-evidence)；0.1.47 进一步接入 ASAR 文本快照、来源核对和字面关注项，证据见[包与关注项验收](delivery-validation.md#rea-asar-focus-evidence)；本轮带引用的中文解释、右侧报告工作区与统一设置继续落在 K2/W1—W4，验证见[解释与工作区验收](delivery-validation.md#rea-explanation-workspace-evidence)；其他格式扩展仍待接入。具体收益证据与取舍只在[技术选型](stack-project-layout.md#rea-effectiveness-improvement)维护；功能重新实现仍待 K3 的独立验收。

<a id="grok-adoption-stage-map"></a>
### Grok Build 借鉴项怎样进入既有工作包

本轮是源码研究与 proposed 设计修订，没有运行外部编码器或提前开放 Shell。完整比较见[技术选型](stack-project-layout.md#grok-build-comparison)，不得把 79 个 workspace 成员整体列为 Jarvis 默认依赖。这里仅将新增细化项映射到已有阶段，不建立第二条路线。

| 既有工作包 | 借鉴后补充的交付 | 退出依据 |
|---|---|---|
| K1/W6 | 保持单机队列/取消/恢复基线，完成现有离线与资源验证 | 原 K1 出口；本轮不会因新增设计而关闭缺项 |
| K2/W1 | 三库入口增加受限技能发现；FTS 基线保持，Grok 的切片/混合召回只作可选算法对照 | 原 V-K2-01、V-MEM；来源、中文、撤回和外发检查仍有效 |
| K2/W2 | 先交付统一工具意图与进度/终态映射，再接有界计划；增加 ContextAssembler，保留任务关键状态与上下文来源 | 原 V-K2-02/06，加 V-OSS-01/02；第一个任务仍是样例目录统计，不提前改为通用 Shell |
| K2/W3—W4 | 会话事件、作用域取消与恢复；压缩失败或断网使用确定性上下文，不无限重试 | 原 V-K2-03—06，加 V-OSS-03；临时/保存会话边界不变 |
| K3 | 在 Codex/Grok 候选中先验证一个 CodingProvider，按需进程、候选工作区和补丁产物；完整 Grok 属可选实现 | 既有工具链/构建验收，加 V-OSS-04—08；无真实适配器不得称编码协作已实现 |
| K4—K5 | 独立验收与发布回退后，再试验检索/上下文模块替换并比较净收益 | 原进化、兼容与恢复验收；代码回退不充当任务或系统版本恢复 |
| K6 | 参考子 Agent 角色与父子生命周期，接既有资源租约；跨设备仍走 federation | 原动态团队/多设备验收；不以单机 leader 或 depth=1 子 Agent 代替共同体 |

0.1.23 已提前完成无执行副作用的[上下文装配子集](contracts.md#context-assembly-current)，只保留用户显式固定的要求；尚未保证任意历史中的隐含约束不会遗失，也没有自动摘要。这个聊天基础增量不关闭 K1 出口或提前开放通用工具循环。继续优先解决“受限计划能调用真实工具、长任务不会靠裁剪遗忘约束”这两个缺口；不先建设插件市场、另一个 TUI 或全自动互联网学习系统。是否引入每个外部组件，继续使用[普通 PC 准入规则](stack-project-layout.md#technology-selection-4)。

<a id="workbench-stage-map"></a>
### 工作台设计怎样进入既有阶段

按用户本轮要求，**先完善类 Codex 的通用工作台，再逐步接入 Jarvis 专属能力**。布局、输入框、设置与标识只在[交互章](interaction-persona.md#desktop-workbench)维护；这里把交付落在已有 K 阶段，不新增第二条开发时间线。界面可提前设计和做无副作用的交互验证，真实执行仍须满足所在阶段前置出口。

| 既有阶段/工作包 | 工作台交付范围 | 相应验证 |
|---|---|---|
| K0 设计与夹具 | 本轮形成布局、目录流程、输入控件、设置、品牌候选和异常场景；均为 proposed | 文档/来源核查；[V-UI](delivery-validation.md#workbench-validation)只登记为待验收 |
| K1/W4、W6 | 在现有网页完善任务队列、真实状态、断联/会话取消和持续待命；保留现有聊天/模型菜单 | K1 原有出口及 V-UI-07/08/13 的相应子集，不能提前宣称通用目录工具已开放 |
| K2/W1—W3 | 默认个人会话、基础人格与记忆接续；按需选择文件夹、项目与会话、文件搜索和引用、保存会话、输入框、产物与任务详情；基础设置复用现有服务 | V-PAL 适用子项与 V-UI-01—10、13—16；完整能力依赖 K1/K2 出口，缺项记录为待验 |
| K2/W4 | 离线能力与模型回退可见，故障后草稿/会话/任务各自恢复 | V-UI-11 及既有离线验收；不是只展示一个“离线”标签 |
| K3—K5 | Git 工作树、终端/构建、候选差异、评估、发布与回退面板 | V-UI-09/12、原有构建/进化验收；非 Git 项目继续正常使用，不自动初始化 Git |
| K6 按能力扩展 | 实时语音、人格形态、多设备、动态团队、NPC；必要时加入完整桌面壳。轻量托盘已按用户要求纳入 K1/W4，不据此跳过后续门 | V-UI-10/12/14 及各领域验收；只启用已实现和可配置的能力 |

通用工作台完成前可预留专属入口和数据展示位置，但不先堆满不可用开关。完整浏览器、多格式编辑和桌面集成按实际适配器增量加入；先沿用一套网页，桌面宿主取舍见[技术栈](stack-project-layout.md#workbench-host-choice)。0.1.11 已落地[项目文件夹与文本保存子集](#project-workspace-entry)，不新增自主执行权或替换运行图标；完整工作台按该表继续推进。

<a id="section-0f6c7791761e"></a>
### K3—K6 什么时候开始

- **K3：K2 限定任务闭环通过后。** 实现一个 CodingProvider 和一个可离线重建小工具的工具链，交付候选补丁、真实构建包与外部验收记录。Codex 可离线等待；在它未接通之前仍可用假适配器验证协议，不把假输出计为协作成功。
- **K4：K3 能稳定产出隔离候选后。** 完成[首个成长演示](#bootstrap-9)，让 Jarvis 自动开发、检验并采用一个原来没有的低风险工具；坏候选被拒、回退有效，才扩大自动研发范围。
- **K5：K4 的发布与回退经验证后。** 只先替换一个检索模块，用相同数据和冻结查询集证明净收益，再讨论规划器或内部结构改造；不把新增模型或改人格当成内核进化。
- **K6：按需求和单项证据逐步加入。** 语音、第二节点、动态团队、NPC 世界分别验收；独立的诊断和设计可提前准备，但不能因此跳过真实权限、任务所有权或停止门禁。

不把阶段写成“过几天必然完成”：当前没有完整权限隔离和离线运行包构建的实测工期。每个工作包完成后记录实际投入、返工和未解问题，再更新剩余估算。是否继续由出口证据决定，不以新增文档数量、模型数量或自评分决定。表中未实现部分仍为设计；当前已有一个显式启用、限定对象的进程内成长观察器，范围见[成长入口](#evolution-loop-entry)，其他自主后台能力仍未实现。

<a id="bootstrap-implementation-boundaries"></a>
## 实施边界与成长演示

<a id="system-health-3"></a>
### 每次成长的共同约束

K0 准备 SeedBundle、契约、规则与夹具；详细开发出口只维护于本页 K0—K6 表。每次成长同步维护代码、知识、规则兼容性和技能目录。初期只准备首个任务所需的完整离线生态，多语言工具链按可验收改进扩展。

外部 Codex 可以作为可替换 CodingProvider。[S54](references.md#s54)[S55](references.md#s55) 所有候选经过同一独立构建评估流程，不改变离线运行能力或本地规则。
<a id="bootstrap-9"></a>
### 第一个应该做的演示

**让 Jarvis 在已有目录清单能力上，自行补齐“清单转 Markdown/CSV 报告工具”，随后改进自己的一个检索模块。**

0.1.4 已有目录清单实现，不能把重新调用它当成自主成长。首个新工具只消费已有清单产物，在获准产物区生成报告，避免为了演示开放任意文件读取。

第一段验证能力扩展：

- 用户要求把已生成的样例目录清单整理为按文件类型统计的 Markdown/CSV 报告。
- 初始核心已能生成结构化清单，但尚未安装这个报告转换工具；演示前记录能力目录和包摘要，证明缺口真实存在。
- Jarvis 生成改进单，Codex 或本地编码模型编写候选工具。
- 测试覆盖空清单、中文文件名、引号/换行和公式型文件名的文本转义、无效输入、权限拒绝、取消、重复执行、输出可重复，以及目录边界/链接路径。
- 工具只读取获准清单产物，在新的产物位置输出；不覆盖源文件，也不发送网络请求。
- 独立验收通过后注册能力并完成原任务；坏候选被拒绝并记录。

第二段验证自身模块迭代：

- 用冻结的检索查询集发现当前排序不足。
- Jarvis 修改独立检索适配器，保留数据接口和原始资料。
- 对照验证检索质量、延迟、内存和已支持任务；收益成立才灰度切换。
- 注入一个错误版本并验证回退；评估器和发布器自身不被候选修改。

这两个演示分别证明“能为自己造工具”和“能修改自己的工作模块”。不能仅用聊天声称学会了、生成了一段代码或换了人格名称来证明自主进化。

<a id="bootstrap-10"></a>
### 首期目录子集

所有目录沿用 [唯一源码树](stack-project-layout.md#project-structure-1)，不另建 jarvis-seed 仓库或第二套核心。

| 首期职责 | 正式目录 |
|---|---|
| 六类契约与种子 | contracts/、seed/ |
| 根控制、恢复 | runtime/sovereignty-supervisor/、runtime/recovery-cli/、modules/core/identity-policy/ |
| 任务、动作、能力 | modules/core/goal-task-runtime/、action-gateway/、capability-registry/ |
| 成长与版本 | modules/intelligence/evolution-lab/、modules/core/release-controller/ |
| 模型与编码 | adapters/models/llamacpp/、adapters/coding/{codex,local}/ |
| 执行、构建和独立验证 | runtime/worker-host/、build-runner/、verification-runner/ |
| 文本入口与工具链 | apps/cli/、toolchains/ |
| 验收 | tests/、evals/；保留集另设保护权限 |

参考实现从 Python 业务宿主与 Worker、小型 Rust 监督/恢复、SQLite 和 CLI 起步。熟悉 Go/.NET 的团队可以替换实现语言，不能换掉状态与权限契约。首个完整离线工具链足以启动成长闭环，多语言通过后续可验收改进加入。

<a id="bootstrap-11"></a>
### 什么时候算“核心已经有了”

个人助手核心首先按 K2 和[V-PAL 的适用场景](delivery-validation.md#personal-companion-validation)判断：能无项目交流、保存和纠正适用记忆、接续交流并按需行动。以下另列**交给自主成长循环之前**的附加条件，仍需同时满足；它们不能代替个人助手体验，也不是首次使用的前置条件：

- 断网可启动、处理至少一个自然语言本地任务，停止入口独立有效。
- 工作进程崩溃后任务仍在，现实效果不因重试被盲目重复。
- 未验证代码无法绕过目录、网络、设备和凭据边界。
- 能从改进单产生一个真实包，独立验收并采用，坏包被拒。
- 有真实版本、评估证据、失败记录与可执行的回退路径。
- Codex 不在线时仍能使用已有能力，不把外部编码服务当作唯一生命线。

完成之后，才逐步扩大它自己负责的开发范围。核心的价值在于持续服务主人；每一次新增能力都应保持这种连续性，并能被执行、验证、停止和恢复。

<a id="delivery-gates-1"></a>
### 第一版必须保留的扩展点

即使第一版功能少，也必须有契约版本、技能清单、模型适配、任务检查点、动作账本、模块生命周期与恢复入口。否则后期“给自己升级”会演变为重写整套系统。

<a id="critical-review-9"></a>
### 首期实施应更小，但不能删除必需边界

首期冻结 Task、Action、Artifact、Capability、Module、BuildProfile 六类契约。保留独立监督、动作网关、输出/外发检查与候选隔离；业务模块先同宿主，进化与模型 Worker 按需运行。

首个完整验证链按 K0—K6 逐步覆盖：断网文字任务与本地查询 → 动作提交/回执故障注入 → 自编低风险工具的验收、发布与回退 → 自身检索模块对照 → 第二语言实现 → 第二节点自治与对账。语音、跨语言与共同体属于后续扩展出口，不是 K4 的前置条件。

动态 Agent 从可解释的小团队开始，NPC 从少量角色验证世界状态。自动改核心拓扑、自动换数据库、大规模多模态人格等待基础闭环稳定。

<a id="product-definition-8"></a>
### 核心先行、外部协作、持续评估

先建立最小种子，再在已有授权内组织后续开发。下列 K0—K6 是唯一实施顺序；能力验收门另见 [验收文档](delivery-validation.md#delivery-gates)。Codex 是可替换的开发提供者，日常运行与恢复不依赖其在线。

<!-- book-footer:start -->
[返回全书目录](README.md#book-tree) · [上一章：NPC 小镇与虚拟世界](simulation.md) · [下一章：后续方向指南：现状、缺口与优化工作清单](development-guide.md)
<!-- book-footer:end -->
