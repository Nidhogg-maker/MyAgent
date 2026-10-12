# 双路 RAG 第二阶段完成记录

## 已完成

1. 新增 `EmbeddingProvider` 和独立 CPU 编码 worker，使用真实 multilingual-e5-small。模型 commit、文件 SHA256、依赖版本与编码参数绑定到索引。
2. 从同一 Registry / 业务案例 / Skill 参考文件派生 21 份资产；没有创建第二套指标公式，也不枚举所有维度组合。
3. `DenseIndex` 读取不可变快照，校验来源版本、内容摘要与向量形状；在线授权集合过滤在 Dense top-k 之前。
4. BM25-style 与 Dense 分别取前 10，按稳定资产 ID 去重，再通过 RRF(k=60) 融合取前 6。回执保留原名次和分数，不标注为概率。
5. 结果接入 QueryContextBroker、TaskInterpreter、AgentLoop 首次决策和原搜索工具；StructuredResolver 继续解析权威定义、粒度、公共维度与关系约束。
6. 索引最后原子发布 active；失败保留旧 active。会话绑定检索模式、active 摘要与算法；运行中切换索引停止，旧会话不能跨索引恢复。
7. 默认真实 Agent 启动脚本使用 hybrid；可选择 hybrid-required 强制验收或 lexical。普通 hybrid 明确记录降级，不把词法当作向量结果。

## 本机真实链路证据

`scripts/retrieval-phase2-demo.py` 使用真实 CPU 神经向量、真实 TheLook 和模拟决策模型。没有调用付费 LLM，没有测量真实模型理解准确率。

输入：`2026年9月平均每张订单的金额是多少`。

执行过程：融合检索得到候选 → 首次模型上下文包含真实 Dense/RRF trace → 模拟模型从 Structured Context 的 `source_amount/order` 单位选择指标 → `run_query` → 语义校验 → DuckDB Worker → 回执。

结果：`88.22046842854883`。另外用 raw.order_items 金额 / raw.orders 数量独立计算，同样为 `88.22046842854883`，误差小于 1e-9。这里是平均下单金额，不是实收/支付指标。

最终索引为 384 维、21 份资产；manifest format=2，固定模型 revision 为 `614241f622f53c4eeff9890bdc4f31cfecc418b3`。完整名次、原分数、版本、Agent 回执及对账见 [真实演示记录](retrieval-phase2-live-demo.json)。

“销售额”仍返回 CLARIFY，说明融合排名不会消除业务口径歧义。没有据此宣称向量检索优于词法：演示证明实际接入、执行与对账，不证明泛化准确率。

## 工程验证

专项检查覆盖：真实接口进入 Broker、稳定 ID 与排名去重、共享索引的受限主体召回与维度遮盖、无权发布、非法向量、损坏摘要、过期版本、失败发布保留旧 active、缺索引降级/强制停止、搜索预算、检索中索引切换停止、会话绑定变化、歧义继续澄清。

新增 14 项第二阶段检查，第一/二阶段合计 28 项专项检查通过。最终完整回归为 197 passed / 1 failed（279.50 秒）；失败的是原有 14 查询异常分析测试，运行记录显示 `Skill deadline exceeded`，Skill 实际耗时 61.422 秒，超过既有 60 秒上限。未修改或放宽超时配置，单独重跑该项为 1 passed（62.35 秒，含 fixture 发布），因此 198 项用例均已验证通过，但最终全量运行没有一次全绿，保留这项时延敏感性记录。较早一轮完整回归的 195 项也全部通过；不要把重叠运行相加。这些工程测试不代表模型准确率。

Python 编译检查、PowerShell 启动脚本语法检查及 Git diff 空白检查通过；隔离依赖环境 `pip check` 通过。

## 当前状态与下一步

当前已具备：语义资产发现 → 真实本地混合召回 → 权威结构解析 → Agent 自主选择 → 受控编译执行 → 证据回执。指标口径、日期和多事实 Join 的原有约束继续生效。

暂未实现 Cross-Encoder、高频语义 IR 模板缓存、ANN、增量索引重建、常驻 embedding worker 或真实 LLM 准确率评测。当前少量资产使用 JSON 和线性精确扫描，子进程加载模型延迟明显，不能当作生产百万指标吞吐验收。

下一阶段优先减少重复模型加载，然后按需增加重排/IR 模板缓存。重排不能替代歧义澄清，模板缓存必须绑定语义/策略版本；实际数据结果缓存还要绑定 release。用户尚未要求开始第三阶段。

操作与调用逻辑见 [第二阶段使用指南](retrieval-phase2-guide.md)。源码与依赖锁可以上传，模型/向量/运行会话保留在本机，Git 忽略。
