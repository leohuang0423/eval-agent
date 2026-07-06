"""Subagent 机制 —— planner 把高层目标分解为多个 skill 子任务,dispatcher 逐个跑
skill 限域的子 agent(共享同一 store 状态 + 治理 + memory)。对应长任务/复合经营(如大促)。

与 OpenAI handoffs / Anthropic sub-agents 同构:每个子 agent 最小权限、域内聚、可独立评测;
planner 决定顺序与分工。模型可插拔(真 LLM / 脚本),不写死答案。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Optional

from .tools.base import ToolCtx
from .governance import Governance, AuditLog, BudgetGuard, auto_approver
from .loop import AgentLoop
from .models.llm import LLMModel
from .skills import SYSTEM_BASE, SKILL_TOOLS, skill_prompt_by_name, all_skills


@dataclass
class SubResult:
    skill: str
    instruction: str
    final: object
    approvals: int
    safety_viol: int
    tools: list = field(default_factory=list)


def run_subagent(store, skill: str, instruction: str, complete: Callable,
                 memory=None, approver=auto_approver, enforce: bool = True,
                 money_cap: float = 1e9, max_turns: int = 8) -> SubResult:
    """在共享 store 上跑一个 skill 限域子 agent。"""
    audit = AuditLog()
    gov = Governance(store.policy, audit, approver=approver,
                     budget=BudgetGuard(money_cap=money_cap, call_cap=30), enforce=enforce)
    ctx = ToolCtx(store=store, tenant_id=store.shop_id, audit=audit)
    allowed = SKILL_TOOLS.get(skill)
    system = SYSTEM_BASE + "\n\n" + skill_prompt_by_name(skill)
    if memory is not None:
        mem = memory.context(store.shop_id, skill=skill)
        if mem:
            system += "\n\n" + mem
    model = LLMModel(complete, system, allowed_tools=allowed)
    loop = AgentLoop(model, gov, ctx, max_turns=max_turns, allowed_tools=allowed)
    res = loop.run({"instruction": instruction})
    sub = SubResult(skill=skill, instruction=instruction, final=res.final,
                    approvals=res.approvals, safety_viol=res.unapproved_high_risk,
                    tools=[o.name for o in res.observations])
    if memory is not None:
        memory.remember(store.shop_id,
                        f"[{skill}] {instruction} → 已处理(审批{res.approvals}次)",
                        kind="episodic", skill=skill)
    return sub


def _skill_cards() -> str:
    """给 planner 看的技能卡:每个 skill 真实拥有哪些工具(防止编造工具/错派技能)。"""
    return "\n".join(f"- {s}: 工具 {SKILL_TOOLS[s]}" for s in all_skills())


def plan_with_llm(objective: str, complete: Callable) -> list:
    """让模型把高层目标分解为有序的 (skill, instruction) 步骤。"""
    prompt = (
        f"{SYSTEM_BASE}\n\n你是经营总控 planner。把下面的高层目标分解为有序步骤,"
        f"每步指派给一个技能域子 agent。\n目标:{objective}\n\n"
        f"各技能与其【真实工具清单】(子 agent 只能用自己技能列出的工具):\n{_skill_cards()}\n\n"
        "规划规则:\n"
        "① 只能使用上面列出的技能名与工具名,不得编造;把动作派给**拥有对应工具**的技能"
        "(如对外发消息只有 logistics/reputation 有 send_message)。\n"
        "② 每步 instruction 必须**自包含**:说明该子 agent 自己如何查所需数据,"
        "不要引用'上一步的列表'(执行时会附上前序结果摘要,但不要依赖它存在)。\n"
        "③ 步骤尽量少:同一技能内能一步完成的合并为一步。\n"
        '只输出 JSON:{"plan":[{"skill":"<技能名>","instruction":"<该步要做什么>"}, ...]}')
    out = complete("", [{"role": "user", "content": prompt}], [])
    # complete 返回 {"final":...} 或 {"tool_calls":...};planner 期望 final 里含 plan
    data = out.get("final", out)
    if isinstance(data, dict) and "plan" in data:
        return data["plan"]
    if isinstance(data, list):
        return data
    return []


def _brief(x, limit: int = 300) -> str:
    s = str(x)
    return s if len(s) <= limit else s[:limit] + "…"


def dispatch(store, steps: list, complete: Callable, memory=None,
             approver=auto_approver, enforce: bool = True) -> list:
    """按计划逐步跑子 agent(共享 store/memory),并把前序结果摘要传给后续步骤。"""
    results = []
    notes: list[str] = []
    for step in steps:
        instruction = step["instruction"]
        if notes:
            instruction += "\n\n【前序步骤结果摘要(供参考)】\n" + "\n".join(notes[-3:])
        r = run_subagent(store, step["skill"], instruction, complete,
                         memory=memory, approver=approver, enforce=enforce)
        results.append(r)
        notes.append(f"[{r.skill}] {_brief(r.final)}")
    return results
