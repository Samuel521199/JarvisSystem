# 模型路由、本地模型与离线生存

> 状态：完整路由 proposed；0.1.19 模型后台、Key 管理与费用估算 implemented / verified，真实接口范围按版本记录 · 更新：2026-10-16
> [文档入口](README.md) · [维护规则](MAINTENANCE.md) · [架构图册](architecture-atlas.md)

<!-- book-nav:start -->
[全书目录](README.md#book-tree) › [第三篇 · 智能运行与多设备协同](README.md#part-runtime) › 第 09 章 · 模型路由、本地模型与离线生存

## 本章导航

- [9.1 当前凭据、模型与调用边界](#configured-models)
  - [9.1.1 编码技能候选模型快照（2026-10-17）](#coding-skills-model-snapshot)
  - [9.1.2 2026-10-15 核验后的模型目录](#section-55d563b5f318)
  - [9.1.3 模型配置后台与费用口径（0.1.19）](#model-admin-config)
  - [9.1.4 Eachlabs Claude 独立调用核验（2026-10-16）](#eachlabs-claude-probe-config)
  - [9.1.5 Google 当前主流与本项目选择（0.1.4，2026-10-15 核验）](#google-model-selection)
  - [9.1.6 统一模型菜单与推理级别（0.1.3）](#reasoning-controls)
  - [9.1.7 当前路由和单次资源边界](#section-896f72aed9a9)
    - [9.1.7.1 当前宿主能力上下文与回答完整性](#runtime-chat-context)
    - [9.1.7.2 本地精确计算与能力分流（0.1.37 implemented）](#deterministic-calculation-runtime)
  - [9.1.8 本地小组件的当前选型](#section-4a9504a4187f)
  - [9.1.9 语音主选与候补：本地优先（2026-10-18）](#voice-model-selection)
    - [9.1.9.1 本地主选、备选与真实能力边界](#voice-local-candidates)
    - [9.1.9.2 内存、显存与模型文件分开预算](#voice-resource-footprint)
    - [9.1.9.3 Qwen 本地主力语音组件](#qwen-tts-runtime)
    - [9.1.9.4 ZipVoice 快速备用组件（2026-10-18）](#fast-speech-runtime)
    - [9.1.9.5 CosyVoice3 独立文件语音组件（2026-10-18）](#cosyvoice3-runtime)
    - [9.1.9.6 说话人识别、分段和重叠分离分开验收](#voice-overlap-separation)
    - [9.1.9.7 国内外云端候补与价格口径](#voice-cloud-candidates)
    - [9.1.9.8 资源与效果驱动的候补规则](#voice-routing-policy)
- [9.2 Computer Use：已验证的 DOM 规划与视觉候选](#computer-use-models)
- [9.3 本地嵌入模型的候选与资源边界（proposed）](#embedding-candidates)
- [9.4 双路模型连接与恢复设计](#model-routing)
  - [9.4.1 结论：需要独立恢复路径，生产与进化还需分配独立资源](#model-routing-1)
  - [9.4.2 通道设计](#model-routing-2)
  - [9.4.3 路由输入与选择顺序](#model-routing-3)
  - [9.4.4 流式回答与工具调用](#model-routing-4)
  - [9.4.5 自检、自愈、进化的模型与档位策略](#growth-model-policy)
    - [9.4.5.1 备选切换的确定规则](#growth-fallback-policy)
    - [9.4.5.2 Token、费用与普通 PC 的资源预算](#growth-budget-policy)
  - [9.4.6 路由流程图](#model-routing-5)
- [9.5 本地小模型、离线生存与网络自恢复](#local-survival)
  - [9.5.1 当前小模型运行、启停与资源边界（0.1.32）](#local-model-runtime)
  - [9.5.2 目标：在较低资源下仍保留有用能力](#local-survival-1)
  - [9.5.3 本地组件种类](#local-survival-2)
  - [9.5.4 离线能力包内容](#local-survival-3)
  - [9.5.5 资源 Profile](#local-survival-4)
  - [9.5.6 自主切换与替换](#local-survival-5)
  - [9.5.7 资源不足时如何换模型](#local-survival-6)
  - [9.5.8 网络诊断和修复](#local-survival-7)
  - [9.5.9 所有恢复从属于 G0](#local-survival-8)
<!-- book-nav:end -->

<a id="configured-models"></a>
## 当前凭据、模型与调用边界

当前已有文本诊断与聊天适配；0.1.2 在 0.1.1 的有限路由上增加每家多个可选模型和独立参数档案，0.1.3 增加跨供应商统一选择与请求级推理调节，仍不是下文设计的完整自主生产路由。0.1.19 的配置与费用权威规则见[模型配置后台](#model-admin-config)，提供商调用实现为 [gateway.py](../adapters/models/provider-native/jarvis_models/gateway.py)，会话层为 [ChatService](../runtime/node-host/jarvis_core/chat.py)。

按主人最新授权，`usage_policy=notify_on_provider_exhaustion`：**取消本地累计调用次数上限**，不再因过去调用了几次而阻断新请求。供应商明确返回额度耗尽时提示；现有调用历史和 UNKNOWN 记录继续保留，不通过删除账本恢复“额度”。不自动查询账户余额；0.1.19 允许在后台显式查询 Eachlabs 账户余额，其余供应商额度仍以账户账单为准。

额度通知依据供应商错误码，而不是累计调用数。明确的余额、账单或用量额度错误归为 `quota_exhausted`；仅有 HTTP 429 时归为 `rate_limited`，提示限流或配额受限，不能直接断言余额已耗尽。不同供应商的 429 也可能表示速率、项目配额或共享容量不足。[S71](references.md#s71)、[S72](references.md#s72)、[S73](references.md#s73)

2026-10-17 后续测试偏好：常规 live 技能验证优先官方 Google Vertex，当前选已有成功历史的 `gemini-3.1-pro-preview` 作为测试默认；这是验收工具偏好，不修改聊天路由。哪些检查可复用、哪些必须在目标接入方验证，唯一规则见[测试模型选择与最小验证范围](delivery-validation.md#model-test-selection)。用户提供余额较充足的信息，本轮未查询账户余额。

<a id="coding-skills-model-snapshot"></a>
### 编码技能候选模型快照（2026-10-17）

此表来自当日本机 0.1.34 的只读 `/api/models`，不是厂商全量目录。6 条线路、20 个档案中，17 个最近记录为 `SUCCEEDED`、2 个 `UNKNOWN`、1 个 `FAILED`。这些是历史探测结果，不是本轮实时调用验收；UNKNOWN 可能包含超时/取消等未确定结果，不能直接认定模型不可用。账户余额、今日剩余额度和完整编程质量未在本轮验证；[本轮静态评估记录](../evals/reports/matt-pocock-skills-review-2026-10-17.json)保存脱敏快照。

| 已配置线路 | 档案数 | 最近历史探测状态 |
|---|---|---|
| Google Vertex | 5 | `gemini-3.8-flash`：UNKNOWN；`gemini-4-argon`：UNKNOWN；`gemini-3.1-pro-preview`：SUCCEEDED；`gemini-3.5-flash-lite`：SUCCEEDED；`gemini-3.1-flash-lite`：SUCCEEDED |
| 阿里云百炼 | 4 | `qwen3.8-flash`：SUCCEEDED；`qwen3.8-max`：SUCCEEDED；`qwen3.7-plus`：SUCCEEDED；`qwen-flash`：SUCCEEDED |
| OpenAI | 5 | `gpt-6-luna`：SUCCEEDED；`gpt-6.1-sol`：SUCCEEDED；`gpt-6-astra`：SUCCEEDED；`gpt-6-sol`：SUCCEEDED；`gpt-5.6-luna`：SUCCEEDED |
| xAI | 2 | `grok-4.7`：SUCCEEDED；`grok-4-1-fast-non-reasoning`：SUCCEEDED |
| 本机 Qwen | 1 | `qwen3-0.6b`：FAILED |
| Eachlabs | 3 | `anthropic/claude-sonnet-5.5`：SUCCEEDED；`anthropic/claude-opus-5.5`：SUCCEEDED；`anthropic/claude-haiku-5.5`：SUCCEEDED |

本地 `127.0.0.1:18180/v1/models` 在本轮能返回 `qwen3-0.6b`，只证明引擎响应模型列表；它与历史聊天失败记录并不矛盾。已有[限定离线任务](delivery-validation.md#offline-task-evidence)通过不能推导通用编码能力；[并行实测](delivery-validation.md#parallel-runtime-evidence)仍记录普通答案正确性失败，因此不选 0.6B 作为编程实现/最终审阅模型。

**候选分工（proposed，未做编码排名）：**

- 日常实现优先比较 **OpenAI `gpt-6.1-sol`** 与 **Eachlabs `anthropic/claude-sonnet-5.5`**。前者的复杂编码定位有官方说明，后者在本项目已有文本连通证据；两者的本项目实际编程增益仍待对照。复杂任务先比较 medium/high 推理，记录质量与成本；现有默认 low 不是上游官方推荐的统一质量基线。[S174](references.md#s174)、[Eachlabs 短调用证据](delivery-validation.md#model-admin-evidence)
- 复杂故障、跨模块设计或重要审阅候选为 **`gpt-6-astra`** 与 **`anthropic/claude-opus-5.5`**。用真实同任务结果决定是否值得升级，不根据模型名称宣称已经优于另一条线路；不必每轮同时调用。
- 小范围草拟、需求整理、摘要与机械修改候选为 **GPT-6 Luna、Qwen3.8 Flash/Max、Qwen3.7 Plus、Gemini Flash 系列、Claude Haiku 5.5、Grok 4.1 Fast**；**Grok 4.7 / Gemini 3.1 Pro** 也可加入同任务比较。Gemini 3.8 Flash 与 Gemini 4 Argon 曾有 0.1.20 小样例成功，但当前最后记录为 UNKNOWN，使用前应单独核对。Haiku 5.5 在 10-16 有成功记录，10-17 所读 Eachlabs 当前价表未明确列出该 ID，继续以实际返回为准。[S175](references.md#s175)

Claude 当前通过 Eachlabs 配置，没有已配置的 Anthropic 官方线路。当前自动路由默认 Vertex，备选是百炼、OpenAI、xAI、本地，**不包含 Eachlabs**；OpenAI 路线默认又是 Luna。因此编程作业应绑定明确的线路、模型与推理档位，不能用“自动”选项代表上述候选方案。若未来接 OpenAI 工具调用，GPT-6.1 Sol / Astra 按官方要求走 Responses；现有文本成功不证明已实现该工具协议。[S174](references.md#s174)

效果预期以[技能选型结论](stack-project-layout.md#matt-pocock-skills-evaluation)为准；既有聊天小样例、短文本探测和结构化报告均不属于代码修改基准。Eachlabs 当前公布 Sonnet 5.5 输入/输出为每百万 Token 2/10 USD，Opus 5.5 为 4/20 USD；按单次 10,000 输入与 2,000 输出估算为 0.04/0.08 USD，未计附加费、缓存、推理计费差异与后续轮次。完整作业必须累加所有请求的实际记录，不能把一轮单价作为全任务费用承诺。[S175](references.md#s175)

<a id="section-55d563b5f318"></a>
### 2026-10-15 核验后的模型目录

下表是[初始模型配置](../config/model-profiles/providers.json)的 17 个基础档案；启用后台后的有效配置位置见[配置后台规则](#model-admin-config)。[catalog.py](../adapters/models/provider-native/jarvis_models/catalog.py)负责校验与请求级选择。提供商的认证、区域和端点与模型档案分开；增加同协议模型通常只需新增配置和兼容验证。

| 提供商 | 当前默认 | 可手动选择的其他模型 |
|---|---|---|
| Google Vertex | `gemini-3.8-flash` | `gemini-4-argon`、`gemini-3.1-pro-preview`、`gemini-3.5-flash-lite`、`gemini-3.1-flash-lite` |
| OpenAI | `gpt-6-luna` | `gpt-6.1-sol`、`gpt-6-astra`、`gpt-6-sol`、`gpt-5.6-luna` |
| 阿里百炼（北京） | `qwen3.8-flash` | `qwen3.8-max`、`qwen3.7-plus`、`qwen-flash` |
| xAI | `grok-4.7` | `grok-4-1-fast-non-reasoning` |
| 本地 CPU | `qwen3-0.6b` | 保持已下载的小模型，不因云端升级额外下载大权重 |

共 17 个配置档案。官方目录确认 GPT-6 家族及 GPT-6.1 Sol、Qwen3.8、Grok 4.7、Gemini 3.8 Flash 和 Gemini 4 Argon。[S74](references.md#s74)、[S76](references.md#s76)、[S77](references.md#s77)、[S78](references.md#s78)、[S79](references.md#s79) 账户模型列表与实际生成是不同证据：0.1.2 的 OpenAI、百炼、xAI 列表请求成功；新增模型逐一生成的状态见[模型目录验收](delivery-validation.md#model-catalog-evidence)。列表出现不保证当下配额、余额或推理成功。

默认档案中，OpenAI Astra、6.1 Sol 使用 Responses 和 `reasoning.effort=low`，Luna、6 Sol 保留 `none`；没有把不受支持的 `none` 传给 Astra/6.1 Sol。[S75](references.md#s75) Gemini 3.8/4 Argon 使用 `LOW`；请求去掉 `candidateCount`，3.8 不再传 `MINIMAL`。[S78](references.md#s78)、[S79](references.md#s79) Grok 4.7 使用 `reasoning_effort=low`，百炼默认文字档案关闭 thinking；0.1.3 允许按请求切换已登记的级别。以上参数属于当前聊天工作负载，不代表模型最高能力测试或全部工具已经接通。

`models` 返回各个模型的最近调用状态与时间，网页显示最近状态，`NOT_TESTED` 表示没有本地记录。这里是历史诊断，绝不等于实时健康保证。手动选模型只影响本次会话请求，不改磁盘默认值、不影响其他会话；未知 ID 或把模型配到错误的提供商会在发送前拒绝。运行时每轮读取当前配置，配置更新不要求重启模型进程；更换适配器代码仍需要重启网页服务，没有宣称代码热替换已经实现。

旧模型保留为手动兼容选择；历史测试和旧 UNKNOWN 记录继续保存于 [0.1.0 基线](delivery-validation.md#k0-evidence)及 [0.1.1 聊天基线](delivery-validation.md#chat-evidence)。后续新模型上线时：核对官方文档和区域 → 在配置中增加档案 → 检查接口参数 → 合成短调用与回归验证 → 选择默认值并登记证据。没有创建定时抓取、自动替换或后台付费探测。

<a id="model-admin-config"></a>
### 模型配置后台与费用口径（0.1.19）

本节是接入配置、Key 版本、模型价格和用量归属的唯一规则页；界面入口见[后台使用](core-bootstrap.md#model-admin-entry)，交互见[后台布局](interaction-persona.md#model-admin-experience)，机器边界见[配置接口](contracts.md#model-admin-contract)，实现与实测见[验收](delivery-validation.md#model-admin-evidence)。

**配置生效。** 首次建立后台时，以 `config/model-profiles/providers.json` 和 [registry.py](../adapters/models/provider-native/jarvis_models/registry.py) 的接入模板生成本机 `model-admin.db`。之后此数据库是唯一有效配置；种子 JSON 只用于新实例与模板，不覆盖已有本机编辑。CLI 聊天、网页聊天和浏览器任务共用 `effective_config`。运行中的请求保留启动时的配置副本；保存只改变后续请求。写入串行化并检查 revision，旧页面不能静默覆盖新配置。

**连接与凭据。** connection ID 与协议 adapter 分开；同一家可以有多个连接，同一模型也可经多条线路调用。模板包括 OpenAI Responses、Google Vertex 服务账户、Google Gemini API Key、百炼区域、xAI、Anthropic Messages、Eachlabs 和 HTTPS Chat Completions 兼容中转。本地 Qwen 保持固定 loopback。官方端点固定，自定义中转保存 Base URL；更换站点另建连接并登记 Key，既有 Key 不随任意网址字段转移。不同百炼区域不沿用北京单价。新增线路不自动进入备用路由；当前首选可在接入设置中更改。

每个 Key 版本有独立 ID、名称、尾号、创建时间和启用状态，完整凭据仅存现有 DPAPI 库。一个连接选择一个当前 Key，不自动轮询备用 Key。替换时新建版本并停用旧版本，旧用量仍归旧 ID；当前 Key 不允许直接停用，应先切换或替换。旧库通过显式 `Registry.import_legacy()` 一次登记，重复导入不复制版本；创建测试实例不读取真实凭据。保存失败不破坏原配置，凭据先写为不可变版本、再提交配置，异常至多留下未引用版本。管理接口和 CSV 不返回完整凭据，模型调用记录不存提示原文。

**Claude。** Eachlabs 新增 `anthropic/claude-sonnet-5.5`（默认，均衡）、`anthropic/claude-opus-5.5`（复杂任务）、`anthropic/claude-haiku-5.5`（低成本）。基础 17 个档案加这 3 个后，初始后台共 20 个模型、6 条线路；实际启用列表随本机配置变化。默认 low，可选 low/medium/high，单次输出上限 8192，仍受现有请求时限约束。Anthropic 官方模板采用原生 `claude-…-5-5` ID；需另有官方 Key，不能把 Eachlabs Key 当作官方凭据。模型目录来源见 [S133](references.md#s133)—[S136](references.md#s136)，三个 Eachlabs 型号的真实文本调用已核验；官方新适配器仅有模拟协议验证。

**用量与费用。** 每次尝试在现有 `model-probes.db` 保存连接/Key 身份、规范化 Token、请求时价格快照与估算结果。输入包含缓存读写；Anthropic 的输入字段不含缓存，先补齐再归一；Gemini 输出包含候选和 thoughts，OpenAI/兼容接口的 reasoning 已包含在输出，不再次相加。价格单位为每百万 Token，可分别配置输入、输出、缓存读、缓存写、USD/CNY、附加费百分比、输入档位上限、核对日、有效期和来源。

估算公式为 `(普通输入×输入价 + 缓存读×读价 + 缓存写×写价 + 输出×输出价) / 1,000,000 × (1 + 附加费% / 100)`。金额用 Decimal 计算；每次调用保存结果，之后修改价格不倒改历史。用量缺失、缓存价格缺失、超档位、价格过期或历史无价格快照均显示待核对；已发送后停止/超时不能作为免费。未派发或本地模型标为无 API 费用，不代表本机电力免费。

按北京时间 UTC+8 的请求创建日期聚合，可选今天、7/30/90 天或最长 366 天自选区间；同一筛选同时作用于每日、连接、模型、Key 和 50 条分页明细。USD 与 CNY 分开相加，不自动换汇。当前统计只覆盖本实例通过网关记录的调用尝试，**不是供应商结算账单**：套餐、赠额、信用返还、税费、其他应用调用与外部历史探测不自动合并。旧版本记录保留为历史未归属/待核对，不用今天的单价反算。

初始价格按 2026-10-16 官方资料核对。[S138](references.md#s138)—[S142](references.md#s142) OpenAI 用 Standard 短上下文价；Gemini 4 Argon 使用未扣促销返还的 4/20 标价，3.8 Flash 限期价有效至 2026-12-31；百炼使用北京原价，缓存未核验则留空；Grok 4.1 Fast 价格未预填。Eachlabs 附加费初始为 5.5%，可按实际账户规则调整。Eachlabs 余额仅点按钮时查询，可能延迟且多个 Key 可共享同一账户余额，不能把余额相加或当作此实例的当日消耗。没有后台轮询、自动付费测试或新预算阻断。

<a id="eachlabs-claude-probe-config"></a>
### Eachlabs Claude 独立调用核验（2026-10-16）

本轮按主人小额测试授权直接验证 Eachlabs；这是 0.1.18 环境下的历史外部 API 探测，当时尚未加入应用。0.1.19 的正式文本接入见[后台规则](#model-admin-config)与[新版本证据](delivery-validation.md#model-admin-evidence)。使用 `https://api.eachlabs.ai/v1/chat/completions` 和 Eachlabs 自己的 Bearer API Key；其他提供商凭据不参与。测试凭据仅留在本轮进程内存，不写入项目文件或替换已有凭据。[S135](references.md#s135)

Anthropic 当前官方目录列出 Opus 5.5、Sonnet 5.5、Haiku 5.5 和 Fable 5.1。[S133](references.md#s133) **原生 API ID 与中转 ID 不同**：例如官方 `claude-opus-5-5`，本中转请求为 `anthropic/claude-opus-5.5`。Eachlabs 实际精选目录列出 Opus/Sonnet 5.5 并标记 OpenRouter 路由；Haiku 5.5、Fable 5.1 在实查的 OpenRouter 目录中，按中转文档允许使用未列入精选的已发布聊天模型 ID。[S134](references.md#s134)、[S136](references.md#s136)

实测可用范围、过滤结果、费用与限制统一见[独立小额探测证据](delivery-validation.md#eachlabs-claude-evidence)。当前不将 Fable 的 HTTP 200 或执行账本 `success` 当作有可用回答；也不以返回型号名称证明真实上游权重身份。0.1.19 已复用目录、会话停止和用量机制接入三个成功型号的非流式文本；SSE 工具执行和 Fable 仍未接入，不由本轮探测推断。

<a id="google-model-selection"></a>
### Google 当前主流与本项目选择（0.1.4，2026-10-15 核验）

服务账户 JSON 通过 OAuth 对 Google Cloud 项目认证，不绑定某一个 Gemini 型号；实际权限、计费状态、区域、发布阶段和可用配额共同决定能否调用。不能把 Gemini 网页的 Google AI Pro 订阅、Developer API key 与本项目的 Vertex 服务账户计费混为一谈。本轮沿用原 DPAPI 凭据，实际调用 Pro、Flash-Lite、Flash、Argon，未新增账号或权限，未查询余额。[验收记录](delivery-validation.md#google-models-evidence)

Google 官方迁移表同时列出 4 Argon、3.1 Pro、3.8/3.7/3.6/3.5 Flash 和 3.5 Flash-Lite；其中 3.1 Pro 仍是 Preview，其他上述文本型号为 GA。[S84](references.md#s84) 本项目对其选型如下，这些是工作负载角色，不是自制质量排行榜：

| 角色 | 目录选择 | 依据与边界 |
|---|---|---|
| 复杂工作与旗舰候选 | 4 Argon | 已在目录，本轮重新调用成功；强任务能力需独立评估 |
| Pro 系列 | 3.1 Pro Preview | 新增，使用精确 ID `gemini-3.1-pro-preview`；界面明确标 Preview，不虚构“3.8 Pro”或“4 Pro”别名 [S82](references.md#s82) |
| 日常默认与速度平衡 | 3.8 Flash | 维持当前默认，避免把每次请求都切成更重模型 |
| 轻量任务 | 3.5 Flash-Lite | 新增当前 Flash-Lite 系列，官方定位为简单编码、文档理解和轻量工作流；旧 3.1 Flash-Lite 保留兼容 [S83](references.md#s83) |
| 其他仍列出的 Flash | 3.5 / 3.6 / 3.7 Flash | 本轮不加入重复选项；3.5 是仍维护的 GA 分支，3.6/3.7 在 Vertex 分别计划 2026-11-19 / 2027-01-28 退役，替代为 3.8 Flash [S85](references.md#s85) |

Vertex 的 Gemini 2.5 Pro / Flash / Flash-Lite 计划于 **2026-10-20** 退役；因此本轮不将 2.5 Pro 新增为主力。Developer API 与 Vertex 的生命周期表可能不同，以本项目实际调用的 Cloud 平台为准。[S85](references.md#s85)

新 Pro 默认 LOW、8192 输出 token，可选 LOW/MEDIUM/HIGH；新 Flash-Lite 默认 MINIMAL、8192，可选 MINIMAL/LOW/MEDIUM/HIGH。[S82](references.md#s82)、[S83](references.md#s83)、[S86](references.md#s86) 当前网关只处理纯文字历史；新 Lite 的 MINIMAL 两轮文字实测成功，但这不代表已处理所有 thought signature、工具或跨模态会话要求，后续接工具需重新验证原生会话协议。

图片、Live、TTS、Embedding 等属于不同调用能力；没有把这些型号塞进纯文字菜单后就声称语音、画图或知识检索已接通。当前 Google 五个选项共享原服务账户与 global 入口，不包含需要额外准入的 Cyber Permissive 端点。

<a id="reasoning-controls"></a>
### 统一模型菜单与推理级别（0.1.3）

所有提供商同时注册在目录中，网页只选择一个模型，自动派生对应提供商；侧栏展示全部提供商和模型数，不再要求先选提供商。输入区并列模型和推理级别，支持搜索、键盘选择和窄屏折叠侧栏。级别是每次请求的参数，切换模型恢复新模型的默认值，不沿用不兼容的旧值，也不修改磁盘配置或其他页面。新对话开启独立上下文；0.1.24 的本机文字归档由[会话模块](knowledge-learning.md#local-chat-archive)管理。

配置项 `reasoning_levels` 声明该模型已核验的选项；`parameters` 保留默认值。目录返回 `reasoning_levels/reasoning_default`；网页请求新增可选 `reasoning`，服务端校验属于该模型后，在请求副本中转换为提供商参数。未声明选项的旧配置仍能运行，但不开放级别调节。网页不接收任意参数字典、URL、认证字段或工具配置。

| 模型 | 界面级别 / 请求值 | 实际参数 |
|---|---|---|
| GPT-6 Astra、GPT-6.1 Sol | 低、中、高、极高、最高 / `low, medium, high, xhigh, max` | Responses `reasoning.effort` |
| GPT-6 Sol、GPT-6 Luna、GPT-5.6 Luna | 上述级别加关闭思考 / `none` | Responses `reasoning.effort` |
| Gemini 3.8 Flash、4 Argon、3.1 Pro Preview | 低、中、高 / `low, medium, high` | `thinkingConfig.thinkingLevel` 转为大写 |
| Gemini 3.1 / 3.5 Flash-Lite | 上述级别加最低 / `minimal` | 同上 |
| Grok 4.7 | 低、中、高、极高 / `low, medium, high, xhigh` | `reasoning_effort` |
| 百炼目录中的 Qwen | 关闭、开启思考 / `off, on` | `enable_thinking=false/true` |
| 本地 0.6B、Grok 非推理版本 | 固定模式，控件禁用 | 不增加请求参数 |
| 自动路由 | 跟随模型，控件禁用 | 各候选的默认参数；拒绝手工级别覆盖 |

依据为 [S59](references.md#s59)、[S60](references.md#s60)、[S76](references.md#s76)、[S78](references.md#s78)、[S79](references.md#s79)、[S80](references.md#s80)、[S81](references.md#s81)。使用 API 支持的枚举，不把 Codex 客户端的额外显示名称直接当作 API 参数。百炼商业模型支持同步思考输出；仅展示最终 `content`，不把内部思考内容混入回答。没有将“开启”假装映射成低/中/高三档。

更高推理级别可能增加等待和 token 使用；现有单次输出与超时边界仍然适用，耗尽输出额度或超时不保证有完整回答。回应详情显示本次实际模型、级别和用量；等级列表是文档与参数兼容核验，不等于每个等级均有实测质量保证。CLI 保持默认档案和原 `--model` 行为，本轮可视调节入口为网页。当前实测见[界面验收](delivery-validation.md#web-workspace-evidence)。

<a id="section-896f72aed9a9"></a>
### 当前路由和单次资源边界

- 显式选择提供商及可选模型 ID 时只请求该模型；仅选 `vertex / bailian / openai / xai / local` 时使用该家的默认模型；`auto` 使用各家的默认模型，按默认提供商与 `fallback_order` 去重，当前顺序为 `vertex → bailian → openai → xai → local`。
- `automatic_fallback=true` 不意味着无限重试。只有已明确拒绝的额度/限流、供应商或模型不可用，且被网关分类为可切换时，才考虑下一个候选；一轮内每家至多一次。界面和 CLI 显示尝试记录，以及最终实际提供商和模型。
- 传输结果不确定的 UNKNOWN、鉴权/参数错误或核心停止不会继续连锁切换。用户可以显式重新发送；先前 UNKNOWN 请求仍可能已执行或计费，不会被新请求覆盖为“未发生”。
- 云端单次输入最多 **64 KiB UTF-8**，本地小模型保留 **4 KiB 输入**；输出额度按下述模型档案分配。取消累计次数上限不取消上下文、超时、并发和停止约束。
- CLI 和浏览器仅在当前会话内存保存历史。ChatService 裁剪后最多保留并发送 20 条历史消息、合计最多 32 KiB UTF-8 的历史；按实际提供商输入上限进一步裁剪，并返回提示。清空会话不删除调用账本。切换提供商或使用 `auto`，会把当前输入和裁剪后历史发送给实际候选提供商。
- 回答附带实际模型 ID、供应商实际返回的数值用量及额度通知；没有数据时不猜测 token、费用或账户余额。消息不会变成工具调用、程序执行或新的自主权限。

Google JSON 是服务账户凭据，以 OAuth 换取短期令牌，并非普通 Gemini API key。基础四家与后续登记凭据由 Windows 当前用户 DPAPI 加密存储，源码只含模型、端点与调用策略。Google 原始附件保持原位，未复制到仓库。凭据位置与信任限制见[凭据与停止实现边界](security-sovereignty.md#prototype-security)。

派发先在核心短事务内检查停止并提交 `dispatch_admitted`，该提交是“已在途”的边界；停止先获得事务时拒绝接纳。已接纳请求可能在停止后完成网络发送、远端执行和计费，不能承诺撤回。0.1.12 的单次聊天取消沿用该已接纳边界：网页传入请求级取消事件，异步等待响应头或正文时检查取消并关闭/等待 HTTPX 传输清理；取消后不自动回退、不采用迟到输出。同步凭据/Google 认证阶段仍按原有超时退出，随后拒绝派发；不会通过提前释放槽位制造无限后台请求。未派发取消记为 CANCELLED，已派发且远端结果不明仍记 UNKNOWN，并附 `cancel_requested`；网页停止回复不证明供应商已经停止计算或免除计费。

网络等待不占核心写锁；0.1.38 起，HTTP 响应协程总期限和读取等待统一取调用方 `deadline_seconds`（须为有限正数）：普通调用默认 60 秒，限定编码调用为 90 秒；连接取至多 10 秒，写入和连接池等待取至多 45 秒，各自也不超过调用方期限。持续到达的数据不会绕过协程总期限。Google 令牌请求另限 15 秒且禁止隐式重试。路由按单家异步等待至多 60 秒、总计 90 秒的合作式预算接纳候选；Google 认证可能额外占用最多 15 秒，不能承诺墙钟时间在 90 秒硬终止，也不是独立进程强制终止能力。传输、超大/坏响应或派发后的停止导致结果不确定时保留 UNKNOWN，不输出结果、不自动重试。本地调用禁用环境代理，固定发往 loopback。诊断账本保留请求摘要、尝试状态和数值用量；0.1.38 另记响应期限，成长回执保留异常类型（如 `ReadTimeout`）、HTTP 状态及期限，不反射异常原文。旧 UNKNOWN 不因改期限而自动补发。诊断记录不持久保存提示原文、模型回答或密钥；浏览器/CLI 会话历史也没有升级为长期记忆。

模型输出额度属于单次资源参数：云端默认 4096 token，当前推理型档案为 8192（包含供应商计入的思考 token），本地仍为 256；配置校验允许云端档案至多 32768。该数值不限制累计调用次数，也不是模型厂商的最大上下文声明。

<a id="runtime-chat-context"></a>
#### 当前宿主能力上下文与回答完整性

0.1.21 起 `assistant_context.py` 提供精简宿主能力说明：Jarvis 身份、配置路由、聊天实际可见的消息/附件，以及文件保存和限定任务属于独立 UI。0.1.25 增加[明确事实上下文](knowledge-learning.md#explicit-memory-runtime)，说明面板记忆可用但自然语言声明不能代替真实写入；0.1.26 增加[明确项目文档摘录](knowledge-learning.md#project-retrieval-runtime)，仍不扫描整个项目或自动检索其他会话。它是当前能力种子，不能代替完整知识、规则或 Skill 系统。调用者历史仍只接受 user/assistant，不允许借历史伪造 system 消息。此说明按各协议使用 Responses `instructions`、Google `systemInstruction`、Anthropic `system` 或 Chat Completions system 消息，依据 [S143](references.md#s143)、[S144](references.md#s144)、[S145](references.md#s145)。

宿主说明也计入云端 64 KiB / 本地 4 KiB 的文本输入预算；0.1.23 起由独立[上下文装配模块](contracts.md#context-assembly-current)预留本轮消息、附件、固定会话要求与说明，再按完整轮次裁剪历史。模型可遵循也可能误解说明，尤其 0.6B 模型实测仍有能力幻觉，详见[本轮评估](delivery-validation.md#readiness-evidence)。因此操作事实必须以系统回执为准，不能以模型自述替代。

网关解析各家完成原因：已知长度截断或其他未完整结束返回 `output_incomplete=true`，`completion_reason` 只保留归一化类型，不保存供应商任意字段。部分正文可在聊天中显示并有持久警示，但不自动保存为完整文件，浏览器规划器也拒绝采用。用户检查后可明确手动另存；不会静默续写、自动重试或自动切换到另一家再次计费。若供应商明确返回不完整且无正文，记为已知失败 `response_incomplete`，保留数值用量；只有未确定的传输结果才按既有 UNKNOWN 规则处理。旧兼容接口未给完成原因时标记 `unspecified`，不伪造完成凭证。

“完整”只表示供应商的协议结束状态，不保证内容满足用户要求。本轮本地模型被要求列出 1—500，却列到 50 就正常结束；此类漏项必须用任务内容验收识别，不能靠 finish reason 发现。另用临时 32-token 输出预算触发了真实 `length` 截断，并确认警示生效；用户持久配置未修改。

<a id="deterministic-calculation-runtime"></a>
#### 本地精确计算与能力分流（0.1.37 implemented）

纯算式先走宿主的独立 [calculator.py](../runtime/node-host/jarvis_core/calculator.py)，再考虑原模型路由。它用受限 AST 和有理数运算计算，不执行 `eval/exec`，不访问网络、凭据、文件、记忆或项目资料，也不加载模型配置。这是 Host 基础能力，不占十项原生技能名额；普通聊天和后台规划仍沿原通道。0.1.39 另有[明确个人指令](interaction-persona.md#personal-core-ui)的本地分流；两者均为固定能力，尚无通用任务识别、模型质量评分或自主切换模型的能力路由器。

识别范围是**当前整条消息中的完整算式**：阿拉伯数字、小数、科学计数法、正负号、括号、加减乘除和整数乘方；支持 `×/÷/−`、中文加/减/乘以/除以及英文 plus/minus/times/divided by，`^` 解释为乘方。可带“计算”“算一下”“等于多少”等短前后缀，末尾最多两项输出要求：“只回答数字/结果”等，或“保留 N 位小数”。自动识别必须含二元运算；显式 `/计算 算式` 或 `/calc expression` 也接受单个数。命令后须有空白。未加计算前缀的日期/编号形状、引用、翻译、代码、混合动作、JSON 格式要求和依赖历史的追问不自动截获，仍交给原聊天。它不解数学应用题、方程、单位换算或程序。

API 收到附件、非空“本会话要求”或显式专业技能时，自动识别退回原聊天，保留原上下文；显式计算命令则返回 `calculation_context_conflict`，不会静默丢弃这些条件。网页显式命令为本次请求跳过技能/任务模式，使用方式见[入口](core-bootstrap.md#calculator-entry)。已选项目、既有聊天历史本身不阻止完整纯算式：局部路径只使用本轮算式，标记 `history_used=false`，不继承先前来源。后台报告内部规划不经过此捷径。共同输入校验、核心待命/停止及取消仍生效。

| 运算边界 | 当前硬限额 |
|---|---|
| 表达式与语法树 | 最多 256 字符、64 个 AST 节点、16 层括号；仅数值常量、正负号与上述二元运算 |
| 数值 | 单个尾数最多 64 位，科学计数指数绝对值至多 100；中间及最终分子/分母最多 4096 bit |
| 乘方 | 整数指数 −32…32；运算前检查预计位数，拒绝 `0^0` 和零的负幂 |
| 显示 | 有限小数精确显示，循环小数显示约分后的分数；指定保留 0…12 位时按 half-up 舍入，显示值最多 512 字符 |

除零、超限、未知语法或不支持的显式命令直接返回本地错误，不让模型猜测答案。结果附[计算回执](contracts.md#deterministic-calculation-contract)，UI 明示“本地精确计算”，不伪装成所选模型回答。摘要用于检测回执内容变化和复现，不是数字签名或独立正确性证明。算式选取、参考运算与界面验收见[本轮证据](delivery-validation.md#calculator-evidence)；原 Qwen3 0.6B 的算术失败记录保留，不能把宿主答案算成模型能力提升。

<a id="section-4a9504a4187f"></a>
### 本地小组件的当前选型

唯一机器可读选型与摘要为 [local-candidates.json](../config/model-profiles/local-candidates.json)。17 个下载文件合计 **961,591,814 字节**，约 962 MB，低于 2 GB 下载预算；这是下载体积，**不等于运行内存上限**，也不含 Python 环境、解压后的运行库和缓存。选择 CPU，避免把集成显卡报告的显存数误当作可用专用 VRAM。

| 能力 | 实际组件 | 初始取舍 |
|---|---|---|
| 离线 LLM | 官方 Qwen3 0.6B Q8_0 GGUF | 4 线程、2048 上下文、1 序列、0 GPU layers、关闭思考；处理短对话/分类，不承担强编码或授权决策 |
| STT | SenseVoiceSmall int8 ONNX | 2 线程、16kHz、中文优先、每段最多 15 秒；非原生流式 |
| TTS | AISHELL3 VITS low | 2 线程、预置说话人 sid=0；实测 8kHz，省资源但自然度有限 |
| 声纹 | CAM++ 中文 16kHz | 1 线程、192 维特征；仅完成向量提取诊断 |
| VAD | Silero ONNX | 1 线程、16kHz；检测语音片段 |
| LLM 引擎 | llama.cpp b11617 Windows CPU x64 | 固定压缩包摘要，解压前验证，无 GPU 驱动依赖 |

[下载器](../tools/manage_models.py) 固定 HTTPS 来源、版本、逐文件 SHA-256 和字节数，限制总量、磁盘余量与路径，临时下载后校验并原子替换；不能只相信远程文件名。运行脚本加载前复核模型，运行库解压拒绝越界/链接并核对已有文件。没有自动更新到 latest，也没有模型自行替换文件；候选升级仍需[组件生命周期](#local-survival-5)和既有回退协议。

选型参考 [S64](references.md#s64)、[S65](references.md#s65)、[S66](references.md#s66)、[S67](references.md#s67)、[S69](references.md#s69)、[S70](references.md#s70) 及清单内固定版本模型卡。SenseVoice 为自定义模型协议，不能从代码的开源许可推导商用或再分发许可；VITS 的模型卡许可与声音/训练数据相关权利也需分别核验。当前按个人原型选择，未宣称商业发布许可已完成。

运行命令统一见[当前实现](core-bootstrap.md#current-implementation)，语音身份能力边界见[当前语音验证](interaction-persona.md#speech-prototype)，实测及未测事项见[验证记录](delivery-validation.md#k0-evidence)。下载和本机推理成功不证明断网安装依赖、网络自修复、模型热更新或 LP 全部降级档位已经通过。

<a id="voice-model-selection"></a>
### 语音主选与候补：本地优先（2026-10-18）

**accepted 的需求顺序：**先满足普通 PC 的本地可用、小体积、低延迟和准确性；CPU/内存不足、所需语种不支持或效果未达标时，再用便宜的国内/国外云端候补。声音克隆、语气与情绪是 TTS 选型要求，不能拿固定音色播报代替。未接入候选仍为 proposed；已实现的快速语音及 CosyVoice3 以各自组件运行页为准，基础四组件文件诊断范围见[本轮证据](delivery-validation.md#voice-selection-evidence)，没有把候选写入当前运行模型菜单或宣布麦克风聊天已上线。

<a id="voice-local-candidates"></a>
#### 本地主选、备选与真实能力边界

**2026-10-18 主人最新要求：本地生成及时、听起来自然、语气/情绪控制，三项都是日常主力的必需条件；声音克隆后置。** 只够快但不能明确控制情绪的组件不能充当正式主力；有情绪接口但本机太慢也不合格。ZipVoice 已改为默认不启动的备选，需要时手动加载。当前主力仍在实测筛选，不因上游宣传或接口受理成功就宣布三项同时通过。组件速度、情绪/自然度及整个会话延迟分别验收，见[语音验收范围](delivery-validation.md#voice-selection-evidence)及[既有速度对照](delivery-validation.md#fast-speech-evidence)。

| 能力 | 主选 | 备选或增强 | 选择理由与限制 |
|---|---|---|---|
| VAD | 已有 Silero ONNX，文件约 1.81 MB | 按键说话作为无 VAD 降级 | 按需判断有无语音；不识别人，也不消除回声 |
| 说话人辨认 | 已有 CAM++ ONNX，文件约 28.28 MB、192 维 | 3D-Speaker ERes2Net ONNX，待同集比较 | 登记多个人的参考样本后比较特征；保留 unknown，跨语种/噪声须校准；现在只有特征诊断，没有完成任何人的登记 |
| 谁在何时说话 | sherpa-onnx 的 pyannote segmentation 3.0 + 声纹 + 聚类，按需启动 | 完整 pyannote.audio 管线作质量对照 | 首期以离线分段/有延迟的增量结果起步，不承诺实时零延迟。分段结果再与登记身份匹配；不是两条独立干净音轨 [S190](references.md#s190) |
| STT 日常 | 已有 SenseVoiceSmall int8，相关文件约 239.73 MB | Qwen3-ASR-0.6B，准确性/语种增强时再加载 | SenseVoice 先覆盖中、英、粤、日、韩，VAD 后整段识别，不是原生逐字流式；当前诊断固定 zh，正式多语入口需开放自动语种并验证中英混说。Qwen 候选支持 30 种语言及 22 种中文方言，但运行依赖和资源须另测，不能按 0.6B 聊天模型复用 [S192](references.md#s192) |
| TTS 日常主力 | **Qwen3-TTS-12Hz-1.7B-CustomVoice Q5_K + speech.cpp 0.8.10，本机优先 Vulkan** | EmotiVoice 已测 CPU 速度可用，但情绪区分不足，暂不作为主力 | 主人已确认 Serena 的三段样本自然、情绪明显，同意作为主力；已接入[独立文件 TTS](#qwen-tts-runtime)。9 个预设音色、10 语种是模型目录，未逐项验收；0.6B 官方未列指令控制，不代替 1.7B [S216](references.md#s216)、[S217](references.md#s217)、[S218](references.md#s218) |
| TTS 快速备选 | **ZipVoice-Distill int8 + Vocos，CPU / sherpa-onnx，4 步；已有独立文件 TTS** | 已有 VITS 作低资源应急；Kokoro int8 已作对照，本机较慢 | 按主人要求默认不启动、手动备用；已测短句及时性，但没有通用情绪指令，不满足主力三项要求。使用见[备用组件](#fast-speech-runtime) [S189](references.md#s189) |
| TTS 克隆与情绪指令 | **Fun-CosyVoice3-0.5B-2512，已接入独立文件 TTS** | 资源不够时按已准入候补降级；当前未接通自动云端 TTS | 本机 Windows/AMD CPU 已通过中文克隆、开心指令与英文跨语种短样本；不自动常驻。原生 CPU 路径明显慢于实时，语气听感/相似度和其他语种仍待验收，详见[真实证据](delivery-validation.md#cosyvoice3-evidence)，不引用上游 150ms 为本机承诺 [S191](references.md#s191) |

**参考录音引导风格与文字指令控制情绪是两种能力。** ZipVoice-Distill 当前公开推理入口接收参考音频、对应文字、待合成文字和速度等参数；可以尝试用不同情绪的参考录音引导风格，效果仍须试听，但没有据此确认它支持“非常开心/伤心地说”等通用情绪指令。不能说它的声音完全没有情绪，也不能把插入任意 `[开心]` 标签当作已经支持。[S189](references.md#s189)、[S213](references.md#s213)

CosyVoice3 的官方 `inference_instruct2` 同时接收指令文字和参考声音；公开指令包含开心、伤心、生气、快慢与轻声等。源码中的克隆、跨语种和指令模式复用同一套 LLM、flow、HiFT 及参考音频前端，不因“同时具备这些能力”各复制一整套模型。增加指令主要改变输入与相关缓存，实际增量随长度和模式变化；多请求并发是另一项资源测试，不能从模式复用推导任意并发无额外占用。[S214](references.md#s214)

ZipVoice 在官方 Release 的压缩包为 **109,162,785 字节**，另需 **54,157,409 字节** Vocos：合计约 **163.32 MB 下载量**，不是解压后体积或运行 RAM；不是整个 Hugging Face 仓库的 1.61 GB。两项已下载、核验并接入[快速组件](#fast-speech-runtime)，不再属于未安装候选。sherpa-onnx 1.13.8 另有说话人分段 API，但相应约 6.96 MB 的分段模型仍未接入本轮实时会话。最初元数据见[选型记录](../evals/reports/voice-selection-2026-10-18.json)，当前安装/实测见[快速语音证据](delivery-validation.md#fast-speech-evidence)；安装继续固定文件摘要，不只接受可变 release 标签。

现有 VITS 仅 8kHz、无声音克隆，不符合日常自然伙伴声音的最终要求。Kokoro 固定音色也不能替代克隆需求；PocketTTS 当前公开路径以英文为主，因此不作为中文主选。Qwen3-ASR-0.6B 尚未安装；CosyVoice3 已有独立按需环境和文件合成入口，不自动常驻。快速 ZipVoice 复用现有轻量环境，不为它额外安装 PyTorch、vLLM 或 CUDA。

<a id="voice-resource-footprint"></a>
#### 内存、显存与模型文件分开预算

现有四组件均使用 `provider=cpu`，占用系统 RAM，不要求独立显存。模型文件、解压后的安装体积、进程驻留工作集、私有提交和 GPU 显存是不同指标。此前顺序诊断的约 1.07 GiB 是私有提交，其采样峰值工作集约 372.6 MiB；不能将 1.07 GiB 称作当时实际占用的物理内存。独立组件的当前实测及基线只在[语音内存证据](delivery-validation.md#voice-component-memory)维护。

**未实测候选仍需可用于选型的预算。** 下表覆盖此前列出的其他本地模型；数字范围是本项目提出的**首轮部署预留（proposed），不是厂商公布的内存要求、本机实测、最低配置或峰值上限**。已经实测的行只链接验收记录；基础四组件仍见上方证据，不把估计当成测量。

估计口径为单独推理进程、batch=1：STT/分段输入不超过 10 秒，TTS 参考与单次输出各不超过约 10 秒，分离输入先限 2—5 秒；不包括训练、网页、核心服务、本地聊天 LLM 和并行 Agent。CPU 列包含模型及推理运行库的 RAM 预留，ONNX 使用下表指定的量化版本，PyTorch CPU 先按 FP32；GPU 列是**另一种部署方案**，同时列出主机 RAM 与设备 VRAM，不是只占显存。Qwen3-ASR/CosyVoice 的 GPU 预算以支持的 FP16/BF16 路径为前提，pyannote/SepFormer 先按 FP32。大批量、长录音整段加载、长文本合成和 vLLM 默认预分配均不在这些范围内。

| 候选及本轮预算配置 | CPU 方案：RAM 预留 | 可选 GPU 方案：RAM + VRAM 预留 | 默认安排 |
|---|---|---|---|
| Qwen3-TTS-12Hz-1.7B-CustomVoice Q5_K，speech.cpp 0.8.10 | 本机 CPU 4/8 线程已有测量，见[情绪语音证据](delivery-validation.md#emotion-tts-evidence) | 本机 Vulkan / 8060S 的进程 RAM 和 WDDM 专用/共享分配已有独立测量，见同一证据；不是 CUDA 预算 | 已接受为主力，手动加载；文件 TTS 接入证据见同一验收页，不是麦克风会话延迟 [S217](references.md#s217)、[S218](references.md#s218) |
| EmotiVoice，原生 CPU 4 线程 | 已有本机加载/合成工作集与峰值，见[情绪语音证据](delivery-validation.md#emotion-tts-evidence) | 本轮仅 CPU，不要求独立显存 | 情绪自然度未过准入，不因速度够快就设为主力 [S216](references.md#s216) |
| ERes2Net **base** ONNX，具体候选 `3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx` | 0.5—1 GiB | 暂不安排；CPU 不要求独立显存 | CAM++ 的按需对照；不把 large/v2 统称为同一占用 [S209](references.md#s209) |
| sherpa-onnx pyannote segmentation 3.0 + CAM++ + 聚类 | 1—2 GiB | 暂不安排；CPU 不要求独立显存 | 多人分段时加载；已含声纹组件，不能再重复加算一次 CAM++ [S190](references.md#s190) |
| 完整 pyannote.audio，预算例固定为 `speaker-diarization-community-1` | 2—4 GiB | RAM 1—2 GiB + VRAM 2—4 GiB | 离线多人分析候补；该数值不适用于任意 pyannote 流水线 [S210](references.md#s210) |
| Qwen3-ASR-0.6B，Transformers，**不带 ForcedAligner** | 4—6 GiB | RAM 2—4 GiB + VRAM 2—4 GiB | 多语/质量增强；带额外对齐模型必须另测另预算 [S192](references.md#s192) |
| ZipVoice-Distill int8 + Vocos，sherpa-onnx | 已有本机短样本测量，见[快速语音证据](delivery-validation.md#fast-speech-evidence)；其他设备另测 | 暂不安排；CPU 不要求独立显存 | 默认停止的备用；启动准入含余量，不等于实际常驻量 [S189](references.md#s189) |
| Fun-CosyVoice3-0.5B-2512，原生推理，不启用 vLLM/TensorRT | 已有本机原生短样本测量，准确口径见[组件验收](delivery-validation.md#cosyvoice3-evidence)；新设备仍须复测 | RAM 2—4 GiB + VRAM 4—6 GiB 仍仅为候选预算，本机未测该 GPU 路径 | 已有[独立组件](#cosyvoice3-runtime)；启动容量准入值见配置，不能把准入值或此前 4—8 GiB 粗估当成实际占用 [S191](references.md#s191)、[S214](references.md#s214) |
| Kokoro **int8 multi-lang v1_1**，sherpa-onnx | 已有本机短样本测量，见[快速语音证据](delivery-validation.md#fast-speech-evidence)；其他设备另测 | 暂不安排；CPU 不要求独立显存 | 固定音色对照；本机实测未优于 ZipVoice，因此未接入当前设置面板 [S211](references.md#s211) |
| PocketTTS **int8 2026-01-26**，sherpa-onnx | 0.5—1.5 GiB | 暂不安排；CPU 不要求独立显存 | 英文克隆候补，不代替中文主选 [S212](references.md#s212) |
| SpeechBrain `sepformer-whamr`，8kHz、2—5 秒短块 | 2—4 GiB | RAM 1—2 GiB + VRAM 2—4 GiB | 双人重叠分离实验，不能按该预算承诺长会议/实时分离 [S206](references.md#s206) |
| WeSep 目标说话人提取框架，**未锁定可部署 checkpoint** | 暂无可负责的统一数值 | 暂无可负责的统一数值 | 当前只保留研究条目，不纳入默认安装；先确定权重、网络和推理入口再报价 [S205](references.md#s205) |

CosyVoice3 的 **0.5B 不是整条语音流水线的全部权重**。2026-10-18 核对官方资产修订 `29e01c4e8d000f4bcd70751be16fa94bf3d85a18`，原生加载路径引用的五个主要权重/ONNX 文件如下；这是静态文件核算，不是 RAM 测量或严格内存下限。[S214](references.md#s214)、[S215](references.md#s215)

| 原生路径的主要资产 | 文件体积（十进制） |
|---|---|
| `llm.pt` | 2.025 GB |
| `flow.pt` | 1.329 GB |
| `hift.pt` | 83.20 MB |
| `speech_tokenizer_v3.onnx` | 969.45 MB |
| `campplus.onnx` | 28.30 MB |
| 五项合计 | **4,434,743,215 字节 ≈ 4.435 GB / 4.130 GiB** |

模型库、ONNX 优化、激活、参考音频、生成缓存及加载时的权重副本还会影响占用；不能拿五文件合计当运行 RAM，也不能拿整个仓库的重复格式/替代权重总量当必需常驻量。官方 CPU 路径在未检测到 CUDA 时关闭 `fp16`，不能仅通过打开一个参数就宣称整套内存减半。**本机现已真实加载 CosyVoice3 并完成三个模式的短样本测量**；分阶段 RAM/私有提交、加载和生成耗时只在[组件验收](delivery-validation.md#cosyvoice3-evidence)维护。此前粗略的 4—8 GiB 不是测量区间；新设备、长文本与并发峰值仍未知。启动准入的 minimum_available_memory_gib 包含前台和加载余量，也不是模型的实际占用。[S214](references.md#s214)

其余范围根据权重精度、辅助网络、运行库和短输入缓存留出试装余量，只用于决定先测哪个候选；上限不是调度器已实施的配额。实际超出时应重新测量、修订预算或淘汰方案，不能靠截断统计掩盖。WeSep 当前维护方说明为研究预览，官方预训练包与本地推理 CLI 尚在验证，不能为“框架”虚构一个模型大小或固定 RAM/VRAM。[S205](references.md#s205) 完整 pyannote 的 CPU 默认与 CUDA 可选路径来自模型卡，但上表的 GiB 数字仍是本项目估计。[S210](references.md#s210)

ZipVoice 尚未安装，163.32 MB 下载量不能当成运行 RAM。即使仅按参数估算，0.6B 的 FP16 参数本身约 1.12 GiB、0.5B 约 0.93 GiB，也未计入前后端模型、激活、缓存和推理库，不能据此宣传整套只占这些内存。当前普通 PC 的轻量目标组合为 Silero + CAM++ + SenseVoiceSmall int8 + ZipVoice int8，先为**语音推理进程合计预留 2—3 GiB RAM、无需独立显存**；这是待测集成预算，当前顺序诊断不能证明该克隆组合已运行，也不构成整台机器只需 3 GiB 的配置建议。

后续记录候选进程的基线、冷加载、预热、单轮、并发和释放后读数，再冻结准入预算；共同运行时的实际峰值不能简单相加各进程独测值。GPU 表仅为兼容后端的候选预算，不证明当前 Windows/AMD 设备支持 CUDA；能分配共享显存也不等于对应算子可运行。集成 GPU 的共享内存来自同一物理 RAM 池，不能把系统内存和共享显存当作两份额外容量。默认不同时常驻全部候选，资源不足时按[候补规则](#voice-routing-policy)降级。

<a id="qwen-tts-runtime"></a>
#### Qwen 本地主力语音组件

**0.1.43 工作树已接入文件 TTS；2026-10-18 主人确认 Serena 的开心、悲伤、生气试听自然且情绪明显，同意作为主力。** 在[设置 → 模块与升级](http://127.0.0.1:18181/settings#modules)最上方“Qwen · 主力语音”加载，选择音色、表达与语言，输入短句生成，再试听或下载 WAV。也可组合并分段使用 `[轻声][慢速]别担心。[停顿350ms][自然][开心]我们一起试试看！`，先点击“预览表达分段”，再合成试听。希望同一句自然起伏时可只写“表达提示”，保留整句生成；需要明确转折再用标签。完整语法、持续/重置规则与限制归[分层表达接口](contracts.md#speech-expression-score)。`usage_role=primary`、`auto_start=false`；打开页面不加载权重，加载后保持就绪，可独立停止释放资源。ZipVoice 保持默认停止的手动备用，CosyVoice3 按需克隆。

生产配置为 [qwen-tts.json](../config/model-profiles/qwen-tts.json)，固定 speech.cpp 0.8.10 Windows Vulkan 发布包及 1.7B CustomVoice Q5_K GGUF 摘要；模型含声码器，不另装 CUDA、PyTorch 或 vLLM。模型和原生运行库位于 `H:/JarvisData` 的独立目录；只启动校验后的绝对路径，不在运行请求中下载或更新文件。换版本需先停止组件、更新固定配置与资产并复验；目前不是任意模型的自更新器。

音色/表达/语言枚举只维护在[输入契约](../runtime/node-host/jarvis_core/qwen_speech_contract.py)，界面从状态能力表生成。CustomVoice 使用预设音色，不接受参考录音克隆；语气和语速可通过标签组合及表达提示控制；不是把一个下拉值当成整句话唯一情绪。9 个音色和 10 语种是模型目录，本轮没有逐项全部试听或准确率验收。

设置短句的完整输入、输出和超时限制归[接口](contracts.md#qwen-tts-contract)。0.1.45 工作树增加[聊天回复手动朗读](interaction-persona.md#chat-readout-ui)，沿同一组件按短句连续播放，可暂停、继续、停止；[占用与分段接口](contracts.md#chat-readout-contract)独立维护。每个短段仍先取得完整 WAV，未接通原生流式扬声器、麦克风、STT、声纹登记、插话打断或聊天自动朗读。实际速度/RAM/GPU 与听感范围只在[验收页](delivery-validation.md#qwen-tts-integration-evidence)维护；4 GiB 可用 RAM/提交准入是加载与前台余量，不是模型固定占用。

<a id="fast-speech-runtime"></a>
#### ZipVoice 快速备用组件（2026-10-18）

**implemented：ZipVoice-Distill int8 + Vocos 独立 CPU 文件 TTS；短样本速度及真实浏览器路径 verified，完整实时聊天仍未实现。** 按主人最新要求改为备选，平时不启动；入口为“设置 → 模块与升级 → ZipVoice · 备用语音”，需要时手动加载，再输入短句、生成、试听或下载 WAV，可独立停止释放进程。默认发布方参考声音可直接使用，上传参考录音与准确文字放在可选折叠项；不会自动切换到慢速 CosyVoice3，也不会因克隆要求静默改为云端。

固定资产、365 项文件摘要与运行参数在 [zipvoice.json](../config/model-profiles/zipvoice.json)；`model_root` 默认为 `H:/JarvisData/models/tts`，使用项目现有轻量 sherpa-onnx 1.13.8 环境，推理另起本实例拥有的进程，不安装 PyTorch/CUDA 或复制聊天核心。固定档案使用 CPU 4 线程、4 步；运行输入限制以[快速语音契约](contracts.md#fast-speech-contract)为准。容量准入为可用 RAM/提交各至少 2 GiB，包含前台余量，**不是运行实测内存**。下载压缩包与声码器约 163.32 MB，展开并加演示参考约 205.32 MB，亦不能当作运行 RAM。

**角色与表达能力。** 此处“角色”指发声的音色，不是聊天人格。ZipVoice-Distill 按参考录音和准确文字定义发声者，没有内置固定人数的预设角色库；当前项目只有 **1 个默认演示声音**，可为单次请求上传其他获许可声音，但尚无持久命名音色库或多角色轮流播报调度。一次合成使用一位参考说话人；同系列 ZipVoice-Dialog 是另一模型，不能把其双人能力算到已安装的 Distill。[S189](references.md#s189)、[S213](references.md#s213)

| 控制项 | 上游接口与本项目当前边界 |
|---|---|
| 中文、英文与音色 | 支持中英参考声音合成；实际混说质量仍须核对，不由“支持双语”推导零错误 |
| 说话语速 | 上游有 speed 参数；当前 Worker 固定 1.0，网页/API 尚未开放语速调节。说得快慢与计算生成耗时是不同指标 |
| 停顿与韵律 | 文字标点及参考音频可提供引导；没有已验收的逐字重音、停顿时长或韵律曲线控制 |
| 开心、伤心、温柔等文字指令 | 当前快速路由只接受 neutral，不支持任意情绪指令或情绪强度参数；不能把 `[开心]` 当作已支持标签 |
| 参考录音的情绪/语气 | 可尝试用不同表达的参考片段引导，但尚未验证能稳定复现情绪；不是完全没有表现力，也不是精确情绪控制 |

蒸馏减少推理步数，int8 进一步压缩并加速 CPU；官方提示量化会有一定质量损失，不能宣称与未量化原版毫无差别。[S213](references.md#s213) 当前角色和控制项以真实 Worker/API 为准，后续增加音色库或语速控件时再更新实现状态，不仅根据上游参数宣称界面已经可用。

首次安装与离线核验：

```powershell
H:/JarvisData/envs/dev/Scripts/python.exe tools/setup_zipvoice.py --download
H:/JarvisData/envs/dev/Scripts/python.exe tools/setup_zipvoice.py
```

只有 `--download` 才联网；固定发布方压缩包和参考原件先验摘要，解包限制路径、类型和体积。默认参考从已锁定 CosyVoice 源码提交取得并转 PCM16，不需要下载 CosyVoice3 大模型或安装其推理环境。观察状态不加载权重、不发网络请求；下一次显式加载才核验全部文件。首次冷启动、已加载后的生成、网页取回结果和实际扬声器起音分开计量，详见[实测及限制](delivery-validation.md#fast-speech-evidence)。

<a id="cosyvoice3-runtime"></a>
#### CosyVoice3 独立文件语音组件（2026-10-18）

**implemented：独立进程、受限合成接口和设置面板；真实模型验证以[组件验收](delivery-validation.md#cosyvoice3-evidence)为准。** 它提供文件 TTS，不代表麦克风 STT、实时双向语音、声纹登记或所有情绪的听感均已通过。入口是“设置 → 模块与升级 → CosyVoice3 本地语音”，打开页面只观察，点击“加载语音模型”才校验并加载；可选择克隆、参考声音配合情绪指令或跨语种合成，试听或下载 WAV，点击停止回收本实例拥有的语音进程。

| 项目资产 | 职责 |
|---|---|
| [独立配置](../config/model-profiles/cosyvoice3.json) | 固定官方模型/源码/Matcha 修订、文件大小与 SHA-256、CPU 参数和外部目录；与原 2 GB 小模型基线分开 |
| [安装工具](../tools/setup_cosyvoice3.py) | 显式下载、断点续传、校验与独立环境准备；启动和打开设置不执行安装 |
| [依赖声明](../config/cosyvoice3-requirements.txt) / [本机锁定依赖](../config/cosyvoice3.lock.txt) | Python 3.12 的独立 CPU 环境；不把 PyTorch 安装进文字聊天的 Python 3.13 环境 |
| [宿主适配](../runtime/node-host/jarvis_core/speech.py) | 一条独立语音操作通道、状态、取消、内存准入和进程所有权 |
| [推理 Worker](../adapters/speech/cosyvoice3/worker.py) | 原生 CosyVoice3 推理；只绑定随机环回端口，用单次实例 token 与宿主通信 |
| [设置面板](../apps/web/speech.js) | 加载、停止、输入文字、情绪选择、参考 WAV、音频播放与下载；桌面/窄屏界面验证单列 |

安装命令在仓库根目录执行：

```text
python tools/setup_cosyvoice3.py install --python 3.12
python tools/setup_cosyvoice3.py verify
python tools/probe_cosyvoice3.py
```

默认模型目录 `H:/JarvisData/models/tts/cosyvoice3`，源码在 `H:/JarvisData/components/cosyvoice3/source`，环境在 `H:/JarvisData/envs/cosyvoice3`；第三方缓存集中在该组件的 `cache` 目录。原生初始化还读取 `CosyVoice-BlankEN/model.safetensors`，因此当前选择的 **13 项下载资产共 5,427,041,085 字节（约 5.427 GB）**，包含上节五项主权重及初始化/词表/配置/说明；五项主权重的 4.435 GB 不是完整安装下载量。没有下载 `llm.rl.pt`、重复 flow ONNX、batch tokenizer、CUDA 运行包或 Web 演示服务。[S214](references.md#s214)、[S215](references.md#s215)

保留上游源码和原 YAML；从已固定并验证的 YAML 生成 `jarvis-inference.yaml`，只保留 LLM、flow、HiFT、词表和参考音频前端，避免在推理时实例化 GAN 判别器和数据训练管线。模型类及三个推理模式继续使用固定上游实现，没有以替代模型冒充 CosyVoice3。安装范围与精确依赖以配置/锁定文件为准。

聊天和后台任务不占用语音单通道；语音错误/超时回收该次组件进程。Windows Job 为生命周期所有权边界，不宣称它是代码安全沙箱。子进程只保留基本系统变量和用户目录路径，不继承 API Key/代理/模型参数覆盖；Hub 设置为离线并使用本机固定文件，这不是操作系统断网防火墙。组件缺失或配置损坏只报告语音不可用，不阻止宿主启动。每次新加载重新读取组件配置并冻结给该次 Worker；更换已校验模型/环境路径可在停止后下次加载生效，不替换正在使用的模型，不提供一键热升级源码或自动下载。

完整输入边界、临时参考音频处理、回执和取消语义仅在[语音组件契约](contracts.md#cosyvoice3-contract)维护。听感、真实速度和资源消耗只以[原生验收记录](delivery-validation.md#cosyvoice3-evidence)说明，不把合成测试后端的界面耗时算成真实 TTS 性能。

<a id="voice-overlap-separation"></a>
#### 说话人识别、分段和重叠分离分开验收

声纹回答“更像登记的哪一个人”；diarization 回答“谁在什么时间说话”，匿名的 speaker_0 本身不是某个人的身份。**两个人同时说话并分别提取波形**还需要分离/目标说话人提取：主研究候选为 [WeSep](references.md#s205) 的目标说话人提取，备选为 [SpeechBrain SepFormer-WHAMR](references.md#s206) 的双人分离。它们尚未安装/实测，不保证普通 PC 实时，也不保证英文训练集上的效果直接迁移到中文与多人房间录音。

先实现单人讲话及轮流讲话的身份/分段；重叠未解决时标记不确定并请重述，不将混合音频认成主人指令。多个麦克风/独立声道有帮助，普通单麦克风无法保证总能准确分开多人。当前 sherpa 的 Spleeter/UVR 接口主要解决人声/伴奏等声源，不能直接称作“主人与朋友分离” [S207](references.md#s207)。

<a id="voice-cloud-candidates"></a>
#### 国内外云端候补与价格口径

以下为 **2026-10-18 查阅的公开原价或待核价状态**，不是当前账户实付、剩余额度或免费资格。STT 按输入音频时长，TTS 按字符/音频 token 等分别计量；不折算汇率，不把不同任务单位直接排名。克隆登记、会话 LLM、重试及生成失败的费用另计。

| 用途 | 候补主选 | 第二候补 | 费用与适用边界 |
|---|---|---|---|
| 国内 STT | **百炼 qwen3-asr-flash**，先接短录音 | 需要增量时用 qwen3-asr-flash-realtime；新 qwen-audio-3.1-asr-flash-streaming 待同集对照 | 北京短录音原价 0.00022 元/秒，约 **0.0132 元/分钟**；实时型号单独核价。保持中英/其他语种支持，不为省价把 16kHz 原声降成 8kHz 电话音频 [S197](references.md#s197)、[S198](references.md#s198) |
| 国内 TTS 克隆/情绪 | **百炼 cosyvoice-v3.5-flash** | qwen-audio-3.1-tts-flash，优先比较自然度与克隆稳定性 | 前者北京原价 **0.8 元/万字符**，支持克隆/声音设计与指令；后者采用其专用接口和计价，不能套旧 qwen3-tts 字符单价 [S196](references.md#s196)、[S199](references.md#s199) |
| 国外 STT 成本候补 | **xAI grok-voice-transcribe-2.0** | Google gemini-3.5-transcribe；必要时 OpenAI gpt-transcribe | xAI 批量 **0.10 美元/小时**、流式 **0.20 美元/小时**，支持中英等 38+ 语种；Google/OpenAI 本轮未冻结费用。Google 文件路径与 live 路径的说话人标签能力不同，不能互相冒充 [S200](references.md#s200)、[S194](references.md#s194)、[S204](references.md#s204) |
| 国外 TTS 克隆/情绪 | **Google gemini-3.8-flash-lite-tts（Preview）** | 需要更强表现时 gemini-3.8-flash-tts（Preview） | Lite 到 2026-12-31 为每百万文本输入 token **0.50 美元**、音频输出 token **6 美元**；2027-01-01 起公开价分别为 1 / 12 美元。支持声音复刻/设计；实际项目准入和用量另验。使用 Gemini Enterprise API，不能套 Cloud TTS 的旧接口 [S193](references.md#s193)、[S208](references.md#s208) |
| 国外固定声音应急 | xAI `/v1/tts` | OpenAI gpt-4o-mini-tts | xAI **15 美元/百万字符**，即 0.15 美元/万字符。其克隆目前有美国地域限制且创建 API 需 Enterprise，不能作为当前国内账户的通用克隆候补。OpenAI 从录音创建自定义声线也有准入条件；预置音色不等于克隆 [S200](references.md#s200)、[S201](references.md#s201)、[S203](references.md#s203) |

OpenAI 当前文件转写推荐为 `gpt-transcribe`；新语音应用指南另推荐 GPT-Live，不能沿用旧版本印象给 GPT-6 Astra/Sol/Luna 增造语音型号 [S202](references.md#s202)、[S204](references.md#s204)。Google 原生实时候选为 `gemini-3.8-live` [S195](references.md#s195)。它们作为后续全双工会话方案比较，不改变首期“STT → 既有聊天核心 → TTS”的选择；省下的接口步骤不自动证明端到端更便宜或主人识别已完成。

本机只读核查确认 Google 服务账户、百炼/OpenAI/xAI/Eachlabs Key 已存在且绑定一致；**未实测这些账户的语音权限、地域、余额或新增 API 启用状态**。沿用现有 DPAPI 凭据，不把 Key 复制到语音配置/文档。Eachlabs 的当前已配置 Claude 档案继续只充当文字核心候选，未验证的第三方语音目录不进入首批。

<a id="voice-routing-policy"></a>
#### 资源与效果驱动的候补规则

本地 TTS 主力必须满足[主人三项要求](#voice-local-candidates)，当前已接受 Qwen3-TTS 1.7B Q5_K，听感与接入范围见[验收页](delivery-validation.md#qwen-tts-integration-evidence)。ZipVoice 默认停止，需手动选择才加载，不在后台偷偷启动；CosyVoice3 保留按需增强。后续聊天接入应采用短句增量合成、可打断播放和对话轮次取消；模型计算 RTF 小于 1 只说明生成速度快于音频长度，不能代替麦克风结束检测、STT、LLM 首句和播放缓冲的联合验收。

第一版使用独立可替换的语音适配层，STT、TTS、声纹、分段分别选型，复用当前 ChatService 的人格/记忆/工具边界；不是再复制一个聊天大脑。默认本地，只加载当轮需要的组件；复杂分离与增强 TTS 按需排队，语音不阻塞文字会话与后台队列。实际接入和验收分别归[交互计划](interaction-persona.md#voice-chat-plan)与[测试要求](delivery-validation.md#voice-selection-evidence)。

候补顺序按能力约束、语种、资源余量、最近实际耗时和费用筛选：内存准入失败、持续不能实时处理、不支持语种或用户要求重识别/增强情绪时，才选已验证的候补；没有可靠置信分数时不凭非空文本宣称识别正确。资源阈值在目标机测试后冻结，未达到时可只将 STT 或 TTS 切云，声纹登记特征默认留本机。网络和资源均不足时退回按键短句、固定本地声音或文字。

云端录音外发需已启用相应候补并明确目的地；本地失败不隐含授权把所有录音发给任意供应商。语音请求用独立时限和并发预算，换 TTS 不重复模型回答或后台动作；未知远端结果不盲目重试计费。语音克隆的参考声音限本人或获许可素材。不同供应商的 voice_id 不通用，备用路由需有兼容声音配置；找不到兼容克隆时明确降级，不能悄悄换成别人声线。最终时延、准确率、分离和克隆自然度以真实测试为准，不预填高分。

<a id="computer-use-models"></a>
## Computer Use：已验证的 DOM 规划与视觉候选

基础 17 个档案提供文本接口，**0.1.8 已复用它们作为浏览器 DOM 规划入口，GPT-6 Luna 完成一次真实四步合成表单任务**。无需视觉模型即可操作有元素语义的网页；这不是截图定位或原生桌面控制。模型目录可选不代表全部通过浏览器规划验收。截图保留本地，文本和目标状态经既有网关外发，见[浏览器使用](core-bootstrap.md#runtime-computer)。

本轮 Google `gemini-3.8-flash` 的首次规划请求等待超时，按 UNKNOWN 保留且没有自动重发；独立新任务改用 `gpt-6-luna`，四次调用均成功，共 2,820 输入 / 166 输出 token，任务约 23 秒。单一合成场景不能推断复杂网站成功率；[证据](delivery-validation.md#computer-evidence)记录两个结果。Google/百炼/XAI/本地模型仍可显式选择，能力验证与接口可调用分开。

| 候选 | 用途与判断 | 本项目状态 |
|---|---|---|
| Gemini 3.8 Flash | 首个云端候选；官方 Computer Use 文档有浏览器和桌面接口 [S115](references.md#s115) | 已有同名文本档案；当前是 Vertex 服务账号，Gemini API 的 Interactions 示例不证明这个账号/端点已经可用，须单独验证 |
| GPT-6.1 Sol / GPT-6 Astra | 复杂任务备选；官方分别提供结构化 computer 动作示例及 Astra 的代码执行接法 [S114](references.md#s114) | 已有文本档案；截图、工具循环与隔离桌面尚未接入，不假设现有余额/权限一定可用 |
| Qwen3-VL-2B / 4B Instruct | 小型离线视觉候选，官方仓库提供 GUI agent 和 computer-use 示例 [S116](references.md#s116) | 未下载；先测量化运行包、截图分辨率、中文定位和峰值内存，不把参数小等同于能可靠自主操作 |
| 现有 Qwen3-0.6B | 可协助简单文本规则或已知元素任务 | 文本模型不能直接理解截图；不作为视觉模型宣传 |

上表的视觉接口均仍为候选，尚未接入本轮 DOM 执行器。下一步先扩展固定网页场景评测，再比较离线候选，不同时安装多套 GUI Agent 框架。百炼现有 Qwen3.8、XAI 与本地 0.6B 文本档案没有通过本项目浏览器规划验收。`auto` 目前沿用聊天候选顺序，尚无基于 Computer Use 成功率的自动优选，推荐显式选择已验证模型。

<a id="embedding-candidates"></a>
## 本地嵌入模型的候选与资源边界（proposed）

嵌入模型负责检索向量，与聊天 LLM、STT、TTS、声纹模型分工不同。现有 Qwen3 0.6B 聊天模型并不等于 Qwen3-Embedding-0.6B；本轮只调研，没有下载或启用下列模型。首期先测中文小模型与多语言小模型两种配置，增强配置按收益启用。

| 候选 | 官方规格与许可 | 本项目用途与待验证点 |
|---|---|---|
| BAAI/bge-small-zh-v1.5 [S102](references.md#s102) | 约 24M 参数、512 维、MIT | 中文资料优先的小资源候选；英文代码/中英跨语言检索另测，不能由中文成绩推断 |
| intfloat/multilingual-e5-small [S103](references.md#s103) | 384 维、最长 512 token、MIT；检索按模型卡添加 `query: ` / `passage: ` 用途前缀 | 多语言小资源对照；中文同样需要规定前缀，长资料切片不得静默截掉答案 |
| Qwen/Qwen3-Embedding-0.6B [S104](references.md#s104) | 0.6B、100+ 语言及代码、32K 上下文、可配置 32—1024 维、Apache-2.0 | 有更多资源时的增强候选；权重和推理成本明显不属于最小档，长上下文也有实际计算成本 |

这是候选用途，不是本机质量排名。BGE/E5 原始权重、ONNX 或其他量化导出分别锁定修订、许可证、分词器和推理运行时；量化后的中文召回要重测。先用 CPU 得到可重复基线，再按目标机器验证加速后端；开发机的集成显卡不能自动等同 CUDA 环境。实际下载体积、常驻/峰值内存、构建依赖和离线加载成功率均写进测量报告。

向量容量计算与设备预算统一见[记忆资源模型](delivery-validation.md#memory-resource-envelope)，不能当作端到端内存实测。缩小 Qwen 输出维度可以减少向量存储，不会按同一比例减少模型权重内存；减少片段数量也可能丢失召回能力。

模型升级时新旧向量空间隔离，使用独立索引构建并追平增量，验收后切换检索指针；不能把相同维数的不同模型结果混进同一空间。旧模型不可用时回退关键词检索，不阻塞事实写入；退役规则沿用[知识迁移](knowledge-learning.md#memory-selection-design)及[组件生命周期](#local-survival-5)。

<a id="model-routing"></a>
## 双路模型连接与恢复设计



<a id="model-routing-1"></a>
### 结论：需要独立恢复路径，生产与进化还需分配独立资源

“两套路由”分成三个问题处理：

| 维度 | 设计 |
|---|---|
| 业务用途 | 实时交互、后台任务、维护进化分别有队列、优先级、预算 |
| 推理位置 | 每类请求可选择本地、局域网或云端模型 |
| 故障恢复 | 主模型网关之外保留简化、独立的恢复连接 |

不要求常态下运行两套完全相同的智能系统。两套网关若共享唯一配置库、运行环境和故障依赖，仍可能同时失效。

<a id="model-routing-2"></a>
### 通道设计

**A：生产模型通道**

- 服务对话与正式任务，按延迟、模型能力、质量、费用和隐私选择部署。
- 支持多个实例、限流、熔断、冷却、健康检查和回退。
- 可使用 LiteLLM 作为可替换实现，外层仍使用项目自己的 ModelGateway 契约。[S15](references.md#s15)

**B：维护与进化通道**

- 服务诊断、代码研发、方案比较与实验。
- 独立队列、预算、并发和超时；生产交互优先占用保留资源。
- 平时可使用同类适配器库；故障处置时不能只依赖已失效的 A 通道。

**R：最小恢复入口**

- 由独立小进程读取最后已验证配置，直接调用本地模型或独立备用部署。
- 不要求主网关、完整记忆服务、Agent 框架或共同体在线。
- 未锁存时的必需能力：状态查询、停止任务、恢复版本、基础文字交互。锁存后只保留固定状态、告警和主人认证，不自动调用任何模型或修复程序。
- 停止、回退和启动由确定性代码完成；没有任何模型可用时仍能使用 CLI 或本地恢复界面。
- R 只接受受限的恢复、状态与基础交互请求，拥有独立配额。生产请求失败后降级或等待，不透明转移到 R 继续运行；故障汇总事件触发诊断，避免恢复资源被普通任务耗尽。

<a id="model-routing-3"></a>
### 路由输入与选择顺序

路由请求包含：任务类型、所需模态、上下文大小、工具/结构化输出能力、延迟预算、费用上限、数据范围、节点资源、允许供应商和当前版本。

顺序：

1. 按权限、数据范围、联网状态与模型能力过滤候选。
2. 检查预算、并发槽和可用显存/内存。
3. 按该类任务的实测质量与延迟选择候选。
4. 请求失败后记录结果，判断能否重试或换部署。
5. 新策略先离线评估和小流量试用，再进入正式路由。

模型自报“我更适合”不能直接替代实测。学习型路由属于后续优化，初期使用可解释规则。

<a id="model-routing-4"></a>
### 流式回答与工具调用

一轮输出绑定 turn_id、generation_id 和已播放/已显示偏移。
- 供应商中断时，不把另一模型的续写无标记拼到已输出文本中；在句段或轮次边界恢复。
- 对话取消只停止对应生成，不自动撤销已经完成的现实操作。
- 模型重试不能重做工具动作；工具调用通过稳定 action_id 查询执行账本。
- 不同模型的工具格式、视觉输入与结构化输出能力不完全一致，适配器需要能力验证。

<a id="growth-model-policy"></a>
### 自检、自愈、进化的模型与档位策略

**proposed，三用途分别配置；当前成长实现仍只有一个编码 route。** 共用一个 ModelGateway 与模型目录，增加用途策略选择器，不启动三个模型服务或复制三套凭据。每种用途先决定是否需要模型，再选择已允许的连接；无模型可用时仍可本地自检和执行确定性恢复。

| 用途档案 | 默认调用时机 | 选择依据 | 可进一步细分的阶段 |
|---|---|---|---|
| 自检 | 正常检查不调用；仅开启 AI 诊断后处理未解释异常 | 有足够上下文与结构化输出能力、低延迟；小模型是否足够由诊断集验证 | 诊断、报告解释 |
| 自愈 | 配方无法解决且证据指向代码缺陷时 | 修复与兼容测试实绩优先；复杂度增加时在已设范围内升档 | 定位、修复编码；默认继承本用途档案 |
| 进化 | 主人目标或已接受的能力提案进入研发 | 规划/编码质量与成本、耗时综合比较 | 规划、编码、评审；默认继承本用途档案 |

每个档案可设置：启用方式、首选连接/模型、**该模型实际支持的推理档位**、有序备选（初期最多三个）、允许自动切换的故障类别、上下文范围、输出上限、总耗时、请求次数与费用提醒。备选每一行独立设置档位；切换模型后只显示目录核验的合法选项，不把不支持思考的模型伪装成“高”。“省资源 / 均衡 / 深度”可作为界面预设，但保存与任务详情必须展示实际原生档位；自动升档若启用须给出上限和原因，不能擅自选任意最贵模型。

默认模型从本机已启用、能力满足、已有测试证据的目录选择，用户可覆盖；不硬编码“某品牌永远最好”。建议首选与至少一个备选来自不同供应商，减少同家配额故障的关联；同模型两个名字不代表两个故障域。本地模型只在已安装、资源足够且该类任务验收通过时成为可执行备选，不能把 0.6B 自动视为复杂修复的等价替代。外部 Codex 的认证、模型和费用仍按 [CodingProvider 边界](evolution-release.md#external-coding-executor)单列。

<a id="growth-fallback-policy"></a>
#### 备选切换的确定规则

任务开始时冻结用途配置版本。顺序为能力/范围过滤 → 配额与资源准入 → 首选请求 → 分类回执 → 合格备选；单次逻辑请求中每条连接最多派发一次，所有备选共享一次任务的时间、调用和费用预算。发现首选未配置/已禁用/明确不可用时直接跳过并解释，不用付费“探活”维持绿灯。

| 结果 | 自动处理 |
|---|---|
| 明确额度耗尽、模型下线、可分类的限流或供应商不可用 | 标记该连接不可用/冷却；按配置选择下一条合格备选，并显示切换原因；不猜测真实余额 |
| 认证失败 | 隔离这一连接，提醒更新凭据；只有单独启用“认证失败可用其他连接”才继续既有备选，不更改 Key |
| 超时/断连且已派发、UNKNOWN 或结果可能已计费 | 先核对请求记录；保留待核对，默认不自动重发，不能通过换模型抹去未知结果 |
| 参数或接口契约错误 | 停止该配置并报告，不轮流调用所有模型掩盖实现缺陷 |
| 返回完整但测试不通过 | 属于候选质量失败，不谎报供应商离线；在剩余研发次数内可向同模型反馈或按质量升级策略换模型，计入同一实验 |
| 全部备选不可用 | 保留检查报告、可用旧包和研发检查点，显示等待原因；联网恢复/冷却到期只恢复获准任务，不重放有未知效果的步骤 |

熔断按连接和故障类别作用，退避后以一个必要的真实请求半开试探，避免多个模块同时抢着测试恢复。切换后的新文本候选从完整契约重建，不拼接两家模型的半截代码；每次尝试均保留实际连接、模型、原生档位、时间、状态与用量。自检、自愈、进化使用不同策略但共用连接健康事实，不因为自愈模型故障而误报工具损坏。

<a id="growth-budget-policy"></a>
#### Token、费用与普通 PC 的资源预算

**零模型检查为 0 token；AI 诊断、编码、模型评审才计费。** 页面分别展示输入、输出、可获得的思考/缓存用量、实际供应商回执及估算费用；缺失用量显示“未知”，未知价格不填 0。供应商配额与账户余额只采用真实接口/错误回执，不能从调用次数估算出“还剩多少钱”。

按用途与整体分别统计，所有备选和重试归同一逻辑任务预算；先预留再派发，避免并发透支本机配置额度。日/月费用默认可采用提醒模式，主人也可选择硬停止模式；不能把原型的每日四次写死为永久产品规则，也不能迁移成三个各四次而无声扩大总额。原型的有限候选次数保留为防循环默认，界面允许在实现支持范围内调整。费用硬界限只能限制新请求准入，不能保证已在供应商执行的请求立刻停止计费；UNKNOWN 仍占用待核对预留。

先预留聊天和任务资源，再让维护使用剩余额度。受影响对象发布串行，后台研发并发首期为一，确定性观察可并行但每探针有时间/输出上限。设置页动画停止时无需停止后台工作；后台也无需保持任何浏览器标签或本地大模型常驻。详细调度归[自检计划](health-maintenance.md#inspection-scheduling)。

<a id="model-routing-5"></a>
### 路由流程图

![model-routing](diagrams/model-routing.png)

[矢量图](diagrams/model-routing.svg) · [可编辑图源](diagrams/model-routing.mmd)


图中的重试受总时间、费用、次数和动作状态限制，不能无限循环。进入任何路由前先检查 security_stop_latch；锁存时本图的模型和恢复调用全部禁止，只提供[主人利益最高原则、独立监督与锁存关停](security-sovereignty.md#sovereignty-shutdown)的固定停止服务。

<a id="local-survival"></a>
## 本地小模型、离线生存与网络自恢复



<a id="local-model-runtime"></a>
### 当前小模型运行、启停与资源边界（0.1.32）

[local_model.py](../runtime/node-host/jarvis_core/local_model.py)统一提供固定组件准备、CPU 启动参数与本实例进程生命周期；设置入口和前台诊断复用同一份校验和参数定义，不维护两套模型选型。只读取清单中已锁定的 Qwen3 0.6B Q8_0 和 llama.cpp b11617，核验字节数及 SHA-256 后检查缓存运行组件；异常不覆盖、不下载、不换大模型。启动不会修改有效路由或主人的模型偏好。

页面显式启动经既有独立维护通道执行，不占聊天槽或任务队列。核验前及创建进程前均检查可用物理/提交内存：模型估算 1,536 MiB，另留 1,024 MiB 前台余量；这不是 OS 内存预留或硬上限。固定为 CPU 4 线程、2048 上下文、256 输出 token、1 序列、0 GPU 层；关闭思考，固定环回地址 18180，使用引擎 `--offline` 及零空转轮询。参数依据固定版 [S168](references.md#s168)，不能仅凭设置值声称质量或峰值资源达标。

仅本实例启动的引擎记为 owned；Windows Job 在创建时绑定并设置 kill-on-close，正常停止回收自己的进程，生命周期机制依据 [S169](references.md#s169)。这不是 AppContainer、恶意模型安全沙箱或 OS 外联防火墙。18180 已被其他服务使用时拒绝接管，不按端口或名称杀进程。停止前有任意聊天/后台任务活动时拒绝主动停止，明确退出 Host 时回收自己拥有的引擎。进程意外退出会显示失败，不自动重启、重新规划或继续付费路由。

打开设置只观察文件大小、环回健康和 owned/state/pid 元数据，不加载权重；仅“启动本地模型”按钮才核验/加载。服务启动后保留模型以供后续请求，使用者可显式停止以释放内存；没有自动开机启动或后台自动下载。健康响应不证明正在推理、模型身份或通用质量，外部服务的健康仍只算观察。页面关闭不停止已启动引擎；默认源码 Host 退出后再次启动需重新显式加载。

规划能力采用[固定流程](tasks-agents.md#sample-task-runtime)，实测见[离线证据](delivery-validation.md#offline-task-evidence)。18 个有针对性的样例不能证明所有中文要求都能被正确分类；结构约束只能保证输出形状和固定范围，最终意图正确性仍须验收。

<a id="local-survival-1"></a>
### 目标：在较低资源下仍保留有用能力

每个承诺独立运行的完整节点提前配置离线能力包。小模型负责语言理解、简短交流、分类、检索和选择已验证操作；确定性程序负责网络检查、配置读写、权限判断、停止与恢复。

“足够小且强”通过目标任务的质量、内存、延迟、能耗和工具参数准确率共同选择，不按参数量或文件大小直接认定。小模型做不到的复杂任务保存状态或缩小范围，继续可靠完成可做的部分。

<a id="local-survival-2"></a>
### 本地组件种类

| 组件 | 作用 | 资源紧张时的处理 |
|---|---|---|
| 小型 LLM | 本地交流、理解命令、解释故障、选择流程 | 短上下文、低并发、按需加载 |
| STT/ASR | 本地语音转文字 | 较小模型、按键说话或退到文字 |
| TTS | 本地语音输出 | 轻量声音、减少长篇播报或文字输出 |
| VAD/唤醒 | 检测说话和触发交互 | 使用低耗组件，不强制大模型常驻 |
| Embedding/重排 | 本地资料检索 | 全文检索、缓存或较小嵌入 |
| 视觉模型 | 屏幕/图像理解 | 降低频率、截图按需，或暂停视觉任务 |
| 规则与诊断工具 | 状态、网络、错误码、已验证修复 | 不依赖 LLM 的基础能力 |
| 独立监督与告警 | G0 检查、门禁、锁存与停止 | 不允许为给模型腾内存而卸载 |

llama.cpp 与 sherpa-onnx 提供本地语言与语音推理的基础能力；具体模型、中文质量、平台和离线依赖必须在目标机器实测。[S17](references.md#s17)[S18](references.md#s18)

<a id="local-survival-3"></a>
### 离线能力包内容

至少一个在支持设备 CPU 上经过验证的语言模型及运行时、分词器、模板。
- 主人主要语言的 STT、TTS、必要词典、音素器、声码器和声音文件。
- 已缓存的基础知识、诊断手册、工具和技能依赖。
- 无模型可用时的固定文本控制台、停止入口、状态和检查点查询。
- 当前已验证包、上一可用版本和必要安装文件。
- 当前私人使用保留本机状态与故障诊断入口，无需恢复密钥或密码；完整监督认证延期，见[适用范围](security-sovereignty.md#prototype-security)。
- 包哈希、来源、许可、兼容性、离线冷启动结果与资源基线。

模型文件存在不等于离线可用。要切断所有外网与共同体后进行冷启动、识别、合成、检索、网络诊断和任务恢复测试。运行时不得因缺依赖而暗中要求在线激活或下载。

设备低于最低资源或所有模型损坏时，仍力争保留确定性控制；不承诺微控制器或任意旧手机都能运行通用 LLM。

<a id="local-survival-4"></a>
### 资源 Profile

| Profile | 工作方式 |
|---|---|
| LP0 deterministic | 不运行通用模型；固定状态、只读诊断、停止控制和任务保存 |
| LP1 survival | CPU 小模型、短上下文、单任务；基础语音按需；暂停学习与大规模模拟 |
| LP2 local-standard | 完整本地交互、有限任务并发与知识检索 |
| LP3 accelerated | GPU/NPU 条件允许时提高模型、上下文、并发或语音质量 |
| LP4 federated | 允许且连接可用时扩展到共同体或云，保留本地回退路径 |

Profile 依据实际可用内存、KV cache、算力、电量、温度、模型预热与延迟实测选择。转换设迟滞、冷却和最大失败次数，防止网络抖动导致反复装卸。

降级顺序一般为暂停低优先级实验/模拟 → 降并发 → 缩上下文 → 换轻量模型 → 减少语音/视觉 → 固定控制台。监督和停止通道始终保留。

<a id="local-survival-5"></a>
### 自主切换与替换

本地模型管理器可以自主选择已批准组件，也可在联网、预算允许时发现候选并下载验证；不要求每次切换都询问主人。新增权限或超出额度仍遵循独立授权。

生命周期为：

```text
discovered → downloading → quarantined → integrity_checked
→ compatibility_tested → quality_tested → ready
→ warming → active → draining → standby / retired
```

来源可信与内容哈希是两回事；不能仅凭哈希一致认为下载内容可信。下载未完成不得激活，最后一套已知可用的离线能力包不得被自动清理。

LLM、STT、TTS、嵌入和推理引擎分别版本化。替换模型时检查格式、运行时、tokenizer、chat template、语言、结构化输出和工具调用；更换 STT 时防重复转写造成重复动作；更换 TTS 时测试停止、打断、数字和指令读法。

模型的 KV cache 一般不能直接搬给另一模型；迁移规范化消息、任务状态和记忆引用，再重建上下文。人格、权限和停机状态不随模型替换。

<a id="local-survival-6"></a>
### 资源不足时如何换模型

容量足够时 B 预热后接收新轮次，A 排空。容量不足时，先保存会话与任务状态、进入固定反馈模式，再卸载 A、载入 B、验证并继续；这可能有局部等待。

严禁同时卸载最后可用模型、唯一恢复工具和监督模块。失败时载入已验证旧版本；若连旧版也无法运行，进入 LP0，不无限重启和下载。

<a id="local-survival-7"></a>
### 网络诊断和修复

![network-recovery](diagrams/network-recovery.png)

[矢量图](diagrams/network-recovery.svg) · [可编辑图源](diagrams/network-recovery.mmd)


检查顺序：链路 → 地址/DHCP → 网关/路由 → DNS → TCP/TLS → 代理/认证 → 模型服务 → 共同体。断网、供应商配额耗尽和共同体不在线是不同故障。

读取网络状态、检查批准端点、连接重试和切换已授权备用服务可在既有范围内自动进行。网卡重启、DNS/代理/路由修改或网络重置需要预先批准的修复策略，并评估是否切断远程管理及能否本机回退。

不得以恢复网络为由关闭 TLS 校验、绕过认证、弱化防火墙或连接未授权网络。断线电缆、运营商故障、未提供的密码、验证码或物理设备损坏可能需要主人或外部处理；模型不能创造不存在的连接。

<a id="local-survival-8"></a>
### 所有恢复从属于 G0

普通故障允许轻量模型接管、切换组件或修复网络。安全锁存禁止这些自动活动，不能以“恢复自己”“小模型备用”“远端替身”继续业务。

锁存后 LP0 仅包含固定状态、告警、审计、设备安全停止和认证验证，不继续网络修复或一般任务。主人认证后的隔离维护是一条单独的、明确授权的流程。

<!-- book-footer:start -->
[返回全书目录](README.md#book-tree) · [上一章：技术栈、源码目录与运行数据](stack-project-layout.md) · [下一章：记忆、知识库与持续学习](knowledge-learning.md)
<!-- book-footer:end -->
