# JARVIS

一个由主人掌控、能够长期相处并持续成长的类钢铁侠贾维斯个人 AI 助手与伙伴。自然交流、个人记忆、连续协助与自主学习进化共同构成核心；围绕主人的需要扩展编程、项目、设备和 Agent 等能力。目标支持离线独立运行、联网协同，已实现范围见下文。

项目代码仓库：[Samuel521199/JarvisSystem](https://github.com/Samuel521199/JarvisSystem)。仓库保存源码、锁定依赖清单、设计文档、图源和验证记录；本机凭据、业务数据库、模型、依赖缓存和构建的运行包不入库。首次运行按[安装与启动说明](docs/core-bootstrap.md#section-6a93004233bf)准备环境。

当前源码与部署版本为 **0.1.64**。新增[成长中心三能力拆分](docs/evolution-release.md#growth-governance)，后续按[当前推进队列](docs/core-bootstrap.md#near-term-work-queue)进入 K3 编码协作。新增[仅此软件离线开关](docs/models-offline.md#application-offline-control)，测试和部署见[本轮证据](docs/delivery-validation.md#application-offline-evidence)。已补称呼与交流配置、相关记忆/接续、三库查询及存储争用修复；[完整 K2 收口与验收状态](docs/delivery-validation.md#k2-completion-evidence)统一列出完成项和未验条件。新增[多轮记忆最终回答先导与能力说明修正](docs/delivery-validation.md#memory-final-answer-evidence)。新增[规则与语义记忆入口统一核对](docs/delivery-validation.md#rule-memory-review-evidence)。新增[混合聊天到样例报告、指定取消和未开始任务修订](docs/delivery-validation.md#mixed-report-admission-evidence)。这是以普通 PC 为主的个人助手与伙伴原型，已逐步接入个人记忆、跨会话接续、项目文件工作区、技能与 MCP、语音和受限成长能力。新增[记忆重复与差异核对](docs/delivery-validation.md#memory-candidate-review-evidence)，以及[限定编程闭环、技能验证状态与质量覆盖](docs/delivery-validation.md#skills-completion-evidence)。

**源码上传与正式部署分开记录。** 各功能的已实现、已验证和部署状态，以[当前进度](docs/README.md#project-status)及[分版本验收](docs/delivery-validation.md#versioned-evidence)为准；不能仅凭源码版本判断本机正在运行的版本。完整设计仍为 `proposed`，K1/K2/K3 尚未整体通过。

- [打开本机工作台](http://127.0.0.1:18181/)：服务未启动时按[本机启动与端口说明](docs/core-bootstrap.md#section-6a93004233bf)操作。
- [后续方向指南](docs/development-guide.md#direction-start)：现状、16项优化工作、全部原需求去向与未验边界；[当前推进队列](docs/core-bootstrap.md#near-term-work-queue)仍归唯一K路线。
- [全书章节树与阅读导航](docs/README.md#book-tree)：按篇、章、节、小节组织全部当前主题及后续技术文档。
- [个人助手与伙伴的核心定义](docs/product-requirements.md#personal-companion-core)：产品定位、体验判据及与扩展能力的关系。
- [当前实现、聊天入口与启动方法](docs/core-bootstrap.md#current-implementation)：从 K0 开始，K0—K6 是唯一实施顺序。
- [本地语音主备选型](docs/models-offline.md#voice-local-candidates)：[Qwen 主力](docs/models-offline.md#qwen-tts-runtime) 已获有限样本听感接受并接入文件合成；ZipVoice 默认停止备用；[真实速度、内存与限制](docs/delivery-validation.md#fast-speech-evidence)，[CosyVoice3](docs/models-offline.md#cosyvoice3-runtime) 按需增强情绪。
- [模型选择、用量提示与路由边界](docs/models-offline.md#configured-models)：取消本地累计调用次数上限，保留单次资源限制；支持显式 Eachlabs 余额查询与本实例费用估算。
- [个人核心联合日常验收](docs/delivery-validation.md#companion-journey-evidence)：人格、记忆、接续、任务与受限成长串联验证；完整 K2 仍有待验范围。
- [实际验证与限制](docs/delivery-validation.md#computer-queue-evidence)：排队、取消、崩溃对账、显式继续、真实网页与回归；单项测试通过不等于完整 Jarvis 达标。
- [文档维护规范](docs/MAINTENANCE.md)：主题权威、图源、变更和检查规则。

后续更新直接维护当前有效主题页，不再生成平行的总设计全文或旧版本副本。

在 Cursor 中，若页面顶部有 `Preview / Markdown`，先选 `Markdown`，再按 `Ctrl+Shift+V` 打开内置预览并单击链接；VS Code 也可使用此快捷键。源码视图使用 `Ctrl+单击`。详见[阅读与链接规范](docs/MAINTENANCE.md#stable-identifiers)。

**0.1.53 增量：**[技能与工具设置、带引用的 REA 中文解释及右侧报告](docs/delivery-validation.md#rea-explanation-workspace-evidence)已接入。默认本地解析；可明确选择模型生成解释，引用与推断分开核对。

项目资源与工程文件见[交互章](docs/interaction-persona.md#project-resource-workbench)；MCP 与额外技能登记见[设置说明](docs/interaction-persona.md#extension-management-ui)；可用的原生技能、源码报告和齿轮交互图见[技能入口](docs/core-bootstrap.md#native-skills-entry)。
