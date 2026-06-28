# 它是 agent 还是 chatbot?—— 诚实评估

回应一个尖锐问题:这版"能跑通 10/10"的东西,本质上是真 agent,还是 chatbot?能不能真正做
推理-规划-执行-反思,带来真实业务结果改进?

## 1. 诚实结论

**当前可跑通 benchmark 的版本 = 一个很真的 agent 运行时(harness)+ 一套手写死的脚本化策略。**
按 Anthropic 的二分,它落在 **workflow(预定义代码路径)** 这边,不是 **agent(LLM 动态决策)**。
它也不是 chatbot(没有对话、没有用 LLM 生成内容)。准确说:**带 HITL 的自动化工作流 + 治理/评测脚手架**。

原因:跑通的"大脑"是 `models/scripted.py` 里按题写死的状态机;`models/llm.py` 的真实 LLM
决策需要注入 `complete()`(无 key 未启用)。**"智能"是开发者喂进去的,不是模型推出来的。**

## 2. 逐能力:哪些真、哪些假

| 能力 | 现状 | 证据 / 说明 |
|---|---|---|
| 执行 Execution | ✅ 真 | 工具真改状态、治理真拦截、终态真校验(`results/scorecard.md`) |
| 反思 Reflection(结构) | ✅ 闭环结构已具备 | `scripts/reflection_demo.py`:过度退款被拒→读 error→修正→通过,**单次 run 内闭环** |
| 状态驱动决策(非死记) | ✅ 已验证 | `scripts/generalization.py`:30 个随机留出环境,GOOD 100% vs 背常数 MEMORIZER 70%(数值题归零) |
| 推理 Reasoning | ❌ 缺 | 脚本不推理;LLM 未接(`models/llm.py` 控制流就绪,差一次 `complete()`) |
| 规划 Planning(开放目标分解) | ❌ 缺 | brain 是固定步骤;planner/sub-agent 只在架构里画了 |
| 自主反思(谁来反思) | ⚠️ 半 | loop **支持**反思闭环,但现在由手写 brain 触发,不是模型自主 |
| 业务结果改进 | ⚠️ 未证 | mock 内可测;真实 API/数据/基线未接,½时间½成本是建模常数 |

## 3. 两个能用代码说话的证据

**泛化(不是死记题面)**:`python scripts/generalization.py`
```
题      GOOD   MEMORIZER
EC-23   100%      0%   ← 日报:背常数崩
EC-05   100%      0%   ← 调价:背常数崩
EC-13   100%      0%   ← 退款:背常数崩
平均    100%     70%
```
GOOD 因为"读 get_policy/get_order 再算"在变体上仍成立;背常数的对照组在数值题上归零。
**注意**:这是手写逻辑的泛化,**不等于** LLM 推理——但它把"过拟合脚本"和"状态驱动决策"分开了。

**反思闭环**:`python scripts/reflection_demo.py`
```
1. get_order()            -> OK
2. issue_refund(148.50)   -> FAIL(exceeds cap 99)
3. issue_refund(99.00)    -> OK     # 读到 error 后修正
```

## 4. 要成为"真 agent"还差什么(roadmap)

| 缺口 | 怎么补 | 现状 |
|---|---|---|
| 推理/决策 | 注入真实 LLM(`LLMModel` + system prompt) | 控制流已就绪,差 `complete()` |
| 开放规划 | planner 子 agent 对新目标分解,而非固定步骤 | 架构有,未实现 |
| 自主反思 | error/驳回/校验失败回灌→模型自主再规划(ReAct+Reflexion) | loop 已回灌,缺模型这一端 |
| 泛化评测 | 留出任务变体 + pass^k(已有变体框架) | `generalization.py` 已起步 |
| 真实业务结果 | 接真 API/历史数据,实测时间/成本/质量 | 全 mock |

## 5. 价值判断

不要因为"现在大脑是脚本"就低估这套东西:**agent 产品化最难、最容易翻车的部分——loop 编排、
风险分级工具、治理层(审批/护栏/审计/凭证)、终态校验式评测、泛化与反思的脚手架——都已是真的、可复用的**,
而且正是 `pi` 这类"薄 loop"缺的。**骨架与安全/评测做扎实了,认知内核(LLM)是下一步要插上的那一块。**
换句话说:现在是"装好了驾驶舱和安全带的车,还没装发动机"——但发动机的接口已经焊好(`models/llm.py`)。
