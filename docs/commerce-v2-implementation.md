# 本地数据融合：第一批可运行实现

以 TheLook 的订单、用户、商品明细及已验证事实表为依据，增加口径，不增加伪造金融数据。语义版本 commerce-v2，共12个指标；原6个定义保持不变。

## 新增口径

| 指标 | ID | 计算 |
|---|---|---|
| 完成订单数 | complete_order_count@1 | 当前订单状态为 Complete 的订单数 |
| 订单完成占比 | complete_order_rate@1 | 完成订单数 / 全部订单数 |
| 取消订单数 | cancelled_order_count@1 | 当前订单状态为 Cancelled 的订单数 |
| 订单取消占比 | cancelled_order_rate@1 | 取消订单数 / 全部订单数 |
| 退货订单数 | returned_order_count@1 | 当前订单状态为 Returned 的订单数 |
| 订单退货占比 | returned_order_rate@1 | 退货订单数 / 全部订单数 |

所有新增指标按 UTC 下单日的闭开窗口取 cohort，粒度为 order_id，订单状态取本次快照。不等于支付成功率、访问转化率、历史当天状态、实际退款金额或成熟订单最终退货率。定义由本地学习项目制定，未获得真实业务Owner审核。

占比以同窗口、同用户过滤聚合后的分子/分母计算，零分母返回 null。占比指标禁止按 order_status 过滤或分组，否则可能得到被状态条件扭曲的分母。允许 country/gender/age_band/traffic_source 与 day 分组。计数仍允许合法订单状态维度。

## 真实调用关系

```mermaid
flowchart LR
    NL[Natural Language] --> K[Lexical Knowledge Retrieval]
    K --> R[Authoritative Metric and Catalog Resolution]
    R --> L[OpenAI Task Interpretation]
    L --> V[Task / Query Validation]
    V --> C[Typed RetrievalContext]
    C --> W[Query or Diagnosis Workflow]
    W --> P[Deterministic SQLCompiler]
    P --> D[Immutable DuckDB Release]
    D --> E[Evidence and Limitations]
```

检索返回业务候选，结构化解析重新读取授权指标定义和目录证据，两个来源在 RetrievalContext 中分开保存；权威来源冲突时停止。明确指标的模型请求也接收权威上下文。没有词法候选时并未实现通用向量发现，仍依靠有限候选检索和任务校验。

KnowledgeRetriever 的规则检索尚未扩展到任意复杂自然语言；男性等值在模型路径由业务词典映射成 M。模型提出任务，本地生成实际SQL。新增 conditional_count AST；没有自由SQL或临时Join入口。

异常诊断新增按指标声明的 additive/ratio 家族路由。占比诊断读取两个比例、两个分子和两个分母，共6次查询，验证恒等关系并输出代数贡献，不平均各组占比。新快照状态指标明确保留 cohort 成熟度未验证；可信完整性水位仍缺失，因此不能确认因果根因。比例维度贡献下钻尚未实现，结果显式列为未解决项。

## 验证与使用

新增10项测试涵盖6指标男性过滤源表对账、状态维度拒绝、空窗口null、权威上下文与冲突停止、比例诊断贡献对账。独立基线使用 raw.orders 与 raw.users，明确UTC日期，避免本机时区偏差。

真实模型已执行“2026年9月男性订单完成占比是多少”，返回 COMPLETE，gender=M，比例0.2480202724105163，即24.80%。最终版本已重新进行真实调用，确认注入1份权威结构化上下文并成功执行；完整记录见 commerce-v2-live-query.json。

```powershell
.\scripts\start-openai.ps1 -Question '2026年9月男性订单完成占比是多少'
```

没有默认猜测比较基准。问“为什么下降”必须提供等时长、不重叠的当前/对照窗口；不支持的金融支付口径继续澄清，不能自动替换成订单完成占比。

## 下一批仍待实现

版本化 Skill Registry、可恢复Session与预算总账、真实模型难例评测、通用维度值注册/未命中澄清、比例维度构成分析、可信水位/状态历史。向量检索与金融数据接入不是本批前提；现有本地能力也不能称为已完成企业级生产治理。
