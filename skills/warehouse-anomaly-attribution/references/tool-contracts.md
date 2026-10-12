# 本地工具与MCP调用边界

本地核心直接调用 AgentTools；stdio MCP 提供同类输入输出的协议适配。两者都不接受模型自由SQL或凭据。本项目仅保留本地调用逻辑，不建设远程认证/集群。

| 能力 | 本地工具 / MCP名称 | 输入与结果 |
|---|---|---|
| 定义解析 | describe / describe_metric | metric_id → 口径、事实grain、允许维度 |
| 元数据 | context / get_context | metric_id → schema、Owner、质量和血缘 |
| 查询规划 | plan / plan_query | Query → 服务端plan_id和完整性hash |
| 执行 | execute / execute_query | plan_id + hash → rows、定义、release、质量和限制 |
| 血缘 | lineage / get_lineage | 合法事实表和可选列 → 有界依赖与未解析项 |
| 比较 | comparison Skill / compare_windows | 明确可比窗口 → 双窗口证据 |
| 诊断 | anomaly-analysis Skill / run_diagnosis | Task → 有界观察与未解决项；协议工具不等于持久会话入口 |

瞬时网络错误、明确临时限流/服务过载、查询worker异常退出可有界重试；每次实际查询尝试都消耗额度。权限拒绝、非法维度、未知值、错误grain、口径冲突、分母为零和查询超时不自动重试。连续瞬时失败触发熔断；冷却后仅一个半开探测。取消和总截止时间能中止等待。

事件中保存工具名、尝试序号、耗时、状态和release，禁止保存API密钥。查询成功回执可在同会话、同版本恢复时复用。
