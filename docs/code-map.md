# 核心源码学习索引

建议顺序：tasks/retrieval → semantic → access/temporal → service → diagnosis/harness → catalog/control_lineage/history → evaluation/MCP。

## __init__.py

|类/方法|行号|中文说明|
|---|---:|---|

## access.py

|类/方法|行号|中文说明|
|---|---:|---|
|AccessDenied|13|权限失败必须停止，不能通过换口径或删过滤静默重试。|
|_encode|16|内部流程/适配函数|
|AccessController|19|本地stdio/CLI信任OS用户；可用签名令牌绑定受限主体，每次工具调用重验。|
|AccessController.__init__|21|内部流程/适配函数|
|AccessController.issue|41|仅可信本地主机管理入口签发；此方法不作为MCP工具暴露。|
|AccessController._verify|49|常量时间验签、有效期、issuer和撤销检查；role只从受信策略映射。|
|AccessController.revoke|70|管理员撤销令牌；不能由模型选择或生成subject。|
|AccessController.role|83|热变更策略后停止旧会话；令牌过期在执行时也会生效。|
|AccessController.metric|92|内部流程/适配函数|
|AccessController.enforce|98|服务器强制行过滤与列维度权限；模型不能移除US限制或查询敏感分组。|
|AccessController.redact_metadata|110|非管理员元数据隐藏敏感字段；数据工具从未暴露原始身份明细。|

## catalog.py

|类/方法|行号|中文说明|
|---|---:|---|
|MetadataCatalog|11|用实体标识定位对象，用 Aspect 存属性，用有向边保存表级血缘。|
|MetadataCatalog.__init__|14|内部流程/适配函数|
|MetadataCatalog.urn|26|标识采用本项目命名空间，不冒充 DataHub 已采集的实体。|
|MetadataCatalog.ingest|30|读取物理 schema 与 dbt depends_on；事务内替换，避免目录处于半更新状态。|
|MetadataCatalog.attach_quality|101|质量是单独 Aspect，记录快照级验证范围，不能冒充逐字段业务质量。|
|MetadataCatalog.context|108|按表读取可验证上下文；目录不存在该表时直接失败。|
|MetadataCatalog.field_lineage|117|追踪已解析的值依赖；聚合行数、过滤条件等未覆盖部分显式保留。|
|MetadataCatalog.lineage|145|广度优先遍历并处理环；返回截断标记，不能把预算耗尽当成没有依赖。|

## cli.py

|类/方法|行号|中文说明|
|---|---:|---|
|main|12|内部流程/适配函数|

## control_lineage.py

|类/方法|行号|中文说明|
|---|---:|---|
|extract_control|5|内部流程/适配函数|

## diagnosis.py

|类/方法|行号|中文说明|
|---|---:|---|
|DiagnosisEngine|6|内部流程/适配函数|
|DiagnosisEngine.__init__|7|内部流程/适配函数|
|DiagnosisEngine.run|10|最多8查询、2维度；失败保留已有证据，不输出未经验证的根因。|

## evaluation.py

|类/方法|行号|中文说明|
|---|---:|---|
|load_cases|7|内部流程/适配函数|
|evaluate_rules|10|固定UTC时钟，逐字段验证指标、窗口、分组、方向和Skill路由。|

## harness.py

|类/方法|行号|中文说明|
|---|---:|---|
|State|9|内部流程/适配函数|
|build_agent|26|有界分支图：任务理解与目录共享，随后选择查询或诊断Skill；失败停止。|

## history.py

|类/方法|行号|中文说明|
|---|---:|---|
|SnapshotHistory|9|内部流程/适配函数|
|SnapshotHistory.__init__|10|内部流程/适配函数|
|SnapshotHistory.capture|20|幂等实体版本；晚到的业务记录从本次观察时刻出现，不回写成过去已知。|
|SnapshotHistory.as_of|57|按当时本地已知的版本查询；时间前无记录返回None，不推测历史状态。|
|SnapshotHistory.capture_warehouse|67|只保留订单状态和业务用户属性，不把姓名/邮箱写入历史库。|

## mcp_server.py

|类/方法|行号|中文说明|
|---|---:|---|
|describe_metric|12|返回版本化口径和合法维度，禁止猜测销售额定义。|
|get_context|17|读取本地实体/字段/Owner/质量/血缘证据。|
|get_lineage|23|遍历本地关系表，字段解析范围与截断会明确返回。|
|plan_query|29|结构化查询→自建编译器→服务端计划，调用方没有自由SQL入口。|
|execute_query|34|只能执行本会话生成并通过校验的计划。|
|compare_windows|39|比较同口径等时长窗口；证据不足时失败，不编造原因。|
|search_business|44|授权后检索业务词/指标/案例，返回可核验引用，不返回原始用户明细。|
|run_diagnosis|51|运行有界异常诊断Skill；不支持的假设和因果证据缺口会明确返回。|
|main|57|内部流程/适配函数|

