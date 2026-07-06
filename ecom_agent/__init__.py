"""电商经营 agent 框架(可运行参考实现)。

模块:
  env        —— mock 电商环境(Store + 种子数据 + 终态快照)
  tools      —— 带风险分级的工具层
  governance —— 治理层(风险策略 / 审批 / 审计 / 预算)
  loop       —— agent loop(可插拔 model)
  models     —— ScriptedModel(参考解) + LLM 适配占位
  benchmark  —— 题目 + runner + 评分
"""

__version__ = "0.1.0"
