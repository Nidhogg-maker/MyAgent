---
name: warehouse-dimension-drilldown
description: 对已确定指标进行合法维度下钻并保留完整性与贡献对账信息。
---

# 维度下钻

先读取指标允许维度；维度与grain不兼容时停止。维度值使用真实快照枚举，不能猜表名或Join。最多按Workflow选择的两个维度分别分析。

调用metric-query获得分组证据。检查截断和抑制；按 [归因方法](../warehouse-anomaly-attribution/references/attribution-methods.md) 汇总，比例用分子/总分母贡献。国家与渠道分别解释同一变化，不能跨维度再次求和。
