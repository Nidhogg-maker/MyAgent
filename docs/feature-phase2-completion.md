# 第一与第二阶段完成报告

完成日期：2026-10-12。截止日期：UTC 2026-10-11 00:00。发布版本：`2026-10-11-7abc6af92efb`。

## 完成了什么

1. 统一 ask/chat 新增画像任务路由；原指标查询和异常分析仍交给原 HarnessRuntime。
2. profile-query Skill 实际注册，加载入口与参考文件，使用受限 FeatureRequest 和固定参数化 SELECT。
3. 用户画像、商品画像、用户商品交互、会话和契约说明共五类读取能力可用；结构化 CLI、自然语言与本地 MCP 均实际执行验证。
4. 新增用户商品日交互、用户商品特征及会话行为三张表，当前合计10张 DWD/DWS/ADS 表。
5. 指定日期版本不存在会澄清；不存在实体返回 found=false，不伪造零特征；读取包含版本、窗口、质量、字段及血缘。
6. 画像会话独立保存状态、输入、回执与事件；缺字段后回复可继续；查询版本被篡改停止。

## 实际落表

| 表 | 行数 | 粒度 |
|---|---:|---|
| dwd.dwd_behavior_event | 2430702 | event_id |
| dwd.dwd_product_view | 845586 | event_id |
| dwd.dwd_order_item | 181946 | order_item_id |
| dws.dws_user_behavior_day | 196306 | activity_date, user_id |
| dws.dws_product_behavior_day | 693193 | activity_date, product_id |
| ads.ads_user_profile_daily | 100000 | as_of_date, user_id |
| ads.ads_product_profile_daily | 29120 | as_of_date, product_id |
| dws.dws_user_product_day | 196598 | activity_date, user_id, product_id |
| ads.ads_user_product_features | 181909 | as_of_date, user_id, product_id |
| dws.dws_session_behavior | 681937 | as_of_date, session_id |

用户商品特征只覆盖已观察交互对，没有构造用户商品笛卡尔积。匿名浏览保留在商品主题，不伪造用户归属。
会话按 session_id 跨日组织；未出现 purchase 标为 UNKNOWN_NOT_VERIFIED_NEGATIVE，不能当训练负例。出现 purchase 也不代表订单归属或支付成功，完整会话结束仍未验证。

## 验证结果

- 两次全量 dbt 构建：每次10个模型、23项数据检查，全部通过。
- 48项独立对账通过，覆盖原始计数金额、全部交互特征和会话事件数/首末时间/purchase数。
- 同截止日重复构建：10张表的行数、双内容摘要稳定，并再次独立对账。
- 包含原有指标查询、Skill、运行管理的相关回归57项通过；随后增加缓存恢复完整性保护，14项专项工程测试再次通过。两组存在重叠，不相加成独立总数。
- 真实数据的5类自然语言请求全部成功；结构化用户画像与自然语言结果相同。
- 真实本地 MCP stdio 发现13个工具，get_user_profile 结果与进程内查询一致。
- 原始库 hash 未变化；当前发布库、元数据及表契约 hash 验证通过。没有重新发布原 commerce 指标快照。
- 本轮画像理解使用有限规则，没有额外请求真实模型，不是模型准确率评测。

## 当前状态

第一、第二阶段核心链路已完成：全量加工发布 → 指定版本读取 → 自然语言或结构化入口 → 注册 Skill → 有证据的结果。
画像服务独立于原指标快照的有效期，不会因为读取画像重新发布指标库。
受限聚合令牌不获得用户级画像权限；当前仅本地管理主体可读取画像。没有新增企业权限平台。

## 未做的范围

按本次要求，不做增量 MERGE、迟到修正、生产补数、调度或并行构建锁。现有同日期全量重建稳定性不等于上述能力。
不训练推荐算法，不制造CTR曝光或支付CVR标签；历史真实摄入时间、生产水位和商品历史可售性依然未验证。
不支持画像任意排名/比较、任意改写或自由SQL；画像 Worker 有15秒上限，没有画像自动重试或分布式恢复承诺。

## 使用

```powershell
.\.venv\Scripts\python.exe -m local_agent.cli ask "查看用户76706截至2026-10-11的画像"
.\.venv\Scripts\python.exe -m local_agent.cli ask "查看用户76706和商品23546截至2026-10-11的交互特征"
.\.venv\Scripts\python.exe -m local_agent.cli chat
```

[详细使用说明](feature-phase2-guide.md)

[实际验收记录](feature-phase2-verification.json) · [真实查询与MCP记录](feature-phase2-live-demo.json) · [相关回归记录](feature-phase2-regression.xml)

核心入口：`src/local_agent/feature_agent.py`、`feature_pipeline.py`、`warehouse-features/models`、`skills/warehouse-profile-query/SKILL.md`。
