# 后续方向指南：现状、缺口与优化工作清单

> 文档 ID：docs-development-guide｜分析基线：v0.1.58；增量更新至 v0.1.77，2026-10-20｜状态：现状为代码/既有证据复核，后续建议 proposed。
> 本章独占维护跨主题缺口清单与优化建议；K0—K6、阶段内推进顺序仍归[核心路线](core-bootstrap.md#next-implementation)，正式通过条件仍归[验收章](delivery-validation.md#next-k1-acceptance)。这里没有第二套开发时间线，也不宣布完整 K1/K2 已通过。

<!-- book-nav:start -->
[全书目录](README.md#book-tree) › [第二篇 · 核心与工程基础](README.md#part-foundation) › 第 05 章 · 后续方向指南：现状、缺口与优化工作清单

## 本章导航

- [5.1 先看结论与使用方法](#direction-start)
- [5.2 本次分析依据与可以复用的成果](#direction-baseline)
- [5.3 当前能力与缺口总览](#direction-inventory)
- [5.4 后续工作项：交付什么、依赖什么](#direction-work)
  - [5.4.1 F01 · 收口统一对话与真实行动受理](#direction-dialogue)
  - [5.4.2 F02 · 统一资源准入，完成真正有负载的并行验证](#direction-resources)
  - [5.4.3 F03 · 统一记忆写入口与纠正、遗忘语义](#direction-memory-integrity)
  - [5.4.4 F04 · 从提取对照升级到“找得到、用得对”的记忆验证](#direction-memory-quality)
  - [5.4.5 F05 · 先交付按键语音，再做连续交流与多人场景](#direction-voice)
  - [5.4.6 F06 · 补长期伙伴连续性与可控主动性](#direction-persona)
  - [5.4.7 F07 · 将限定编程扩大为真实、可回退的开发能力](#direction-coding)
  - [5.4.8 F08 · 分离自检、自愈、进化，并证明净收益](#direction-growth)
  - [5.4.9 F09 · 收口真实离线、迁移恢复与普通 PC 验证](#direction-offline)
  - [5.4.10 F10 · 将多模型目录推进为用途与证据驱动路由](#direction-routing)
  - [5.4.11 F11 · 让监控、验证新鲜度与升级状态覆盖所有模块](#direction-maintenance)
  - [5.4.12 F12 · 收敛架构、依赖与数据退役，防止迭代污染](#direction-architecture)
  - [5.4.13 F13 · 做目标驱动的知识编纂与联网学习](#direction-learning)
  - [5.4.14 F14 · 逐项扩展电脑、硬件和可编辑创作产物](#direction-connectors)
  - [5.4.15 F15 · 从两台机器验证离线自治与重连合并](#direction-federation)
  - [5.4.16 F16 · 动态 Agent、NPC 与可变形态按预算扩展](#direction-agents)
- [5.5 与原需求的逐组对应，防止只优化工程工具](#direction-requirements)
- [5.6 工程优化原则与暂不投入的内容](#direction-engineering)
  - [5.6.1 继续复用的结构](#direction-preserve)
  - [5.6.2 现在不应作为主线的投入](#direction-defer)
- [5.7 还没验证的内容，应怎样补证](#direction-evidence)
- [5.8 如何持续维护这份指南与完成一次迭代](#direction-release)
<!-- book-nav:end -->

<a id="direction-start"></a>
## 1. 先看结论与使用方法

当前 Jarvis 是**已有真实工具执行、持久个人状态和有限成长能力的本机助手**。它已经能够承担有边界的日常文字交流、资料查询、报告与编程辅助；距离“长期理解主人、自然语音交流、自主完成复杂事务、跨设备延续”的目标，主要差距是整条体验链和验证深度。

后续应把已有部件接成可靠闭环，而不是继续以模型数量、技能卡片数量或新框架数量代表进步：

- 对话能理解“陪我聊聊”和“顺便做件事”的组合，行动有真实回执，补充/取消能找到正确对象。
- 记忆不仅能保存，还能在需要时找对、用对；纠正、遗忘和私人/工作边界影响最终回答。
- 本地语音先做到按键说话可用，再追求连续交谈、打断和更丰富的声音表现。
- 编程与进化从有限演示扩大到真实需求，但保留独立测试、候选副本、版本回退和成本记录。
- 普通 PC 上聊天、语音、任务、索引、维护共享资源时可控降级，后台也能持续完成工作。

**当前按主人要求恢复后续开发，不重复 K2 验收。** K2 冻结结果与待验条件保留于[收口记录](delivery-validation.md#k2-completion-evidence)，开发顺序只归[当前推进队列](core-bootstrap.md#near-term-work-queue)。F 编号是工作项索引，不另立时间线。

<a id="direction-baseline"></a>
## 2. 本次分析依据与可以复用的成果

基线为 `v0.1.58` 标签对应提交 `d323f666500a54657abdb45d5ea884d5f68a51a1`。分析结合有效主题页、源码抽查、验收报告和本机只读状态；这是一次方向整理，不是重新执行全部模型、语音或硬件测试。后续文档修改会使工作树不同于该标签，不应因此覆盖旧报告摘要。

| 证据 | 已证明的范围 | 不应外推的结论 |
|---|---|---|
| [0.1.58 汇总](../evals/reports/skills-completion-release-2026-10-19.json) | 249 项主套件、62 项 Web/队列、34 项维护恢复；限定真实编程、回执复取、计费修复；本机已部署 | 不是仓库所有测试在一个全产品场景中全部重跑；不是通用开发能力 |
| 同一汇总的资源记录 | 20 分钟冻结源码、50 轮混合任务；30 分钟临时核心空闲；310 秒、15 轮界面观察 | 混合负载使用合成模型；未覆盖麦克风/TTS/索引/维护同时饱和、物理 8 GiB PC 或通宵 |
| [对话分槽](delivery-validation.md#conversation-lanes-evidence)、[意图与限定文档受理](delivery-validation.md#dialogue-intent-shadow-evidence) | 普通上下文/模型进程及限定后台模型路径；Flash 单项 Context7 只读任务；校准与留出分开 | 不是任意模型、所有工具、多意图修改和全局资源公平性的证明 |
| [候选记忆核对](delivery-validation.md#memory-candidate-review-evidence) | 显式沿用/更新、来源和修订保护；临时核心与 UI；部署资产匹配；千条事实本地核对测量 | 没有用主人正式记忆作写入测试；不是通用语义去重或全链路遗忘 |
| [LangMem](delivery-validation.md#memory-langmem-shadow-evidence)、[Mem0](delivery-validation.md#memory-mem0-shadow-evidence) | 相同公开单条样例的约束提取；Mem0 另有小规模多轮库行为观察 | 不是长期记忆检索或最终会话质量排名；不是独立留出盲评 |
| [Qwen TTS](delivery-validation.md#qwen-tts-integration-evidence)、[表达标签](delivery-validation.md#speech-expression-evidence)、[朗读](delivery-validation.md#chat-readout-evidence) | 本地主力文件合成、用户试听认可的部分音色/情绪、分段手动朗读 | 不是麦克风输入、全双工、所有语言和声线的全面验收 |

0.1.58 的指导技能质量结果还有明显分层：Sol 的带技能样本为 27/27 完全通过，Google 为 8/27 完全通过、16 部分通过、3 失败；无技能对照分别为 18/27 和 6/27 完全通过。每个指南每模型仅三个自编场景，每臂一次回答，由实现助手逐项审阅，非独立盲评。它支持“技能在部分组合上有帮助”，不支持“所有模型都一样好”或“加技能必然提升”。详细方法只维护在[技能验收](delivery-validation.md#skills-completion-evidence)。

<a id="direction-inventory"></a>
## 3. 当前能力与缺口总览

本表是跨主题索引，完整实现规则仍在链接的权威页。`局部 verified` 意味着已有明确测试通过，不表示整个需求完成；`未闭环` 包括尚未实现与缺少整体验证两种情况。

| 领域 | 当前可复用状态 | 仍缺什么 | 后续工作项 |
|---|---|---|---|
| 文字交流与任务 | 局部 verified：回执、持久恢复、两个对话槽、独立后台槽、限定混合报告及指定修改/取消 | 通用混合意图与模糊指代、更多模型/能力、逐步输出 | [F01](#direction-dialogue)、[F02](#direction-resources) |
| 语音 | 局部 verified：Qwen 表达/朗读、按键录音、本地转写与新回复播报 | 持续轮次、声学回声/打断、多人识别、真实环境质量与全面资源竞争 | [F05](#direction-voice) |
| 记忆与经历 | 局部 verified：明确记忆、按需候选、修订屏障、本地核对；0.1.62 补相关事实选择与话题推荐 | 复杂转述、有效时间、通用语义经历召回、完整受众与跨来源遗忘仍缺 | [F03](#direction-memory-integrity)、[F04](#direction-memory-quality) |
| 人格与主动性 | implemented/局部 verified：自定义称呼、固定交流风格/关系、持久修订与整组撤销界面 | 自定义复杂表达/多形态、长期情境一致性、可撤回的主动跟进 | [F06](#direction-persona) |
| 技能与工具 | 局部 verified：11 个可见技能；Context7 有实际调用 | 其他 MCP 多为目录推荐；自动组合仍有限，技能生效条件与收益不均 | [F01](#direction-dialogue)、[F07](#direction-coding) |
| 编程与成长 | [K3 已闭环](delivery-validation.md#k3-closure-matrix)；K4 已有受审阅工具发布、灰度/回退、契约体检及退役版本归档 | 0.1.78 已完成三个明确领域的 K4 闭环；长期收益、通用业务语义仍未证明；当前 K5 已拆排序接口，模型生成的自身模块与持久切换待补 | [F07](#direction-coding)、[F08](#direction-growth) |
| 模型与离线 | 局部 verified：多供应商、用量/估算、固定本地小模型及封闭任务 | 跨用途统一策略、质量驱动路由、真实整机断网和组件自更新 | [F09](#direction-offline)、[F10](#direction-routing) |
| 资源与可靠性 | 局部 verified：准入、进程回收、UNKNOWN、短时与本机长时子集 | 跨通道原子资源预留、CPU/GPU/配额公平、完整设备/磁盘故障矩阵 | [F02](#direction-resources)、[F09](#direction-offline) |
| 模块管理与版本 | implemented/局部 verified：监控、运行包切换、技能验证失效显示 | 任意有状态模块热换、在途版本兼容、跨库迁移、长期退役 | [F11](#direction-maintenance)、[F12](#direction-architecture) |
| 学习与知识库 | 局部 implemented：登记资料词法查询、来源片段、限定成长记录 | 增量索引/编纂、目标相关互联网学习、派生依赖撤销 | [F04](#direction-memory-quality)、[F13](#direction-learning) |
| 电脑、设备、创作 | 局部 verified：限定浏览器、REA 静态分析、固定齿轮科普 | 通用桌面/应用操作、设备反馈、任意 CAD/三维/视频创作 | [F14](#direction-connectors) |
| 多设备、动态 Agent、NPC | proposed，存在契约与设计，未形成系统验收 | 双节点自治与合并、任务唯一执行、资源受控组队、虚拟世界隔离 | [F15](#direction-federation)、[F16](#direction-agents) |

<a id="direction-work"></a>
## 4. 后续工作项：交付什么、依赖什么

以下优先程度针对 0.1.58 后的工程价值，不改产品 R/N 的 P0/P1/P2。具体选择顺序只维护在[当前推进队列](core-bootstrap.md#near-term-work-queue)。必要检查随新增实现执行；主人已要求继续开发，不再反复重跑 K2 收口。

<a id="direction-dialogue"></a>
### F01 · 收口统一对话与真实行动受理

**优先：近期主线；归属 K2/W1—W3。** 保留 `DialogueTurns`、真实任务账本和 Context7 已通过范围。当前自动受理是一个模型/一个只读能力的限定规则；固定四项编码指导的组合也不是通用 Agent 规划器。

**0.1.59增量已实现并完成限定验证：**混合报告、明确编号取消、未开始任务原子替换及真实模型→LPAC产物已接通，详见[验证与漏受理](delivery-validation.md#mixed-report-admission-evidence)。完整F01仍缺独立人工标注、更多模型/能力、模糊指代和多行动依赖。F03入口子集现已交付，主线已进入F04开发先导，继续按核心队列扩展场景；F01保留这些开放项，不能整项标为完成。

本次采用的最小增量以现有 `sample.report.v1` 为对象：冻结“情绪回应＋目录报告”“只停报告 A”“修改目标”“引述/否定/假设”“同一请求重送”的正反例；让混合回应和实际任务分别形成回执，任务只接收必要参数。先影子验证，再启用明确通过的模式；能力不可用时给出具体原因或必要澄清，不用一句“正在执行”冒充受理。

需要澄清、重新规划、修改已受理任务和取消是不同操作：修改必须绑定原任务及版本；已经产生的效果不因改口被假装撤销。页面待发文字不自动等同于当前任务补充。扩展模型时沿用同一测试集，不从 Flash 结果推断其他模型通过。

**主要落点：**[intent.py](../runtime/node-host/jarvis_core/intent.py)、[turns.py](../runtime/node-host/jarvis_core/turns.py)、[conversation_tasks.py](../runtime/node-host/jarvis_core/conversation_tasks.py)、[documentation_admission.py](../runtime/node-host/jarvis_core/documentation_admission.py)、[task_queue.py](../runtime/node-host/jarvis_core/task_queue.py) 及对应 Web 路由。先提取可复用的受理端口和能力描述，再接一个执行器；不先写完整通用规划语言。退出证据按 [V-DLG-01—05](delivery-validation.md#conversation-separation-validation)、[V-K2-02/06](delivery-validation.md#next-k2-acceptance)；已有只读文档能力保持单独可回退。

<a id="direction-resources"></a>
### F02 · 统一资源准入，完成真正有负载的并行验证

**优先：随 F01/F05 收口的基础工作；归属 K1/W4—W6、K2/W3—W4。** 现有 `ResourceAdmission` 是内存观察与准入，不能当作 OS 预留；聊天、成长、维护、TTS 也尚未共享一份原子资源租约。

0.1.62 已修复数据库争用造成的长取消等待、对话持久收尾占用公共锁；慢模型/4 CPU 争用、真实本地模型混合运行和浏览器分别测量，结果统一见 [K2 证据](delivery-validation.md#k2-completion-evidence)。这是文本与一个后台任务的适用范围；全语音/索引/维护的统一资源租约仍保留在本项。

先用小型本机 Admission 接口统一“申请、等待、释放、超时、崩溃回收”，保留对话、执行、维护不同通道。逐项加入 CPU、RAM、显存、供应商并发/限流及费用来源；状态查询和取消不得等待推理槽。后台采用限额与老化/公平策略，避免只靠永久暂停后台维持聊天速度。

先纳入聊天与一个真实任务，再接 Qwen/STT 和索引；每次记录空闲、单独运行、并行运行的分项延迟与后台完成量。启动/预热、首字、首声、最终完成分开计时；冷启动不能混进热样本平均。8 GiB 设备不可得时保留未验，模拟内存计数不能替代真机。已有 20 分钟测试可作回归，不能顶替 [V-DLG-07/08](delivery-validation.md#conversation-separation-validation) 的真实全链路负载。

**主要落点：**[resources.py](../runtime/node-host/jarvis_core/resources.py)、[dialogue_process.py](../runtime/node-host/jarvis_core/dialogue_process.py)、[runtime_metrics.py](../runtime/node-host/jarvis_core/runtime_metrics.py)、[task_queue.py](../runtime/node-host/jarvis_core/task_queue.py)、语音/成长的已有生命周期接口。沿用[资源契约](contracts.md#parallel-runtime-contract)，不引入 K8s、集中队列集群或为每个模块常驻一个服务。

<a id="direction-memory-integrity"></a>
### F03 · 统一记忆写入口与纠正、遗忘语义

**优先：近期主线；归属 K2/W1。** 0.1.58 的本地核对已支持语义候选沿用/替代；0.1.60 已将规则事实接到同一核对、修订屏障和事务写入，[限定证据](delivery-validation.md#rule-memory-review-evidence)另列。当前词项差异提示仍不能裁决所有同义、时间变化或矛盾，完整 F03 未完成。

已完成入口统一并保持明确记忆指令的确定性。继续冻结同义改述、临时偏好、前后时间变化、同名人物、项目/个人范围、助手错误猜测纠正、多来源以及并发确认场景；确认仍检查来源修订与事实库修订。本次 UI 探针发现“白开水”与已有饮品记录可能漏关联，保留为 F04 开发反例，不计入独立留出。低相似度不等于新事实，高相似度也不自动覆盖旧事实。

之后补多来源证据和派生依赖失效：区分“不再使用”“删除事实”“保留审计”“原会话仍含这句话”，把相应选择对后续上下文的作用展示清楚。防止已删事实从摘要、接续卡片、Wiki、索引或重试候选回流；不要通过删除历史审计掩盖该问题。

**主要落点：**[personal_candidates.py](../runtime/node-host/jarvis_core/personal_candidates.py)、[semantic_candidates.py](../runtime/node-host/jarvis_core/semantic_candidates.py)、[memory_review.py](../runtime/node-host/jarvis_core/memory_review.py)、[memory_comparison.py](../runtime/node-host/jarvis_core/memory_comparison.py)、[memory.py](../runtime/node-host/jarvis_core/memory.py)、[continuity.py](../runtime/node-host/jarvis_core/continuity.py)。沿用[候选契约](contracts.md#memory-candidate-review-contract)和 [V-MEM](delivery-validation.md#memory-domain-validation)，不要另建一个事实数据库或自动重解释全部旧聊天。

<a id="direction-memory-quality"></a>
### F04 · 从提取对照升级到“找得到、用得对”的记忆验证

**优先：近期主线；归属 K2/W1—W3，组件替换扩展归 K5。** 目前 LangMem/Mem0 的同分只覆盖单条提取。Mem0 约束接法提示较长、公开样例漏项更少但反例弃答更差；这不是最终聊天质量结论。

0.1.62 已增加生活、学习、工作三个冻结场景的相关事实/无记忆/纠正/遗忘回答对照，以及可追溯的话题推荐；本轮词法选择保留背景偏好，排除无关事实。该结果和费用见 [K2 证据](delivery-validation.md#k2-completion-evidence)，不能替代独立人工语料、完整语义召回或框架质量排名；以下 0.1.61 记录是前一轮基础。

**已进入真实最终回答验证：**[先导与修复复验](delivery-validation.md#memory-final-answer-evidence)沿规则候选、确认、纠正/遗忘和新会话回答运行，增加开/关记忆成对对照。该开发集只有八个中文饮品场景，不是独立留出，也没有比较框架优劣；下一增量仍需扩大到人物、时序、项目资料、混合语言和保留历史，补总资源测量及独立标注。已发现模型可能承诺自动记忆，0.1.61 更新宿主能力说明；不能把关键词通过等同于整体对话质量通过。

按[分轨比较](delivery-validation.md#memory-comparison-tracks)补独立多轮开发/保留集合，再比较完整路径：新增片段 → 候选与确认 → 纠正/遗忘 → 隔会话提问 → 找到证据 → 装入上下文 → 生成最终回答。提取、检索命中、引用支持、回答正确、过时事实使用、越域和总成本分别计分，不能合并成一个“智能分”。

对同一组中文及代码资料，先测现有词法检索和来源失效，再引入一个可关闭的混合召回适配器；只有反例显示词法不足才承担 embedding 常驻/加载和索引维护成本。旧事实仍是权威，索引可以重建。评估提取器时固定输入/模型；评估框架完整配置时另表报告，不让更强模型的收益冒充框架收益。

**需要交付：**可复跑的多轮数据与判据、三个环节的逐例结果、最后回答的实际证据使用记录、每轮总费用与资源账单、关闭新后端后的恢复测试。Mem0 的提示精简/批次提取可以作候选实验，未通过反例与最终回答验证前不替换生产默认。

**主要落点：**[knowledge.py](../runtime/node-host/jarvis_core/knowledge.py)、[memory_view.py](../runtime/node-host/jarvis_core/memory_view.py)、[context_assembly.py](../runtime/node-host/jarvis_core/context_assembly.py)、[assistant_context.py](../runtime/node-host/jarvis_core/assistant_context.py)、`tools/memory_lab/`。正式门槛继续归 [V-MEM](delivery-validation.md#memory-selection-evaluation) 和 [V-PAL-02/03/07](delivery-validation.md#personal-companion-validation)。

<a id="direction-voice"></a>
### F05 · 先交付按键语音，再做连续交流与多人场景

**优先：近期可交付体验；归属 K2 输入适配，完整语音按 K6/M2。** 复用已有 Qwen 主力、ZipVoice 手动备用和 CosyVoice 按需增强；本轮不重新选一整套 TTS，也不把九种音色/十语种目录写成全部验过。

0.1.80 已实现[首个语音增量](interaction-persona.md#voice-chat-plan)：麦克风开始/结束、录音状态、本地 STT、可编辑转写及同一文字发送入口，另有显式新回复播报。录音先暂停旧播报；权限拒绝、设备拔出、模型未加载和识别失败时仍可打字。只保存用户选择发送的文本，音频缓存按现有语音契约管理。用真实中文/英文和混合句测转写，而非仅用 TTS 生成的干净音频。

下一增量才是增量回答与短段自动播报、VAD 轮次、有效代际过滤、AEC/插话及匿名说话人分段。声纹匹配、多人分离、声音克隆各自测试；声纹不是动作授权凭证。用户已认可的自然度/情绪继续做回归，克隆与复杂分离不抢占基本交谈预算。

**主要落点：**现有 [speech_routes.py](../apps/web/speech_routes.py)、[speech.js](../apps/web/speech.js)、[readout.js](../apps/web/readout.js)、[readout.py](../runtime/node-host/jarvis_core/readout.py)、[qwen_speech.py](../runtime/node-host/jarvis_core/qwen_speech.py) 和独立 STT 适配器。逐字流式要与结束状态、取消、断线和未完成回答保存语义共同设计；部分文本不能提前成为可执行工具参数。具体交互与目标见[语音接入计划](interaction-persona.md#voice-chat-plan)、[V-DLG-06—08](delivery-validation.md#conversation-separation-validation)。

<a id="direction-persona"></a>
### F06 · 补长期伙伴连续性与可控主动性

**优先：K2 核心体验逐项补齐；更复杂形态归 K6。** 0.1.62 已实现自定义称呼、持久风格/关系、版本冲突保护、整组撤销和设置界面，正在生成的回答保持原快照，修改从下一轮生效。性别表达、声音/化身映射及长期情境一致性仍未实现/完整验证，不能将称呼继续列为待实现。

先扩展版本化 PersonaProfile 的表达字段，固定一次对话快照；人格变化不能改写事实、任务权限或把虚拟经历当现实。用换模型、重启、切换工作/日常模式、主人纠正等场景验证同一身份和适用记忆连续，而非只看一句角色介绍。

主动性先从已授权、可解释的未结事项做起：显示来源、触发条件、安静时间、撤回方式及实际执行状态。提出“下次继续”不等于自动建立定时器；普通闲聊和情感回应不强制生成任务或记忆。提醒/自动行动只有相应授权和实现后才启用，待命不能变成连续付费推理。

**主要落点：**[persona.py](../runtime/node-host/jarvis_core/persona.py)、[personal.py](../runtime/node-host/jarvis_core/personal.py)、[continuity.py](../runtime/node-host/jarvis_core/continuity.py)、[work_state.py](../runtime/node-host/jarvis_core/work_state.py)、[turns.py](../runtime/node-host/jarvis_core/turns.py)。按[伙伴核心判据](product-requirements.md#personal-companion-core)和 [V-PAL-01—06/09](delivery-validation.md#personal-companion-validation)评估；自然度、打扰感由实际使用反馈衡量，不用聊天时长或依赖程度充当收益。

<a id="direction-coding"></a>
### F07 · 将限定编程扩大为真实、可回退的开发能力

**0.1.65 完成候选、独立案例、多文件源码构建和 Codex 适配；0.1.66 补可运行 PYZ、严格离线重建与损坏源码修复。0.1.67 [阶段验收](delivery-validation.md#k3-acceptance-evidence)修复内置能力声明/诊断问题，0.1.68 已接通[改进单到编码任务的有界交接](delivery-validation.md#coding-demand-evidence)；后续按原阶段扩大受控构建与故障矩阵。** 证据见[K3 编码协作](delivery-validation.md#k3-coding-evidence)，完整使用规则只归[编程工作流](tasks-agents.md#bounded-coding-workflow)。原有单文件 `transform(data) -> str`、LPAC、冻结可见案例、差异、明确应用/恢复已经可用。下一步不应立即开放任意终端和整个仓库写入。

已补独立输入、输入不变/输出契约检查、基线变化与失败产物检查，并完成两模块文件清单汇总。本轮已增加三个真实开发场景与第二种固定构建配方，证据见[构建验收](delivery-validation.md#k3-build-evidence)。0.1.69 已增加[锁定的轻量离线依赖配方](toolchains.md#bounded-python-dependencies)，本轮结果见[依赖验收](delivery-validation.md#coding-dependencies-evidence)。0.1.70 已增加[Python 包、新文件与 JavaScript 场景](toolchains.md#bounded-package-scene-recipes)，已通过[K3 收口清单](delivery-validation.md#k3-closure-matrix)的真实任务、质量对照和故障检查；0.1.71—0.1.76 已接入 K4 受审阅工具发布、灰度和归档子集，当前剩余工作只见[推进队列](core-bootstrap.md#k4-next-delivery)，冻结路径与交付契约不变。将“生成者写的测试”“宿主冻结测试”“真实需求结果”分别保留；通过三个可见案例不能证明任意输入正确。

外部 Codex 已以文本候选方式接到现有 CodingProvider，约束作业而非赋予发布权。候选、真实构建、取消恢复与用量已纳入[K3 收口证据](delivery-validation.md#k3-closure-matrix)；扩大交互或工具范围仍按新增范围独立验收。无需为支持多语言而预装所有编译器；先保证一个按需工具链可离线重建。

**主要落点：**[coding_workflow.py](../runtime/node-host/jarvis_core/coding_workflow.py)、[skill_tasks.py](../runtime/node-host/jarvis_core/skill_tasks.py)、[evolution/provider.py](../runtime/node-host/jarvis_core/evolution/provider.py)、[evolution/runner.py](../runtime/node-host/jarvis_core/evolution/runner.py) 和 [evolution/recipes.py](../runtime/node-host/jarvis_core/evolution/recipes.py)。当前仓库没有已部署的通用 `toolchains/` 实现；未来工具链资产按[唯一源码树](stack-project-layout.md#project-structure)逐项接入。范围规则见[编程工作流](tasks-agents.md#bounded-coding-workflow)、[外部执行器](evolution-release.md#external-coding-executor)，退出按 [B 系列](delivery-validation.md#development-platform-12)、[V-OSS](delivery-validation.md#open-source-adoption-validation)。

<a id="direction-growth"></a>
### F08 · 分离自检、自愈、进化，并证明净收益

**优先：扩大自动性前先做；归属 K2 最小成长到 K3—K5。** 0.1.64 已实现限定工具的观察/恢复/进化分工、用途配置与三标签；完整行为见[成长运行](evolution-release.md#bounded-evolution-loop)。F08 的事件调度、跨模块修复、真实未知需求净收益仍未完成，不将其整体关闭。

0.1.62 已完成本轮实际验收文件的索引交付、同能力复用、损坏修复及保留个人状态的回退；相关性回答也有前后对照。范围和收益见 [K2 证据](delivery-validation.md#k2-completion-evidence)；已知配方不是未知算法发明，主人主观收益反馈仍待实际使用，不据此关闭本项全部扩展。

本轮已使 Inspect 只产出观察，Heal 消费故障并恢复原契约，Evolve 消费需求并增加能力；三者共享已有账本/候选/验证/发布底座。健康旧版本低于目标版本应是能力差距，余额不足、网络失败、低内存不能自动变成改代码任务。

K4 已由 0.1.78 的[限定领域整链](delivery-validation.md#k4-growth-closure-evidence)补证；后续扩大领域仍须用未提供完整候选答案、但能独立验收的真实工具需求验证收益，现有[三任务挑战](delivery-validation.md#k4-quality-storage-evidence)不代替正常基线和长期使用证据。K5 的[首个受限检索模块闭环](delivery-validation.md#k5-ranking-module-evidence)已在 0.1.79 接通模型源码生成、独立对照、持久选择和回退；后续更广泛替换仍须冻结任务集、比较质量/成本、验证原能力不退化。具体推进只见[当前队列](core-bootstrap.md#k4-next-delivery)。修复通过不应把触发它的原失败任务改写为成功。自检触发与去重按[分层检查](health-maintenance.md#inspection-scheduling)，不另加一套常驻模型心跳。

**主要落点：**[evolution/manager.py](../runtime/node-host/jarvis_core/evolution/manager.py)、[evolution/store.py](../runtime/node-host/jarvis_core/evolution/store.py)、[evolution/recipes.py](../runtime/node-host/jarvis_core/evolution/recipes.py)、[evolution/demand.py](../runtime/node-host/jarvis_core/evolution/demand.py) 及用途路由。准入和退出仍按[三能力治理](evolution-release.md#growth-governance)、[净收益](delivery-validation.md#bootstrap-8)、[V-PAL-10](delivery-validation.md#personal-companion-validation)；任意自身模块改写仍需 K5 证据。

<a id="direction-offline"></a>
### F09 · 收口真实离线、迁移恢复与普通 PC 验证

**优先：K1/W5—W6、K2/W4 持续收口。** 固定小模型与应用层出站阻断已有证据，但不能替代整机断网冷启动。现有个人使用策略中延期的高级身份/锁存项目不应悄悄变为本轮必需前置。

0.1.62 已补当前个人数据的明确启动兼容检查、真实运行包 A/B/A 与坏槽位回退；旧运行包不能因主账本 schema 相同就接管新增个人数据。整机断网脚本已准备，主人已确认没有另一台普通设备；具体完成/未验项统一见 [K2 证据](delivery-validation.md#k2-completion-evidence)。

先形成离线运行清单：所选运行包、Python/原生组件、模型、索引、资料、字体/网页资产、许可证及恢复材料；逐项标“必需/按需/未安装”。在独立演练环境验证冷启动、没有云凭据时的本地操作、模型不可用/内存不足、端口冲突、数据库忙或损坏、磁盘满与恢复包回退。网络诊断先只读分类，实际修复必须有明确作用范围和可验证结果。

备份恢复验证应包括跨库的一致状态、任务/记忆/人格、删除标记和 UNKNOWN，而不只验证复制了几个 `.db` 文件。当前普通开发机测试与物理 8/16 GiB 设备、无独显、休眠唤醒、长时负载分别登记；测试时长不提前写成通过。

**主要落点：**[releases.py](../runtime/node-host/jarvis_core/releases.py)、[local_model.py](../runtime/node-host/jarvis_core/local_model.py)、[恢复 CLI](../runtime/recovery-cli/main.py)、[运行包工具](../tools/release_bundle.py) 与[启动探针](../tools/probe_runtime_start.py)。正式出口是 [V-K1-05/07](delivery-validation.md#next-k1-acceptance)、[V-K2-04—06](delivery-validation.md#next-k2-acceptance) 和 [PC 资源验收](delivery-validation.md#pc-footprint)。

<a id="direction-routing"></a>
### F10 · 将多模型目录推进为用途与证据驱动路由

**优先：近期纠偏与中期扩展；归属 K2，组件自主替换归 K5/K6。** 保留现有多供应商配置、固定适配器和费用账本；0.1.58 已修复编码用途价表传递，后续要防止相同问题在不同调用路径复发。

统一聊天、规划、解释、编码、检索整理等用途的模型/档位/候补、资料允许范围、真实 usage 与费用来源。模型支持某 API 不等于本任务质量通过；根据领域验证结果选路由，未知成本显示未知，估算不能写成账单结算。路由切换不重放已发生动作，UNKNOWN 先对账。

“两套路由”应分成主用途路由与最小恢复路径：后者保留确定性诊断、已验证本地组件和回退材料；它不需要另一套常驻大模型，也不能绕过任务权限。模型自动替换必须具有包摘要、能力/语言兼容、冷/热资源测量、影子对照及失败回退；先实现一个组件的流程再泛化。

**主要落点：**[chat.py](../runtime/node-host/jarvis_core/chat.py)、[模型网关](../adapters/models/provider-native/jarvis_models/gateway.py)、[费用计算](../adapters/models/provider-native/jarvis_models/billing.py)、[local_model.py](../runtime/node-host/jarvis_core/local_model.py)、[evolution/provider.py](../runtime/node-host/jarvis_core/evolution/provider.py) 及现有管理页路由。政策与参数只维护在[模型章](models-offline.md#configured-models)、[成长用途路由](models-offline.md#growth-model-policy)，本文不复制实时模型排行榜或价格表。

<a id="direction-maintenance"></a>
### F11 · 让监控、验证新鲜度与升级状态覆盖所有模块

**优先：近期可见性完善；跨模块升级属于 K3—K5。** 0.1.58 已对技能显示版本、覆盖范围与源码变化后的“待复验”，不需要再从零增加技能验证状态。剩余是将同样的证据语义扩展到语音、记忆、模型、资料索引和维护模块。

0.1.62 已增加人格配置与话题接续的独立观察，模块页共 25 项；观察只读取元数据，坏个人配置显示未知而不冒充默认值。该增量不代表所有模块都能独立热升级。

区分安装、启用、就绪、当前被使用、空闲加载、失败、等待资源、验证过期、仅规划；“最近一次成功”与“当前版本已验证”分开呈现。错误要指向实际对象与可执行恢复动作，避免一个全局绿色状态掩盖局部故障。

升级先按对象明确能力：无状态工作进程可排空后换包；有状态 Host/数据库迁移需维护窗口与恢复策略；长任务固定旧包与验证器，新任务才用新版本。不能把服务平滑重启称为任意模块零停机。按[模块监控](health-maintenance.md#module-monitoring)、[版本连续性](evolution-release.md#service-continuity)与[当前验证索引](../config/skills/validation.json)增量实现。

<a id="direction-architecture"></a>
### F12 · 收敛架构、依赖与数据退役，防止迭代污染

**优先：随功能修改实施，不先全面重写；归属 K1/K2 工程基础及 K3—K5。** 本次源码抽查确认 [server.py](../apps/web/server.py) 仍约 1,071 行；`memory ↔ memory_view`、`memory_view ↔ knowledge` 与 `extensions ↔ mcp_catalog` 的依赖耦合仍需处理，包含函数内导入，不等于当前导入失败。历史问题编号仍归[架构审计](decisions-review.md#current-code-findings)。

拆分先围绕变化频繁的接口：抽出纯作用域/能力类型；存储不反向依赖查询编排；HTTP 只做传输与组合，不成为另一份业务规则；前端将会话状态和 API 客户端从全局 DOM 状态中逐步移出。保持原接口行为和测试，通过依赖检查防止新增反向依赖，不能只按文件行数拆空壳。

模块“可替换”的最低材料是输入输出契约、版本、状态所有者、资源估计、确定性测试、迁移与回退入口。跨库事务要有可重放对账协议，不强行合并所有 SQLite，也不把一次 Python 调用当成跨库原子提交。

长期增长需要引用分析和只读整理预览：活动包、回退包、在途任务、审计及证据不能按年龄直接删除。0.1.76 已增加[无引用退役版本归档](evolution-release.md#project-tool-quality-storage)，可释放 64 个在线版本中的名额；0.1.77 增加[回执归档与退役目录收存/恢复](evolution-release.md#growth-ledger-maintenance)，满在线名额仍可显式整理，原编号与恢复材料保留；总索引、归档和整理审计仍有上限。归档不释放整机磁盘，尚不是无限期自动存储治理。后续交付只归[当前队列](core-bootstrap.md#k4-next-delivery)。开发调试文件、已替代文档、可重建缓存、用户材料、恢复材料分别依[退役规则](health-maintenance.md#system-health-7)处理；本次指南不执行清理。

当前仓库未见 `.github` 自动检查配置，可把已有检查入口接成轻量持续集成：无云契约/业务测试、导航/链接、源码依赖方向、配置/版本一致性和暂存资产检查。真实 Windows 隔离、麦克风、模型质量及资源测试单列环境条件，不将跳过项计为通过；默认 CI 不读取个人凭据或自动启动付费评测。发布清单绑定提交、配置、验证器与报告摘要；依赖来源/许可、锁文件及可重建运行包一起核对。CI 接通属于后续实现，本指南没有创建流水线。

<a id="direction-learning"></a>
### F13 · 做目标驱动的知识编纂与联网学习

**优先：F03/F04 的来源与失效链稳定后；归属 K2/W1、K3，后端替换归 K5。** 先选一组明确资料，比较直接读原文与增量编纂的回答收益；保留材料版本、段落引用、时间、冲突与重建入口，不先把全库转 Wiki。

联网学习从一个真实未解决需求触发：查证来源 → 形成候选知识/技能 → 运行实验 → 经过验收晋升。网页、论文和工具返回是资料，不能改权限或自授更新权。过期知识、失效链接、矛盾证据需要撤销/更新；“看到新技术”不是自动安装理由。

后台批次整理要比较总费用、前台延迟、重要信息遗漏与最长等待时间。接入新后端后，旧事实、原文及删除语义仍可导出和恢复。完整规则归[知识学习](knowledge-learning.md#memory-operating-cycle)、[编纂](knowledge-learning.md#project-knowledge-compilation)与[选型实验](delivery-validation.md#memory-comparison-tracks)，不为本指南另建定时学习服务。

<a id="direction-connectors"></a>
### F14 · 逐项扩展电脑、硬件和可编辑创作产物

**优先：由真实需求驱动，归属 K2 已准入工具及 K6 扩展。** Context7 之外的 MCP 卡片目前不能视为全部连通；REA 的 JavaScript/ASAR 静态证据也不是任意二进制逆向、程序运行轨迹或安全结论。

每次选择一个工具或应用，明确发现/认证、参数范围、取消、真实结果验证和恢复；官方 API/CLI 能完成时先用其稳定接口，UI 操作补缺。浏览器可控不等于桌面键鼠、文件管理器、任意应用都可控。扩展 REA 格式或通用创作前，先补真实样本、分页/预算和不可支持原因，不能只放大输入上限。

硬件从模拟设备和一个只读状态接口开始，再做有状态的限定动作；设备端反馈、动作幂等、失联策略及互锁必须实际验证。创作从一个可编辑产物类型开始，如确定范围的图形/文档/三维工程，校验打开、修改、导出和引用资产；固定齿轮交互不是通用机械 CAD、工程正确性或视频制作能力。

归属与边界见[电脑执行架构](architecture.md#computer-use-design)、[任务运行](tasks-agents.md#initial-task-loop)、[科普验收](delivery-validation.md#anatomy-validation)。注册连接器本身不扩大现有数据外发和动作权限。

<a id="direction-federation"></a>
### F15 · 从两台机器验证离线自治与重连合并

**优先：设计保留，单机状态/恢复契约稳定后实施；归属 K6。** “离线是独立 Jarvis，联网形成共同体”应落为身份/策略、事实/经历、任务所有权和资源能力的协作，不是把各节点提示词或数据库文件直接拼在一起。

第一步只用两节点、一个记忆域和一种任务，测试断连时本机交流和已有能力、重连后的版本协商与授权同步、冲突保留、删除传播、重复/乱序事件和任务唯一执行。暂时离线不意味着可以对同一真实设备无限并行执行；没有权威租约的效果须按域策略等待或限定本地范围。

先让资料复制与任务委派使用不同协议边界；不共享正在写入的 SQLite 文件，不把副本数当可用性。同步不必立即引入集群平台。完整一致性、冲突和“统一意志”定义仍归[共同体章](federation.md#offline-federation)，验收沿[扩展验收](delivery-validation.md#extensions-6)。

<a id="direction-agents"></a>
### F16 · 动态 Agent、NPC 与可变形态按预算扩展

**优先：后续按实际场景，归属 K6；依赖 F01/F02/F03/F15 的适用子集。** 现有四项指导组合不是四个独立 Agent，多个并发模型请求也不是已经实现动态团队。

先用两个不同职责的 Agent 验证目标拆分、输入范围、交付物、预算、失败接管和结果汇总；蓝图是受控数据，执行权限仍来自现有能力。再依据设备可用资源动态增加或回收数量，显示分配理由与真实占用。“理论可扩展”不等于运行时无限 Agent 或无限模型常驻。

NPC 小镇先采用小规模、可暂停的虚拟场景，区分世界事实、角色相信的内容和现实记忆；按观察需求调整模拟精度，保存可复现事件与分支。模拟角色不能直接取得现实工具权限。声音、外形、性别表达、机器人呈现各自是可替换适配器，保持同一助手的真实状态。

定义继续归[Agent 工厂](tasks-agents.md#agent-factory)、[NPC 世界](simulation.md#npc-world)、[人格形态](interaction-persona.md#persona-embodiment)。“绝对忠诚”“统一意识”是产品宗旨与表达，软件只能对明确授权、记录和可观察效果给出证据，不能证明所有内部想法永不出错。

<a id="direction-requirements"></a>
## 5. 与原需求的逐组对应，防止只优化工程工具

需求定义、优先级和正式追踪矩阵仍归[产品需求](product-requirements.md#r01)与[验收追踪](delivery-validation.md#requirement-traceability)。下表只说明后续清单覆盖去向，不复制需求全文，也不把多个 R 合并为一个通过项。

| 原需求编号 | 后续方向 | 当前主要缺口类型 |
|---|---|---|
| [R01](product-requirements.md#r01)、[R07](product-requirements.md#r07)、[R19](product-requirements.md#r19)、[R28](product-requirements.md#r28) | [F01](#direction-dialogue)、[F02](#direction-resources)、[F04](#direction-memory-quality)、[F09](#direction-offline) | 已有执行/分槽子集；缺跨环节质量、资源公平和适用出口收口 |
| [R04](product-requirements.md#r04)、[R33](product-requirements.md#r33) | [F05](#direction-voice)、[F09](#direction-offline) | 本地 TTS/小模型有基础；语音输入与低资源全链路缺实现/验证 |
| [R05](product-requirements.md#r05)、[R17](product-requirements.md#r17)、[R20](product-requirements.md#r20) | [F03](#direction-memory-integrity)、[F04](#direction-memory-quality)、[F06](#direction-persona) | 基础人格/记忆已实现；长期接续、受众及纠正/遗忘扩展待补 |
| [R10](product-requirements.md#r10)、[R16](product-requirements.md#r16)、[R22](product-requirements.md#r22)、[R34](product-requirements.md#r34)、[R35](product-requirements.md#r35) | [F09](#direction-offline)、[F10](#direction-routing) | 现有目录/路由和固定离线任务可用；整机离线、独立恢复、质量路由、组件自换和网络自修待补 |
| [R12](product-requirements.md#r12)、[R18](product-requirements.md#r18) | [F06](#direction-persona)、[F08](#direction-growth) | 待命和限定后台已有；通用目标推进、主动跟进及打扰控制待补 |
| [R13](product-requirements.md#r13)、[R14](product-requirements.md#r14)、[R15](product-requirements.md#r15)、[R29](product-requirements.md#r29)、[R30](product-requirements.md#r30) | [F07](#direction-coding)、[F08](#direction-growth)、[F11](#direction-maintenance)、[F12](#direction-architecture)、[F13](#direction-learning) | K3 多文件/外部编码已闭环，K4 有受审阅成长子集；长期净收益、更多语言工具链、自身替换和知识重构待补 |
| [R02](product-requirements.md#r02)、[R03](product-requirements.md#r03)、[R06](product-requirements.md#r06) | [F14](#direction-connectors) | 浏览器/静态解析/固定科普有子集；桌面、硬件、通用可编辑创作待补 |
| [R08](product-requirements.md#r08)、[R24](product-requirements.md#r24) | [F09](#direction-offline)、[F11](#direction-maintenance)、[F15](#direction-federation) | 单机回退有基础；数据迁移、版本协商、双节点自治合并待补 |
| [R11](product-requirements.md#r11)、[R26](product-requirements.md#r26)、[R27](product-requirements.md#r27) | [F02](#direction-resources)、[F16](#direction-agents) | 动态 Agent 工厂和 NPC 运行系统尚未验证 |
| [R23](product-requirements.md#r23)、[R25](product-requirements.md#r25) | [F06](#direction-persona)、[F11](#direction-maintenance)、[F16](#direction-agents) | 表达配置已有；多形态和拓扑变更仍需独立协议与回退 |
| [R09](product-requirements.md#r09)、[R31](product-requirements.md#r31)、[R32](product-requirements.md#r32)、[R36](product-requirements.md#r36) | [F01](#direction-dialogue)、[F09](#direction-offline)、[F11](#direction-maintenance)、[F15](#direction-federation)、[F16](#direction-agents) | 当前主人控制与会话取消保留；高级监督/认证/全局锁存按现行范围延期，不混入已通过项 |
| [R21](product-requirements.md#r21)、[R37](product-requirements.md#r37)、[R38](product-requirements.md#r38)、[R39](product-requirements.md#r39) | [F01](#direction-dialogue)、[F05](#direction-voice)、[F11](#direction-maintenance)、[F12](#direction-architecture) | 工作台、品牌、模块/任务入口已有；上下文透明、语音状态、验证覆盖与可接管性持续完善 |

| 非功能需求 | 本轮以后必须持续检查的关系 |
|---|---|
| [N01](product-requirements.md#n01)、[N04](product-requirements.md#n04)、[N12](product-requirements.md#n12) | [F02](#direction-resources)/[F09](#direction-offline)/[F11](#direction-maintenance)：局部故障、恢复、渐进降级与真实任务进展；不能靠整系统停掉证明隔离 |
| [N02](product-requirements.md#n02)、[N03](product-requirements.md#n03)、[N05](product-requirements.md#n05)、[N08](product-requirements.md#n08) | [F07](#direction-coding)/[F11](#direction-maintenance)/[F12](#direction-architecture)：契约、版本、证据绑定、测试、迁移和可解释状态 |
| [N06](product-requirements.md#n06)、[N07](product-requirements.md#n07)、[N09](product-requirements.md#n09) | [F02](#direction-resources)/[F09](#direction-offline)/[F10](#direction-routing)/[F16](#direction-agents)：普通 PC、按需组件、平台适配与有界扩展；跨平台逐个平台验收 |
| [N10](product-requirements.md#n10)、[N11](product-requirements.md#n11) | [F03](#direction-memory-integrity)/[F07](#direction-coding)/[F15](#direction-federation)/[F16](#direction-agents)：现实/虚拟、候选/生产、数据/执行权区分；延期监督项保留状态 |
| [N13](product-requirements.md#n13) | [F05](#direction-voice)/[F06](#direction-persona)/[F11](#direction-maintenance)：键盘、中文输入法、聚焦提示、窄屏、录音和真实错误状态 |

<a id="direction-engineering"></a>
## 6. 工程优化原则与暂不投入的内容

<a id="direction-preserve"></a>
### 继续复用的结构

- 保留 Python/SQLite 本机底座、现有网页与托盘、原生模型适配、LPAC/Job 和已有回复/任务账本。模块独立优先表现为清晰接口、状态所有者与可测试替换，而不是服务数量。
- 保留“候选 → 验证 → 采用/拒绝”的分离；记忆、代码、技能和知识都不以模型自述作为最终成功依据。
- 保留明确取消、UNKNOWN、版本绑定、来源引用和失败证据；让这些能力通过共享接口复用，避免每新增一个模块就另写一套重试与账本。
- 优先小范围提取纯规则/适配器和可选组件，不为消除文件体积而同时换后端框架、前端框架、数据库和任务框架。

<a id="direction-defer"></a>
### 现在不应作为主线的投入

| 暂不优先的做法 | 原因与转入条件 |
|---|---|
| 一次安装全部 MCP/记忆框架 | 尚无全链路收益；先由明确任务或失败例证明需要，再做单项准入 |
| 追逐最大模型、所有编译器和全平台环境 | 普通 PC 与维护代价不匹配；先固定任务质量与最低资源 Profile |
| 完整 Kubernetes、消息集群或每模块微服务 | 当前单机瓶颈是状态/接口/调度语义，分布式基础设施不能替代这些工作 |
| 仅增加聊天情绪、克隆声线或动画 | 用户已要求先自然及时交流；先把麦克风和首声链路跑通，再扩展呈现 |
| 同时开放任意代码、自改宿主、所有硬件 | 超过现有执行/恢复证据；分别按 K3—K6 的契约与单项验收扩大 |
| 从旧数据全量自动生成画像 | 来源/受众/遗忘链尚不完整；先做获准片段、显式核对与影子比较 |
| 为显得自主而定时调用模型、自动清理旧文件 | 不能证明有益；需要真实目标、事件触发、引用分析和可撤回结果 |
| 把高级身份认证与全局锁存重新设成当前个人使用前置 | 与[已确定个人范围](security-sovereignty.md#current-personal-scope)不符；保留延期设计，扩大使用场景时再明确评估 |

<a id="direction-evidence"></a>
## 7. 还没验证的内容，应怎样补证

“已实现”和“可长期放心使用”之间需要补以下证据；正式场景、阈值仍引用验收章，本文不另定一套门槛。

| 证据缺口 | 最小可复跑补证方式 | 权威出口 |
|---|---|---|
| 日常交流到行动的完整链 | 冻结混合意图、否定、指代、修改、取消、重复与重启样例，核对唯一效果和无关上下文排除 | [V-DLG](delivery-validation.md#conversation-separation-validation) |
| 长期记忆是否改善最终回答 | 多轮、跨会话、时间变化、无答案及遗忘后提问；检索与最终回答分别评分，记录总成本 | [V-MEM](delivery-validation.md#memory-comparison-tracks)、[V-PAL](delivery-validation.md#personal-companion-validation) |
| 自然语音与多人场景 | 真实房间/耳机/扬声器/噪声，中英混合；转写、首声、误打断及设备错误分项 | [语音](delivery-validation.md#voice-selection-evidence)、[V-DLG](delivery-validation.md#conversation-separation-validation) |
| 普通 PC 长时与全负载 | 当前机器和物理低配机器分开，真实语音/任务/索引/维护组合，记录后台进展和资源退化 | [PC 资源](delivery-validation.md#pc-footprint) |
| 真离线与跨版本数据恢复 | 固定运行包整机断网冷启动、缺组件/磁盘满/坏配置，导出恢复和任务不重放 | [K1/K2 出口](delivery-validation.md#next-k1-acceptance) |
| 技能效果是否稳定 | 每技能补失败类型、跨模型及独立保留样例；按模型/提示/配置分组报告，避免只报总平均 | [V-SKL](delivery-validation.md#skill-selection-validation) |
| 成长是否确实有益 | 真实未解决需求、基线与保留集、独立验证、采用后实际调用、代价与回退 | [净收益](delivery-validation.md#bootstrap-8)、[V-PAL-10](delivery-validation.md#personal-companion-validation) |
| 双节点与虚拟/现实边界 | 先两节点/一个域与小型 NPC 场景，加入乱序、冲突、断连、删除和任务重复 | [扩展验收](delivery-validation.md#extensions-6) |

性能数据必须标清临时核心还是线上 Host、进程还是整机、RAM 工作集还是私有提交量、GPU 专用还是共享、是否包含浏览器及模型权重。不要用约 32 MiB 的临时核心空闲峰值代表整套本地语音助手占用。负载测量的模型替身、真实云调用和真本地推理分别报告。

<a id="direction-release"></a>
## 8. 如何持续维护这份指南与完成一次迭代

本文是滚动指南，历史由 Git 保存，不新增“下一步-v2-final”副本。每次发布后：

1. 核对实际源码提交/标签、运行版本与实例、模型/配置/验证器摘要；不能只凭 `__version__` 推断当前能力。
2. 在[验收章](delivery-validation.md#versioned-evidence)登记本轮证据和失败，更新主题页实际语义；有接口变化同时更新契约。
3. 更新本章对应 F 项的剩余差距，以及核心章的当前推进队列。已完成子项移出“待实现”，局部通过仍保留未验范围，不累加旧测试数量伪造覆盖率。
4. 将本轮事实摘要链接到首页；manifest 与篇章归属同步。源码、运行数据、报告、文档状态有各自所有者，避免并行会话各自宣称统一发布。
5. 运行导航同步与文档检查；代码变化按实际影响做回归与发布核对。文档检查不能代替模型、性能或功能测试。

每个准备实施的 F 子项应明确：用户可见问题、复用对象、允许改动、输入/产物、状态所有者、失败与恢复、资源/模型预算、冻结判据、回滚办法和对应 K/V 编号。缺少这些材料时先缩小子项，而不是增加不可复核的“整体智能提升”承诺。

本次指南只整理与修正文档，不启用额外后台工作、录音、下载、云评测或清理；后续实施沿用户实际要求和既有授权推进。

<!-- book-footer:start -->
[返回全书目录](README.md#book-tree) · [上一章：最小核心、初始资产与开发路线](core-bootstrap.md) · [下一章：系统架构、运行边界与模块职责](architecture.md)
<!-- book-footer:end -->
