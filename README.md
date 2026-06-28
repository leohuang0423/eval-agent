# eval-agent

给电商商家(Shopify / 抖音电商)用的、可自助完成经营任务的 agent —— 框架设计与评测集。

## 目录

- [`docs/research-agent-loops.md`](docs/research-agent-loops.md) —— OpenAI / Anthropic / `earendil-works/pi` 的 agent loop 架构调研与选型结论
- [`docs/architecture.md`](docs/architecture.md) —— 分层架构图(Loop 内核 / 工具层 / 电商治理层)+ 关键调用链
- [`docs/spec.md`](docs/spec.md) —— 精简技术 spec(选型 / 抽象 / loop 规范 / 治理层 / 适配器 / 路线)
- [`benchmark/ecommerce-agent-benchmark.md`](benchmark/ecommerce-agent-benchmark.md) —— 电商经营 agent benchmark(28 题,8 经营域)

## 核心结论

用成熟 SDK(OpenAI Agents SDK / Anthropic Agent SDK)的 loop 原语做内核,借鉴 `pi` 的薄 loop + subagents + goal 编排,**自建电商治理层**(审批 / 多租户 / 凭证 / 审计 / 预算)。评测对齐 τ-bench 的"终态 + 合规 + 可靠性",再叠"≤½时间 / ≤½成本 / ≥同等质量"的效率门槛。
