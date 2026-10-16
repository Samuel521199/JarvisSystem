# Jarvis 文档首页

这里是 Jarvis 项目的总入口。我们要做的是一个能在本机独立工作、联网后与其他设备协同，并逐步具备记忆、执行任务和自我改进能力的个人智能助手。

**部署方向：以普通 PC/笔记本为主，先 Windows，再按需求跨平台；能力按需扩展，默认安装保持轻量。** 具体约束见[普通 PC 优先规则](stack-project-layout.md#technology-selection-4)。

**第一次了解这个项目，先读 [Jarvis 要做什么、最终能做什么](product-requirements.md#product-definition)。**

> **在 Cursor 中打开链接：**打开整个 `Jarvis` 文件夹。若页面顶部有 `Preview / Markdown`，先选 `Markdown`，再按 `Ctrl+Shift+V` 打开内置预览（标签名为 `Preview README.md`），单击链接阅读对应文件。VS Code 也可使用此快捷键；源码视图使用 `Ctrl+单击`。更多说明见[阅读与链接规范](MAINTENANCE.md#stable-identifiers)。

[选择阅读入口](#start-here) · [查看当前进度](#project-status) · [查找专题](#quick-topics) · [完整文档目录](#book-tree) · [维护文档](#for-maintainers)

---

<a id="start-here"></a>
## 你现在想做什么？

| 目的 | 从这里开始 | 接着看 |
|---|---|---|
| **了解整个 Jarvis 构想** | [产品目标与能力](product-requirements.md#product-definition) | [系统架构图](architecture-atlas.md#overview) → [核心如何起步](core-bootstrap.md#bootstrap-1) |
| **启动并使用现有原型** | [启动方法与聊天入口](core-bootstrap.md#current-implementation) | [可选模型与切换方式](models-offline.md#configured-models) |
| **继续设计或开发** | [下一步具体工作](core-bootstrap.md#next-implementation) | [技术栈与代码结构](stack-project-layout.md#technology-selection) → [下一阶段验收](delivery-validation.md#next-k1-acceptance) |

<a id="project-status"></a>
## 目前做到哪里了？

| 状态 | 当前情况 |
|---|---|
| **已有可运行原型 · 0.1.18** | 新增[Windows 右下角托盘](core-bootstrap.md#windows-tray-entry)，可查看状态、打开界面和退出当前助手；验证见[托盘与待命资源](delivery-validation.md#tray-evidence)。保留任务恢复、项目根目录和会话停止。 |
| **下一步重点** | 按私人使用范围完成任务可靠性、离线与资源验收，随后推进 K2 工具循环、K3 开发协作；认证和全局监督延期，不再要求登记密钥。阶段状态见[推进表](core-bootstrap.md#next-implementation)。 |
| **仍属设计目标** | 长期记忆、多设备共同体、自主编程发布、完整语音交互和 NPC 世界等完整能力尚未实现。 |

以[当前实现说明](core-bootstrap.md#current-implementation)和[分版本验证记录](delivery-validation.md#versioned-evidence)为准。文档中的设计方案不代表功能已经上线。

<a id="quick-topics"></a>
## 直接查找你关心的内容

| 关注的问题 | 直接阅读 |
|---|---|
| **让模型操作网页、以后控制电脑？** | [网页任务面板](core-bootstrap.md#web-computer-console) · [模块架构](architecture.md#computer-use-design) · [实际验证](delivery-validation.md#k1-progress-evidence) |
| **知识与记忆怎么选？** | [开源方案比较](stack-project-layout.md#memory-open-source) · [记忆架构](knowledge-learning.md#memory-selection-design) · [小型嵌入模型](models-offline.md#embedding-candidates) |
| **单机如何变成多设备 Jarvis？** | [离线与联网模式](federation.md#offline-federation) · [记忆同步与冲突](federation.md#memory-replication) |
| **怎么同时聊天、执行任务和组织 Agent？** | [对话与任务并行](tasks-agents.md#end-to-end-flows) · [Agent 生成与分工](tasks-agents.md#agent-factory) |
| **怎么自己编程、升级，又避免越改越差？** | [进化与发布](evolution-release.md#self-evolution) · [健康与防退化](health-maintenance.md#system-health) |
| **人格、语音、NPC 和控制边界在哪里？** | [人格与交流](interaction-persona.md#persona-embodiment) · [NPC 世界](simulation.md#npc-world) · [权限与停止](security-sovereignty.md#identity-authorization) |
| **打开文件夹后怎样保存内容？** | [当前使用方法](core-bootstrap.md#project-workspace-entry) · [根目录与输出规则](interaction-persona.md#project-root-output) |
| **怎样做成类 Codex 的 Jarvis 应用？** | [工作台布局与功能](interaction-persona.md#desktop-workbench) · [打开文件夹](interaction-persona.md#workspace-folder-flow) · [输入区](interaction-persona.md#composer-design) · [设置与专属能力](interaction-persona.md#jarvis-distinctive-controls) · [图标候选](interaction-persona.md#jarvis-brand-icon) |

---

<!-- book-tree:start -->
<a id="book-tree"></a>
## 按主题查阅完整文档

点击章节名打开正文，正文顶部可跳转到具体小节。下面的编号是阅读顺序；开发顺序以核心章中的 K0—K6 为准。

<a id="part-product"></a>
### 第一篇 · 产品与体验

| 章 | 文档 | 这章回答什么 |
|---|---|---|
| 01 | [产品定义、需求与能力边界](product-requirements.md) | Jarvis 要解决什么问题，完成后能做什么？ |
| 02 | [桌面工作台、实时交流与人格形态](interaction-persona.md) | 怎样打开项目、输入任务、设置专属能力并与 Jarvis 交流？ |
| 03 | [NPC 小镇与虚拟世界](simulation.md) | 怎样运行 NPC 小镇，并隔离虚拟与现实？ |

<a id="part-foundation"></a>
### 第二篇 · 核心与工程基础

| 章 | 文档 | 这章回答什么 |
|---|---|---|
| 04 | [最小核心、初始资产与开发路线](core-bootstrap.md) | 现在怎么启动，核心从哪里做起，下一步做什么？ |
| 05 | [系统架构、运行边界与模块职责](architecture.md) | 模块怎样连接，谁负责什么，数据归谁管理？ |
| 06 | [主人利益原则、身份授权与停止控制](security-sovereignty.md) | 当前个人使用边界是什么，哪些监督与认证设计已延期？ |
| 07 | [公共接口与数据契约](contracts.md) | 模块之间怎样交换任务、事件和记忆数据？ |
| 08 | [技术栈、源码目录与运行数据](stack-project-layout.md) | 选哪些技术，代码放哪里，开源组件如何取舍？ |

<a id="part-runtime"></a>
### 第三篇 · 智能运行与多设备协同

| 章 | 文档 | 这章回答什么 |
|---|---|---|
| 09 | [模型路由、本地模型与离线生存](models-offline.md) | 用哪些云端和本地模型，怎样切换与离线降级？ |
| 10 | [记忆、知识库与持续学习](knowledge-learning.md) | 记住什么，怎样检索、纠正、遗忘和持续学习？ |
| 11 | [任务、动作、多 Agent 与资源调度](tasks-agents.md) | 怎样一边交流一边执行任务，如何组织多 Agent？ |
| 12 | [离线自治、多设备共同体与重连](federation.md) | 断网怎样独立工作，重连怎样共享记忆与协同？ |

<a id="part-evolution"></a>
### 第四篇 · 自主成长与维护

| 章 | 文档 | 这章回答什么 |
|---|---|---|
| 13 | [自主进化、外部编码协作与版本发布](evolution-release.md) | 怎样自编工具、改进模块，并验证和回退？ |
| 14 | [开发环境、多语言工具链与构建](toolchains.md) | 怎样准备编译环境，构建和测试不同语言的程序？ |
| 15 | [系统健康、防退化与自愈](health-maintenance.md) | 怎样发现故障与结构退化，清理和修复隐患？ |

<a id="part-evidence"></a>
### 第五篇 · 验证与参考

| 章 | 文档 | 这章回答什么 |
|---|---|---|
| 16 | [能力验收、故障演练与评估证据](delivery-validation.md) | 哪些能力测过，证据在哪里，下一阶段怎样验收？ |
| 17 | [架构决策、批判性评审与评分](decisions-review.md) | 为什么这样设计，有哪些不足和替代方案？ |
| 18 | [架构与流程图册](architecture-atlas.md) | 在哪里集中查看架构图和流程图？ |
| 19 | [研究资料与证据边界](references.md) | 设计和选型参考了哪些论文与官方资料？ |
| 20 | [文档维护规范](MAINTENANCE.md) | 以后怎样归类、更新、检查和清理文档？ |
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
| [core-bootstrap.md](core-bootstrap.md) | 当前启动、聊天、预检与独立控制操作、迁移、SeedBundle、知识/规则/技能种子、K0—K6 与阶段内工作包、首个演示 |
| [architecture.md](architecture.md) | 总体视图、部署、信任边界、数据所有权、唯一控制权威 |
| [security-sovereignty.md](security-sovereignty.md) | G0、权限、委派、安全代际、锁存、离线解锁 |
| [federation.md](federation.md) | 单机/局域网/外网模式、所有权、租约、记忆复制协议、同步选型与冲突 |
| [interaction-persona.md](interaction-persona.md) | 桌面工作台、项目文件夹与会话交互、输入区、功能入口与设置、品牌图标规范；语音通道、个性、性别表达、关系设定与形态 |
| [tasks-agents.md](tasks-agents.md) | 任务状态、动作账本、后台任务与有限工具循环、Agent 工厂、团队、预算与资源租约 |
| [models-offline.md](models-offline.md) | 当前模型目录/提供商参数/用量策略与有限路由；嵌入模型候选、生产路由、恢复入口、模型生命周期、LP 降级与网络诊断 |
| [knowledge-learning.md](knowledge-learning.md) | 首期运行时知识与会话边界、事实与派生索引分层、记忆来源、纠错/遗忘、学习晋升、知识结构迁移与防污染 |
| [evolution-release.md](evolution-release.md) | CodingProvider、改进事务、兼容、版本并存、灰度与回退 |
| [toolchains.md](toolchains.md) | 开发能力、构建配方、依赖闭包、目标验证与隔离 |
| [contracts.md](contracts.md) | 跨域契约、字段语义、只读预检与主人恢复消息、K1/K2 最小接口面、记忆组件替换契约、模块生命周期和公共事件 |
| [stack-project-layout.md](stack-project-layout.md) | 技术取舍、普通 PC 默认部署与组件准入、开源知识/记忆组件对照、唯一源码树、模块模板、运行数据树与依赖规则 |
| [health-maintenance.md](health-maintenance.md) | 观测、结构约束、文档/代码健康、退役清理、分级自愈 |
| [simulation.md](simulation.md) | 世界事实、角色、时间、精度、分支及现实效果隔离 |
| [delivery-validation.md](delivery-validation.md) | M 验收门、R/N 追踪、阶段出口验收、B/H/V-MEM/V-PC/V-UI 测试、选型探测、性能与故障证据 |
| [decisions-review.md](decisions-review.md) | ADR、历史设计评分、EV 证据等级、取舍与待验证假设 |
| [references.md](references.md) | 稳定 S 系列来源、使用范围与论据限制 |
| [architecture-atlas.md](architecture-atlas.md) | 19 张图的导航、图源和渲染说明 |
| [MAINTENANCE.md](MAINTENANCE.md) | 文档权威、章节树与技术文档归类、状态、增删改、检查、删除与历史规则 |

### 文档与资产结构

```text
Jarvis/
├── README.md                       # 简短项目入口
├── AGENTS.md                       # AI 维护约定
├── docs/
│   ├── README.md                   # 本页，完整导航和权威地图
│   ├── <topic>.md                  # 上表的20篇当前主题页
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

0.1.0—0.1.11 的历史证据与当前 0.1.12 聊天停止验证分别保留在[验收章](delivery-validation.md#versioned-evidence)；历史设计评分见[评审章](decisions-review.md#critical-review)，不能当作当前产品成绩。原文档迁移依据保存在 manifest 的 migration 字段。

已按主人 2026-10-16 的明确要求建立 Git，并关联 [Samuel521199/JarvisSystem](https://github.com/Samuel521199/JarvisSystem)；后续历史按[受控历史与退役规则](MAINTENANCE.md#retirement-and-history)管理。既有版本报告仍保留原时点的文件摘要，不补造历史提交。当前没有定时维护或自主修改程序，启动与运行边界见[核心章](core-bootstrap.md#current-implementation)。

</details>
