#!/usr/bin/env python3
"""J1 capstone 真模型操盘 —— 700 件连衣裙 · 成本红线 20 · 30 天(留出变体)。

用法:python scripts/capstone_llm.py [variant]
评分只看模拟器终态 + 审计(KPI50/checkpoint30/纪律20,硬门槛:未审批/破成本=0)。
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ecom_agent.benchmark.capstone import run_capstone
from ecom_agent.models.llm import LLMModel, claude_cli_completion

MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


def main():
    variant = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    complete = claude_cli_completion(MODEL)
    models = []

    def factory(system_prompt):
        m = LLMModel(complete, system_prompt)   # 工具限域由 loop 层强制
        models.append(m)
        return m

    print(f"J1 清仓操盘 | 模型 {MODEL} | 留出 variant={variant}")
    t0 = time.time()
    r = run_capstone(factory, variant=variant)
    mins = round((time.time() - t0) / 60, 1)
    cost = round(sum(m.cost_usd() for m in models), 2)

    print(f"\n===== 结果 =====")
    print(f"总分: {r.score}/100  硬门槛失败: {r.hard_fail}")
    print(f"KPI: {r.kpis}")
    print(f"分项: {r.breakdown}")
    print(f"审批 {r.approvals} 次 | 未审批违规 {r.unapproved} | 总轮数 {r.turns_total}")
    print(f"真实耗时 {mins} min | 真实模型花费 ${cost}")
    print("\n每日操盘摘要(最后10天):")
    for a in r.adjust_log[-10:]:
        print(f"  D{a['day']:02d} behind={a['behind']} actions={a['actions']}")

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"capstone-v{variant}.json"), "w", encoding="utf-8") as f:
        json.dump({"model": MODEL, "variant": variant, "score": r.score,
                   "hard_fail": r.hard_fail, "kpis": r.kpis, "breakdown": r.breakdown,
                   "approvals": r.approvals, "unapproved": r.unapproved,
                   "minutes": mins, "cost_usd": cost, "adjust_log": r.adjust_log},
                  f, ensure_ascii=False, indent=2)
    print(f"\n已写 results/capstone-v{variant}.json")


if __name__ == "__main__":
    main()
