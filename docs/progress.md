# 自主 Agent 已完成与等待事项

2026-10-11；此目录是后续开发与提交的主项目。

## 已完成：本地可运行范围

- 独立源码包local_agent和运行环境；不导入MetricFlow/DataHub/WrenAI，另行隔离dbt数据开发环境。
- 官方TheLook七表本地快照：3,358,422行；五个电商dbt模型、11项数据测试实际通过。
- 自建实体/Aspect/关系目录、Schema、占位Owner及明确范围的质量证据；dbt任务和表级血缘。
- 字段值依赖与Join/Where/Group/Having控制依赖分开解析；未知/歧义/复杂SQL保持unresolved。金额追到raw.order_items.sale_price。
- 自建六指标权威合同、结构化IR和AST编译；合法维度、单事实Grain、同事实比例、零分母处理。
- 发布重跑当前物理库的dbt断言，独立键/金额对账，生成不可变快照，数据/合同/目录hash与24小时质量门禁。
- 受控计划、重编译对比、只读子进程、资源/期限/结果预算、审计和结果证据封装。
- 规则自然语言→query/diagnose Task IR→中文Skill路由；别名、业务案例、词法检索和图Schema Linking；非法限定语不被静默丢弃。
- 模拟模型接口验收、明确指标/日期一致性检查；规则/MockTransport/真实数据执行分别记录，没有调用真实模型。
- 有界诊断：用户假设验证、交易量/客单价/比例分解、维度对账、反证、8查询/2维度/60秒预算；证据不足保持INSUFFICIENT_EVIDENCE。
- MCP八个真实工具，增加search_business和run_diagnosis；真实stdio会话验证查询、检索与诊断。
- 签名本地身份、过期/撤销/策略检查、强制US行过滤、指标/维度权限、敏感元数据遮盖、SQL小组抑制；不是企业SSO。
- 快照观测与完整性水位分离、hash绑定管道收据、未结束日/超观察范围拒绝；真实源端水位未提供。
- 观察历史记录订单125,416条、用户100,000条；迟到记录、状态变化与事务回滚由fixture验证，不冒充业务历史SCD2。
- 85项自动测试全部通过；32/32规则用例、15/15检索Hit@3；三次真实数据自然语言规则执行和两次澄清。
- DuckDB副本重复明细故障证明：旧dbt PASS不能发布变化后的库；源库hash保持不变。
- 独立环境实际验收成绩见verification-summary.json与own-agent-tests.xml；演示见demo-result.json。
- 核心类和重要方法中文注释；源码依据和局限见architecture.md，逐方法行号见code-map.md。

## 等待与下一步

|事项|等待什么|完成标准|
|---|---|---|
|真实自然语言模型问数|模型地址/凭据/型号|实际NL→IR评测，记录澄清、拒绝与执行正确性；不把结构化测试当NL准确率|
|更广业务知识与检索|真实业务语料、保留独立评测集|扩充语言覆盖；现有词法/别名/图链接已完成，不宣称向量模型召回|
|成熟漏斗|匿名会话、未来事件和观察窗口策略|可验证session口径、时间边界、分母质量与截断处理|
|因果根因与更大故障集|独立业务事件、源端覆盖及更多故障真值|当前已验证有界假设/反证和代数分解；不能据此确认生产根因|
|业务历史与增量数仓|真实状态/退款流水、删除契约与源端水位|观察历史已完成；仍需业务有效时间、增量物化和迟到重算策略|
|全SQL字段血缘|复杂相关子查询、UNION、排序/limit等语义|当前支持Select/CTE控制依赖，未知范围明确记录|
|企业身份与部署权限|IdP/SSO、密钥管理、真实业务授权主体|当前本地签名和工具RLS/维度权限已完成；仍需远程认证/多租户/持续审计|
|可靠发布与更大规模|可信水位、发布签名、性能目标|量化完整性/新鲜度与增量索引；当前每次全库hash是学习期取舍|

没有等待DataHub GMS启动；没有等待MetricFlow服务接入。三个项目是源码参考而不是运行前提。

用户已选择“先完成本地规则、模拟模型与工程评测”，所以真实LLM验收本轮明确延后，不把Mock成绩当模型准确率。详细范围、接口与证据见seven-areas.md和evaluation-report.json。


## OpenAI 接入更新

接入代码与启动脚本完成，全量回归91项通过。真实模型验收等待本机配置新密钥。模拟协议测试不能作为真实模型准确率证据。见 [接入说明](openai-integration.md)。


## Live OpenAI verification

Real gpt-6.1-sol smoke calls completed. A country-value linking bug was found and fixed; the US September query returns 1420 and independently reconciles to raw tables using UTC dates. Ambiguous revenue, incomplete today, and unequal month windows clarify. See [live verification](openai-live-verification.md). This is smoke verification, not full model accuracy evaluation.


## Core runtime delivery

Six executable skills, comparison/component/drilldown/quality/report workflow, SQLite session checkpoints and query receipts, read-only replay, durable cancellation, worker termination, clarification continuation and chat entry are implemented. 112 engineering tests pass. Real model query succeeded through the new runtime. A full real-data ratio workflow saved 14 queries and three decompositions in runtime-workflow-demo.json. Model accuracy evaluation is deferred as requested. See [guide](runtime-skills-guide.md).


## Simplified local core scope

Directory-based skills now drive model instructions and report assets; transient retries/circuit breakers are live; retrieval resolves dimension enums and metric components; semantic compilation exposes logical plans; NLU protects explicit filters and comparison windows. Real NL query and 14-query diagnosis succeeded. MCP remains a local protocol demo; no enterprise permission expansion or monetary accounting. See [current scope](core-local-scope.md).
