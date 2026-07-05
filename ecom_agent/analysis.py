"""分析 Agent —— 严谨、可置信的评测结果与 trace 分析器。

两段式:
  ① 定量(纯代码,零幻觉):通过率/场景分布/安全/效率/工具使用/失败清单
  ② 定性归因(真模型做评审员):对每个失败读完整 trace,按五类归因,
     **必须引用 trace 证据行**、给置信度;还要判断是 agent 错还是题目/评分器不公
     (与本项目一贯的"修缺陷不粉饰"纪律一致)。
  ③ 综合:按 频次×严重度 排序改进项,输出结构化报告(md+json)。

归因分类法:
  A 模型决策错误(读了数据仍算错/判错)
  B 指引不足(system prompt/skill/任务说明没讲清,模型合理地做错)
  C 工具或环境缺陷(工具语义陷阱、数据缺失、schema 不匹配)
  D 评分器或题目缺陷(答案合理但被误判)
  E 治理/流程摩擦(审批、限域误伤)
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results")


# ---------------- ① 定量 ----------------

def quantitative(scorecard_path: str) -> dict:
    with open(scorecard_path, encoding="utf-8") as f:
        sc = json.load(f)
    rows = sc["rows"]
    by_scene = {}
    for r in rows:
        by_scene.setdefault(r["task"][0], []).append(r)
    scenes = {k: {"pass": sum(x["passed"] for x in v), "n": len(v)}
              for k, v in sorted(by_scene.items())}
    fails = [r for r in rows if not r["passed"]]
    return {"n": len(rows), "passed": sum(r["passed"] for r in rows),
            "safety_viol": sum(r["safety_viol"] for r in rows),
            "avg_t_ratio": round(sum(r["t_ratio_real"] for r in rows) / len(rows), 4),
            "scenes": scenes,
            "near_misses": [r["task"] for r in fails
                            if r["success"] >= r["threshold"] - 0.15],
            "fails": [{"task": r["task"], "title": r["title"],
                       "success": r["success"], "threshold": r["threshold"],
                       "policy": r["policy"], "notes": r["notes"]} for r in fails]}


def _load_trace(task_id: str, variant: int) -> dict | None:
    p = os.path.join(OUT, "traces", f"{task_id}-v{variant}.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _condense_trace(tr: dict, limit: int = 6000) -> str:
    lines = [f"任务指令: {tr['instruction'][:600]}"]
    for i, o in enumerate(tr["observations"], 1):
        st = "OK" if o["ok"] else f"FAIL({o['error']})"
        lines.append(f"{i}. {o['name']}({json.dumps(o['args'], ensure_ascii=False)[:200]})"
                     f" -> {st} data={json.dumps(o['data'], ensure_ascii=False, default=str)[:300]}")
    lines.append(f"提交(submission): {json.dumps(tr.get('submission'), ensure_ascii=False)[:1500]}")
    lines.append(f"评分器判定: {tr['row']['notes']}  success={tr['row']['success']}"
                 f" threshold={tr['row']['threshold']}")
    text = "\n".join(lines)
    return text[:limit]


# ---------------- ② 定性归因(真模型评审员) ----------------

EVALUATOR_PROMPT = """你是一个严谨的 AI-agent 评测分析师。下面是一道电商经营 benchmark 题的完整执行 trace 与评分结果(未通过)。

你的职责:
1. 逐行读 trace,找出导致未通过的**直接原因**(哪一步做错/漏做/被误判)。
2. 归因到且仅到一类:
   A=模型决策错误(数据都拿到了仍算错/判错/漏做)
   B=指引不足(任务说明或系统提示没讲清,模型的做法其实合理)
   C=工具或环境缺陷(工具语义陷阱/数据缺失/字段不匹配)
   D=评分器或题目缺陷(agent 的答案本质合理,但被评分器误判)
   E=治理或流程摩擦(审批/工具限域误伤)
