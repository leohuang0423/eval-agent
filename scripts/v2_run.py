#!/usr/bin/env python3
"""跑 v2 27 题(真模型)。用法: python scripts/v2_run.py [variant] [task_id ...]"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ecom_agent.models.llm import LLMModel, claude_cli_completion
from ecom_agent.benchmark.v2.tasks_v2 import TASKS_V2
from ecom_agent.benchmark.v2.runner_v2 import run_v2_task, write_scorecard

MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")


def main():
    args = sys.argv[1:]
    variant = int(args[0]) if args and args[0].isdigit() else 1
    ids = [a for a in args if not a.isdigit()] or [t.id for t in TASKS_V2]
    complete = claude_cli_completion(MODEL)

    def factory(system_prompt, allowed_tools):
        return LLMModel(complete, system_prompt, allowed_tools=allowed_tools)

    print(f"v2 评测 | 模型 {MODEL} | variant={variant} | {len(ids)} 题")
    rows = []
    for tid in ids:
        row = run_v2_task(tid, variant, factory)
        rows.append(row)
        print(f"  {'✅' if row['passed'] else '❌'} {row['task']:3} {row['title']:14} "
              f"success={row['success']:<5} viol={row['safety_viol']} "
              f"{row['t_seconds']}s :: {row['notes'][:70]}")
    npass, viol = write_scorecard(rows, variant)
    print(f"\n小结: {npass}/{len(rows)} 通过, 违规 {viol} → results/v2-scorecard.md")


if __name__ == "__main__":
    main()
