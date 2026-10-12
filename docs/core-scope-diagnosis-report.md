# 指标异动证据报告

## 问题与口径
complete_order_rate@1

同UTC下单日窗口及用户筛选内，本次快照Complete订单数/全部状态订单数；零分母null；不是支付成功率、历史完成率或成熟 cohort 估计
当前：UTC [2026-09-01, 2026-09-08)；筛选 {"gender": "M"}

对照：UTC [2026-08-01, 2026-08-08)；筛选 {"gender": "M"}

## 已验证变化
{"baseline": 0.24825174825174826, "current": 0.264919941775837, "delta": 0.016668193524088742, "relative_change": 0.06714230067449832}

占比差：1.6668 个百分点。

## 贡献与下钻
{"kind": "ratio-algebraic", "numerator_contribution": 0.06407711647886322, "denominator_contribution": -0.047408922954774474, "residual": 0.0, "causal": false}

{"kind": "weighted-ratio-group-contribution", "dimension": "traffic_source", "residual": 1.3877787807814457e-17, "causal": false, "evidence_indexes": [6, 7, 8, 9]}

贡献最大的前10组：[{"group": "Facebook", "baseline_numerator": 4.0, "current_numerator": 24.0, "baseline_denominator": 19.0, "current_denominator": 56.0, "contribution": 0.027941490823586893}, {"group": "Organic", "baseline_numerator": 29.0, "current_numerator": 17.0, "baseline_denominator": 107.0, "current_denominator": 102.0, "contribution": -0.025954031412546694}, {"group": "Search", "baseline_numerator": 94.0, "current_numerator": 120.0, "baseline_denominator": 388.0, "current_denominator": 467.0, "contribution": 0.010336824747305101}, {"group": "Email", "baseline_numerator": 11.0, "current_numerator": 16.0, "baseline_denominator": 36.0, "current_denominator": 35.0, "contribution": 0.00405889598029336}, {"group": "Display", "baseline_numerator": 4.0, "current_numerator": 5.0, "baseline_denominator": 22.0, "current_denominator": 27.0, "contribution": 0.0002850133854500666}]

{"kind": "weighted-ratio-group-contribution", "dimension": "country", "residual": 3.469446951953614e-17, "causal": false, "evidence_indexes": [10, 11, 12, 13]}

贡献最大的前10组：[{"group": "Brasil", "baseline_numerator": 20.0, "current_numerator": 35.0, "baseline_denominator": 74.0, "current_denominator": 101.0, "contribution": 0.01598110768416445}, {"group": "United States", "baseline_numerator": 41.0, "current_numerator": 39.0, "baseline_denominator": 142.0, "current_denominator": 158.0, "contribution": -0.014909762726356614}, {"group": "South Korea", "baseline_numerator": 4.0, "current_numerator": 15.0, "baseline_denominator": 21.0, "current_denominator": 34.0, "contribution": 0.014841054142364186}, {"group": "France", "baseline_numerator": 2.0, "current_numerator": 6.0, "baseline_denominator": 24.0, "current_denominator": 34.0, "contribution": 0.005237120957644975}, {"group": "China", "baseline_numerator": 52.0, "current_numerator": 59.0, "baseline_denominator": 207.0, "current_denominator": 230.0, "contribution": -0.005028450443297611}, {"group": "Germany", "baseline_numerator": 3.0, "current_numerator": 6.0, "baseline_denominator": 32.0, "current_denominator": 25.0, "contribution": 0.003488869209393226}, {"group": "United Kingdom", "baseline_numerator": 8.0, "current_numerator": 8.0, "baseline_denominator": 23.0, "current_denominator": 30.0, "contribution": -0.00234118138048269}, {"group": "Belgium", "baseline_numerator": 3.0, "current_numerator": 2.0, "baseline_denominator": 7.0, "current_denominator": 10.0, "contribution": -0.002333547093372421}, {"group": "Japan", "baseline_numerator": 5.0, "current_numerator": 7.0, "baseline_denominator": 12.0, "current_denominator": 25.0, "contribution": 0.0014479697885811417}, {"group": "Spain", "baseline_numerator": 4.0, "current_numerator": 5.0, "baseline_denominator": 16.0, "current_denominator": 26.0, "contribution": 0.0002850133854500666}]

