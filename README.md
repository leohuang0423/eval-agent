# eval-agent

给电商商家(Shopify / 抖音电商)用的、可自助完成经营任务的 agent —— **可运行框架 + 评测集 + 迭代验证**。

目标:用不到人工 **½ 的时间与成本**,达成同等或更好的经营结果,且涉钱/库存/对外的高风险动作必须人工审批。

## 快速开始

```bash
python scripts/report.py                  # 跑 benchmark(脚本参考解),生成 results/scorecard.{json,md}
python scripts/generalization.py          # 留出泛化测试(状态驱动 vs 背常数)
python scripts/reflection_demo.py         # 反思闭环 demo(执行→失败→反思→修正)
python scripts/llm_run.py 3 EC-13 EC-05 EC-23   # 真实 Claude Sonnet 4.6 在环(需 claude CLI)
python -m unittest tests.test_smoke -v    # 回归测试(10 项)
```

## 真实模型在环(Claude Sonnet 4.6)

把模型节点换成真实 Sonnet 4.6,在留出数据上 **3/3 通过、零安全违规**;真模型自己推理→规划→执行,
治理层在其上拦审批。过程暴露并修复了 benchmark 的 3 处缺陷(工具未限域 / 任务欠指令 / 判断题死抠公式 /
裸文本解析脆)。详见 [`docs/real-model-eval.md`](docs/real-model-eval.md) 与 [`results/real-model-run.txt`](results/real-model-run.txt)。

## 当前结果(`results/scorecard.md`)

| 配置 | 通过 | 平均分 | 时间比 | 成本比 | 安全违规 |
|---|---|---|---|---|---|
| v1 朴素·无治理 | 1/10 | 35.0 | 0.011 | 0.026 | 5 |
| v1.5 好brain·无治理(消融) | 4/10 | 88.0 | 0.017 | 0.040 | 7 |
| **v2 改进·有治理** | **10/10** | **100.0** | 0.121 | 0.092 | **0** |

消融实验证明:**治理层**(审批/护栏/审计)是把"高质量但不安全"的 agent 变成"可上线"的决定性一环——这正是 `pi` 缺失、需自建的部分。

## 代码结构(`ecom_agent/`)

```
env/         mock 电商环境(Store + 种子数据 + 终态快照)
tools/       带风险分级(🟢🟡🔴)的工具层 + 纵深防御硬校验
governance/  治理层:风险路由 / HITL 审批 / 预算护栏 / 审计 / 凭证注入
loop.py      薄 agent loop(可插拔 model)
models/      ScriptedModel(参考解) + LLMModel(接 OpenAI/Anthropic SDK 占位)
benchmark/   题目 + 终态校验 + 5维评分 runner(含效率门槛、pass^k)
```

## 文档

- [`docs/real-model-eval.md`](docs/real-model-eval.md) —— **真实 Sonnet 4.6 在环测试**:3/3 通过 + 暴露并修复的 benchmark 缺陷
- [`docs/agent-vs-workflow.md`](docs/agent-vs-workflow.md) —— **诚实评估**:它是 agent 还是 workflow?推理/规划/反思缺什么 + roadmap
- [`docs/agent-design.md`](docs/agent-design.md) —— **最终设计**:环境 / 工具 / Loop / 权限 / System Prompt / Skills
- [`docs/iteration-log.md`](docs/iteration-log.md) —— 迭代日志:v1→v1.5→v2 的效果变化与设计改进
- [`docs/architecture.md`](docs/architecture.md) —— 分层架构图 + 调用链时序图
- [`docs/spec.md`](docs/spec.md) —— 技术 spec
- [`docs/research-agent-loops.md`](docs/research-agent-loops.md) —— OpenAI / Anthropic / `pi` 的 loop 调研与选型
- [`benchmark/ecommerce-agent-benchmark.md`](benchmark/ecommerce-agent-benchmark.md) —— 电商经营 benchmark(28 题)

## 核心结论

用成熟 SDK(OpenAI/Anthropic)的 loop 原语做内核,借鉴 `pi` 的薄 loop + subagents + goal 编排,**自建电商治理层**;能力(brain/system prompt/skills)与安全(治理层)正交,二者齐备才既快又对又安全。评测对齐 τ-bench 的"终态+合规+可靠性",叠加"≤½时间 / ≤½成本 / ≥同等质量"效率门槛。
