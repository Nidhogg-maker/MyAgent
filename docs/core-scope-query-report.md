# 指标查询证据报告

## 问题与口径
complete_order_rate@1

同UTC下单日窗口及用户筛选内，本次快照Complete订单数/全部状态订单数；零分母null；不是支付成功率、历史完成率或成熟 cohort 估计
当前：UTC [2026-09-01, 2026-10-01)；筛选 {"country": "United States", "gender": "M"}

## 已验证变化
列：["value"]

结果：[[0.24066390041493776]]

## 贡献与下钻
本次无分解结果

## 数据质量与观察条件
{"quality": {"dbt_tests_passed": 11, "scope": "grain, relationships, statuses and amounts; not full temporal/funnel completeness"}, "temporal": {"mode": "snapshot-observation", "observed_at": "2026-10-11T10:19:14.558627+00:00", "complete_through": null, "verified": false, "reason": "No producer completeness attestation; source maximum timestamp is not a watermark"}}

## 假设与反证
[]

## 结论与未解决项
已执行指定口径，只报告观察结果；不确认因果原因
["Synthetic source", "Current dimension/status snapshot; no historical SCD2", "No verified coverage watermark; no causal attribution"]

## 查询证据
- plan_id=89c3f52e7b74426188c95d89ea57b1e6；release=b11159a997c146aab8ec27814c00835d
