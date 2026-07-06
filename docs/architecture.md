# 电商经营 Agent —— 架构设计

> 结论先行(见 `docs/research-agent-loops.md`):**用成熟 SDK 的 loop 原语做内核(OpenAI Agents SDK / Anthropic Agent SDK),借鉴 `earendil-works/pi` 的薄 loop + subagents + goal 编排思路,外面自建一层电商治理层(审批/多租户/审计)。** pi 本身"无内置权限/审批/多租户/审计",不直接作为生产底座。

---

## 1. 分层架构

```mermaid
flowchart TB
    subgraph U["商家 / 运营(多店铺)"]
      M1["对话 / 指令"]
      M2["审批台 Approval Inbox"]
      M3["经营看板 Dashboard"]
    end

    subgraph GOV["② 电商治理层 (自建 · pi 缺失的部分)"]
      direction TB
      AUTH["租户 & 凭证保险库\nTenant / Secrets Vault"]
      RISK["风险分级 & 策略引擎\nRisk Policy Engine 🟢🟡🔴"]
      APPR["审批工作流\nHITL Approval (中断/恢复)"]
      AUDIT["审计 & 可观测\nAudit Log · Tracing"]
      BUDGET["预算/配额护栏\nCost & Rate Guardrails"]
    end

    subgraph CORE["① Loop 内核 (SDK 原语)"]
      direction TB
      LOOP["Agent Loop\ncall model→run tools→feed back→repeat"]
      ORCH["编排 / Sub-agents\nplanner · executor · per-domain"]
      MEM["状态 & 记忆\nSession · 长任务 Goal State"]
      GUARD["输入/输出 Guardrails"]
    end

    subgraph TOOLS["③ 工具层 (带风险标注的 capability)"]
      direction LR
      T_RO["🟢 只读\n查单/查价/报表"]
      T_RW["🟡 可逆写\n改草稿/建计划"]
      T_HI["🔴 不可逆/碰钱\n退款/上架/投放/发货"]
    end

    subgraph EXT["④ 外部平台 (经适配器接入)"]
      direction LR
      SHOP["Shopify Admin API"]
      DOUDIAN["抖店开放平台"]
      QIANCHUAN["巨量千川 / 星图"]
      LOGI["物流 / 支付 / 财务"]
    end

    DATA[("⑤ 数据底座\n业务状态 · 向量记忆 · fixtures")]

    M1 --> GOV --> CORE
    CORE -->|"调用工具前过策略"| RISK
    RISK -->|"🔴/🟡命中"| APPR --> M2
    M2 -->|"批准→resume"| LOOP
    CORE --> TOOLS --> EXT
    CORE <--> MEM --> DATA
    LOOP -.-> AUDIT
    TOOLS -.-> AUDIT
    APPR -.-> AUDIT
    AUDIT --> M3
    BUDGET -.->|"超额熔断"| LOOP
    AUTH -.->|"按店铺注入凭证"| TOOLS
```

---

## 2. 关键调用链(以"EC-13 退款裁决"为例)

```mermaid
sequenceDiagram
    participant Mer as 商家
    participant Gov as 治理层
    participant Agent as Loop内核
    participant Tool as 工具层
    participant Plat as 退款API

    Mer->>Gov: "处理这批退款申请"
    Gov->>Gov: 鉴权 + 注入店铺凭证 + 预算检查
    Gov->>Agent: 启动 run(含退款政策 system prompt)
    loop Agent Loop
      Agent->>Tool: 🟢 查订单/物流(直接执行)
      Tool-->>Agent: 事实数据
      Agent->>Agent: 依政策裁决(可解释)
      Agent->>Gov: 申请 🔴 refund(金额/订单)
      Gov->>Gov: 风险引擎判定→需审批
      Gov-->>Mer: 推送审批卡(含依据/金额)
      Mer-->>Gov: 批准 / 改额 / 驳回
      Gov->>Tool: 批准→执行退款
      Tool->>Plat: refund(dry-run→real)
      Plat-->>Tool: 终态
    end
    Agent-->>Gov: 结果 + 终态
    Gov-->>Mer: 回执 + 全程审计链路
```

---

## 3. 设计要点

| 层 | 职责 | 实现取舍 |
|---|---|---|
| ① Loop 内核 | 模型循环、工具调用、子agent、记忆 | 直接用 SDK 的 Runner/handoffs/sessions;长任务用 goal-state(借鉴 pi-goal) |
| ② 治理层(**自建,最关键**) | 多租户、凭证、风险分级、审批中断恢复、审计、预算护栏 | pi 完全没有;SDK 的 HITL/guardrails/tracing 提供一半,另一半(多租户/审计/凭证保险库)自建 |
| ③ 工具层 | 把平台 API 封装成**带风险等级**的 capability | 每个工具声明 `risk: 🟢/🟡/🔴` + `reversible` + `cost`;🔴 强制经审批 |
| ④ 适配器 | Shopify / 抖店 / 巨量 / 物流 统一接口 | 适配器模式;鉴权与限流隔离在治理层 |
| ⑤ 数据底座 | 业务状态、长任务状态、向量记忆、benchmark fixtures | 状态可中断恢复(对应 EC-28 长任务) |

**安全默认值**:工具默认 deny,显式声明风险等级才放行;🔴 永远 HITL;agent 永不持有长期凭证(凭证由治理层按店铺即时注入);所有写动作先 dry-run 入审计再执行。

详见 `docs/spec.md`。
