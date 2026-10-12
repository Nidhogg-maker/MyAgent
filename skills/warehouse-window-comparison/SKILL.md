---
name: warehouse-window-comparison
description: 比较同口径、同筛选、等时长且不重叠的两个明确窗口，并检验用户的变化前提。
---

# 窗口比较

同metric_id、同分组与过滤才可比较；默认不选择基准。调用两次metric-query，保持同release与定义版本。先返回baseline/current/delta，分母为零或无数据保留null。

用户声称下降但实际没有下降时返回前提反证，停止归因。不将比较差值称为原因，遵守 [归因方法](../warehouse-anomaly-attribution/references/attribution-methods.md)。
