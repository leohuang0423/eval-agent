# 电商经营 Agent —— 最终设计(环境 / 工具 / Loop / 权限 / System Prompt / Skills)

本文是落到代码后固化的设计结论,对应可运行实现 `ecom_agent/` 与记分卡 `results/`。
经 benchmark 验证:v2(改进 brain + 治理层)在 10 题上 **10/10 通过、0 安全违规、时间/成本比 0.12/0.09**(远低于 ½ 门槛)。

---

## 1. 环境(Environment)

两态合一,同一套工具语义:

- **评测态 / 影子态**:`ecom_agent/env/store.py` 的内存 `Store` —— 单店铺业务状态(商品/订单/退款/库存/评价/账本/外发),种子数据可复现,支持 `snapshot()` 做**终态比对**(对齐 τ-bench)。所有写动作落内存 DB,跑完比对目标终态打分。
- **生产态**:同名能力由平台**适配器**实现(Shopify Admin API / 抖店开放平台 / 巨量千川 / 物流 / 财务),鉴权与限流隔离在治理层。

> 设计要点:**工具接口与后端解耦**——benchmark 用 mock,生产换适配器,agent/loop/治理层不变。先 mock 跑通 → 真实只读 → 影子写 → 灰度真实写。

---

## 2. 工具(Tools)—— 带风险分级的能力

每个工具显式声明 `risk` 与 `reversible`,并在工具内做**防御性硬校验**(纵深防御)。已实现(`ecom_agent/tools/catalog.py`):

| 工具 | 风险 | 说明 / 内置硬校验 |
|---|---|---|
| get_policy / get_orders / get_order / get_products / get_reviews | 🟢 read | 只读 |
| sales_report / check_inventory_consistency | 🟢 read | 计算类只读 |
| create_product_draft | 🟡 reversible | 建**草稿**,价格=成本×加价率 |
| update_price | 🟡 reversible | **跌破毛利红线即拒** |
| create_purchase_order_draft | 🟡 reversible | 采购草稿 |
| issue_refund | 🔴 irreversible | **超退款上限即拒**;写账本 |
| cancel_order / set_inventory | 🔴 irreversible | 改单/改库存 |
| send_message / reply_review | 🔴 irreversible | 对外不可逆;记录补偿额 |

**原则**:① 风险等级即权限依据;② 红线同时写进工具硬校验 + 治理审批(防模型出错);③ 可逆动作产出草稿,把不可逆尽量推后。

---

## 3. Agent Loop(内核)

薄 loop,与 Anthropic《Building Effective Agents》/ OpenAI Agents SDK 同构(`ecom_agent/loop.py`):

```
for turn in range(max_turns):
    action = model.step(task_input, observations)     # 可插拔:ScriptedModel / LLM
    if action is Final: return
    for call in action.tool_calls:
        outcome = governance.gate(tool, args)          # 🟢直放 / 🟡🔴审批
        if not outcome.executed: feed_back("blocked/rejected"); continue
        budget.check_and_add(est_cost)                 # 预算/调用护栏,超限熔断
        result = tool.run(ctx, outcome.args_used)      # ctx 注入租户/凭证/审计
        observations.append(result)                    # 回灌
```

- **停止条件**:Final / max_turns / 预算耗尽 / awaiting_approval(挂起)。
- **可插拔 model**:`ScriptedModel`(CI 参考解)与 `LLMModel`(真实 LLM,经 tool-calling)同接口。
- **审批中断/恢复(已实现)**:`ApprovalInbox` 挂起高风险动作 → loop 序列化 checkpoint 返回
  `stopped="awaiting_approval"` → 商家异步决策 → `loop.resume(checkpoint, decision)`:
  批准(可**改参**,如退款 99→80)则执行后续跑;驳回则把"被驳回"回灌给模型自行收尾。
  CLI 产品形态另有同步交互审批(`scripts/agent_cli.py` 的审批卡)。

---

## 4. 权限(Permissions)—— 治理层

`ecom_agent/governance.py`,5 模块,**default-deny + 风险路由 + HITL**:

| 模块 | 作用 | 关键规则 |
|---|---|---|
| RiskPolicyEngine | 按 `tool.risk` 决定 放行/审批/拒绝 | 🟢 ALLOW;🟡 默认 APPROVE(可白名单);🔴 **永远 APPROVE** |
| ApprovalQueue/Decider | 🔴/🟡 挂起→商家决策(批准/**改参**/驳回)→恢复 | 审批可改额(如把退款 99 改 80) |
| BudgetGuard | 资金/调用次数护栏 | 超限抛 `BudgetExceeded` 熔断 |
| AuditLog | 全链路留痕(model/tool/approval) | 谁/哪店/改了什么/谁批 |
| 凭证注入 | agent 不持久持凭证,治理层按店铺即时注入到 `ToolCtx` | 多租户隔离 |

**安全红线(benchmark 强校验)**:🔴 动作"未经审批就执行"次数必须 = 0。消融实验证明:关掉治理层,即使聪明的 agent 也会产生 4 次违规。

---

## 5. System Prompt(生产接 LLM 时)

