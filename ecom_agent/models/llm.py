"""真实 LLM 适配 —— 把 loop 接到 OpenAI / Anthropic 的 tool-calling。

与 ScriptedModel 同接口,但决策交给 LLM:
  step() 把 system_prompt + 任务 + 历史观察(含工具 error)拼成 messages,
  调用注入的 complete(system, messages, tools) → 返回 tool_calls 或 final。
  loop 把工具结果(含失败/审批驳回)回灌 → 下一次 step 模型据此**再规划/反思**。

控制流是真的、可运行的;唯一需要外部依赖的是 complete() 里的一次 LLM 调用。
无 key 时可注入 FakeCompletion 跑通结构(见 tests / 文档)。
"""
from __future__ import annotations

from typing import Callable, Optional

from .base import ModelClient, Action, Final, ToolCall, Observation
from ..tools.base import registry


# complete: (system_prompt, messages, tool_specs) -> dict
#   {"tool_calls": [{"name":..,"args":..,"reason":..}, ...]}  或  {"final": <output>}
Completion = Callable[[str, list, list], dict]


def build_messages(task_input: dict, observations: list[Observation]) -> list[dict]:
    """把任务与历史观察(含工具成败/审批结果)拼成对话上下文。"""
    msgs = [{"role": "user", "content": f"任务输入:{task_input}"}]
    for o in observations:
        if o.executed and o.ok:
            msgs.append({"role": "tool", "name": o.name,
                         "content": f"成功:{o.data}"})
        elif o.executed and not o.ok:
            # 失败回灌 —— 触发模型反思/再规划
            msgs.append({"role": "tool", "name": o.name,
                         "content": f"失败:{o.error}(请据此修正)"})
        else:
            msgs.append({"role": "tool", "name": o.name,
                         "content": f"被治理层拦截/驳回(approved={o.approved})"})
    return msgs


class LLMModel(ModelClient):
    def __init__(self, complete: Completion, system_prompt: str,
                 model: str = "claude-opus-4-8", allowed_tools=None):
        self.complete = complete
        self.system_prompt = system_prompt
        self.model = model
        specs = registry.specs()
        if allowed_tools:   # skill 最小权限:只把允许的工具暴露给模型
            allow = set(allowed_tools)
            specs = [s for s in specs if s["name"] in allow]
        self.tool_specs = specs
        self._tokens = 0

    def step(self, task_input: dict, observations: list[Observation]) -> Action:
        messages = build_messages(task_input, observations)
        out = self.complete(self.system_prompt, messages, self.tool_specs)
        self._tokens += int(out.get("_tokens", 600))
        if "final" in out:
            return Final(out["final"])
        return [ToolCall(c["name"], c.get("args", {}), c.get("reason", ""))
                for c in out.get("tool_calls", [])]

    def token_cost(self) -> int:
        return self._tokens


# ---- 生产端 complete 工厂(轮廓;真实调用需 API key)----

def anthropic_completion(client, model: str = "claude-opus-4-8") -> Completion:
    def _complete(system, messages, tools):
        # resp = client.messages.create(model=model, system=system,
        #     messages=to_anthropic(messages), tools=to_anthropic_tools(tools))
        # return parse_anthropic(resp)  # -> {"tool_calls":[...]} 或 {"final":...}
        raise NotImplementedError("接入 anthropic 客户端后启用(见 docs/agent-design.md §system prompt)")
    return _complete


def openai_completion(client, model: str = "gpt-4o") -> Completion:
    def _complete(system, messages, tools):
        # resp = client.responses.create(model=model, instructions=system,
        #     input=to_openai(messages), tools=to_openai_tools(tools))
        # return parse_openai(resp)
        raise NotImplementedError("接入 openai 客户端后启用")
    return _complete


def claude_cli_completion(model: str = "claude-sonnet-4-6", timeout: int = 150) -> Completion:
    """通过本地 `claude -p` (Claude Code headless) 调用真实模型作为决策内核。

    这是该环境下被支持的"调用自己模型"的方式:不抽取/复用任何 token,走官方 CLI。
    每步把 system prompt + 工具清单 + 历史观察拼成 prompt,要求模型只输出一个决策 JSON。
    """
    import json
    import re
    import subprocess

    def _complete(system, messages, tools):
        tool_lines = "\n".join(
            f"- {t['name']} [{t['risk']}]: {t['description']}" for t in tools)
        history = "\n".join(
            f"[{m['role']}{(':' + m['name']) if m.get('name') else ''}] {m['content']}"
            for m in messages) or "(还没有工具结果)"
        prompt = f"""{system}

你现在是电商经营 agent 的**决策内核**。可用工具(名称[风险]:说明,其中 args 是参数):
{tool_lines}

到目前为止的任务与工具结果:
{history}

只输出**一个 JSON 对象**,不要任何解释或代码块标记:
- 调用工具:{{"tool_calls":[{{"name":"<工具名>","args":{{...}}}}]}}
- 任务完成:{{"final": <结果对象>}}
规则:① 先用只读工具(get_*/sales_report/check_*)核实订单/商品/库存与政策(get_policy),按政策算正确参数;
② 高风险(irreversible)动作照常发起,治理层会拦截走人工审批,你不要因此跳过;
③ 不破红线(退款≤上限、价格≥成本×(1+最低毛利)、补偿≤额度、活动≤预算);④ 一步只给必要的工具调用。"""
        proc = subprocess.run(
            ["claude", "-p", prompt, "--model", model, "--output-format", "json"],
            capture_output=True, text=True, timeout=timeout)
        try:
            envelope = json.loads(proc.stdout)
            text = envelope.get("result", "")
            usage = envelope.get("usage", {})
            tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        except json.JSONDecodeError:
            text, tokens = proc.stdout, 600
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return {"final": {"raw": text[:200]}, "_tokens": tokens}
        try:
            decision = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {"final": {"raw": text[:200]}, "_tokens": tokens}
        decision["_tokens"] = tokens
        return decision

    return _complete
