# MyAgent 整体项目验收报告与学习基线

本次验收覆盖整个MyAgent，不仅是第四阶段RAG。源码基线：04cb493f97facc68e7c6be35f4bebb19aade6b27；本次提交在此基础上补充验收脚本、运行证据与学习文档，不重构核心运行代码。精确执行时间与源码摘要见 [核心验收JSON](project-final-acceptance.json)。

**结论：在Windows本机学习工程、TheLook快照、受限语义查询与证据分析的范围内，整体验收通过，可以以此作为学习基线。** 没有发现需要大改核心链路才能继续学习的阻断问题。生产扩展、模型泛化准确率、严格历史PIT、企业权限和因果根因证明仍不属于已完成范围。

## 1. 这次实际执行了哪些检查

|验收项|结果|本次证据|
|---|---|---|
|初始全量回归|未通过，保留记录|122通过、106fixture错误、1断言失败，全部关联过期dbt质量凭证|
|commerce重新构建与发布|PASS|真实dbt build/docs generate，当前断言重跑、grain/金额独立核对、生成新release|
|最终全量工程回归|PASS|229 passed，280.51秒；JUnit 0 errors/0 failures/0 skipped|
|统一入口核心场景|PASS|7个实际场景，包含1查询取数、14查询诊断和零查询拒绝|
|规则查询独立对账|PASS|2026年9月订单量与raw.orders独立计算一致|
|真实本地神经检索|PASS|E5/Dense/RRF/Cross-Encoder实际推理，非假向量|
|结构关系进入Agent|PASS|脚本化决策调用query_relations，再查真实数据并引用证据|
|真实OpenAI模型|PASS|gpt-6.1-sol模型预检200；2轮真实推理、run_query→finish、1次查询|
|真实模型数值对账|PASS|客单价88.22046842854883，与raw明细金额/raw订单数一致|
|语义资产生命周期|PASS|隔离真实编码器更新/删除/恢复，旧图与旧会话拒绝|
|Multi Plan与多事实|PASS|模拟决策模型+真实数据，58个分组raw独立对账，未截断|
|特征十表完整加工|PASS|重新真实构建23项dbt检查、48项独立对账；再次重建十表内容摘要一致|
|画像与统一入口|PASS|5条自然语言数据产品请求，结构化请求与结果一致|
|本地MCP|PASS|实际stdio客户端发现13工具，并调用get_user_profile成功|
|环境完整性|PASS|.venv/.warehouse-venv/.retrieval-venv三环境pip check均无冲突|
|Python编译|PASS|核心源码与新增/修改验收脚本compileall|
|源码与文档一致性|已修正|README、AgentLoop与Multi Plan文档中早期“无向量/无首次检索”描述更新|
|模型准确率/生产性能|未进行|没有用单次成功冒烟替代统计评测或规模压力测试|

这些计数存在覆盖重叠：229项工程测试不能与23+48数据检查、7场景或模型调用次数相加为“准确率”。本轮不以统计模型评测为目标。

## 2. 初验失败原因与真实处理

初验时本地commerce dbt质量文件generated_at为2026-10-11T10:42:26Z，运行时已超过允许的24小时。service.AgentTools.publish在执行前拒绝，多个使用发布fixture的测试因此报错；一个预期检测实际数据错误的用例先遇到有效期阻断，断言也失败。

处理步骤：保留 [初验JUnit](project-final-initial-regression.xml)，真实运行build-warehouse.ps1，重新在当前库执行dbt模型与断言、生成目录并发布，再完整重跑测试。没有修改凭证时间、放宽有效期或绕开质量检查。

**学习意义**：测试/示例依赖有效的数据与质量证据。昨天完成的release不是永远有效；“重跑质量验证”与“重新获取源数据”不同。刷新质量时间不会刷新TheLook源观测时间，也不会验证未到齐数据的水位。

## 3. 当前数据、语义和工具盘点