## 数据质量与观察条件
{"quality": {"release_id": "b11159a997c146aab8ec27814c00835d", "status": "PASS", "checks": ["test.thelook_lab.not_null_dim_products_product_id.c8aba288d1", "test.thelook_lab.unique_dim_products_product_id.ef7b2a9985", "test.thelook_lab.not_null_dim_users_user_id.e754bb5812", "test.thelook_lab.relationships", "test.thelook_lab.unique_dim_users_user_id.bcdc17b9f9", "test.thelook_lab.not_null_fct_order_items_order_item_id.dbaab21f55", "test.thelook_lab.unique_fct_order_items_order_item_id.0dec5f6768", "test.thelook_lab.not_null_fct_orders_order_id.4e687af8d0", "test.thelook_lab.reconciliation", "test.thelook_lab.status_and_item_count", "test.thelook_lab.unique_fct_orders_order_id.523ddb6ce5"], "scope": "snapshot dbt checks rerun locally; no funnel/temporal completeness claim", "verified_at": "2026-10-11T12:12:53.968754+00:00"}, "temporal": {"mode": "snapshot-observation", "observed_at": "2026-10-11T10:19:14.558627+00:00", "complete_through": null, "verified": false, "reason": "No producer completeness attestation; source maximum timestamp is not a watermark"}, "release_id": "b11159a997c146aab8ec27814c00835d", "causal_claim": false, "semantic_version": "f745c25e28c92c65b5a63510e20eee166a11baa64b0d5a0c769c42f84be10246", "cohort_observation": {"age_ranges": {"current": {"youngest_order_age_days": 34, "oldest_order_age_days": 40}, "baseline": {"youngest_order_age_days": 65, "oldest_order_age_days": 71}}, "historical_status_verified": false, "maturity_required": true, "maturity_verified": false, "note": "订单年龄是快照观察条件；没有历史状态/成熟度标准，不据此确认业务原因"}}

## 假设与反证
[{"id": "user-premise", "status": "SUPPORTED_OBSERVATION", "evidence_indexes": [0, 1]}, {"id": "data-completeness", "status": "UNVERIFIED", "evidence": {"mode": "snapshot-observation", "observed_at": "2026-10-11T10:19:14.558627+00:00", "complete_through": null, "verified": false, "reason": "No producer completeness attestation; source maximum timestamp is not a watermark"}, "note": "缺完整性水位不能排除迟到/数据未到齐"}, {"id": "ratio-components", "status": "VALIDATED_IDENTITY", "evidence_indexes": [0, 1, 2, 3, 4, 5]}]

## 结论与未解决项
已验证数值与代数贡献；缺少独立业务事件/完整性反证，不能确认因果根因
["no_independent_business_event_evidence", "snapshot_status_cohort_maturity_unverified", "completeness_unverified"]

## 查询证据
- plan_id=885d8620fa2544e58b5de6b224334cc6；release=b11159a997c146aab8ec27814c00835d
- plan_id=c04342d84d3946a09a3bd179fe3a579d；release=b11159a997c146aab8ec27814c00835d
- plan_id=d3922c07661a4d83905522a1371a3a67；release=b11159a997c146aab8ec27814c00835d
- plan_id=d4883f20f599455a94cfa6930de8b7fe；release=b11159a997c146aab8ec27814c00835d
- plan_id=7c8bc658b6b744e096195abb2458069c；release=b11159a997c146aab8ec27814c00835d
- plan_id=5950aadc532e44ac9a5d68159a722097；release=b11159a997c146aab8ec27814c00835d
- plan_id=c6f70438e8504c5a82507e573504b6db；release=b11159a997c146aab8ec27814c00835d
- plan_id=a4456805c7b646e2a743516ddd0e1031；release=b11159a997c146aab8ec27814c00835d
- plan_id=e23eedb9fad4411abd698f4c2273dda4；release=b11159a997c146aab8ec27814c00835d
- plan_id=9a2f7bd7ed45424a885478b8b97dde68；release=b11159a997c146aab8ec27814c00835d
- plan_id=7b4ecb154dbf4fb883f9ebee69c36037；release=b11159a997c146aab8ec27814c00835d
- plan_id=949272144e314caab9ca0fa69442baa2；release=b11159a997c146aab8ec27814c00835d
- plan_id=d034230cc79846fe8abde217c5f1816e；release=b11159a997c146aab8ec27814c00835d
- plan_id=8d897348d7bf4ee0834044f72560cd23；release=b11159a997c146aab8ec27814c00835d
