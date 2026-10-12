# 第一阶段电商主题数据加工与交付

本文保留第一阶段的七表交付说明。当前已扩展到第二阶段十表并接入画像查询，最新使用见 [第二阶段说明](feature-phase2-guide.md)。

## 做了什么

新增一个独立写入通道，将现有 TheLook raw 数据加工为 DWD、DWS、ADS 七张表。现有 Agent 的只读查询服务与 commerce 指标快照不改动；不训练推荐模型，不制造曝光或支付标签。

```text
data/thelook.duckdb 中的 raw 五表（只读）
  -> 复制到独立候选 features.duckdb
  -> dbt DWD 三张明细
  -> dbt DWS 两张日汇总
  -> dbt ADS 两张画像
  -> dbt 测试 + raw 独立重算 + 可选重建稳定性验证
  -> 输出契约、血缘、质量、日志
  -> 所有检查通过才更新 data/feature-mart/active.json
```

具体落表、行数、检查与发布路径见 [实际验收记录](feature-phase1-verification.json) 和 [完成报告](feature-phase1-completion.md)。

## 表与口径

| 表 | 粒度 | 内容 |
|---|---|---|
| dwd.dwd_behavior_event | event_id | 行为明细、匿名标记、来源时间、质量与可用性标记 |
| dwd.dwd_product_view | event_id | URI 匹配到合法商品的页面访问 |
| dwd.dwd_order_item | order_item_id | 下单商品、下单日与金额、引用检查 |
| dws.dws_user_behavior_day | 日期 × 用户 | 浏览、加购事件、purchase事件、下单量与金额 |
| dws.dws_product_behavior_day | 日期 × 商品 | 浏览含匿名、登录浏览用户数、下单商品量与金额 |
| ads.ads_user_profile_daily | 截止日期 × 用户 | 7/30天浏览、30天加购及下单统计、最近下单间隔 |
| ads.ads_product_profile_daily | 截止日期 × 商品 | 7/30天浏览、30天匿名浏览、下单商品量与金额 |

两条明细分支先按目标粒度聚合，再 FULL OUTER JOIN。没有把 events 和 order_items 直接多对多关联。
每日用户去重数不能相加成月 UV；不同商品上的订单数不能相加成总体订单数。订单商品金额不等于支付实收。

## 运行方式

在 MyAgent 根目录执行：

```powershell
.\scripts\build-feature-mart.ps1 -AsOf 2026-10-11 -VerifyRepeat
```

或者：

```powershell
.\.venv\Scripts\python.exe -m local_agent.feature_pipeline --as-of 2026-10-11 --verify-repeat
```

截止日期固定到 UTC 零点，窗口为 `[as_of-N天, as_of)`。当前源采集结束于 2026-10-11 10:19 UTC，因此本次使用 2026-10-11，不盲目按电脑当天构建未覆盖窗口。

每次生成独立 release。dbt 全量替换表，重复运行不向同表追加历史记录；历史版本通过不同 release 保留。active 只是最新成功版本指针。

## Skill 如何执行

`skills/warehouse-feature-engineering/SKILL.md` 定义输入、加工过程、停止条件与交付规范；`references/table-contracts.md` 定义业务口径。
`feature_pipeline.build` 实际读取两份资源并记录 hash，执行固定模型和质量验证，输出阶段日志。

这个构建 Skill 使用独立命令入口，没有加入旧查询 SkillRegistry 或自然语言路由。这样不会为了落表把 Agent 的只读查询能力放开为任意写入；自然语言触发受控构建与读取画像是下一阶段工作。

## 质量与血缘

- dbt：唯一性、非空、复合粒度、引用、金额有效性、截止时间与基础窗口关系。
- 独立对账：raw 的行为数、商品浏览数、订单商品数、订单数及 Decimal 金额与 DWS 对齐。
- 全量特征验证：从 raw 重新计算全部用户及商品的 7/30 天浏览、30 天订单商品金额与数量、用户最近下单与间隔，再与 ADS 逐条比较。
- 重建验证：同一候选库重新 dbt build，比较七张表的行数及两种交换性内容摘要，随后再次独立对账。
- 技术血缘：dbt manifest 输出表级依赖；SQLGlot 结合真实 schema 解析字段值来源，并单独记录控制依赖。
- 无法解析、常量字段、行计数依赖等不强行标记为完整；不是业务因果图。

每个成功目录包含 `release.json`、`quality.json`、`metadata.json`、`table-contracts.json`、`events.jsonl`、两次 dbt 的日志与 manifest/run_results。
数据库、元数据、表契约都有 hash。失败目录保留诊断，旧 active 不切换。

## 当前限制

- 源是一次公开合成数据快照，且采用顺序读表，不是跨表原子快照。
- 事件时间截止已落实，但过去真实摄入时间、水位、迟到记录和生产完整性未验证。
- 当前订单状态保留于 DWD，仅供观察，不进入历史统计特征。
- 用户画像未加入年龄、地区等未经历史版本验证的属性；商品画像使用当前商品全集，但标记历史可售性未验证。
- 匿名事件保留在行为和商品统计中，无法可靠识别的身份不补进用户画像。
- 无生产增量 MERGE、调度、并行构建锁、通用取消/恢复/重试；单次 dbt 最长300秒。
- 未生成用户商品笛卡尔积、CTR 样本或商品级 CVR 归属标签。

## 下一步和最终目标

下一步：增加只读画像查询工具并接入 Agent；新增用户商品日交互与会话主题表；再设计增量、迟到修正和按分区补数。

最终目标：业务需求经过澄清进入受控数据开发 Skill，形成有版本、有质量、有血缘、可补数的数据产品，交付推荐、转化分析或其他业务方。模型负责理解与选择受支持方案；确定性代码负责加工和发布，不替代指标权威或数据完整性证据。
