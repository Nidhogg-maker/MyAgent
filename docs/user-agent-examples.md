# 用户输入与 Agent 输出示例

以下分为“模拟交互说明”和“已有真实历史回执”。模拟段落解释状态逻辑，不声称每一句都刚执行；历史段落从已有文件提取，重新采集数据后不保证相同数值。实际 CLI 返回内容比示例更完整。

## 一、画像查询与澄清（模拟交互）

```text
用户：查看用户76706的画像
Agent：CLARIFY，请明确画像截止日期，例如截至2026-10-11。
用户：截至2026-10-11
Agent：保留 user_id=76706，补齐 as_of=2026-10-11，读取该日期成功发布版本。
       COMPLETE；返回画像、字段定义、质量、血缘和限制。
```

内部结构化请求：

```json
{
  "feature_input": {
    "kind": "profile",
    "data_product": "user_profile",
    "user_id": 76706,
    "as_of": "2026-10-11"
  }
}
```

调用逻辑：`UnifiedRuntime -> FeatureRuntime -> parse_feature_question / FeatureRequest -> profile-query -> FeatureTools.read_profile -> Worker`。在 chat 中回复日期可以继续；单独 ask 后可用返回的 session_id 执行 reply，不能另起一次 ask 就假设自动继承上下文。

```powershell
.\.venv\Scripts\python.exe -m local_agent.cli ask "查看用户76706的画像"
# 用上一条返回的 session_id 替换占位符
.\.venv\Scripts\python.exe -m local_agent.cli reply <session-id> "截至2026-10-11"
```

## 二、真实画像回执（截取）

来源：[feature-phase2-live-demo.json](feature-phase2-live-demo.json)，规则模式、没有模型调用。

```json
{
  "status": "COMPLETE",
  "feature_task": {
    "kind": "profile",
    "data_product": "user_profile",
    "as_of": "2026-10-11",
    "user_id": 76706,
    "product_id": null,
    "session_id": null
  },
  "feature_release_id": "2026-10-11-7abc6af92efb",
  "answer": {
    "kind": "profile",
    "summary": "已按指定版本读取数据产品",
    "evidence": {
      "data_product": "user_profile",
      "as_of": "2026-10-11",
      "release_id": "2026-10-11-7abc6af92efb",
      "quality": "PASS",
      "found": true,
      "columns": [
        "user_id", "as_of_date", "product_views_7d", "product_views_30d",
        "cart_events_30d", "placed_orders_30d", "placed_items_30d",
        "booked_amount_30d", "last_order_at", "days_since_last_order", "temporal_scope"
      ],
      "rows": [[76706, "2026-10-11", 0, 9, 9, 1, 3, "1168.9900",
        "2026-09-16 20:11:38+10:00", 25,
        "snapshot-observed-history; not production point-in-time certified"]]
    }
  }
}
```

为便于阅读省略了 definition、lineage、source_observed_at 和 warnings 的完整内容，原文件有证据。金额是下单商品价格合计，不是实收。7/30 天窗口以 UTC 截止点过滤；历史回执时间串带 +10:00 的显示偏移，比较时要解析带时区时间，不要将显示日期直接当 UTC 业务日。PASS 只涵盖已执行检查，历史 point-in-time 可用性仍未认证。

## 三、真实用户商品交互回执（字段映射展示）

问题：`查看用户76706和商品23546截至2026-10-11的交互特征`。

历史回执返回该交互对 30 天浏览 3 次、下单商品 1 件、订单 1 个、下单金额 999.0000。这里是将原 rows/columns 映射成便于理解的文本展示，实际工具仍返回 columns 与 rows，未新增另一套响应 API。

```text
status: COMPLETE
release: 2026-10-11-7abc6af92efb
user_id: 76706 / product_id: 23546 / as_of: 2026-10-11
product_views_7d: 0
product_views_30d: 3
placed_items_30d: 1
placed_orders_30d: 1
booked_amount_30d: 999.0000
population_scope: observed-interaction pairs only; absence is not a negative label
```

没有记录返回 found:false，不能自动补成“不喜欢”或“未转化”。当前工具按已知交互对读取，不生成全用户×全商品笛卡尔积。

## 四、指标查询（真实历史证据 + 结构化示例）

问题：2026 年 9 月美国男性的订单完成占比是多少？

