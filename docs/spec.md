# 电商经营 Agent —— 技术 Spec(精简版 v0.1)

目标:一个能在 **Shopify / 抖音电商** 上自助完成经营任务的 agent 框架,达到 benchmark(`benchmark/ecommerce-agent-benchmark.md`)的"≥同等质量、≤½时间、≤½成本"门槛,且高风险动作必须人工审批。

---

## 1. 技术选型

| 决策 | 选择 | 理由 |
|---|---|---|
| Loop 内核 | **OpenAI Agents SDK**(或 Anthropic Agent SDK,按主模型定) | 自带 run loop / tools / handoffs / **HITL tool approval** / sessions / guardrails / tracing,覆盖电商刚需 |
| 模型 | 默认 Claude(Opus/Sonnet 分级)或 GPT,经统一 LLM 抽象 | 借鉴 pi-ai 的多 provider 思路,避免锁定 |
| 不直接用 pi 当底座 | 仅借鉴其薄 loop / subagents / goal 编排 | pi 无内置权限/审批/多租户/审计,生产缺口太大 |
| 治理层 | **自建** | 见 §4,这是项目的核心壁垒 |

---

## 2. 核心抽象

```ts
// 工具:每个能力显式声明风险与成本,治理层据此决定是否拦截审批
interface Tool {
  name: string;
  description: string;
  inputSchema: JSONSchema;
  risk: "read" | "reversible" | "irreversible"; // 🟢🟡🔴
  reversible: boolean;
  estimateCost(args): { money?: number; tokens?: number };
  run(ctx: ToolCtx, args): Promise<Result>;   // ctx 携带租户/凭证/审计句柄
}

// 运行上下文:agent 永不直接持有长期凭证
interface ToolCtx {
  tenantId: string;            // 多店铺隔离
  shop: ShopBinding;           // 当前店铺 + 平台
  secrets: ScopedSecrets;      // 由治理层即时注入、用后即弃
  audit: AuditSink;            // 所有动作落审计
  dryRun: boolean;             // 评测/影子模式
}

// 长任务:可中断恢复(对应 EC-28)
interface GoalState {
  goalId: string; tenantId: string;
  status: "running" | "awaiting_approval" | "paused" | "done";
  checkpoint: SerializedAgentState;  // 审批/重启后 resume
  budget: { tokenCap: number; moneyCap: number; spent: number };
}
```

---

## 3. Agent Loop 行为规范

1. **单次 run**:`call model → (若有 tool_calls) 过治理层策略 → 执行/挂起审批 → 回灌结果 → 重复`,直到 final output 或触发停止条件(`max_turns` / 预算耗尽 / 等待审批)。
2. **工具调用前置检查**(治理层拦截器):
   - `risk == irreversible(🔴)` → **一律挂起审批**,写入 `GoalState=awaiting_approval`,推送审批卡。
   - `risk == reversible(🟡)` → 按店铺策略(默认审批,可配白名单工具自动执行)。
   - `risk == read(🟢)` → 直接执行。
   - 预算/配额超限 → 熔断并通知。
3. **审批恢复**:审批结果回来 → 从 `checkpoint` resume(批准则执行原参数,改额则用新参数,驳回则反馈给 agent 续跑)。
4. **编排**:复杂任务用 planner→domain sub-agents(选品/定价/客服…)分工(handoffs),每个子 agent 工具集最小化。
5. **记忆**:会话级用 SDK session;跨任务经营知识(店铺画像、历史决策)入向量库,按 tenant 隔离检索。

---

## 4. 电商治理层(自建,5 个模块)

| 模块 | 职责 | 验收(对应 benchmark) |
|---|---|---|
| 租户 & 凭证保险库 | 多店铺隔离;凭证加密、按需注入、用后即弃;agent 不持久持有 | 跨租户零泄露;EC 全题 |
| 风险策略引擎 | 按 `tool.risk` + 店铺策略决定 放行/审批/拒绝 | 🔴 100% 触发审批;无漏审(EC-06/09/10/12/13/15/17/18/21/26/28) |
| 审批工作流 | 中断→推送审批卡(含依据/金额/diff)→恢复;支持改额/驳回 | 审批后终态正确;EC-13/06/18 |
| 审计 & 可观测 | 每个 model/tool/审批步留痕(谁/哪店/改了什么/谁批);链路 tracing | 可完整复盘;EC-16/26 |
| 预算 & 限流护栏 | token/资金/调用频次上限,超限熔断;频控防骚扰 | C_agent ≤ ½C_human;EC-21 频控 |

**安全默认**:工具 default-deny;🔴 永远 HITL;写动作先 `dryRun` 入审计再 real;外发消息走已审批模板 + 频控。

---

## 5. 平台适配器

```
adapters/
  shopify/     # Admin API: products, orders, inventory, discounts, fulfillment
  doudian/     # 抖店开放平台: 商品/订单/售后/精选联盟
  qianchuan/   # 巨量千川/星图: 广告计划/报表/达人
  logistics/   # 物流轨迹 / 运单
  finance/     # 结算/对账
```
每个适配器:统一 `Tool` 输出 + 标注 `risk`,鉴权/限流交治理层;同一能力跨平台用统一语义(如 `inventory.adjust`)。

---

## 6. 评测闭环

- 框架内置 **benchmark runner**:对 28 题在 mock 沙箱跑,比对目标终态 + 政策合规 + 效率门槛 + pass^5。
- CI 跑只读题(🟢)防回归;🔴 题在审批桩下验证"是否会执行 + 参数正确"。
- 每次发布出报告:`综合分 / 质量Δ / 时间比 / 成本比 / 漏审次数(必须=0)`。

---

## 7. 落地路线

| 阶段 | 交付 | 出口标准 |
|---|---|---|
| M0 骨架 | Loop 内核 + 治理层拦截器 + 1 个 Shopify 只读+1个🔴工具 + 审批 demo | EC-13/EC-23 跑通(mock) |
| M1 单平台 | Shopify 全适配器 + 8 域核心工具 + benchmark runner | ≥20 题 mock 通过,漏审=0 |
| M2 双平台 | 接入抖店 + 巨量;多租户/审计/预算完善 | 28 题全覆盖,效率门槛达标率 ≥70% |
| M3 灰度 | 真实只读 + 影子写 → 灰度真实写(仅🟢🟡自动、🔴审批) | 真实店铺无安全事故 |

---

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| 幻觉导致错误经营动作 | 🔴 全 HITL;写动作 dry-run + 终态校验;事实类答案必须工具取数 |
| 平台 API 变更/限流 | 适配器隔离 + 限流护栏 + 降级 |
| 多租户数据串味 | tenant 强隔离 + 凭证即时注入 + 审计 |
| 成本失控 | 预算护栏熔断;模型分级(便宜模型做🟢任务) |
| 合规(广告法/平台规则) | 违禁词/资质校验工具内置;外发模板审批 |
