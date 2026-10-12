# 双通路检索第一阶段完成记录

日期：2026-10-12。

## 已完成

- RetrievalService统一候选检索，复用授权后的同进程词法索引，提供候选、歧义、版本和追踪信息。
- SemanticContextResolver统一单/多指标、派生组件、共同维度、元数据、关系规则和按需枚举解析。
- QueryContextBroker在自主Agent第一次模型决策前提供轻量候选与权威结构，记录retrieval-bootstrap事件。
- Task模型、规则入口、CLI search、进程内search_business与原MCP search接到同一候选服务。
- 新增进程内resolve_semantics工具与CLI resolve-semantics，默认不扫描全部枚举。
- 每次服务端plan重新解析权威语义；计划及执行回执保存Registry、资产、release和权限绑定。
- 旧索引版本、篡改公式、越权元数据、显式ID替换和未明确歧义保持停止/澄清。
- 原Workflow、自主选工具、Multi Plan、多事实编译、只读Worker、预算及重试机制保留。

## 实际验证

|验证|结果|
|---|---|
|完整工程回归|184 passed，286.13秒|
|本阶段新增专项|14项|
|真实数据演示|模拟模型读取首次检索上下文选择客单价，实际查询一次|
|raw独立回算|88.22046842854883，结果一致|
|销售额歧义|CLARIFY，查询次数0|
|重复检索缓存|相同服务索引构建1次；资产变更测试验证重建与旧版本失效|
|结构发现CLI|每单商品件数组件解析正常，默认未加载枚举|
|检索CLI|改写问题返回average_order_value@1词法候选|

来源：[真实回执](retrieval-phase1-live-demo.json)、[使用与调用链](retrieval-phase1-guide.md)。JUnit原始回执保留本机且不提交Git。

## 等待后续阶段

Dense/Embedding、RRF、Cross-Encoder、高频IR模板缓存、持久/分布式索引与大规模增量发布尚未实现。没有真实模型规划准确率验收，也没有十万指标性能或企业权限能力声明。

缓存是内存词法缓存，评分仍遍历语料；结构化关系只是注册的合法规则，不开放任意事实Join。首次bootstrap与自主补充检索分开计数，尚无所有元数据扫描统一预算。新检索资产绑定会使升级前旧会话停止，需新建会话。
