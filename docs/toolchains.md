# 开发环境、多语言工具链与构建

> 状态：proposed（设计基线，尚未实现） · 更新：2026-10-15  
> [文档入口](README.md) · [维护规则](MAINTENANCE.md) · [架构图册](architecture-atlas.md)

<!-- book-nav:start -->
[全书目录](README.md#book-tree) › [第四篇 · 自主成长与维护](README.md#part-evolution) › 第 15 章 · 开发环境、多语言工具链与构建

## 本章导航

- [15.1 自带开发环境与多语言自我开发平台](#development-platform)
  - [15.1.1 需求定义与交付形态](#development-platform-1)
  - [15.1.2 三环境与职责](#development-platform-2)
  - [15.1.3 图 E：从自编源码到正式运行](#development-platform-3)
  - [15.1.4 开放接口：ToolchainProvider 与 RuntimeProvider](#development-platform-4)
  - [15.1.5 开发包内容与初期选择](#development-platform-5)
  - [15.1.6 构建清单示例](#development-platform-6)
  - [15.1.7 真正离线与可复现](#development-platform-7)
    - [15.1.7.1 有界 Python 离线依赖配方（0.1.69）](#bounded-python-dependencies)
    - [15.1.7.2 Python 包与 JavaScript 场景配方（0.1.70）](#bounded-package-scene-recipes)
  - [15.1.8 跨平台并非一个编译开关](#development-platform-8)
  - [15.1.9 来源证据与发布权](#development-platform-9)
  - [15.1.10 工具链本身的更新与退役](#development-platform-10)
<!-- book-nav:end -->

<a id="development-platform"></a>
## 自带开发环境与多语言自我开发平台



<a id="development-platform-1"></a>
### 需求定义与交付形态

**完整研发节点必须能够在断开互联网和共同体后，使用已安装开发包修改、构建、测试当前获支持的 Jarvis 实现及技能。** 新语言、新平台和新依赖可以由 Jarvis 自主选择并准备，但必须先具备对应工具链、许可、存储、目标验证条件和已有授权。它不等于所有设备预装所有编译器，也不等于网络中断时可以凭空获得缺失 SDK。

| 安装形态 | 包含内容 | 承诺 |
|---|---|---|
| 运行节点 | 已发布程序、运行时、本地模型/语音包及恢复材料 | 离线执行已支持能力；按节点等级配置 |
| 研发节点 | 运行节点 + 工具链、构建器、验证器、候选源码 | 可为已准备生态自主开发 |
| 离线研发节点 | 研发节点 + 指定版本完整依赖闭包、SDK、测试资源与离线重建记录 | 在验收矩阵内断网开发与重建 |
| 轻节点 | 交互和少量本地能力 | 不宣称拥有完整离线研发能力 |

普通 Windows PC 默认从运行节点安装开始；当前开发机可继续承担研发验证，但不代表所有用户都要安装离线研发包。进入 K3 时先为当前实现与技能准备一个所需生态，再按具体任务增加其他语言。完整离线研发能力仍须准备对应依赖闭包并验收，不能仅靠远端工具声称实现。开发包的安装成本、缓存、内存峰值和构建时间与[离线模型包](models-offline.md#local-survival)一起测量；极低资源时保留恢复、交互和已发布工具，暂停构建。部署准入遵守[普通 PC 优先规则](stack-project-layout.md#technology-selection-4)。

<a id="development-platform-2"></a>
### 三环境与职责

| 环境 | 能访问的资源 | 禁止拥有的能力 |
|---|---|---|
| 生产运行 | 已发布包、声明的运行依赖、限定业务能力 | 任意候选脚本、可写编译器目录、共享开发账户凭据 |
| 隔离构建 | 候选源码快照、只读工具链、只读缓存、有限临时空间 | 生产凭据、任意主人目录、真实设备控制、发布私钥 |
| 独立验收 | 候选产物、受保护测试、模拟或专用测试设备 | 修改通过标准、直接替换生产、自签发布权限 |

下载准备与执行构建进一步分离：受控下载器按清单和来源策略准备材料，构建环境默认无网络。编译器插件、构建后端、安装钩子和代码生成器都可以执行程序，必须从准备阶段就视为待约束工作负载。可信构建缓存只接受来源已验证的不可变对象；候选过程不能把任意文件写回可信公共缓存。

<a id="development-platform-3"></a>
### 图 E：从自编源码到正式运行

![build-and-release](diagrams/build-and-release.png)

[矢量图](diagrams/build-and-release.svg) · [可编辑图源](diagrams/build-and-release.mmd)


图中的逻辑角色可由少数服务实现，不新增一套与任务账本竞争的调度系统。BuildRequest 本身是持久任务，重试有预算；Artifact 是不可变产物。生产启动无需编译器在线，构建器损坏也不能阻止停止和恢复。

<a id="development-platform-4"></a>
### 开放接口：ToolchainProvider 与 RuntimeProvider

`ToolchainProvider` 提供：`ProbeHost`、`DescribeTargets`、`ResolvePlan`、`PrepareOfflineClosure`、`Build`、`Test`、`Package`、`ExportEvidence`。方法返回结构化状态、产物和诊断，不只返回自由文本日志。

`RuntimeProvider` 提供：`ProbeArtifact`、`Start`、`Health`、`Drain`、`Stop`、`Checkpoint`（如支持）。它负责运行已发布产物，不兼任生成源码、安装依赖或自我授权。程序不支持检查点时必须如实声明，不能自动序列化任意进程内存。

可支持的产物类型包括原生独立进程、Python/Node 包、.NET/JVM 产物、适用的 WASI 组件和 OCI 镜像。通用“命令配方”适配器负责常规生态，主力语言再增加更严格的专用适配器。选择接口兼容的实现不要求 Jarvis 本身迁移到相同语言。

加入一种新语言的准入步骤：

1. 检查工具链、目标平台、许可和系统需求，生成版本固定的工具链包提案。
2. 准备安装源与依赖闭包，在隔离环境安装；系统级安装通过受保护的有限安装接口，不将管理员权限交给研发 Agent。
3. 编译或封装最小契约样例，验证输入输出、取消、超时、日志和资源边界。
4. 在目标运行环境验收，记录支持矩阵后启用。
5. 在预算内逐步用于真实任务；失败可撤回新包，保留原有能力。

不能因为模型能生成某语言的文本，就把该语言显示为“可构建且可运行”。

<a id="development-platform-5"></a>
### 开发包内容与初期选择

| 开发包 | 随当前参考实现准备的材料 | 独立升级注意事项 |
|---|---|---|
| Rust | 锁定编译器、Cargo、目标标准库、依赖源、链接所需材料 | 版本并存；只升级编译器不会自动更新全部系统 SDK |
| Windows Native | 所需 MSVC Build Tools、Windows SDK、链接器与目标库 | 按组件布局固定；部分组件需安装或管理员服务，不能假设都可便携解压 |
| Python | 固定解释器、uv、目标平台 wheels、必要源码构建依赖 | 生产环境不使用 editable 安装，不在启动时自动改锁文件 [S50](references.md#s50) |
| Node/TypeScript | 固定 Node、pnpm、锁文件对应包、前端构建资源 | 若首期没有前端源码则可后装；当前完整构建配方需要时必须预装 |
| 通用工具 | Git、契约生成器、按需 CMake/Ninja、测试与打包工具 | 不要求每个配方都依赖全部工具 |
| 扩展生态 | Go、.NET、JDK、C/C++、Swift、其他领域语言等 | 有任务需要再准备对应包，不扩大基础常驻体积 |

优先复用各生态原有构建器。Jarvis 不自研通用编译器，也不在第一版重造 Bazel/Nix/通用包管理器。统一的是输入快照、工具链身份、执行隔离、证据和运行契约。将来需要更复杂构建缓存或远程执行时，再通过构建提供者接入成熟系统。

<a id="development-platform-6"></a>
### 构建清单示例

以下 YAML 说明字段关系；摘要为占位值，实际准入要求真实且可校验的摘要。参数以数组传递，默认不经 shell 拼接。必须使用 shell 时，配方需明确解释器、固定脚本和受控变量。

```yaml
api_version: jarvis.build/v1
build_id: build-example-001
task_ref: task-example-001
source:
  snapshot_digest: "sha256:<immutable-source-tree>"
  repository_commit: "<commit-if-available>"
  patch_digest: "sha256:<patch-or-empty-object>"
toolchain:
  provider: python
  bundle_digest: "sha256:<toolchain-bundle>"
  recipe_digest: "sha256:<reviewed-build-recipe>"
environment:
  template_digest: "sha256:<isolated-environment>"
  host: windows-x86_64
  target: windows-x86_64
  network: denied
  readable_mounts: [source, toolchain, dependency-store]
  writable_mounts: [scratch, output]
dependencies:
  lock_digest: "sha256:<lockfile>"
  closure_digest: "sha256:<all-build-and-runtime-inputs>"
  missing_policy: fail
steps:
  - executable_ref: toolchain.python
    argv: ["-m", "build", "--no-isolation", "--wheel"]
artifact:
  kind: python-wheel
  runtime_profile: python-windows-x86_64-v1
  contract_ref: jarvis.capability/v1
verification:
  targets: [windows-x86_64]
  suite_ref: capability-contract-and-heldout-v1
limits:
  cpu_cores: 2
  memory_mib: 2048
  scratch_mib: 4096
  wall_seconds: 600
authorization:
  grant_ref: maintenance-budget-example
  publication_scope: candidate-only
```

该例选择 `--no-isolation` 是在**已有外层隔离且预置构建依赖**的环境里避免隐式创建和下载依赖，不表示关闭 OS 隔离。这些资源数字只是一个小工具配方示例，不是编译完整 Jarvis 的硬件承诺。旧配方中的未锁定“最新版本”不得进入生产构建。

<a id="development-platform-7"></a>
### 真正离线与可复现

离线闭包包含：源码、补丁、锁文件、直接与传递依赖、构建期依赖、目标 SDK/sysroot、运行时、打包器、代码生成输入和测试素材。预下载模型包与编译包分别登记，不能混称“已有离线缓存”。

Cargo vendoring 可保留依赖源 [S49](references.md#s49)；pnpm fetch 可用于准备依赖，但本地 `file:` 依赖仍需另行包含 [S44](references.md#s44)；VS 离线布局只有选定组件，缺项不能在封网构建中回源补齐 [S43](references.md#s43)。因此验收必须在干净候选工作区、屏蔽宿主全局 PATH、关闭网络的环境重建。缺项返回 `MISSING_OFFLINE_DEPENDENCY`，不悄悄联网、放宽锁文件或借用生产全局安装。

区分三个结论：

- **来源可追溯：**能说明输入、构建者和输出分别是什么。
- **过程可重做：**同一配方和材料可以再次完成构建。
- **字节可复现：**独立构建得到完全相同输出摘要。

前两项不自动证明第三项。时间戳、绝对路径、签名封装和构建器行为都可能影响字节；不满足字节复现时报告差异及验证方式。发布签名可作用于已记录摘要，不用修改来源信息来“凑”一致。

<a id="bounded-python-dependencies"></a>
#### 有界 Python 离线依赖配方（0.1.69）

**implemented；限定验证见[依赖构建证据](delivery-validation.md#coding-dependencies-evidence)。** 新配方 `python-jmespath-v1` 用于嵌套 JSON 查询、筛选与报告。它延伸已有编码任务和改进单，不新增执行队列、环境管理器或常驻服务；原 `python-source-v1`、`python-zipapp-v1` 保留原固定启动器与字节重建规则。

- **依赖准入：**首个登记库为 [JMESPath 1.1.0](https://pypi.org/project/jmespath/1.1.0/)（MIT）。上游 wheel 为 20,419 字节，无 Requires-Dist。原包保存在 `third_party/coding/`，来源、版权见 NOTICE；`coding_dependencies.py` 固定版本、SHA256、长度和导出接口。构建只读数据，不在 Host 导入库、不执行 wheel 脚本或构建钩子，不使用 pip，也不从本机全局环境补依赖。
- **缺项与修改：**受理时检查完整 wheel，缺失为 `missing_offline_dependency`，摘要不符为 `coding_dependency_invalid`，都在模型调用前拒绝。排队后丢失或损坏也停止构建；不得联网补齐、放宽锁定或自动换库。普通无依赖配方不需要该 wheel。原包属于可随版本分发的开发资产；修复缺项应恢复已登记原包，新库需另审查并登记，模型不能用任务参数添加任意 URL 或版本。
- **运行接口：**沿用 1—4 个同目录模块与 `transform(data)→str`。额外提供 `jmespath.search(expression, data)` 和 `json.dumps`；查询表达式最多 4 KiB，不开放 Options、自定义扩展或其他库。候选源码继续静态检查，第三方库视为已锁定的受信执行依赖；两者仍在真实 LPAC Worker 内运行，AST 检查本身不是 OS 安全边界。
- **验收与产物：**该配方的源码检查通过后直接构建候选 PYZ，在 Worker 中用公开/留出输入运行；最终交付包再以实际归档入口复验。模型只得到公开案例和公开失败反馈。包内含源码、固定启动器、依赖库源码、原许可证/METADATA 和清单；不携带 wheel 的命令行脚本、案例答案或账户信息。清单绑定原 wheel、每个库文件、候选源码及案例摘要。
- **离线与兼容：**交付包在已有 CPython 3.11—3.13 上即可运行，不依赖 Jarvis 或全局 JMESPath。Jarvis 的严格重建仍需要同版本配方与已登记 wheel；重建器逐字节比较整个包，不执行 Host 候选。包最多 64 KiB，新配方最多 17 个成员、展开最多 128 KiB；原配方仍保留 7 个成员/48 KiB 展开限制。库只在临时 Worker 按需加载，既有每 Worker 192 MiB、12 秒与任务 240 秒上限不变；这是限制，实际资源消耗见验收证据。
- **应用与后续：**应用/恢复仅操作被冻结的项目源码；不会向原项目安装依赖。需要直接运行时使用自带依赖的 PYZ；源码导入后的环境由相应项目管理。下载包手动执行使用当前账户权限，并不自动创建 LPAC。此版本不支持任意 wheels、原生扩展、传递依赖求解、通用 package 布局或新语言工具链；后续按新版本配方扩展，不改变旧配方解释。

<a id="bounded-package-scene-recipes"></a>
#### Python 包与 JavaScript 场景配方（0.1.70）

**implemented；本轮闭环验证归[K3 收口清单](delivery-validation.md#k3-closure-matrix)。** 各配方独立版本，保持旧启动器的字节解释；共同使用原任务、冻结案例、候选目录、明确应用和恢复，没有新增常驻服务。

| 配方 | 输入与构建 | 交付 |
|---|---|---|
| python-package-v1 | 1—8 个 .py、最多三级子目录；所有父包 __init__.py 显式选择；可绝对/相对包内导入，禁止循环与清单外模块 | 固定 PYZ 启动器、模块映射、源码与摘要 |
| python-package-query-v1 | 同上，额外使用[固定 JMESPath 接口](#bounded-python-dependencies) | PYZ 自带库及许可；不向原项目安装 |
| javascript-scene-v1 | 一个 .js，transform({phase:角度}) 返回 JSON 帧字符串；公开及留出案例后另编译 0—355°、间隔5°的72帧 | candidate-scene.zip：源码、frames.json、固定 scene.html、清单与说明 |

包目录不是任意 Python 工程执行：每文件16 KiB、合计32 KiB不变，__init__.py 可为空，不执行 setup.py、钩子或自动发现。入口不能是包初始化文件，模块不得覆盖固定运行库。新增文件必须同时列入 paths 和 new_paths，冻结不存在状态；文件创建/恢复规则归[编程工作流](tasks-agents.md#bounded-coding-workflow)。包工具仍需兼容 CPython，最多21个归档成员、128 KiB展开；旧配方限制不变。

场景执行器使用 [QuickJS-NG Python binding 0.17.0.1](https://pypi.org/project/quickjs-ng/0.17.0.1/) 的 Windows AMD64 abi3 wheel（519,389字节，MIT）。版本/摘要固定于 coding_js.py，来源及上游许可保存在 third_party/coding；缺失或被修改在调用模型前拒绝，不联网安装或替换。它提供独立上下文和资源限制，见[上游接口](https://github.com/genotrance/quickjs-ng)。原生库只在短命 Worker 装载，实际隔离规则归[执行边界](security-sovereignty.md#bounded-coding-boundary)，不是扩大整个 Host 的第三方环境。

每帧仅包含 parts（2—24项），跨帧 id/kind 顺序一致。部件含 id、kind、color、x/y；line 再含 x2/y2，circle 含 r，rect 含 width/height。坐标/尺寸为0—1000内有限数、尺寸正数；颜色只允许 #RRGGBB，标识符限定 ASCII。固定1000×600画布不接受生成 HTML、事件、URL或可执行字符串。查看器支持播放/暂停、相位、展开、键盘和减弱动效；真实浏览器核对后才交付。查看器仅显示预计算帧，曲柄、连杆等运动关系必须来自本次生成源码，不能用固定齿轮替代。数值案例和取样不等于连续物理验证、CAD/制造图或工程安全认证，视频仍在后续阶段。

场景包最多64 KiB压缩、1 MiB展开。读取时按固定配方重建并逐字节核对；实际复验重新运行包内源码，帧摘要必须相同，再运行独立案例。下载者解压后离线打开 scene.html 即可，不需要 Python；开发者通过现有 coding_build.py 离线复验则需要 Jarvis 的已锁定执行器。无浏览器/模型常驻实例；现场资源值见本轮证据。

<a id="development-platform-8"></a>
### 跨平台并非一个编译开关

| 构建与运行形态 | 适合 | 必须额外验证 |
|---|---|---|
| Windows 原生 | 桌面桥、服务、Windows SDK 集成 | 实际 OS/CPU、会话权限、安装与卸载 |
| Linux 原生或隔离 VM | 后端、部分模型服务、工具构建 | 内核/运行库、设备映射、模型驱动 |
| 交叉编译 | 明确目标的程序与嵌入式工具 | 目标头文件、库、链接器、ABI，以及目标设备执行 [S42](references.md#s42) |
| macOS/iOS | Apple 原生模块 | 匹配的 Mac/Xcode/SDK、目标系统与必要签名条件 [S48](references.md#s48) |
| WASI 组件 | 受限计算、格式处理、明确接口的插件 | 语言/运行时支持及宿主能力，不默认支持桌面、GPU和所有原生库 [S45](references.md#s45)[S46](references.md#s46) |
| OCI 镜像 | 可隔离打包的服务和构建环境 | 宿主平台、内核/镜像兼容、实际隔离模式；不是万能跨 OS 包 [S47](references.md#s47) |

分别记录 `built`、`contract-tested`、`target-validated`、`release-admitted`。仅交叉编译成功不能提升为“目标平台支持”。缺目标设备时保存候选并等待，不把仿真或模拟器的结果冒充实机结论。

Windows 首期优先一个明确配置的本地构建 VM 或等效隔离方案；复用快照但每次工作区隔离。Windows Sandbox 的网络、共享和映射目录选项需要明确配置，不能直接沿用默认值并宣称安全。[S51](references.md#s51) WSL 可用于便利开发，但“在 WSL 里”本身不是足以隔离恶意候选代码的判据。

<a id="development-platform-9"></a>
### 来源证据与发布权

内容哈希识别文件，构建证明说明来源，发布签名授予生产准入；三者不能互相代替。证据至少关联源码快照、工具链/环境摘要、配方、依赖闭包、构建日志、产物摘要、运行依赖清单、目标验收与测试集版本。

可借用 SLSA 的 `buildDefinition`、`resolvedDependencies`、`builder.id`、`runDetails` 和产物 subject 表达来源；使用该格式不意味着自动达到任何 SLSA 安全等级，也不证明代码无缺陷。[S41](references.md#s41)

来源记录由候选环境外的构建控制器采集，独立验收服务签发测试结果，发布控制器核对一致的产物摘要。研发 Agent 不获得发布私钥，也不能自己修改保留测试后签发“通过”。远端构建节点按授权收到必要源码；私人源码是否离机由资料策略决定。离线本地发布采用预登记信任材料，不强制联网验签；在线后再接收新撤销信息。

<a id="development-platform-10"></a>
### 工具链本身的更新与退役

生命周期：发现 → 隔离准备 → 来源/完整性验证 → 离线重建与目标验收 → 可用 → 弃用 → 撤销或删除。

每个构建固定工具链和环境摘要；新版注册不改变正在执行的构建。新旧包并存，先对同一源码建立基线对照；收益包括质量、速度、空间或支持范围，不能仅因为版本号较新而替换。

删除前检查运行时引用、未完成构建、存量任务和回退版本；不得删除最后可用的恢复或开发包。共享磁盘不足时先暂停新实验、按引用回收缓存，保留明确的恢复空间。工具链更新失败只影响候选研发，不应停止已发布业务。

工具链维护服从[主人利益最高原则、独立监督与锁存关停](security-sovereignty.md#sovereignty-shutdown)锁存。安全停机后不能以“只是在编译修复补丁”为由继续自主活动；主人授权的独立维护流程另行处理。

<!-- book-footer:start -->
[返回全书目录](README.md#book-tree) · [上一章：自主进化、外部编码协作与版本发布](evolution-release.md) · [下一章：系统健康、防退化与自愈](health-maintenance.md)
<!-- book-footer:end -->
