---
name: warehouse-profile-query
description: 按明确日期读取用户商品画像、交互特征与会话证据。
---

# 画像与会话数据产品查询

输入：user_profile、product_profile、user_product 或 session，明确 UTC 截止日期及实体标识。
契约说明可使用 describe；不接受 SQL、表名、自由字段或自报身份。

执行：验证请求 → 选择该日期成功发布版本 → 验证数据库、契约和血缘 hash → 参数化只读查询 → 输出特征与证据。
资源和结构化输入由注册 SkillExecutor 实际加载校验。统一 ask/chat 按有限规则路由，画像路径不额外调用模型。

停止或澄清：缺日期或ID、日期无版本、数据产品未构建、版本被改动、复合粒度违规、超时、身份不允许。
返回不存在实体时不能伪造零特征。用户商品仅覆盖已有交互，不把未出现的商品作为负例。
会话没观察到 purchase 只能标未知；不能推断订单、支付成功或已结束。
只开放本地管理主体；受限聚合主体不会因此获得用户级读取权限。

详细语义见 [查询契约](references/query-contracts.md)。
