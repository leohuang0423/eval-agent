#!/usr/bin/env python3
"""分析 agent 入口:读 v2 记分卡 + traces → 定量统计 + 真模型归因 → 改进报告。

用法: python scripts/analyze.py [variant]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ecom_agent.analysis import quantitative, qualitative, synthesize, OUT
from ecom_agent.models.llm import claude_cli_completion

MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")


def main():
    variant = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    quant = quantitative(os.path.join(OUT, "v2-scorecard.json"))
    print(f"定量: {quant['passed']}/{quant['n']} 通过 | 违规 {quant['safety_viol']} "
          f"| 场景 {quant['scenes']}")
    if not quant["fails"]:
        print("无失败题,无需归因。")
        synthesize(quant, [], variant)
        return
    print(f"失败 {len(quant['fails'])} 题,逐题真模型归因(引用 trace 证据)…")
    complete = claude_cli_completion(MODEL)
    attributions = qualitative(quant["fails"], variant, complete)
    report = synthesize(quant, attributions, variant)
    print("\n归因分布:", report["class_counts"])
    for a in attributions:
        print(f"  [{a['task']}·{a.get('root_cause_class')}·{a.get('confidence')}] "
              f"{str(a.get('direct_cause'))[:100]}")
    print(f"\n报告 → results/analysis-report.md")


if __name__ == "__main__":
    main()
