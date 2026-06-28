"""真实 LLM 适配占位 —— 展示如何把 loop 接到 OpenAI / Anthropic SDK。

生产中:把 registry 的工具 specs 转成各家的 tool schema,带上 system prompt(见
docs/agent-design.md),用 SDK 的原生 tool-calling 循环驱动。此处仅给接口轮廓,
默认未启用(无 API key 时不影响 benchmark 用 ScriptedModel 跑通)。
"""
from __future__ import annotations

from typing import Optional

from .base import ModelClient, Action, Final, ToolCall, Observation


class LLMModel(ModelClient):
    def __init__(self, provider: str = "anthropic", model: str = "claude-opus-4-8",
                 system_prompt: str = "", tool_specs: Optional[list] = None):
        self.provider = provider
        self.model = model
        self.system_prompt = system_prompt
        self.tool_specs = tool_specs or []
        self._tokens = 0

    def step(self, task_input: dict, observations: list[Observation]) -> Action:
        # 伪代码(生产实现):
        #   messages = build_messages(self.system_prompt, task_input, observations)
        #   resp = client.messages.create(model=self.model, tools=self.tool_specs, ...)
        #   self._tokens += resp.usage.total_tokens
        #   return parse_tool_calls(resp) or Final(resp.text)
        raise NotImplementedError(
            "LLMModel 需配置 API key 与 SDK;benchmark 默认用 ScriptedModel。"
            "接入步骤见 docs/agent-design.md 的 §system prompt / §tools。")

    def token_cost(self) -> int:
        return self._tokens
