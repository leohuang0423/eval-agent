#!/usr/bin/env python3
"""跑全部配置,输出 results/scorecard.json + results/scorecard.md。"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ecom_agent.benchmark.runner import (
    run_suite, CONFIG_V1, CONFIG_ABLATE, CONFIG_V2)

CONFIGS = [CONFIG_V1, CONFIG_ABLATE, CONFIG_V2]
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


def main():
    os.makedirs(OUT, exist_ok=True)
    results = {c.name: run_suite(c) for c in CONFIGS}

    with open(os.path.join(OUT, "scorecard.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    lines = ["# Benchmark 记分卡(自动生成)", ""]
    lines.append("> `python scripts/report.py` 复现。评分:Success40/Policy20/Efficiency20/Safety10/Reliability10。")
    lines.append("")
    # 汇总
    lines.append("## 配置汇总")
    lines.append("")
    lines.append("| 配置 | 通过 | 平均分 | 时间比(均) | 成本比(均) | 安全违规 |")
    lines.append("|---|---|---|---|---|---|")
    for c in CONFIGS:
        s = results[c.name]["summary"]
        lines.append(f"| {c.name} | {s['passed']}/{s['n']} | {s['avg_total']} | "
                     f"{s['avg_t_ratio']} | {s['avg_c_ratio']} | {s['safety_violations']} |")
    lines.append("")
    # 每配置明细
    for c in CONFIGS:
        lines.append(f"## {c.name} 明细")
        lines.append("")
        lines.append("| 题 | 风险 | 总分 | S | P | E | Safe | Rel | 通过 | 时间比 | 成本比 | 备注 |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r in results[c.name]["rows"]:
            sc = r["scores"]
            ed = r["efficiency_detail"]
            lines.append(
                f"| {r['task']} | {r['risk'][:3]} | {sc['total']} | {sc['success']} | "
                f"{sc['policy']} | {sc['efficiency']} | {sc['safety']} | {sc['reliability']} | "
                f"{'✅' if r['passed'] else '❌'} | {ed['t_ratio']} | {ed['c_ratio']} | {r['notes']} |")
        lines.append("")

    with open(os.path.join(OUT, "scorecard.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # 控制台速览
    for c in CONFIGS:
        s = results[c.name]["summary"]
        print(f"{c.name:22} pass {s['passed']}/{s['n']}  avg {s['avg_total']:>5}  "
              f"t={s['avg_t_ratio']} c={s['avg_c_ratio']}  safety_viol={s['safety_violations']}")


if __name__ == "__main__":
    main()
