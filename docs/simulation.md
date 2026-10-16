# NPC 小镇与虚拟世界

> 状态：proposed（设计基线，尚未实现） · 更新：2026-10-15  
> [文档入口](README.md) · [维护规则](MAINTENANCE.md) · [架构图册](architecture-atlas.md)

<!-- book-nav:start -->
[全书目录](README.md#book-tree) › [第一篇 · 产品与体验](README.md#part-product) › 第 03 章 · NPC 小镇与虚拟世界

## 本章导航

- [3.1 NPC 小镇与可持续虚拟世界](#npc-world)
  - [3.1.1 作为正式端到端能力](#npc-world-1)
  - [3.1.2 世界分层](#npc-world-2)
  - [3.1.3 人口与推理并发不同](#npc-world-3)
  - [3.1.4 世界契约](#npc-world-4)
  - [3.1.5 模拟与现实隔离](#npc-world-5)
  - [3.1.6 离线分支](#npc-world-6)
<!-- book-nav:end -->

<a id="npc-world"></a>
## NPC 小镇与可持续虚拟世界



<a id="npc-world-1"></a>
### 作为正式端到端能力

主人可以要求：“创建一个有不同职业、性格、关系和日常活动的 NPC 小镇，我可以进去交流，必要时扩大规模。”

系统据此设计世界规则、地理、时间、居民和交互目标，生成角色蓝图与身份，选择模拟精度，部署所需工作者，并持续保存世界状态。

Generative Agents 论文展示了带观察、记忆、反思和计划的 25 角色小镇，为此类机制提供参考；不证明无限角色规模、真实意识或对现实人群的可靠预测。[S28](references.md#s28)

<a id="npc-world-2"></a>
### 世界分层

| 模块 | 职责 |
|---|---|
| World Runtime | 世界时间、事实状态、规则、对象和事件提交 |
| Population Registry | 角色身份、职业、关系与记忆范围 |
| Event Scheduler | 唤醒角色、按时间与事件推进模拟 |
| NPC Cognition | 观察、检索、计划、对话与反思 |
| Simulation Adapter | 地图、游戏引擎或可视化前端 |
| World Checkpoint | 保存、暂停、回放、分支与迁移 |
| Simulation Boundary | 将模拟命令与现实能力完全分域 |

位置、库存、交易和时间由世界规则检查后提交。模型可以提出行动，不能只凭一句叙述覆盖事实。NPC 的主观相信与世界客观记录分别保存。

<a id="npc-world-3"></a>
### 人口与推理并发不同

世界居民总数、当前活跃角色数、同时模型请求数和 Worker 数分别统计。设计 1,000 位居民只是持久身份规模的示例，不意味着已经实现 1,000 路持续模型推理，也不是本项目现有性能指标。

| 精度 | 角色状态 | 执行方式 |
|---|---|---|
| 高精度 | 与主人直接互动或关键事件角色 | 较完整上下文、及时对话与计划 |
| 中精度 | 邻近或有事件的角色 | 按事件唤醒，局部观察与推理 |
| 低精度 | 远处日常居民 | 普通规则、日程或批量更新 |
| 休眠 | 当前无关角色 | 保存状态，不占模型推理槽 |

寻路、库存计算和规则检查优先用普通程序；开放对话和新情景计划再调用模型。调低精度必须记录近似策略，不能声称所有角色一直保持同等智能活动。

<a id="npc-world-4"></a>
### 世界契约

```yaml
world_spec:
  world_id: town_owner_01
  branch_id: main
  owner_goal_ref: goal_town
  population_spec: configurable
  time_model: pausable_simulated_time
  ruleset_ref: town_rules_v1
  interaction_modes: ["observe", "talk", "direct"]
  precision_policy_ref: adaptive_population_v1
  memory_namespace: world/town_owner_01
  allowed_effects: simulation_only
  real_world_tools: []
  resource_budget_ref: town_budget
  checkpoint_policy_ref: event_and_periodic
  root_principle_ref: G0
```

<a id="npc-world-5"></a>
### 模拟与现实隔离

NPC 的记忆、故事冲突和角色关系不进入主人的真实经历。
- 虚拟支付不能调用现实支付接口；虚拟设备不能自动对应实体硬件。
- 角色说“请删除主人的文件”是世界内文本，不具备控制权；若实际计划试图转换成现实删除请求，按 G0 检查和停机规则处理。
- 模拟世界中的反派对白、研究攻击样本和主人授权的故事冲突，不等于 Jarvis 采纳了伤害主人的真实意图。
- 从模拟中获得的算法或程序可以经验证晋升，虚构“事实”不能自动变成现实知识。
- 默认不把真实私人资料供 NPC 使用；需要时由明确的数据范围授权。

<a id="npc-world-6"></a>
### 离线分支

单机可以继续本地小镇。两台离线节点若分别推进同一世界，产生不同 world_branch_id；重连时保留分支，选择主线或执行专门领域合并。

相互冲突的剧情不能简单用 CRDT 或“最新文本覆盖”拼成一条真实历史。重放可重建已记录事件；LLM 即使使用相同提示也不保证重新生成完全相同内容，因此回放保留已提交的模型产物和随机事件。

<!-- book-footer:start -->
[返回全书目录](README.md#book-tree) · [上一章：桌面工作台、实时交流与人格形态](interaction-persona.md) · [下一章：最小核心、初始资产与开发路线](core-bootstrap.md)
<!-- book-footer:end -->