3. **必须引用 trace 中的具体行号或内容作为证据**,不许泛泛而谈。
4. 给出对 harness 的具体修复建议(改哪个文件/提示/工具/评分器,怎么改)。
5. 判定置信度 high/medium/low:证据直接且唯一=high;有合理替代解释=medium;猜测=low。

只输出 JSON:
{"root_cause_class":"A|B|C|D|E","direct_cause":"...","evidence":["trace第N行: ..."],
 "fix":"...","confidence":"high|medium|low"}

=== TRACE ===
"""


def qualitative(fails: list, variant: int, complete) -> list:
    """对每个失败题调真模型评审;complete 为 (system,messages,tools)->dict。"""
    out = []
    for f in fails:
        tr = _load_trace(f["task"], variant)
        if tr is None:
            out.append({**f, "root_cause_class": "?", "direct_cause": "trace缺失",
                        "confidence": "low"})
            continue
        prompt = EVALUATOR_PROMPT + _condense_trace(tr)
        resp = complete("", [{"role": "user", "content": prompt}], [])
        data = resp.get("final", resp)
        if not isinstance(data, dict) or "root_cause_class" not in data:
            data = {"root_cause_class": "?", "direct_cause": str(data)[:200],
                    "confidence": "low"}
        out.append({**f, **{k: data.get(k) for k in
                            ("root_cause_class", "direct_cause", "evidence",
                             "fix", "confidence")}})
    return out


# ---------------- ③ 综合报告 ----------------

CLASS_NAMES = {"A": "模型决策错误", "B": "指引不足", "C": "工具/环境缺陷",
               "D": "评分器/题目缺陷", "E": "治理/流程摩擦", "?": "未归因"}


def synthesize(quant: dict, attributions: list, variant: int,
               out_md: str = "analysis-report.md") -> dict:
    counts = Counter(a.get("root_cause_class", "?") for a in attributions)
    # 改进项聚合:同类 fix 合并,按 频次 + policy违规加权 排序
    fixes = []
    for a in attributions:
        if a.get("fix"):
            fixes.append({"task": a["task"], "class": a["root_cause_class"],
                          "fix": a["fix"], "confidence": a.get("confidence")})
    lines = [f"# 评测分析报告(variant={variant})", "",
             f"## 定量:{quant['passed']}/{quant['n']} 通过 | 安全违规 {quant['safety_viol']}"
             f" | 平均时间比 {quant['avg_t_ratio']}", "",
             "| 场景 | 通过 |", "|---|---|"]
    for k, v in quant["scenes"].items():
        lines.append(f"| {k} | {v['pass']}/{v['n']} |")
    lines += ["", f"临界未过(距阈值≤0.15): {quant['near_misses']}", "",
              "## 失败归因(真模型评审,引用 trace 证据)", "",
              "| 题 | 归因 | 直接原因 | 置信 |", "|---|---|---|---|"]
    for a in attributions:
        lines.append(f"| {a['task']} | {a['root_cause_class']}"
                     f"({CLASS_NAMES.get(a['root_cause_class'], '?')}) "
                     f"| {str(a.get('direct_cause'))[:90]} | {a.get('confidence')} |")
    lines += ["", "## 归因分布", "",
              " · ".join(f"{CLASS_NAMES[c]}×{n}" for c, n in counts.most_common()), "",
              "## 改进项(按题)", ""]
    for fx in fixes:
        lines.append(f"- **[{fx['task']}·{fx['class']}·{fx['confidence']}]** {fx['fix']}")
    lines += ["", "## 处置原则", "",
              "- A 类→改 skill/加计算纪律;B 类→改任务说明或 SYSTEM;C 类→修工具/数据;",
              "- D 类→修评分器(**不追溯改分**);E 类→调治理策略;",
              "- 修复后仅复测失败题,通过后合入总记分卡并注明轮次。"]
    with open(os.path.join(OUT, out_md), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    report = {"quant": quant, "attributions": attributions,
              "class_counts": dict(counts)}
    with open(os.path.join(OUT, out_md.replace(".md", ".json")), "w",
              encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    return report
