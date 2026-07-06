# 项目成功标准(SMART)与进展审计

**项目目标(回顾)**:做一个给电商商家(Shopify / 抖音电商)用的、能**自助完成经营任务**的
agent 产品 —— 用不到人工 ½ 的时间与成本达成同等或更好结果;高风险动作必须人工审批;
是真 agent(推理-规划-执行-反思),不是 chatbot,更不能靠写死 mock 答案自欺欺人。

## 1. SMART 成功标准

每条:Specific(具体)+ Measurable(可测)+ Achievable(本环境可达)+ Relevant(对商家有价值)+ Time-bound(里程碑)。

| # | 标准(Specific) | 度量(Measurable) | 里程碑 | 状态 |
|---|---|---|---|---|
| **S1 能力** | 真实 LLM(非脚本)在**留出随机环境**上自主完成全部已实现 benchmark 题 | ≥10 题 × ≥3 留出变体,通过率 100%,由终态校验判定 | M1(本session) | ✅ **30/30**(v1/2/4)+ v5 复测 |
| **S2 安全** | 高风险动作 0 次未审批执行;审批支持**异步挂起→批准/改参/驳回→恢复** | `unapproved_high_risk`=0;pause/resume/改参/驳回有自动化测试 | M1 | ✅ 30/30 中 0 违规;15 项测试含 pause/resume/改参/驳回 |
| **S3 非死记** | 通过不靠背题:数值/环境扰动后仍成立;有"背常数"对照组 | 留出泛化:状态驱动 100% vs 背常数 70%(数值题归零);真模型全部跑在留出变体上 | M1 | ✅ `scripts/generalization.py` + 真模型矩阵 |
| **S4 效率** | **实测**(非折算)时间 ≤ ½ 人工基线;真实模型花费可核算 | 真模型每题 wall-clock 秒 / 人工基线分钟 ≤ 0.5;$ 成本从 API 计费实取 | M1 | ✅ 记分卡含实测秒 + 真实 $(见 `results/real-model-scorecard.md`) |
| **S5 产品形态** | 商家可用的入口:一句话指令→规划→审批→执行→终态摘要;记忆跨运行持久;多租户隔离;审计落盘 | `agent_cli.py` 端到端跑通;租户隔离测试;`results/audit/*.jsonl` | M1 | ✅ CLI + 隔离测试 + 审计落盘 |
| **S6 agent 能力面** | loop / tools / skills / system prompt / subagent / memory 全部落地且各有实证 | 每项有代码 + 测试或真模型 demo | M1 | ✅(见 §3 映射表) |
| **S7 真实平台** | 接真实 Shopify Admin / 抖店 / 巨量 API,在沙箱店铺上复跑评测 | 真实 API 上任务成功率、真实工单时长对比 | **M2(被凭证阻塞)** | ⬜ 需商家侧沙箱凭证 + 出网授权 |
| **S8 题库规模** | benchmark 从 10 题扩到 28 题全量 + 大促长任务(EC-28) | 28/28 有 setup/checker;真模型通过率报告 | M2 | ⬜ 10/28(覆盖全部风险等级与 8 域中的 7 域) |

**通过定义**:M1 = S1–S6 全绿(本 session 内);M2 = S7–S8(需外部资源,已给 roadmap)。

## 2. 代码审计结论(本轮)

**重写判断:不重写。** 架构分层(env / tools / governance / loop / models / skills / memory / planner / benchmark)
清晰、可测、真模型已验证;重写只会损失已验证性。但审计发现 6 个真实缺口(多为 spec 承诺未兑现),本轮全部闭合:

| 缺口 | 修复 |
|---|---|
| G1 审批中断/恢复未实现(approver 是同步秒批桩) | `ApprovalInbox` + `loop.resume(checkpoint, decision)`:挂起→序列化断点→批准/改参/驳回→恢复 |
| G2 审批改参/驳回是死代码 | 测试锁定:改额 99→80 后恢复执行;驳回后模型收到"被驳回"自行收尾 |
| G3 效率证据是折算常数 | 真模型记分卡改用**实测 wall-clock + API 真实 $**(`total_cost_usd`) |
| G4 没有商家产品入口 | `scripts/agent_cli.py`:指令→planner→子agent→交互审批卡(y/n/改额)→终态摘要 |
| G5 审计不落盘 | `AuditLog.to_jsonl`,每次评测/CLI 运行写 `results/audit/*.jsonl` |
| G6 多租户无验证 | 隔离测试:状态/记忆/审计跨租户互不串味 |

## 3. agent 能力面 → 代码/实证映射(S6)

| 能力 | 代码 | 实证 |
|---|---|---|
| agent_loop(含暂停/恢复) | `ecom_agent/loop.py` | 15 项测试;真模型 30/30 |
| tools(风险分级+纵深防御) | `ecom_agent/tools/` | 红线 guard 测试;真模型 0 违规 |
| 权限/治理 | `ecom_agent/governance.py` | 消融实验(无治理 7 违规 → 有治理 0) |
| skills(域指引+最小工具集) | `ecom_agent/skills.py` | 真模型 8/10→30/30 的主因 |
| system prompt | `skills.SYSTEM_BASE` + 域纪律 | 全部真模型运行使用 |
| subagent/planner | `ecom_agent/planner.py` | `composite_demo`:大促分解 4 步、5 审批 0 违规 |
| memory | `ecom_agent/memory.py` | `memory_demo`:同题换记忆,定价 52.5→50.78/52.9 |
| 评测(不自欺) | `benchmark/` + `scripts/llm_run.py` | 留出变体 + 终态校验 + memorizer 对照 + 真实效率 |

## 4. 防自欺声明(方法论)

1. 评分只看**终态/DB 状态**与政策合规,不信模型自述。
2. 真模型只在**留出随机变体**上评测;种子 variant=0 仅供脚本 CI。
3. 有**背常数对照组**证伪"死记题面"。
4. 效率/成本用**实测值**(wall-clock、API 计费),折算常数已弃用于真模型记分卡。
5. 脚本参考解(ScriptedModel)明确降级为 CI 回归,不进任何"agent 能力"结论。
6. 未达成的(S7/S8)在文档中显式标注为未达成,不含糊。
