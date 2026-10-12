# 画像查询与交互会话主题表

本次只完成画像查询接入和交互/会话表，不实现生产增量、迟到修正或补数。

## 统一使用入口

在 MyAgent 根目录：

```powershell
.\.venv\Scripts\python.exe -m local_agent.cli ask "查看用户76706截至2026-10-11的画像"
.\.venv\Scripts\python.exe -m local_agent.cli ask "查看商品23546截至2026-10-11的画像"
.\.venv\Scripts\python.exe -m local_agent.cli ask "查看用户76706和商品23546截至2026-10-11的交互特征"
.\.venv\Scripts\python.exe -m local_agent.cli ask "说明截至2026-10-11的用户画像字段"
.\.venv\Scripts\python.exe -m local_agent.cli chat
```

日期必须包括年份。缺日期或实体 ID 时进入 CLARIFY，回复完整日期或 ID 后通过字段补丁继续，不能自动换成最新日期。
会话请求使用真实 session_id；示例和真实执行结果在 `feature-phase2-live-demo.json`。

结构化入口：

```powershell
.\.venv\Scripts\python.exe -m local_agent.cli profile --product user_profile --user-id 76706 --as-of 2026-10-11
.\.venv\Scripts\python.exe -m local_agent.cli profile --product user_product --user-id 76706 --product-id 23546 --as-of 2026-10-11
.\.venv\Scripts\python.exe -m local_agent.cli profile --product product_profile --as-of 2026-10-11 --describe
```

持续聊天保留 /show、/resume、/cancel、/new。画像会话使用 feature- 前缀，保存到独立 feature-sessions.sqlite；指标会话仍走原 HarnessRuntime。
画像路径是有限规则解析，即使整体 intent-mode=llm，也不会为这些明确画像请求额外调用模型。当前不支持任意改写、画像排名、比较或自由 SQL。

## 调用链

```text
ask / chat / profile
  -> UnifiedRuntime
       |-- 指标任务 -> 原 HarnessRuntime -> 原查询/诊断图
       `-- 画像任务 -> FeatureRuntime
             -> FeatureRequest 校验或澄清
             -> 指定日期成功 release（不依赖指标质量有效期）
             -> profile-query 注册 Skill
             -> FeatureTools：库/契约/血缘 hash 验证
             -> 固定 SELECT + 绑定实体参数
             -> 只读、禁外部访问、限资源 Worker
             -> 特征 + 日期 + 版本 + 质量 + 血缘
             -> 会话回执与观察记录
```

读取不存在实体时返回 found=false，不能制造零特征。受限聚合凭证不能绕过原行范围去读取用户级画像；当前只向本地管理主体开放这类数据产品。

## 工具与 Skill

新增注册 `profile-query` Skill，加载目录入口和查询参考；现有查询、比较、诊断等六项能力仍保留。
本地 MCP 新增：get_user_profile、get_product_profile、get_user_product_features、get_session_profile、describe_data_product。当前共13个协议工具。
主 Workflow 仍是进程内领域调用；脚本中的 MCP 验证是真实 stdio 调用，不把两者混为一谈。

## 第二阶段三张新表

| 表 | 粒度 | 内容与边界 |
|---|---|---|
| dws.dws_user_product_day | 日期 × 用户 × 商品 | 登录浏览和订单商品分别预聚合后关联，匿名浏览不分配给用户 |
| ads.ads_user_product_features | 截止日期 × 用户 × 商品 | 已观察交互对的7/30天浏览、30天下单量和金额、最近交互间隔；不是全量笛卡尔积 |
| dws.dws_session_behavior | 截止日期 × session_id | 跨日会话整体观察、首末时间、事件数、浏览、加购、purchase与身份状态 |

用户商品没有记录不是负例。会话观察到 purchase 标为 OBSERVED_PURCHASE_EVENT；未观察到则标 UNKNOWN_NOT_VERIFIED_NEGATIVE。
所有会话都明确 session_closure_verified=false、order_attribution_verified=false、payment_success_verified=false。
会话观察时长不是经过验证的完整会话时长；没有水位，不推断已经结束或已经未转化。

## 构建与验证

```powershell
.\scripts\build-feature-mart.ps1 -AsOf 2026-10-11 -VerifyRepeat
.\.venv\Scripts\python.exe scripts/feature-query-demo.py
```

构建仍然是独立候选库中的全量 dbt 加工。成功后切换 feature-mart/active.json；原 commerce 指标快照不重新发布。
新增 raw 独立对账包括：交互浏览与金额、全部交互对7/30天浏览和30天下单特征、全部会话的事件数及首末时间/purchase数。
同一截止日期重复全量替换的稳定性检查不等于增量与生产补数已经完成。

验收文件：feature-phase2-verification.json、feature-phase2-live-demo.json、feature-phase2-tests.xml、feature-phase2-regression.xml。
实际落表与最终状态见 [完成报告](feature-phase2-completion.md)。

## 当前边界

- 没有新增推荐模型、CTR曝光样本、支付CVR标签。
- 保持快照观察的时间限制，未认证历史真实可用性或生产完整性。
- 画像 Runtime 使用有界只读查询、会话和回执，不宣称分布式恢复或画像自动重试；Worker最长15秒。
- 全量重建仍保留，增量 MERGE、迟到修正和补数本次明确不做。