|对象|当前数量/状态|来源|
|---|---|---|
|raw表|7表，3,358,422行|本次release物理查询|
|commerce模型|2维度、2事实、1汇总|dbt模型/MetadataCatalog|
|标准指标|12|commerce.json.metrics|
|跨事实派生|1，items_per_order@1|commerce.json.multi_fact.ratios|
|特征模型|3 DWD、4 DWS、3 ADS，总10|feature_pipeline.TABLES与实际dbt|
|注册查询Skill|7|SkillRegistry|
|独立加工Skill|1个warehouse-feature-engineering包|加工入口，未算进7个查询Skill|
|Agent进程内动作工具|12|agent_tools.AgentTools.inputs|
|MCP stdio工具|13|本次真实list_tools|
|Flat语义资产|21，向量维度384|已发布format3快照|
|语义关系投影|61节点、140边|Registry派生SQLite图|
|物理Metadata实体|12dataset、146field、1flow、5job|本次catalog.sqlite统计|
|Owner|声明存在，verified_business_owner:false|本地学习Owner，非业务签收|
|源完整性水位|未验证|snapshot-observation、complete_through:null|
|特征截止日期|2026-10-11 UTC零点|本次features release|

两个图不能混用数量：catalog.sqlite是物理元数据/任务/值与控制依赖；structured.sqlite是指标和grain等语义投影。它们都是本项目自己的SQLite实现，没有启动DataHub或专用图数据库。

## 4. 七个实际入口场景

|场景|状态|实际查询尝试|验证了什么|
|---|---|---:|---|
|查询2026年9月订单量|COMPLETE|1|规则理解、Task、Skill、编译、Worker、raw对账|
|2026年9月销售额是多少|CLARIFY|0|口径歧义不替用户选择|
|2026年9月支付成功率|CLARIFY|0|没有支付事实不拿订单状态替代|
|order_count按category|STOPPED|0|错误grain/非法维度不做隐式Join|
|查询尚未结束的UTC当天|CLARIFY|0|可比窗口与完整日约束|
|订单完成占比两周诊断|INSUFFICIENT_EVIDENCE|14|比较、分子分母、两维下钻、总量重构、质量证据、停止因果|
|2010年空窗口客单价|COMPLETE|1|零分母返回null，不伪造0|

诊断的INSUFFICIENT_EVIDENCE是预期结果：14查询完成，无stopped_reason，缺完整性/历史成熟度与独立业务事件证据，因此不确认因果。不能把这个状态叫“代码失败”，也不能叫“证明了业务原因”。

Workflow完成任务resume返回已有完成状态且不新增查询；中断重放/版本阻断/回执复用由本轮全量工程用例验证。AgentLoop明确不支持中断resume，这是已知限制。

## 5. 真实模型与模拟决策必须区分

|运行|决策模型|数据/检索|能得出的结论|
|---|---|---|---|
|客单价真实冒烟|真实gpt-6.1-sol|真实E5/重排/Registry/TheLook|当前账号模型和一次自主取数链路可运行且对账一致|
|关系工具进入Agent|脚本化模拟选择|真实关系图/本地神经模型/TheLook|工具契约与工程链路连通，不能证明LLM自主选图准确率|
|58组Multi Plan|脚本化模拟选择|真实多事实查询与raw独立基准|先聚合Join实现正确，不能证明真实LLM复杂规划泛化|
|异常诊断|确定性Skill/Workflow|真实数据+质量/元数据|数学拆解与停止边界可运行，不能证明因果识别|
|工程测试|规则/Mock/临时数据及实际本地数据混合|按用例类型|输入/执行/安全/状态边界通过，不等于LLM准确率|

真实模型本轮使用平均订单金额问题，两轮动作run_query→finish，查询次数1，实际Agent运行约17.17秒。此耗时只属于本机本条暖缓存路径，不能作为一般SLA；整个检索模型生命周期验收耗时不同。

第一阶段/第四阶段历史真实模型失败记录继续保留；本轮没有通过放宽Decision协议获得成功。

