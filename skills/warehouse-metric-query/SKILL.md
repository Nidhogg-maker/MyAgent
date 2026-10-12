---
name: warehouse-metric-query
description: 按已定义指标、时间窗口、维度及筛选执行本地语义查询，适用于多少或按维度统计的问题。
---

# 指标查询

先确定唯一metric_id和UTC闭开窗口。歧义词或缺少日期先澄清；当前Task与上轮Task分开，追问只能继承用户未改动的口径和过滤。

读取 [指标规则](../warehouse-anomaly-attribution/references/metric-rules.md)，解析每个过滤值到实际枚举。非法维度不能通过Join补救；不把零分母改为0，不把未知值执行成零结果。

调用 plan_query → execute_query，禁止自由SQL。按照 [工具契约](../warehouse-anomaly-attribution/references/tool-contracts.md) 处理瞬时错误、停止原因和熔断。返回数值、口径、单位、UTC窗口、release与质量限制，不能只说“查询成功”。