## retrieval.py

|类/方法|行号|中文说明|
|---|---:|---|
|tokens|8|中文用字符二元组，英文按词；轻量方案无需下载embedding模型。|
|KnowledgeRetriever|14|内部流程/适配函数|
|KnowledgeRetriever.__init__|15|内部流程/适配函数|
|KnowledgeRetriever.metric_candidates|19|优先匹配最长别名，避免'平均订单金额'同时被识别成'订单金额'。|
|KnowledgeRetriever.search|29|先做授权过滤再评分；返回权威来源定位，不把检索文档当执行指令。|
|KnowledgeRetriever.link|64|从指标走到物理事实与列，字段血缘由目录读取，不让LLM猜表名。|

## semantic.py

|类/方法|行号|中文说明|
|---|---:|---|
|file_hash|13|流式校验大文件，避免把整个数仓加载进 Python 内存。|
|Query|21|模型只能提交结构化意图；不接受 SQL、表名、任意表达式或身份参数。|
|Query.bounds|32|内部流程/适配函数|
|SemanticRegistry|39|指标口径唯一来源；支持受限单事实查询，拒绝隐式多事实关联。|
|SemanticRegistry.__init__|41|内部流程/适配函数|
|SemanticRegistry.describe|46|内部流程/适配函数|
|SQLCompiler|52|自行实现聚合规则，SQLGlot 负责 AST；没有调用 MetricFlow 编译器。|
|SQLCompiler.__init__|54|内部流程/适配函数|
|SQLCompiler.expression|57|递归展开比例，检测循环；比例在聚合后计算，防止平均日均值。|
|SQLCompiler.compile|82|表/字段来自受信合同；过滤值构建为 SQL 字面量，不能改变 SQL 结构。|

## service.py

|类/方法|行号|中文说明|
|---|---:|---|
|fingerprint|16|内部流程/适配函数|
|AgentTools|19|本地单用户工具边界；身份在服务侧固定，模型不能提交 principal。|
|AgentTools.__init__|21|内部流程/适配函数|
|AgentTools.publish|31|验证真实数据后复制不可变快照；dbt PASS 只是证据之一，仍独立物理对账。|
|AgentTools.release|96|每次执行重新检查快照、合同和目录，旧计划不能跨版本偷偷复用。|
|AgentTools.context|108|内部流程/适配函数|
|AgentTools.describe|113|口径来自注册表，用户可见维度还要经过权限过滤。|
|AgentTools.lineage|121|仅对授权指标相关事实开放图查询；敏感字段关系对受限主体遮盖。|
|AgentTools._metric_allowed|136|内部流程/适配函数|
|AgentTools.plan|143|工具只接受 Query；生成计划保存在服务内，调用方不能替换 SQL。|
|AgentTools.execute|162|重新编译与服务端计划对比；hash 用于完整性，不是远程认证签名。|
|AgentTools.compare|204|双窗口证据比较：保证口径、分组、过滤、时长一致，只报告变化不归因。|

## tasks.py

|类/方法|行号|中文说明|
|---|---:|---|
|Task|13|任务类型是执行路由，不允许模型提交SQL、自由工具名或自报身份。|
|Task.coherent|23|内部流程/适配函数|
|TaskInterpreter|38|规则模式透明标记；LLM模式只输出任务JSON，再经过相同的运行时校验。|
|TaskInterpreter.__init__|40|内部流程/适配函数|
|TaskInterpreter._windows|48|显式两个日期是闭开端点；中文'至/到'不明确端点时要求澄清。|
|TaskInterpreter.parse|68|内部流程/适配函数|
|TaskInterpreter._rules|85|不猜未覆盖语言；识别失败返回澄清，不能偷偷换指标或丢弃过滤条件。|
|TaskInterpreter._model|138|供真实或MockTransport验收；密钥不进入检索文档、计划、审计或错误报告。|

## temporal.py

|类/方法|行号|中文说明|
|---|---:|---|
|CoverageReceipt|9|可信本地管道可提交绑定数据库hash的水位；模型和MCP调用者无写入入口。|
|CoverageReceipt.aware|19|内部流程/适配函数|
|coverage|26|默认仅记录快照观测时间；有真实管道收据才声明完整性。|
|check_window|39|拒绝未结束日和超过快照观测的日期；历史空区间仍可返回零/空值。|
|DateResolver|53|本地UTC日历解析；没有猜测业务时区或用模型计算今天/昨天。|
|DateResolver.__init__|55|内部流程/适配函数|
|DateResolver.relative|61|内部流程/适配函数|

## worker.py

|类/方法|行号|中文说明|
|---|---:|---|
|main|6|只读、禁外部访问、限定资源；仅通过 JSON 管道返回结果。|