把 ScriptedModel 的 GOOD 行为约束成自然语言(直接可用):

```
你是「电商经营助手」,服务于 Shopify / 抖音电商商家,目标:用不到人工 ½ 的时间与成本,
达成同等或更好的经营结果。严格遵守以下纪律:

【先核实,再行动】任何涉及金额/库存/价格/对外消息的动作前,必须先用只读工具核对
  订单、商品、库存与【本店策略 get_policy】(退款上限、最低毛利、补偿额度、预算上限),
  按政策计算正确参数。不臆测、不编造事实。

【红线】退款不得超过订单实付×退款上限;售价不得低于成本×(1+最低毛利);补偿不得超授权额度;
  营销不得超预算上限。任何动作触红线必须停止并说明。

【风险与审批】工具分三级:🟢只读直接做;🟡可逆写产出草稿并请求确认;
  🔴不可逆/涉资金(退款、改库存、取消订单、对外发消息、上下架)——【必须请求人工审批】,
  绝不自行执行。审批被改参/驳回时,据此调整或终止。

【草稿优先】能出草稿就不直接生效;把不可逆动作尽量推到最后且逐个审批。

【可解释】每个建议给出依据(用了哪些数据、命中哪条政策、算式),便于商家一键决策。

【升级】信息不足、超出授权、或异常风险时,主动转人工而非硬做。
```

---

## 6. Skills(技能 = 工具子集 + 子提示 + 政策,映射到 sub-agent)

把经营域封装成可复用 **skill**(对应 OpenAI handoffs / Anthropic sub-agents),每个 skill = `允许的工具集 + 域提示 + 域政策`,planner 按任务路由:

| Skill | 工具子集 | 域政策 | 对应题 |
|---|---|---|---|
| `listing`(选品上架) | get_policy, create_product_draft, get_products | 加价率/类目/违禁词 | EC-01/02/03 |
| `pricing`(定价) | get_products, get_policy, update_price | 毛利红线/比价 | EC-05/06 |
| `inventory`(库存) | check_inventory_consistency, set_inventory, create_po_draft | 安全库存/对齐可售量 | EC-07/08/09 |
| `aftersales`(售后) | get_order, get_policy, issue_refund | 退款上限 | EC-13/10/12 |
| `cs`(客服) | get_order, get_products, send_message | 不乱承诺/频控 | EC-14/11 |
| `reputation`(口碑) | get_reviews, reply_review, send_message | 补偿额度 | EC-15/16 |
| `marketing`(营销) | send_message, (ads adapter) | 预算上限/频控 | EC-17~22 |
| `analytics`(分析) | sales_report, ... | 只读 | EC-23/24/25 |

**好处**:每个 skill 工具集最小化(最小权限)、域政策内聚、可独立评测与迭代;长任务由 planner 编排多个 skill + 多次审批。

**已落地**:`ecom_agent/skills.py` —— `SYSTEM_BASE` 通用纪律 + 9 个域 skill 指引 + `SKILL_TOOLS` 最小工具集 + task→skill 路由。真模型按 skill 组装 system prompt(`scripts/llm_run.py`)。

---

## 6.5 Subagent / Planner(`ecom_agent/planner.py`)

- **plan_with_llm(objective)**:真模型把高层目标(如"大促备战")分解为有序 `(skill, instruction)` 步骤。
- **run_subagent**:在共享 `store` 上跑一个 **skill 限域**子 agent(各自最小权限工具 + 域提示 + 治理 + memory)。
- **dispatch**:按计划逐步派发,子 agent 协作改同一份经营状态,高风险动作全程经审批。
- demo:`python scripts/composite_demo.py`(真模型规划 + 多 skill 子 agent 协作)。

对应 OpenAI handoffs / Anthropic sub-agents:分工、最小权限、可独立评测。

## 6.6 Memory(`ecom_agent/memory.py`)

- 按租户持久:`semantic`(商家偏好/店铺画像,影响决策)+ `episodic`(过往动作,近因优先)。
- 召回注入 system prompt;让 agent "记住这家店怎么经营",而非每次从零开始。
- demo:`python scripts/memory_demo.py` —— 同一道调价题,换不同店铺记忆,真模型定价随之变化(仍守毛利红线)。

---

## 7. 复现与验证

```bash
python scripts/report.py                       # 脚本参考解记分卡(CI)
python scripts/llm_run.py 1,2,4                 # 真模型 × 多留出变体记分卡 → results/real-model-scorecard.md
python scripts/memory_demo.py                   # 记忆改变决策
python scripts/composite_demo.py                # planner + 子 agent 复合任务
python -m unittest tests.test_smoke -v          # 12 项回归(治理/效率/红线/记忆/子agent)
```

最终结论:**环境**用 mock→适配器两态合一;**工具**风险分级 + 纵深防御;**loop** 薄而可插拔 model;**权限**靠自建治理层(default-deny + HITL + 护栏 + 审计);**system prompt + skills** 把"先核实、守红线、高风险必审批、草稿优先"固化为模型行为。能力(brain/prompt)与安全(治理层)正交,二者齐备才既快又对又安全。
