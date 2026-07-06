# 研究:可扩展 Agent Loop 架构(OpenAI / Anthropic / pi)

> 为电商经营 agent 选底层 AgentLoop 框架而做的调研。结论支撑 `docs/architecture.md` 与 `docs/spec.md`。

## 1. OpenAI vs Anthropic 的 loop 范式

两家核心 loop 同构:`call model → run tools → feed results back → repeat`。差别在产品化程度。

- **Anthropic —《Building Effective Agents》**:主张 loop 要薄。agent = `environment + tools + system prompt` 三要素在循环里反复调用模型;区分 **workflow(预定义代码路径)** 与 **agent(模型自主决定流程)**;能不加复杂度就不加,智能来自 tool/context 工程与 sub-agents。([来源](https://www.anthropic.com/research/building-effective-agents))
- **OpenAI — Agents SDK**:把同一个 loop 产品化为原语:`Agent / Runner(run loop) / function tools / handoffs(子agent委派) / guardrails / sessions(记忆) / 内置 HITL tool approval / tracing`。生产化能力开箱即用。([repo](https://github.com/openai/openai-agents-python))

| 维度 | Anthropic | OpenAI Agents SDK |
|---|---|---|
| 子agent | sub-agents | handoffs(一等公民) |
| 记忆 | context 工程/文件系统 | Sessions 自动托管 |
| HITL | 自己在 loop 里插 | 内置 tool approval / 中断恢复 |
| 可观测 | 自建 | 内置 tracing |

**对电商**:OpenAI 风格原语(HITL/sessions/guardrails/tracing)更贴近经营 agent 的强审批、长周期需求。

## 2. earendil-works/pi

- TypeScript 工具包:`pi-ai`(多 provider 统一 API)+ `pi-agent-core`(Agent loop:发消息→执行 tool→回灌→重复)+ `pi-coding-agent`(CLI)+ `pi-tui`。
- 扩展生态:`ralph`(hat-based 多agent编排)、`pi-goal`(长期目标)、`pi-subagents`(隔离子agent)。
- **关键限制**:README 明确"**不含内置权限系统**,以启动它的用户/进程权限运行",安全靠**外部容器化**(Gondolin/Docker/OpenShell),**无内置 HITL 审批**。([repo](https://github.com/earendil-works/pi))

## 3. 结论

pi 是优秀的**架构参考与单人 coding agent 底座**,但"无权限/审批/多租户/审计"与电商经营 agent 的安全合规需求正面冲突。

**推荐**:用 **OpenAI Agents SDK(或 Anthropic Agent SDK)做 loop 内核**,借鉴 pi 的薄 loop / subagents / goal 编排,**自建电商治理层**(审批/多租户/凭证/审计/预算)。详见 `docs/architecture.md`、`docs/spec.md`。

## 4. 标杆 benchmark(支撑评测设计)

- **τ-bench / τ²-bench**(Sierra):tool-agent-user 多轮、retail 域、终态比对、policy 合规、pass^k 可靠性。([repo](https://github.com/sierra-research/tau2-bench))
- **WebArena / WebShop / ShoppingBench / WebMall**:web 电商任务、功能性校验、下单成功率、多店比价。

详见 `benchmark/ecommerce-agent-benchmark.md`。
