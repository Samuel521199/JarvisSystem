# JARVIS

一个由主人掌控、离线可独立运行、联网可协同，并通过受控编程与独立验证逐步成长的个人智能系统。

项目代码仓库：[Samuel521199/JarvisSystem](https://github.com/Samuel521199/JarvisSystem)。仓库保存源码、锁定依赖清单、设计文档、图源和验证记录；本机凭据、业务数据库、模型、依赖缓存和构建的运行包不入库。首次运行按[安装与启动说明](docs/core-bootstrap.md#section-6a93004233bf)准备环境。

当前种子原型为 **0.1.17**：新增启动前健康检查、故障时尝试上一个已验证版本，以及可查询的启动记录；保留任务数据、内存等待、会话停止与助手待命。使用方法见[核心入口](docs/core-bootstrap.md#current-implementation)，证据见[本轮验证](docs/delivery-validation.md#runtime-start-evidence)。完整设计仍为 `proposed`，K1/K2/K3 尚未整体通过；当前不要求恢复密钥或密码。

- [全书章节树与阅读导航](docs/README.md#book-tree)：按篇、章、节、小节组织全部当前主题及后续技术文档。
- [当前实现、聊天入口与启动方法](docs/core-bootstrap.md#current-implementation)：从 K0 开始，K0—K6 是唯一实施顺序。
- [模型选择、用量提示与路由边界](docs/models-offline.md#configured-models)：取消本地累计调用次数上限，保留单次资源限制；没有查询供应商余额。
- [实际验证与限制](docs/delivery-validation.md#computer-queue-evidence)：排队、取消、崩溃对账、显式继续、真实网页与回归；单项测试通过不等于完整 Jarvis 达标。
- [文档维护规范](docs/MAINTENANCE.md)：主题权威、图源、变更和检查规则。

后续更新直接维护当前有效主题页，不再生成平行的总设计全文或旧版本副本。

在 Cursor 中，若页面顶部有 `Preview / Markdown`，先选 `Markdown`，再按 `Ctrl+Shift+V` 打开内置预览并单击链接；VS Code 也可使用此快捷键。源码视图使用 `Ctrl+单击`。详见[阅读与链接规范](docs/MAINTENANCE.md#stable-identifiers)。