## 6. 工程约束检查与主要证据

|约束|源码|测试/运行证据|
|---|---|---|
|不接受模型SQL/身份|Query extra=forbid；Decision/工具schema|test_agent_loop、test_own_agent、test_openai_provider|
|事实粒度与合法维度|SQLCompiler/MultiFactCompiler|错误category实际零查询；test_multi_plan_fact|
|聚合后比例/零分母|SQLCompiler.expression|空窗口null、raw客单价与多指标对账|
|多事实目标一致|conformed_dimensions/time_basis/population|58组独立对账及fanout/null/分支LIMIT反例|
|执行前重编译|service.AgentTools.execute|SQL/plan篡改与版本变化拒绝用例|
|当前授权/行过滤|AccessController/RuntimeTools|test_extensions、retrieval阶段授权负例|
|授权先于检索/遍历|AssetBuilder/DenseIndex/GraphService|test_retrieval_phase2/4敏感节点与分区测试|
|索引发布完整性|read_snapshot/publish_index|checksum、失败不切active、并发发布阻断|
|旧会话/计划失效|HarnessRuntime.binding/authorize|真实隔离生命周期+phase4回归|
|预算/取消/Worker期限|SessionStore/RuntimeTools/service.execute|test_runtime_skills中的超时/子进程取消检查|
|瞬时重试/持久熔断|retry_call/CircuitBreaker|test_core_scope及OpenAI provider专项|
|特征重复加工|feature_pipeline.validate/signatures|本次23dbt+48独立检查+十表重复摘要|
|异常停止因果|DiagnosisEngine|本次14查询诊断+比率贡献残差测试|

多数测试文件混合多个类型。可打开JUnit查看逐个名称，也可在tests目录搜对应方法；完整源码起始行映射在project-final-acceptance.json，学习手册提供重点入口。

## 7. 保留的问题、影响与是否必须修改

|事项|当前影响|本轮判断|
|---|---|---|
|规则解析语言子集|部分自然语言只能澄清/用结构化请求|接受，学习边界清楚|
|摘要文字未自动逐项证明|模型可能引用证据后仍写不准确解释|接受但必须以回执为准；summary_verified:false|
|普通Agent finish未强制数值执行证据|成功检索/目录观察也能使循环COMPLETE，不能保证数字问题已查数|必须核对run_query等实际回执；本轮真实取数有执行证据|
|普通Agent缺日期不总有硬性澄清|明确日期会核对，缺日期仍依赖模型遵循提示；Task模式更严格|保留差异，不能宣称任意自然语言已可靠理解|
|自主Agent不支持resume|中断后开启新turn|接受，不冒称已实现|
|AgentLoop模型请求无Task模式同等重试|模型网络错误直接停止|接受，不把Worker重试泛化到所有模型调用|
|画像取消/重试较弱|15秒固定Worker，取消前后检查|接受，不保证即时取消或自动重试|
|直接MCP绕过部分Harness组织|预算/诊断能力与Agent Skill入口不同|接受，仅本地受信客户端，不当生产控制面|
|Skill元信息非插件沙箱|声明tools/dependencies不能自动隔离未来任意代码|接受，当前固定白名单实现|
|缺可信完整性/历史SCD2|不证明迟到排除、历史当时状态/PIT|保留证据不足，不能靠代码“补齐真相”|
|特征为全量重建|没有生产CDC/迟到修正/幂等分区补数|按此前范围接受，重复构建验证不冒充增量|
|向量/授权资产全量扫描|资产大量增长后延迟/内存变差|当前21资产可用，规模未验收|
|模型/数据库hash读取和冷启动|运行成本/120秒预算受影响|学习范围接受，未承诺吞吐|
|commerce发布不是多发布者事务|共享catalog和active.partial存在并发/崩溃一致性限制|必须按单发布者使用；生产扩展前需要改造|
|索引/数据旧快照未GC|长期运行磁盘增长|接受，手动管理前先留存证据，无自动清理|
|本地权限不是企业治理|无SSO/租户/远程MCP/全局审计|按用户范围接受，不宣称企业完成|
|本机凭据/环境/数据不随仓库上传|新机器需重建与配置|文档明确，非项目缺文件|
|旧Word和历史阶段报告可能过时|不能把旧计数和链路当当前事实|以本手册/本报告为学习主入口|