结构化 Task 示例（不包含模型自行决定的表名或 SQL）：

```json
{
  "kind": "query",
  "query": {
    "metric_id": "complete_order_rate@1",
    "start": "2026-09-01",
    "end": "2026-10-01",
    "group_by": [],
    "filters": {"country": "United States", "gender": "M"}
  },
  "baseline": null,
  "expected_direction": "unknown",
  "diagnosis_dimensions": []
}
```

实际 Task 会校验窗口、维度与过滤；计划由服务端从权威合同展开。概念 SQL 是同一事实范围的 `Complete 订单计数 / NULLIF(全部订单计数,0)`，不是先 WHERE Complete 再计算比例，也不是平均各渠道比例。

已有 [真实报告](core-scope-query-report.md) 返回：

```text
metric: complete_order_rate@1
UTC window: [2026-09-01, 2026-10-01)
filters: country=United States, gender=M
columns: [value]
rows: [[0.24066390041493776]]
显示百分比: 24.0664%
结论: 当前快照状态观察结果，不是支付成功率，不确认因果原因。
质量: dbt_tests_passed=11；仅覆盖明确的粒度/关系/状态/金额检查。
时间: complete_through=null, verified=false；没有可信源端完整性水位。
```

该结果对应当时源快照。重新构建后应读取新回执，不要求固定返回上述数值。

## 五、异常分析（模拟交互与历史结果）

```text
用户：今天的转化率为什么比昨天低？
Agent：先明确“转化率”是订单完成占比、会话 purchase 观察还是支付成功率。
       当前公开数据没有可靠支付流水；今天可能未结束，不能直接做完整日比较。
用户：比较两个已结束的等长窗口，分析订单完成占比，按渠道和国家下钻。
Agent：校验指标、日期和过滤；先查 baseline/current，验证是否真的下降。
       前提不成立 -> PREMISE_REFUTED。
       前提成立 -> 组件拆解 -> 下钻 -> 对账 -> 质量检查 -> 证据报告。
       缺历史状态/水位/独立业务事件 -> INSUFFICIENT_EVIDENCE，停止确认根因。
```

历史 [core-scope-live-diagnosis.json](core-scope-live-diagnosis.json) 记录 14 次查询，完成占比从约 24.8252% 到 26.4920%，变化 +1.6668 个百分点。它是观察到的数值上升与代数解释，不是一个“下降已证明”的案例，也不证明渠道变动导致业务因果。请以原文件任务窗口和过滤为准。

可执行入口：

```powershell
.\.venv\Scripts\python.exe -m local_agent.cli diagnose --task config\diagnosis.example.json
```

该配置使用 booked_amount@1 与两等长窗口，不是上面历史完成占比诊断的逐字复制。示例与历史记录的差异必须保留。

## 六、画像字段说明与会话标签

```text
用户：说明截至2026-10-11的用户画像字段
Agent：返回 kind=describe 的数据产品契约，说明 grain、字段类型、来源、质量与血缘。

用户：这个会话没 purchase，能标为未购买负例吗？
Agent：不能直接确认。无 purchase 可能未结束、延迟、匿名或观测不完整。
       标签保留 UNKNOWN_NOT_VERIFIED_NEGATIVE。
       session_closure_verified / order_attribution_verified / payment_success_verified 为 false。
```

第二段是能力边界说明，不承诺当前有限规则能自动理解任意标签讨论；会话工具本身返回相应事实与 flags。当前不是自由通用问答系统。

## 七、本地 MCP 调用形态

```text
客户端 -> 启动 python -m local_agent.mcp_server
       -> initialize -> list_tools（13 个）
       -> call_tool(get_user_profile, {user_id:76706, as_of:"2026-10-11"})
       -> FeatureRequest 校验 -> FeatureTools -> Worker -> 结构化证据
```

指标是先 `plan_query` 再 `execute_query`，二者必须在同一服务会话内；重启重新规划。主 Agent 使用进程内工具调用，不把 Responses Task 输出说成模型原生 function calling 自由循环。

## 八、结果如何判断可靠

检查返回的指标定义、Grain、时间窗口、过滤、release、质量范围与限制；查询成功不自动证明业务口径或完整性。缺少证据时保留未知，不能为提高“成功率”填造支付、标签、水位或业务根因。
