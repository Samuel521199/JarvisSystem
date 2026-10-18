---
name: rea-software-analysis
description: Analyze a user-selected JavaScript or Electron application directory or ASAR package using Jarvis's fixed REA adapter. Use for software structure, module relationships, bridge APIs and IPC paths. Do not use for concept questions, source editing, mechanical diagrams, native executables, Android, runtime tracing or recovery of private cloud code.
---

# 软件结构与行为解析

1. 确认用户的分析目标与所选项目内应用目录或 ASAR 包。没有提供软件时先用自建样例，不猜测用户磁盘中的目标。
2. 使用 Jarvis 技能任务，选择 `rea.software-analysis`，传入 `target_path`（项目内相对目录或 `.asar` 文件，空串表示项目根目录）。可选应用根目录或 `dist`、`build` 等发布子目录。需要关注具体通道或文件时传入可选 `focus` 字面标识符；也可从需求中的引号标识符或通道名自动提取，不能当作语义分析。宿主负责策略、依赖、路径、预算、取消和账本。
3. ASAR 经宿主核对容器索引、成员范围、可选 SHA256 与 `.asar.unpacked` 所需文本文件后，以筛选后的目录快照交给 REA；保留原包摘要、成员路径与字节偏移。它不运行目标、不保证运行时行为。读取经过核对的文本报告；查看摘要的省略数量，按需浏览关系、节点、文件和排除范围的证据分页，按字面标识符筛选或清空筛选，或下载独立保存的完整证据 JSON。先列输入范围、摘要与证据编号，再解释模块、桥接 API 和 IPC 路径。引用源位置与 edge_id。分页标注截短的条目需读取完整证据后才能据此下结论。
4. 区分语法中观察到的事实、静态推导和运行时未验证项；找不到关系不等于关系不存在。结论不能超过证据覆盖范围。
5. 用户需要中文解释时，在同一技能任务显式设置 `explain=true` 和明确的 `provider::model`。宿主仅装配有界的相关证据摘要，最多调用一次；没有证据时为零次。默认 `explain=false`，完整应用包不上传。报告分观察、推断和未知事项，E 引用绑定本次原始关系；引用存在不保证结论正确，不能把无法验证说成不存在或错误。解释格式错误、来源变化或调用未知时不交付成功报告，不自动重发。
6. 主进程目录可能只有 IPC 注册（`handles`）而没有渲染端调用；可以说明注册通道和源位置，不能仅凭注册关系解释函数体或返回值。宿主保留原证据的 observed/inferred 分类，模型不得把静态推导提升为观察。完整目录超限时明确报告原因；另选子目录的结果只能代表该子目录。
7. 用户需要复刻功能时，将已观察的行为整理为规格与验收案例，再交给编程技能。静态解析本身不代表已实现或测试了目标功能。

这是一个完整组合技能：目录 / ASAR 快照、REA 静态解析、关系整理、可选中文解释、证据交付属于同一流程。REA 上游其他维护技能不作为用户菜单项。具体实现范围和限制以 Jarvis 任务执行器返回的运行状态为准。