这些限制没有被隐藏为TODO式承诺。当前可以稳定学习和演示已验收闭环，但不能以“后续不会大改”为由把未实现能力写成已完成。

## 8. 本次更新清单

1. 新增project-acceptance.py，实际跑统一入口场景、独立raw核对、目录统计，保存源码SHA256和类/方法行号。
2. 给retrieval-iteration-acceptance.py增加可选--output，让整体回执与阶段历史证据分开存放；默认行为不变。
3. 新增本详细验收报告和PROJECT-STUDY-GUIDE.md，包含Mermaid/ASCII、核心代码、框架责任、30个进阶回答及一周学习顺序。
4. 更新README、AgentLoop、Multi Plan、安装文档的过期表述，明确首次检索与四阶段最终状态。
5. 真实重建commerce与features，刷新相应阶段生成回执；保留初验失败和最终全量JUnit。
6. 重跑真实神经检索+实际OpenAI取数、特征MCP和Multi Plan独立对账。

没有改动核心Agent/数仓算法，没有扩建上游服务，没有新增生产部署或模型准确率评测任务。

## 9. 如何复验与学习

先读 [整体学习手册](PROJECT-STUDY-GUIDE.md) 第1–8节，亲手运行规则取数，再读第12–18节并沿源码复述执行；检索放在理解权威指标以后学习。

```powershell
# 先真实检查并发布，避免质量TTL过期
.\scripts\build-warehouse.ps1
.\.venv\Scripts\python.exe -m pytest --junitxml=docs/project-final-regression.xml
.\.venv\Scripts\python.exe scripts\project-acceptance.py
.\.venv\Scripts\python.exe scripts\multi-plan-demo.py

# 若要重新生产画像版本
.\scripts\build-feature-mart.ps1 -AsOf 2026-10-11 -VerifyRepeat
.\.venv\Scripts\python.exe scripts\feature-query-demo.py

# 真实模型与神经链路（使用已保存本机凭据，会产生API请求）
.\scripts\accept-retrieval-iteration.ps1 -LiveLLM
```

上面复验会生成新的release/session/回执和时间，不应要求UUID与历史证据完全一致。结构关系和Dense索引没有业务资产变化时可复用；更改Registry/knowledge/reference后需要重建相关索引与新建会话。

## 10. 证据文件导航

- [最终工程JUnit](project-final-regression.xml)：229个测试，含每项耗时与结果。
- [初验过期凭证记录](project-final-initial-regression.xml)：保留失败，避免把环境修复隐藏。
- [整体核心执行JSON](project-final-acceptance.json)：7实际请求/响应、14查询证据、数据行数、目录统计、源码hash与symbols。
- [整体真实检索/模型JSON](project-final-retrieval-acceptance.json)：真实模型两轮动作、神经检索trace、语义图、生命周期与raw对账。
- [本次特征加工回执](feature-phase2-verification.json)：23dbt检查在release产物、48独立checks、重复构建摘要。
- [本次画像/MCP回执](feature-phase2-live-demo.json)：5条自然语言、结构化结果、13工具stdio发现与画像读取。
- [本次Multi Plan回执](multi-plan-live-demo.json)：模拟决策、真实查询、58组raw对账。
- [当前dbt检查产物](thelook-dbt-run-results.json)：commerce本次真实build，不能用作永不过期质量证据。

本机data/project-final-*.log保留构建/演示日志，数据库、模型权重、签名密钥和会话不提交。学习时优先读取Markdown，再按需要打开对应JSON，不必先阅读所有大回执。
