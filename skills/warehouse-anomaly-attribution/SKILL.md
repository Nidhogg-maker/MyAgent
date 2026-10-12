---
name: warehouse-anomaly-attribution
description: 对本地订单指标异动进行窗口比较、分子分母拆解、维度验证和证据报告；适用于为什么下降或上升的分析请求。
---

# 数仓指标异动分析

目标是解释已验证的指标变化及证据边界。使用 commerce-v2 的权威指标，不创建临时公式，不把订单状态当作支付结果。

## 执行顺序

1. 明确 metric_id、当前/对照窗口和筛选。缺少基准先澄清；两个窗口须等时长、不重叠，日期是 UTC 闭开区间。
2. 读取指标定义、允许维度与质量上下文。使用 [指标规则](references/metric-rules.md) 判断 grain、非可加性及状态观察限制。
3. 调用 comparison，先验证用户声称的变化方向。方向不成立则返回前提反证，结束归因。
4. 金额拆订单量与客单价，比例拆分子与分母；根据 [归因方法](references/attribution-methods.md) 选择可对账的贡献公式。
5. 最多选择两个合法维度调用 drilldown。检查分组是否截断/抑制，分子分母是否与整体对账。不完整则保留证据并停止。
6. 调用 quality-check，检查实际 dbt 质量、覆盖水位和下单 cohort 成熟度。用 [工具契约](references/tool-contracts.md) 的错误分类判断是否可重试；口径、权限、数据不完整不靠重试修复。
7. 调用 evidence-report，按 [报告模板](assets/report-template.md) 返回变化、贡献、质量、假设与未解决项。

## 停止边界

预算或截止时间耗尽、分母为零、维度不兼容、口径冲突、贡献不能对账、工具熔断时停止。保留已执行查询ID和release，不用未经验证的根因填补报告。数值贡献不是因果证明；业务事件与完整性证据不足时返回 INSUFFICIENT_EVIDENCE。

该Skill由本地 SkillExecutor 调用确定性代码。MCP接口说明用于理解工具边界，不要求启动远程MCP服务。
