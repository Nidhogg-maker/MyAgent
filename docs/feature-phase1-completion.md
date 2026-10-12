# 第一阶段闭环完成报告

完成日期：2026-10-12；数据截止：UTC 2026-10-11 00:00，使用源采集结束时间 2026-10-11T10:19:14.558627+00:00。

## 已完成

实际执行了独立 DWD → DWS → ADS 构建，发布版本 `2026-10-11-c7df9c34302a`。原始数据文件 hash 未变化，现有 Agent 的 commerce 查询快照未重新发布。

| 表 | 实际行数 | 主键粒度 |
|---|---:|---|
| dwd.dwd_behavior_event | 2430702 | event_id |
| dwd.dwd_product_view | 845586 | event_id |
| dwd.dwd_order_item | 181946 | order_item_id |
| dws.dws_user_behavior_day | 196306 | activity_date, user_id |
| dws.dws_product_behavior_day | 693193 | activity_date, product_id |
| ads.ads_user_profile_daily | 100000 | as_of_date, user_id |
| ads.ads_product_profile_daily | 29120 | as_of_date, product_id |

用户画像包含 7/30天商品浏览、30天加购事件、下单订单数、订单商品量、下单金额及最近下单间隔。
商品画像包含 7/30天浏览、30天匿名浏览、下单商品量及金额。
最终状态不作为历史特征，用户当前属性不进入历史画像；商品当前全集的历史可售性明确未验证。

## 验收证据

- 两次 dbt 构建都完成 7 个模型、16 项测试，0 失败。
- 35 项独立检查通过：主键、复合粒度、截止窗口、raw计数及金额、全部用户商品特征真值、最近下单与间隔。
- 同一截止日期全量重建两次，七张表行数及两种内容摘要一致，重新对账通过。
- 5 项保护性工程测试通过：越界截止、重复主键、空主键、内容变化检测及字段血缘。
- 技术血缘覆盖七张输出表，字段值依赖 77/87 项解析为有来源的结果；其余常量或未充分支持项仍标记不完整，整体不宣称完整血缘。
- 原库、发布库、元数据和契约 hash 检查通过。

质量观察：保留 1,124,193 条匿名事件；1,672 条晚于采集时点事件有标记；共 1,996 条事件不满足本次截止条件，未进入汇总。未知用户 0，商品浏览非法商品引用 0。

## 当前状态

第一阶段数据开发闭环已完成，本地可重新构建、验证与发布。生产完整性水位、历史真实摄入时间、属性有效时间和跨表原子快照未具备。
加工 Skill 是独立受控命令入口，尚未接入原查询 SkillRegistry 的自然语言路由。画像已落表，现有 Agent 尚未通过专用工具读取这些新表。

## 下一步

1. 增加只读用户/商品画像工具并接入 Agent，返回截止日期、窗口、契约、质量与血缘。
2. 扩展用户商品日交互和会话主题表，再做业务所需的特征交付。
3. 增加按日期增量与幂等补数、迟到修正及清晰的数据完成状态。
4. 最后才考虑自然语言触发受支持构建任务；不开放任意写表 SQL。

## 最终目标

业务方提出需求 → 澄清口径与粒度 → 受控 Skill 构建数据 → DWD/DWS/ADS 落表 → 质量对账 → 版本化发布 → 业务方/算法方/Agent 获取可追溯数据产品。
重点是数据开发和交付，不以训练推荐算法或制造真实 CTR 标签为目标。

## 文件和使用

- [运行与口径说明](feature-phase1-guide.md)
- [机器可读验收记录](feature-phase1-verification.json)
- [工程测试记录](feature-phase1-tests.xml)
- [加工 Skill](../skills/warehouse-feature-engineering/SKILL.md)
- [dbt 项目](../warehouse-features/dbt_project.yml)
- [独立执行器](../src/local_agent/feature_pipeline.py)

发布数据库：`C:\Users\Nidhog\OneDrive\Desktop\MyAgent\data\feature-mart\releases\2026-10-11-c7df9c34302a\features.duckdb`。
发布目录包含 release.json、quality.json、metadata.json、table-contracts.json、events.jsonl 与两次 dbt 编译和运行产物。

```powershell
.\scripts\build-feature-mart.ps1 -AsOf 2026-10-11 -VerifyRepeat
```
