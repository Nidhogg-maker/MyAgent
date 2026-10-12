# 当前源码地图

本文件由scripts/generate-code-map.py生成；行号来自当前AST。职责和调用关系见 [架构导航](../ARCHITECTURE.md)。

规范名称：service.QueryService、agent_tools.AgentToolRouter。旧AgentTools为兼容别名，不是额外服务。

## 入口与意图

### cli.py

提交项目的独立入口：只使用自己的核心模块和通用开源库。

|对象/方法|源码位置|职责|
|---|---|---|
|main|[第12行](../src/local_agent/cli.py#L12)|实现细节见源码与所属类说明|

### chat.py

统一终端入口：显示简洁结果，完整状态和证据保存在会话库。

|对象/方法|源码位置|职责|
|---|---|---|
|display|[第4行](../src/local_agent/chat.py#L4)|实现细节见源码与所属类说明|
|chat_loop|[第28行](../src/local_agent/chat.py#L28)|实现细节见源码与所属类说明|

### tasks.py

用户问题→受限任务IR→Skill路由；本地规则只处理明确的有限语言子集。

|对象/方法|源码位置|职责|
|---|---|---|
|Task|[第13行](../src/local_agent/tasks.py#L13)|任务类型是执行路由，不允许模型提交SQL、自由工具名或自报身份。|
|Task.coherent|[第23行](../src/local_agent/tasks.py#L23)|实现细节见源码与所属类说明|
|TaskInterpreter|[第38行](../src/local_agent/tasks.py#L38)|规则模式透明标记；LLM模式只输出任务JSON，再经过相同的运行时校验。|
|TaskInterpreter.parse|[第79行](../src/local_agent/tasks.py#L79)|实现细节见源码与所属类说明|

### agent_loop.py

有界自主决策循环：每轮选择工具，观察结果，再作下一轮决策。

|对象/方法|源码位置|职责|
|---|---|---|
|Decision|[第16行](../src/local_agent/agent_loop.py#L16)|实现细节见源码与所属类说明|
|Decision.coherent|[第25行](../src/local_agent/agent_loop.py#L25)|实现细节见源码与所属类说明|
|ModelDecision|[第34行](../src/local_agent/agent_loop.py#L34)|Responses 严格结构化决策；arguments_json 随后按工具 schema 校验。|
|AgentLoop|[第97行](../src/local_agent/agent_loop.py#L97)|共享 SQLite 会话、版本绑定和 RuntimeTools 查询账本；首版不支持中断恢复。|
|AgentLoop.resume|[第103行](../src/local_agent/agent_loop.py#L103)|实现细节见源码与所属类说明|
|AgentLoop.show|[第106行](../src/local_agent/agent_loop.py#L106)|实现细节见源码与所属类说明|
|AgentLoop.followup|[第113行](../src/local_agent/agent_loop.py#L113)|实现细节见源码与所属类说明|
|AgentLoop.start|[第130行](../src/local_agent/agent_loop.py#L130)|实现细节见源码与所属类说明|
|AgentLoop.guard_request|[第244行](../src/local_agent/agent_loop.py#L244)|保留用户明确的指标、筛选与日期；不把模型选择当作授权。|
|AgentLoop.evidence_result|[第297行](../src/local_agent/agent_loop.py#L297)|实现细节见源码与所属类说明|
|AgentLoop.model_observation|[第302行](../src/local_agent/agent_loop.py#L302)|限制模型上下文大小，完整回执仍在会话中；摘要明确标注截断。|

### agent_tools.py

模型可选择的有限工具；业务执行仍由受控 Skill 完成。

|对象/方法|源码位置|职责|
|---|---|---|
|SearchInput|[第13行](../src/local_agent/agent_tools.py#L13)|实现细节见源码与所属类说明|
|RelationInput|[第20行](../src/local_agent/agent_tools.py#L20)|实现细节见源码与所属类说明|
|MetricInput|[第28行](../src/local_agent/agent_tools.py#L28)|实现细节见源码与所属类说明|
|ResolveInput|[第33行](../src/local_agent/agent_tools.py#L33)|实现细节见源码与所属类说明|
|AgentToolRouter|[第41行](../src/local_agent/agent_tools.py#L41)|模型动作适配器：公布工具 schema、验证参数并路由到业务服务/Skill。|
|AgentToolRouter.specifications|[第73行](../src/local_agent/agent_tools.py#L73)|实现细节见源码与所属类说明|
|AgentToolRouter.validate|[第77行](../src/local_agent/agent_tools.py#L77)|实现细节见源码与所属类说明|
|AgentToolRouter.call|[第82行](../src/local_agent/agent_tools.py#L82)|实现细节见源码与所属类说明|
|AgentTools兼容别名|[第114行](../src/local_agent/agent_tools.py#L114)|沿用旧导入路径；新代码使用规范名称|

### multi_plan.py

候选方案 -> 静态校验 -> 模型选择 -> 单步执行 -> 观察后重规划。

|对象/方法|源码位置|职责|
|---|---|---|
|PlanStep|[第9行](../src/local_agent/multi_plan.py#L9)|实现细节见源码与所属类说明|
|Candidate|[第16行](../src/local_agent/multi_plan.py#L16)|实现细节见源码与所属类说明|
|Proposals|[第23行](../src/local_agent/multi_plan.py#L23)|实现细节见源码与所属类说明|
|PlanSelection|[第28行](../src/local_agent/multi_plan.py#L28)|实现细节见源码与所属类说明|
|StepRequest|[第33行](../src/local_agent/multi_plan.py#L33)|实现细节见源码与所属类说明|
|MultiPlanManager|[第37行](../src/local_agent/multi_plan.py#L37)|仅保存当前 turn 的逻辑方案；SQL 计划仍由服务端即时生成与校验。|
|MultiPlanManager.propose|[第49行](../src/local_agent/multi_plan.py#L49)|实现细节见源码与所属类说明|
|MultiPlanManager.select|[第124行](../src/local_agent/multi_plan.py#L124)|实现细节见源码与所属类说明|
|MultiPlanManager.execute_step|[第134行](../src/local_agent/multi_plan.py#L134)|实现细节见源码与所属类说明|
|MultiPlanManager.snapshot|[第149行](../src/local_agent/multi_plan.py#L149)|实现细节见源码与所属类说明|

### mcp_server.py

本地 stdio MCP 适配只暴露受控工具，业务逻辑全部在自己的 AgentTools。

|对象/方法|源码位置|职责|
|---|---|---|
|describe_metric|[第12行](../src/local_agent/mcp_server.py#L12)|返回版本化口径和合法维度，禁止猜测销售额定义。|
|get_context|[第17行](../src/local_agent/mcp_server.py#L17)|读取本地实体/字段/Owner/质量/血缘证据。|
|get_lineage|[第23行](../src/local_agent/mcp_server.py#L23)|遍历本地关系表，字段解析范围与截断会明确返回。|
|plan_query|[第29行](../src/local_agent/mcp_server.py#L29)|结构化查询→自建编译器→服务端计划，调用方没有自由SQL入口。|
|execute_query|[第34行](../src/local_agent/mcp_server.py#L34)|只能执行本会话生成并通过校验的计划。|
|compare_windows|[第39行](../src/local_agent/mcp_server.py#L39)|比较同口径等时长窗口；证据不足时失败，不编造原因。|
|search_business|[第44行](../src/local_agent/mcp_server.py#L44)|授权后检索业务词/指标/案例，返回可核验引用，不返回原始用户明细。|
|run_diagnosis|[第51行](../src/local_agent/mcp_server.py#L51)|运行有界异常诊断Skill；不支持的假设和因果证据缺口会明确返回。|
|_feature|[第57行](../src/local_agent/mcp_server.py#L57)|实现细节见源码与所属类说明|
|get_user_profile|[第62行](../src/local_agent/mcp_server.py#L62)|按明确UTC截止日期读取用户画像和质量血缘。|
|get_product_profile|[第67行](../src/local_agent/mcp_server.py#L67)|按指定日期成功发布版本读取商品画像。|
|get_user_product_features|[第72行](../src/local_agent/mcp_server.py#L72)|只读取已有交互对，不把不存在记录伪装成负例。|
|get_session_profile|[第77行](../src/local_agent/mcp_server.py#L77)|读取会话观察结果，不推断支付、订单归属或负标签。|
|describe_data_product|[第82行](../src/local_agent/mcp_server.py#L82)|返回指定发布的数据产品契约、粒度和技术血缘。|
|main|[第86行](../src/local_agent/mcp_server.py#L86)|实现细节见源码与所属类说明|

## 业务能力与运行

### skills.py

可执行 Skill 注册表：契约、权限前置、预算与业务实现分别管理。

|对象/方法|源码位置|职责|
|---|---|---|
|SkillSpec|[第7行](../src/local_agent/skills.py#L7)|实现细节见源码与所属类说明|
|Pair|[第25行](../src/local_agent/skills.py#L25)|实现细节见源码与所属类说明|
|QualityInput|[第30行](../src/local_agent/skills.py#L30)|实现细节见源码与所属类说明|
|ReportInput|[第36行](../src/local_agent/skills.py#L36)|实现细节见源码与所属类说明|
|EvidenceOutput|[第42行](../src/local_agent/skills.py#L42)|实现细节见源码与所属类说明|
|SkillRegistry|[第49行](../src/local_agent/skills.py#L49)|实现细节见源码与所属类说明|
|SkillRegistry.validate|[第74行](../src/local_agent/skills.py#L74)|启动时验证依赖完整、无环；不是让模型任意拼接函数名。|
|SkillExecutor|[第83行](../src/local_agent/skills.py#L83)|实现细节见源码与所属类说明|
|SkillExecutor.run|[第88行](../src/local_agent/skills.py#L88)|实现细节见源码与所属类说明|

### skill_resources.py

轻量目录式Skill资源：按实际引用加载，不增加企业配置目录。

|对象/方法|源码位置|职责|
|---|---|---|
|entry|[第11行](../src/local_agent/skill_resources.py#L11)|实现细节见源码与所属类说明|
|resources|[第14行](../src/local_agent/skill_resources.py#L14)|实现细节见源码与所属类说明|
|report_template|[第27行](../src/local_agent/skill_resources.py#L27)|实现细节见源码与所属类说明|

### harness.py

自主 Harness：确定性约束负责正确性，模型仅负责受限意图转换。

|对象/方法|源码位置|职责|
|---|---|---|
|State|[第9行](../src/local_agent/harness.py#L9)|实现细节见源码与所属类说明|
|build_agent|[第27行](../src/local_agent/harness.py#L27)|有界分支图：任务理解与目录共享，随后选择查询或诊断Skill；失败停止。|

### diagnosis.py

有界假设验证与反证；数值变化、代数贡献、因果证据分别报告。

|对象/方法|源码位置|职责|
|---|---|---|
|DiagnosisEngine|[第6行](../src/local_agent/diagnosis.py#L6)|实现细节见源码与所属类说明|
|DiagnosisEngine.run|[第11行](../src/local_agent/diagnosis.py#L11)|最多8查询、2维度；失败保留已有证据，不输出未经验证的根因。|

### reporting.py

用Skill输出资产组织真实证据；模板中没有模型生成的虚构结论。

|对象/方法|源码位置|职责|
|---|---|---|
|compact|[第5行](../src/local_agent/reporting.py#L5)|实现细节见源码与所属类说明|
|render_report|[第8行](../src/local_agent/reporting.py#L8)|实现细节见源码与所属类说明|

### runtime.py

本地持久 Harness：保存状态和查询回执，恢复时重新规划并验证权限/版本。

|对象/方法|源码位置|职责|
|---|---|---|
|encode|[第13行](../src/local_agent/runtime.py#L13)|实现细节见源码与所属类说明|
|SessionStore|[第16行](../src/local_agent/runtime.py#L16)|实现细节见源码与所属类说明|
|SessionStore.connect|[第34行](../src/local_agent/runtime.py#L34)|实现细节见源码与所属类说明|
|SessionStore.create|[第37行](../src/local_agent/runtime.py#L37)|实现细节见源码与所属类说明|
|SessionStore.get|[第46行](../src/local_agent/runtime.py#L46)|实现细节见源码与所属类说明|
|SessionStore.acquire|[第55行](../src/local_agent/runtime.py#L55)|实现细节见源码与所属类说明|
|SessionStore.event|[第63行](../src/local_agent/runtime.py#L63)|实现细节见源码与所属类说明|
|SessionStore.checkpoint|[第68行](../src/local_agent/runtime.py#L68)|实现细节见源码与所属类说明|
|SessionStore.finish|[第72行](../src/local_agent/runtime.py#L72)|实现细节见源码与所属类说明|
|SessionStore.reserve_query|[第77行](../src/local_agent/runtime.py#L77)|执行前扣预算，崩溃后的不确定查询也算已消耗，不能无限重试。|
|SessionStore.receipt|[第83行](../src/local_agent/runtime.py#L83)|实现细节见源码与所属类说明|
|SessionStore.save_receipt|[第88行](../src/local_agent/runtime.py#L88)|实现细节见源码与所属类说明|
|RuntimeTools|[第92行](../src/local_agent/runtime.py#L92)|所有 Skill 共用工具预算；本地回执复用也必须先重新授权和规划。|
|RuntimeTools.check_execution|[第99行](../src/local_agent/runtime.py#L99)|实现细节见源码与所属类说明|
|RuntimeTools.emit|[第101行](../src/local_agent/runtime.py#L101)|实现细节见源码与所属类说明|
|RuntimeTools.plan|[第105行](../src/local_agent/runtime.py#L105)|实现细节见源码与所属类说明|
|RuntimeTools.execute|[第109行](../src/local_agent/runtime.py#L109)|实现细节见源码与所属类说明|
|HarnessRuntime|[第145行](../src/local_agent/runtime.py#L145)|实现细节见源码与所属类说明|
|HarnessRuntime.binding|[第151行](../src/local_agent/runtime.py#L151)|实现细节见源码与所属类说明|
|HarnessRuntime.authorize|[第166行](../src/local_agent/runtime.py#L166)|实现细节见源码与所属类说明|
|HarnessRuntime.start|[第172行](../src/local_agent/runtime.py#L172)|实现细节见源码与所属类说明|
|HarnessRuntime.show|[第177行](../src/local_agent/runtime.py#L177)|实现细节见源码与所属类说明|
|HarnessRuntime.cancel|[第195行](../src/local_agent/runtime.py#L195)|实现细节见源码与所属类说明|
|HarnessRuntime.followup|[第202行](../src/local_agent/runtime.py#L202)|澄清回复显式保留原问题；只允许用户明确选择的指标替换歧义词。|
|HarnessRuntime.resume|[第222行](../src/local_agent/runtime.py#L222)|实现细节见源码与所属类说明|

### resilience.py

共享有界重试与本地熔断；确定性错误永不重试，半开只允许一个探测。

|对象/方法|源码位置|职责|
|---|---|---|
|TransientFailure|[第12行](../src/local_agent/resilience.py#L12)|实现细节见源码与所属类说明|
|CircuitOpen|[第17行](../src/local_agent/resilience.py#L17)|实现细节见源码与所属类说明|
|retry_after|[第19行](../src/local_agent/resilience.py#L19)|实现细节见源码与所属类说明|
|RetryPolicy|[第28行](../src/local_agent/resilience.py#L28)|实现细节见源码与所属类说明|
|CircuitBreaker|[第35行](../src/local_agent/resilience.py#L35)|实现细节见源码与所属类说明|
|CircuitBreaker.connect|[第43行](../src/local_agent/resilience.py#L43)|实现细节见源码与所属类说明|
|CircuitBreaker.before|[第49行](../src/local_agent/resilience.py#L49)|实现细节见源码与所属类说明|
|CircuitBreaker.success|[第62行](../src/local_agent/resilience.py#L62)|实现细节见源码与所属类说明|
|CircuitBreaker.failure|[第66行](../src/local_agent/resilience.py#L66)|实现细节见源码与所属类说明|
|CircuitBreaker.release_probe|[第74行](../src/local_agent/resilience.py#L74)|实现细节见源码与所属类说明|
|CircuitBreaker.snapshot|[第78行](../src/local_agent/resilience.py#L78)|实现细节见源码与所属类说明|
|retry_call|[第84行](../src/local_agent/resilience.py#L84)|deadline为整个操作的monotonic截止点；取消/权限/业务错误直接传播。|

### openai_provider.py

官方 Responses 接入：模型只产出任务，SQL 和身份始终由本地系统控制。

|对象/方法|源码位置|职责|
|---|---|---|
|task_schema|[第11行](../src/local_agent/openai_provider.py#L11)|严格模式要求每个属性必填；可选任务/对照窗口用 null 表达。|
|request_task|[第28行](../src/local_agent/openai_provider.py#L28)|仅重试明确瞬时错误；共享熔断，日志不回显密钥或错误正文。|

## 可信查询与计算

### service.py

本地可信工具服务：发布、计划、受限执行和审计都由自己的代码完成。

|对象/方法|源码位置|职责|
|---|---|---|
|QueryService|[第17行](../src/local_agent/service.py#L17)|可信指标查询服务，负责数据发布、元数据、计划、授权和只读执行。|
|QueryService.publish|[第33行](../src/local_agent/service.py#L33)|验证真实数据后复制不可变快照；dbt PASS 只是证据之一，仍独立物理对账。|
|QueryService.release|[第98行](../src/local_agent/service.py#L98)|每次执行重新检查快照、合同和目录，旧计划不能跨版本偷偷复用。|
|QueryService.context|[第110行](../src/local_agent/service.py#L110)|实现细节见源码与所属类说明|
|QueryService.describe|[第115行](../src/local_agent/service.py#L115)|口径来自注册表，用户可见维度还要经过权限过滤。|
|QueryService.lineage|[第123行](../src/local_agent/service.py#L123)|仅对授权指标相关事实开放图查询；敏感字段关系对受限主体遮盖。|
|QueryService.plan|[第145行](../src/local_agent/service.py#L145)|工具只接受 Query；生成计划保存在服务内，调用方不能替换 SQL。|
|QueryService.enforce_request|[第180行](../src/local_agent/service.py#L180)|多事实每个分支独立授权，并施加同一强制行过滤，不借 Join 扩权。|
|QueryService.execute|[第212行](../src/local_agent/service.py#L212)|重新编译与服务端计划对比；hash 用于完整性，不是远程认证签名。|
|QueryService.compare|[第282行](../src/local_agent/service.py#L282)|双窗口证据比较：保证口径、分组、过滤、时长一致，只报告变化不归因。|
|AgentTools兼容别名|[第307行](../src/local_agent/service.py#L307)|沿用旧导入路径；新代码使用规范名称|

### semantic.py

自建语义注册表与编译器：先约束 Grain，再生成受控 SQL AST。

|对象/方法|源码位置|职责|
|---|---|---|
|file_hash|[第13行](../src/local_agent/semantic.py#L13)|流式校验大文件，避免把整个数仓加载进 Python 内存。|
|Query|[第21行](../src/local_agent/semantic.py#L21)|模型只能提交结构化意图；不接受 SQL、表名、任意表达式或身份参数。|
|Query.bounds|[第32行](../src/local_agent/semantic.py#L32)|实现细节见源码与所属类说明|
|SemanticRegistry|[第39行](../src/local_agent/semantic.py#L39)|指标口径唯一来源；支持受限单事实查询，拒绝隐式多事实关联。|
|SemanticRegistry.describe|[第46行](../src/local_agent/semantic.py#L46)|实现细节见源码与所属类说明|
|SQLCompiler|[第55行](../src/local_agent/semantic.py#L55)|自行实现聚合规则，SQLGlot 负责 AST；没有调用 MetricFlow 编译器。|
|SQLCompiler.expression|[第60行](../src/local_agent/semantic.py#L60)|递归展开比例，检测循环；比例在聚合后计算，防止平均日均值。|
|SQLCompiler.compile|[第89行](../src/local_agent/semantic.py#L89)|表/字段来自受信合同；过滤值构建为 SQL 字面量，不能改变 SQL 结构。|

### multi_fact.py

多事实先各自聚合再关联：模型选择指标与目标 Grain，不能选择物理 Join 键。

|对象/方法|源码位置|职责|
|---|---|---|
|MultiFactQuery|[第9行](../src/local_agent/multi_fact.py#L9)|实现细节见源码与所属类说明|
|MultiFactQuery.bounds|[第23行](../src/local_agent/multi_fact.py#L23)|实现细节见源码与所属类说明|
|MultiFactQuery.branch|[第32行](../src/local_agent/multi_fact.py#L32)|实现细节见源码与所属类说明|
|parse_query|[第37行](../src/local_agent/multi_fact.py#L37)|持久计划重验时按显式类型解析，不允许通过额外字段绕过旧 Query。|
|MultiFactCompiler|[第42行](../src/local_agent/multi_fact.py#L42)|实现细节见源码与所属类说明|
|MultiFactCompiler.compile|[第46行](../src/local_agent/multi_fact.py#L46)|实现细节见源码与所属类说明|

### dimensions.py

维度值链接：业务别名→真实快照枚举，未知值澄清而不是伪零结果。

|对象/方法|源码位置|职责|
|---|---|---|
|DimensionResolver|[第7行](../src/local_agent/dimensions.py#L7)|实现细节见源码与所属类说明|
|DimensionResolver.values|[第13行](../src/local_agent/dimensions.py#L13)|实现细节见源码与所属类说明|
|DimensionResolver.resolve|[第29行](../src/local_agent/dimensions.py#L29)|实现细节见源码与所属类说明|
|DimensionResolver.query|[第44行](../src/local_agent/dimensions.py#L44)|实现细节见源码与所属类说明|
|DimensionResolver.summary|[第55行](../src/local_agent/dimensions.py#L55)|实现细节见源码与所属类说明|
|DimensionResolver.explicit_filters|[第61行](../src/local_agent/dimensions.py#L61)|保护明确的国家/性别词，防止模型遗漏或偷偷替换用户筛选。|

### query_templates.py

高频语义 IR 缓存：只缓存聚合表达式，不缓存日期/过滤值/完整 SQL/数据结果。

|对象/方法|源码位置|职责|
|---|---|---|
|QueryTemplateCache|[第11行](../src/local_agent/query_templates.py#L11)|实现细节见源码与所属类说明|
|QueryTemplateCache.connect|[第19行](../src/local_agent/query_templates.py#L19)|实现细节见源码与所属类说明|
|QueryTemplateCache.compile|[第22行](../src/local_agent/query_templates.py#L22)|实现细节见源码与所属类说明|
|QueryTemplateCache.stats|[第65行](../src/local_agent/query_templates.py#L65)|实现细节见源码与所属类说明|

### worker.py

工具服务内部的独立执行进程；不对 Agent 暴露自由 SQL 接口。

|对象/方法|源码位置|职责|
|---|---|---|
|main|[第6行](../src/local_agent/worker.py#L6)|只读、禁外部访问、限定资源；仅通过 JSON 管道返回结果。|

## 检索与语义上下文

### retrieval_service.py

统一候选服务：精确、词法、可选 Dense/RRF，最终收敛到权威解析。

|对象/方法|源码位置|职责|
|---|---|---|
|Discovery|[第12行](../src/local_agent/retrieval_service.py#L12)|实现细节见源码与所属类说明|
|RetrievalService|[第23行](../src/local_agent/retrieval_service.py#L23)|实现细节见源码与所属类说明|
|RetrievalService.retrieve|[第28行](../src/local_agent/retrieval_service.py#L28)|实现细节见源码与所属类说明|
|QueryContextBroker|[第99行](../src/local_agent/retrieval_service.py#L99)|实现细节见源码与所属类说明|
|QueryContextBroker.prepare|[第105行](../src/local_agent/retrieval_service.py#L105)|实现细节见源码与所属类说明|
|get_retrieval_service|[第127行](../src/local_agent/retrieval_service.py#L127)|实现细节见源码与所属类说明|

### retrieval.py

本地业务检索与Schema Linking：词法、别名、图上下文组合，不伪称向量检索。

|对象/方法|源码位置|职责|
|---|---|---|
|tokens|[第8行](../src/local_agent/retrieval.py#L8)|中文用字符二元组，英文按词；轻量方案无需下载embedding模型。|
|KnowledgeRetriever|[第14行](../src/local_agent/retrieval.py#L14)|实现细节见源码与所属类说明|
|KnowledgeRetriever.metric_candidates|[第22行](../src/local_agent/retrieval.py#L22)|优先匹配最长别名，避免'平均订单金额'同时被识别成'订单金额'。|
|KnowledgeRetriever.search|[第32行](../src/local_agent/retrieval.py#L32)|先做授权过滤再评分；返回权威来源定位，不把检索文档当执行指令。|
|KnowledgeRetriever.paths|[第79行](../src/local_agent/retrieval.py#L79)|两种路径的数据类型独立，权威结构不参与RRF文本投票。|
|KnowledgeRetriever.link|[第88行](../src/local_agent/retrieval.py#L88)|从指标走到物理事实与列，字段血缘由目录读取，不让LLM猜表名。|

### dense_retrieval.py

离线语义资产快照与在线 Dense/RRF。索引不是指标口径权威。

|对象/方法|源码位置|职责|
|---|---|---|
|digest|[第16行](../src/local_agent/dense_retrieval.py#L16)|实现细节见源码与所属类说明|
|asset_id|[第21行](../src/local_agent/dense_retrieval.py#L21)|实现细节见源码与所属类说明|
|EmbeddingProvider|[第26行](../src/local_agent/dense_retrieval.py#L26)|实现细节见源码与所属类说明|
|EmbeddingProvider.encode|[第28行](../src/local_agent/dense_retrieval.py#L28)|实现细节见源码与所属类说明|
|LocalEmbeddingProvider|[第31行](../src/local_agent/dense_retrieval.py#L31)|独立 CPU 子进程；在线只读本地模型，超时终止，不调用付费 API。|
|LocalEmbeddingProvider.validate_identity|[第36行](../src/local_agent/dense_retrieval.py#L36)|实现细节见源码与所属类说明|
|LocalEmbeddingProvider.encode|[第43行](../src/local_agent/dense_retrieval.py#L43)|实现细节见源码与所属类说明|
|normalized|[第75行](../src/local_agent/dense_retrieval.py#L75)|实现细节见源码与所属类说明|
|read_snapshot|[第88行](../src/local_agent/dense_retrieval.py#L88)|查询和增量构建共用快照完整性检查；不在此接受旧快照作为当前语义。|
|publish_index|[第114行](../src/local_agent/dense_retrieval.py#L114)|先构建、校验完整不可变快照，最后原子替换 active；失败保留旧索引。|
|configuration|[第187行](../src/local_agent/dense_retrieval.py#L187)|实现细节见源码与所属类说明|
|retrieval_binding|[第195行](../src/local_agent/dense_retrieval.py#L195)|实现细节见源码与所属类说明|
|DenseIndex|[第203行](../src/local_agent/dense_retrieval.py#L203)|实现细节见源码与所属类说明|
|DenseIndex.search|[第208行](../src/local_agent/dense_retrieval.py#L208)|实现细节见源码与所属类说明|
|rrf|[第234行](../src/local_agent/dense_retrieval.py#L234)|只融合名次，不相加 BM25 与 cosine；同一资产每路只投一票。|

### reranking.py

有界、按需重排；模型分数只调整名次，不授权、不定义公式。

|对象/方法|源码位置|职责|
|---|---|---|
|reranker_binding|[第14行](../src/local_agent/reranking.py#L14)|实现细节见源码与所属类说明|
|LocalReranker|[第26行](../src/local_agent/reranking.py#L26)|实现细节见源码与所属类说明|
|LocalReranker.score|[第27行](../src/local_agent/reranking.py#L27)|实现细节见源码与所属类说明|
|rerank|[第55行](../src/local_agent/reranking.py#L55)|实现细节见源码与所属类说明|

### semantic_context.py

统一权威语义解析：候选只提供ID，定义从当前Registry重新读取。

|对象/方法|源码位置|职责|
|---|---|---|
|asset_version|[第8行](../src/local_agent/semantic_context.py#L8)|实现细节见源码与所属类说明|
|SemanticContext|[第16行](../src/local_agent/semantic_context.py#L16)|实现细节见源码与所属类说明|
|SemanticContextResolver|[第32行](../src/local_agent/semantic_context.py#L32)|实现细节见源码与所属类说明|
|SemanticContextResolver.binding|[第36行](../src/local_agent/semantic_context.py#L36)|实现细节见源码与所属类说明|
|SemanticContextResolver.resolve|[第46行](../src/local_agent/semantic_context.py#L46)|实现细节见源码与所属类说明|
|SemanticContextResolver.validate|[第116行](../src/local_agent/semantic_context.py#L116)|实现细节见源码与所属类说明|
|SemanticContextResolver.resolve_request|[第126行](../src/local_agent/semantic_context.py#L126)|实现细节见源码与所属类说明|

### retrieval_context.py

两路上下文保留类型和权威边界；案例不能覆盖公式和权限。

|对象/方法|源码位置|职责|
|---|---|---|
|RetrievalContext|[第4行](../src/local_agent/retrieval_context.py#L4)|实现细节见源码与所属类说明|
|resolve_context|[第20行](../src/local_agent/retrieval_context.py#L20)|结构化定义重新从授权工具读取，不信任检索副本或模型提供的公式。|

## 资产与元数据

### assets.py

Registry 唯一权威同时派生 Flat 文档和 Structured 关系；不是自由实体抽取。

|对象/方法|源码位置|职责|
|---|---|---|
|AssetBuilder|[第6行](../src/local_agent/assets.py#L6)|实现细节见源码与所属类说明|
|AssetBuilder.build|[第11行](../src/local_agent/assets.py#L11)|实现细节见源码与所属类说明|

### structure.py

SQLite 结构投影与有界关系遍历；路径可达不是 Join 授权。

|对象/方法|源码位置|职责|
|---|---|---|
|write_graph|[第10行](../src/local_agent/structure.py#L10)|实现细节见源码与所属类说明|
|graph_binding|[第34行](../src/local_agent/structure.py#L34)|实现细节见源码与所属类说明|
|GraphService|[第46行](../src/local_agent/structure.py#L46)|实现细节见源码与所属类说明|
|GraphService.load|[第50行](../src/local_agent/structure.py#L50)|实现细节见源码与所属类说明|
|GraphService.evidence|[第67行](../src/local_agent/structure.py#L67)|实现细节见源码与所属类说明|
|GraphService.query|[第84行](../src/local_agent/structure.py#L84)|实现细节见源码与所属类说明|

### catalog.py

自建 Metadata Graph：实体、Aspect、关系保存在本地 SQLite，不调用 DataHub。

|对象/方法|源码位置|职责|
|---|---|---|
|MetadataCatalog|[第11行](../src/local_agent/catalog.py#L11)|用实体标识定位对象，用 Aspect 存属性，用有向边保存表级血缘。|
|MetadataCatalog.urn|[第26行](../src/local_agent/catalog.py#L26)|标识采用本项目命名空间，不冒充 DataHub 已采集的实体。|
|MetadataCatalog.ingest|[第30行](../src/local_agent/catalog.py#L30)|读取物理 schema 与 dbt depends_on；事务内替换，避免目录处于半更新状态。|
|MetadataCatalog.attach_quality|[第101行](../src/local_agent/catalog.py#L101)|质量是单独 Aspect，记录快照级验证范围，不能冒充逐字段业务质量。|
|MetadataCatalog.context|[第108行](../src/local_agent/catalog.py#L108)|按表读取可验证上下文；目录不存在该表时直接失败。|
|MetadataCatalog.field_lineage|[第117行](../src/local_agent/catalog.py#L117)|追踪已解析的值依赖；聚合行数、过滤条件等未覆盖部分显式保留。|
|MetadataCatalog.lineage|[第145行](../src/local_agent/catalog.py#L145)|广度优先遍历并处理环；返回截断标记，不能把预算耗尽当成没有依赖。|

### control_lineage.py

保守解析Join/Where/Group/Having控制依赖；不能证明的列保持unresolved。

|对象/方法|源码位置|职责|
|---|---|---|
|extract_control|[第5行](../src/local_agent/control_lineage.py#L5)|实现细节见源码与所属类说明|

### history.py

本地快照观察历史：支持变化/迟到记录，但不捏造真实业务生效时间。

|对象/方法|源码位置|职责|
|---|---|---|
|SnapshotHistory|[第9行](../src/local_agent/history.py#L9)|实现细节见源码与所属类说明|
|SnapshotHistory.capture|[第20行](../src/local_agent/history.py#L20)|幂等实体版本；晚到的业务记录从本次观察时刻出现，不回写成过去已知。|
|SnapshotHistory.as_of|[第57行](../src/local_agent/history.py#L57)|按当时本地已知的版本查询；时间前无记录返回None，不推测历史状态。|
|SnapshotHistory.capture_warehouse|[第67行](../src/local_agent/history.py#L67)|只保留订单状态和业务用户属性，不把姓名/邮箱写入历史库。|

## 特征数据产品

### feature_pipeline.py

独立写入通道：构建电商主题数据产品，不放开 Agent 的只读工具。

每次从原库复制相关 raw 表到独立目录，通过 dbt 全量重建和独立对账，
成功后才切换 active.json。没有生产者水位，不能宣称严格 PIT 完整性。

|对象/方法|源码位置|职责|
|---|---|---|
|write_json|[第37行](../src/local_agent/feature_pipeline.py#L37)|实现细节见源码与所属类说明|
|validate|[第41行](../src/local_agent/feature_pipeline.py#L41)|独立于 dbt PASS：从 raw 重新计算计数、金额与每个用户的窗口特征。|
|signatures|[第173行](../src/local_agent/feature_pipeline.py#L173)|重跑比对全表行数和两个交换性内容摘要，不把它冒充安全哈希。|
|catalog|[第183行](../src/local_agent/feature_pipeline.py#L183)|从 dbt 依赖与编译 SQL 输出技术血缘；COUNT(*) 等不能保证字段完整。|
|build|[第223行](../src/local_agent/feature_pipeline.py#L223)|实现细节见源码与所属类说明|
|main|[第314行](../src/local_agent/feature_pipeline.py#L314)|实现细节见源码与所属类说明|

### feature_agent.py

画像工具与统一入口路由。有限规则理解明确请求，不生成自由 SQL。

特征发布版本独立于指标快照，避免旧指标质量过期阻断画像读取。
画像只向本地主体开放；受限聚合令牌不因此获得用户级数据访问。

|对象/方法|源码位置|职责|
|---|---|---|
|FeatureRequest|[第27行](../src/local_agent/feature_agent.py#L27)|实现细节见源码与所属类说明|
|FeatureRequest.coherent|[第37行](../src/local_agent/feature_agent.py#L37)|实现细节见源码与所属类说明|
|is_feature_question|[第48行](../src/local_agent/feature_agent.py#L48)|实现细节见源码与所属类说明|
|parse_feature_question|[第52行](../src/local_agent/feature_agent.py#L52)|支持显式实体和完整日期；澄清通过字段补丁合并，不拼接矛盾问题。|
|FeatureTools|[第79行](../src/local_agent/feature_agent.py#L79)|实现细节见源码与所属类说明|
|FeatureTools.release|[第90行](../src/local_agent/feature_agent.py#L90)|实现细节见源码与所属类说明|
|FeatureTools.read_profile|[第110行](../src/local_agent/feature_agent.py#L110)|实现细节见源码与所属类说明|
|FeatureRuntime|[第145行](../src/local_agent/feature_agent.py#L145)|画像小任务也保存状态和证据；不调用过期的指标 release。|
|FeatureRuntime.base_binding|[第151行](../src/local_agent/feature_agent.py#L151)|实现细节见源码与所属类说明|
|FeatureRuntime.authorize|[第157行](../src/local_agent/feature_agent.py#L157)|实现细节见源码与所属类说明|
|FeatureRuntime.start|[第165行](../src/local_agent/feature_agent.py#L165)|实现细节见源码与所属类说明|
|FeatureRuntime.resume|[第169行](../src/local_agent/feature_agent.py#L169)|实现细节见源码与所属类说明|
|FeatureRuntime.show|[第207行](../src/local_agent/feature_agent.py#L207)|实现细节见源码与所属类说明|
|FeatureRuntime.cancel|[第213行](../src/local_agent/feature_agent.py#L213)|实现细节见源码与所属类说明|
|FeatureRuntime.followup|[第218行](../src/local_agent/feature_agent.py#L218)|实现细节见源码与所属类说明|
|UnifiedRuntime|[第224行](../src/local_agent/feature_agent.py#L224)|同一 ask/chat 入口分派指标任务和画像任务，持久化各自的证据。|
|UnifiedRuntime.target|[第233行](../src/local_agent/feature_agent.py#L233)|实现细节见源码与所属类说明|
|UnifiedRuntime.authorize|[第234行](../src/local_agent/feature_agent.py#L234)|实现细节见源码与所属类说明|
|UnifiedRuntime.show|[第235行](../src/local_agent/feature_agent.py#L235)|实现细节见源码与所属类说明|
|UnifiedRuntime.resume|[第236行](../src/local_agent/feature_agent.py#L236)|实现细节见源码与所属类说明|
|UnifiedRuntime.cancel|[第237行](../src/local_agent/feature_agent.py#L237)|实现细节见源码与所属类说明|
|UnifiedRuntime.followup|[第238行](../src/local_agent/feature_agent.py#L238)|实现细节见源码与所属类说明|
|UnifiedRuntime.start|[第239行](../src/local_agent/feature_agent.py#L239)|实现细节见源码与所属类说明|

## 共同约束与验证

### access.py

本地能力令牌与服务侧权限；不是企业SSO，也不接受模型自报身份。

|对象/方法|源码位置|职责|
|---|---|---|
|AccessDenied|[第13行](../src/local_agent/access.py#L13)|权限失败必须停止，不能通过换口径或删过滤静默重试。|
|_encode|[第16行](../src/local_agent/access.py#L16)|实现细节见源码与所属类说明|
|AccessController|[第19行](../src/local_agent/access.py#L19)|本地stdio/CLI信任OS用户；可用签名令牌绑定受限主体，每次工具调用重验。|
|AccessController.issue|[第41行](../src/local_agent/access.py#L41)|仅可信本地主机管理入口签发；此方法不作为MCP工具暴露。|
|AccessController.revoke|[第70行](../src/local_agent/access.py#L70)|管理员撤销令牌；不能由模型选择或生成subject。|
|AccessController.role|[第83行](../src/local_agent/access.py#L83)|热变更策略后停止旧会话；令牌过期在执行时也会生效。|
|AccessController.metric|[第92行](../src/local_agent/access.py#L92)|实现细节见源码与所属类说明|
|AccessController.enforce|[第98行](../src/local_agent/access.py#L98)|服务器强制行过滤与列维度权限；模型不能移除US限制或查询敏感分组。|
|AccessController.redact_metadata|[第110行](../src/local_agent/access.py#L110)|非管理员元数据隐藏敏感字段；数据工具从未暴露原始身份明细。|

### temporal.py

时间边界与完整性证据；max(event_time)绝不能自动升级为完整性水位。

|对象/方法|源码位置|职责|
|---|---|---|
|CoverageReceipt|[第9行](../src/local_agent/temporal.py#L9)|可信本地管道可提交绑定数据库hash的水位；模型和MCP调用者无写入入口。|
|CoverageReceipt.aware|[第19行](../src/local_agent/temporal.py#L19)|实现细节见源码与所属类说明|
|coverage|[第26行](../src/local_agent/temporal.py#L26)|默认仅记录快照观测时间；有真实管道收据才声明完整性。|
|check_window|[第39行](../src/local_agent/temporal.py#L39)|拒绝未结束日和超过快照观测的日期；历史空区间仍可返回零/空值。|
|DateResolver|[第53行](../src/local_agent/temporal.py#L53)|本地UTC日历解析；没有猜测业务时区或用模型计算今天/昨天。|
|DateResolver.relative|[第61行](../src/local_agent/temporal.py#L61)|实现细节见源码与所属类说明|

### integrity.py

共享内容摘要：业务服务、语义上下文和运行账本使用同一序列化规则。

这是完整性校验工具，不负责身份认证，也不作为指标口径来源。
保持历史序列化规则，避免整理模块时使已有计划摘要发生无意义变化。

|对象/方法|源码位置|职责|
|---|---|---|
|fingerprint|[第10行](../src/local_agent/integrity.py#L10)|对稳定排序的 JSON 计算 SHA256；日期等对象沿用历史 str 转换。|

### evaluation.py

离线评测只衡量本地规则；模拟模型测协议，真实LLM成绩必须独立记录。

|对象/方法|源码位置|职责|
|---|---|---|
|load_cases|[第7行](../src/local_agent/evaluation.py#L7)|实现细节见源码与所属类说明|
|evaluate_rules|[第10行](../src/local_agent/evaluation.py#L10)|固定UTC时钟，逐字段验证指标、窗口、分组、方向和Skill路由。|

### __init__.py

自主电商 Agent 核心；运行时不导入 MetricFlow、WrenAI 或 DataHub。

|对象/方法|源码位置|职责|
|---|---|---|
