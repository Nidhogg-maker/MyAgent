# 有限自主工具选择与 Workflow

入口：`python -m local_agent.cli agent "你的问题" --max-steps 6 --max-searches 3`。
使用现有 `OPENAI_API_KEY` 与 `OPENAI_MODEL`；每轮决策会请求模型。
原 ask/chat 模式保持现有行为。首版自主模式仅支持指标工具，不支持画像。

当前模型从12个进程内工具中选择，包括 search_business、resolve_semantics、query_relations、
describe_metric、get_context、run_query、run_comparison、run_diagnosis、run_multi_fact
以及 propose_plans/select_plan/run_plan_step；工具返回后再决定下一动作、clarify 或 finish。
第一轮决策前已经由 QueryContextBroker 自动准备候选检索和权威语义上下文；模型仍可按需补充检索。
工具采用结构化决策分发，不是原生 function_call 协议。
参数使用 Pydantic 验证，执行复用现有 Skill、受控编译器和只读 Worker。

最多 6 轮决策、3 次检索（可调上限为 12/6），默认沿用 16 次查询与 120 秒
共享预算。比较和诊断内部查询扣同一 SQLite 账本。每轮重验身份、策略、
数据版本与资源期限；重复参数不会二次执行。非法工具/参数允许下一轮修正；
执行错误、权限拒绝、取消、预算耗尽立即停止，保留已有证据。

会话持久化决策、观察结果、模型 usage 和查询回执。可通过 Python
`AgentLoop.show/cancel/followup` 或 CLI 的 session/cancel/reply 查看、取消或继续
澄清。CLI 根据会话绑定自动识别自主模式；自主会话首版不支持中断恢复，
resume 会明确拒绝，需开启新 turn。

finish 必须引用成功观察 ID；返回完整证据，`summary_verified:false` 标明模型
摘要未经过业务语义证明。证据引用检查不等于数字、筛选语义或因果正确性评测。
执行前校验明确指标候选、筛选值和日期窗口，并拒绝用电商口径替代支付口径。
这些有限规则不覆盖所有自然语言表达，需在真实难例评测后再扩大使用范围。

专项测试使用脚本化决策和 MockTransport，查询测试读取真实本地发布副本；
不发起真实模型请求，不代表模型选工具准确率。


## Multi Plan与多事实扩展

在上述循环上加入候选计划选择与逐步执行，以及run_multi_fact工具。运行方式、合同更新和当前边界见 [Multi Plan与Join说明](multi-plan-and-join-guide.md)。外层规划保留本说明的有界预算、摘要未验证和首版不能中断恢复等限制。
