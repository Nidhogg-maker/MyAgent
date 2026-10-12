# 脚本入口

脚本分为日常使用、构建验收和历史阶段演示。它们不是三个互不相干的Agent版本。

|用途|脚本|
|---|---|
|安装Agent|bootstrap.ps1|
|采集TheLook|thelook_ingest.py|
|指标数仓构建/真实质量重验/发布|build-warehouse.ps1|
|十表特征产品|build-feature-mart.ps1|
|保存/读取本机模型凭据|configure-openai.ps1、openai-settings.ps1|
|模型Task Workflow入口|start-openai.ps1|
|模型自主工具选择入口|start-agent.ps1|
|本地向量/重排准备|prepare-embedding.py、prepare-reranker.py|
|统一语义索引构建|build-retrieval-index.py|
|完整本地核心场景|project-acceptance.py|
|真实检索与可选LLM验收|accept-retrieval-iteration.ps1、retrieval-iteration-acceptance.py|
|多事实独立对账|multi-plan-demo.py|
|画像/实际stdio MCP演示|feature-query-demo.py、mcp-local-demo.py|
|当前源码导航生成|generate-code-map.py|

embedding-worker/reranker-worker是内部隔离推理进程；不作为用户提问入口。demo/extensions/runtime/retrieval-phase*-demo/evaluate等为特定路径或历史阶段演示，查看对应文档后使用；部分会覆盖阶段回执。

build脚本执行真实写入，查询入口只读。质量凭证过期需真实重建，不改时间制造PASS。运行详细条件见 [安装文档](../docs/setup-and-dependencies.md)。
