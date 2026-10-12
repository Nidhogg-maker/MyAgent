---
name: warehouse-quality-check
description: 检查本地发布快照的质量证据、时间覆盖和当前状态观察限制，供查询或异动分析使用。
---

# 数据质量检查

读取真实release与目录质量，报告验证时间和检查范围；PASS不代表数据完全到齐。区分完整UTC日、源观察时间、生产方完整性水位和cohort成熟度。

订单状态只代表快照，比较订单年龄与成熟观察窗的缺口；缺少状态历史或可信水位时标记未验证，禁止声称已排除迟到数据。按 [指标规则](../warehouse-anomaly-attribution/references/metric-rules.md) 报告限制。
