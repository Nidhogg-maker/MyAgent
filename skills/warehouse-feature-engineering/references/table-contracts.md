# 表契约与口径

| 层 | 表 | 粒度 | 口径 |
|---|---|---|---|
| DWD | dwd_behavior_event | event_id | 保留匿名与异常标记，不包含直接身份字段 |
| DWD | dwd_product_view | event_id | 合法商品 URI 浏览，不是 CTR 点击 |
| DWD | dwd_order_item | order_item_id | 下单商品事实；当前状态仅明细保留，不入历史统计 |
| DWS | dws_user_behavior_day | UTC日期 × user_id | 登录用户行为及下单量；两分支先聚合再关联 |
| DWS | dws_product_behavior_day | UTC日期 × product_id | 浏览含匿名；下单数量与金额独立聚合 |
| ADS | ads_user_profile_daily | as_of_date × user_id | 截止日期前已注册用户，7/30天浏览、30天下单与最近下单 |
| ADS | ads_product_profile_daily | as_of_date × product_id | 当前商品目录全集；历史可售性未知，7/30天行为统计 |
| DWS | dws_user_product_day | 日期 × user_id × product_id | 登录浏览与下单先聚合再关联 |
| ADS | ads_user_product_features | as_of_date × user_id × product_id | 仅已有交互对；7/30天浏览与下单特征 |
| DWS | dws_session_behavior | as_of_date × session_id | 跨日会话观察；purchase不代表支付，缺purchase不代表负例 |

窗口为 [as_of-N天, as_of)，UTC。事件和订单商品可用时间均必须早于截止。
没有状态历史、生产完整性水位、真实过去 ingested_at；不宣称生产 PIT 认证。
源采集为顺序读表，不是跨表原子快照；引用与金额对账通过也不能证明完整性。
当前 user/product 属性不作为历史特征；商品候选全集来自当前快照。
cart/purchase 事件没有商品订单唯一关联，不参与商品购买数；商品购买数来自 order_items。
下单金额为所有状态订单商品金额，不是实收收入。取消订单仍属曾下单。
用户日订单数允许跨天求和（每订单只有一个下单日）；不同商品上的订单数不能求和成总体订单数。
每日登录浏览用户数不跨天加总成月UV。匿名量单列，不把 session_id 冒充 user_id。
全量构建按当前单个截止日发布，active 中不累积历史画像；多日期保留在不同 release。
