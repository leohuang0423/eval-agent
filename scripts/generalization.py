#!/usr/bin/env python3
"""泛化测试 —— 回答"它是死记了这几道题,还是有基于状态的真决策逻辑?"

做法:对同一套题跑 N 个**随机扰动的留出环境变体**(数值变、结构不变),对比两种策略:
  - GOOD       读当前状态/政策再计算(治理开)
  - MEMORIZER  背 variant=0 的答案常数(治理开)
两者治理层一致,所以差异纯粹来自"任务求解能否泛化"。

预期:GOOD 在变体上仍高通过率;MEMORIZER 在数值题(日报/退款/调价)上崩。
注意:这仍是**手写逻辑**的泛化,不等于 LLM 推理——但它能把"过拟合脚本"和
"状态驱动的决策逻辑"区分开,也标出未来接 LLM 的位置。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ecom_agent.benchmark.tasks import TASKS
from ecom_agent.benchmark.runner import AgentConfig, _run_once
from ecom_agent.benchmark import solvers

N = int(os.environ.get("N_VARIANTS", "30"))
GOOD = AgentConfig("GOOD(读状态再算)", solvers.GOOD, enforce=True)
MEM = AgentConfig("MEMORIZER(背常数)", solvers.MEMORIZER, enforce=True)


def passrate(cfg):
    per = {}
    for t in TASKS:
        ok = 0
        for v in range(1, N + 1):     # variant 0 是基准,留出从 1 开始
            _, res, chk, _ = _run_once(t, cfg, variant=v)
            if chk["success"] >= 0.999 and res.unapproved_high_risk == 0:
                ok += 1
        per[t.id] = ok / N
    return per


def main():
    g, m = passrate(GOOD), passrate(MEM)
    print(f"留出泛化测试:{N} 个随机环境变体,治理层均开启\n")
    print(f"{'题':6} {'GOOD':>8} {'MEMORIZER':>11}  说明")
    for t in TASKS:
        tag = ""
        if t.id in ("EC-23", "EC-13", "EC-05"):
            tag = "← 数值题:背常数会崩"
        print(f"{t.id:6} {g[t.id]*100:7.0f}% {m[t.id]*100:10.0f}%  {tag}")
    ga = sum(g.values()) / len(g)
    ma = sum(m.values()) / len(m)
    print(f"\n平均通过率  GOOD={ga*100:.0f}%   MEMORIZER={ma*100:.0f}%")
    print("\n结论:GOOD 因为'读 get_policy/get_order 再计算'在变体上仍成立;"
          "\nMEMORIZER 在日报/退款/调价上崩 —— 证明 GOOD 的通过不是死记题面,"
          "\n而是状态驱动的决策逻辑(这正是未来交给 LLM 去做推理的那个槽位)。")


if __name__ == "__main__":
    main()
