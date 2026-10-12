# 可执行 Skill、异常 Workflow、持久 Harness 与连续提问

这批实现聚焦核心工程链路，不计算模型准确率。现有 TheLook 数据、commerce-v2 指标合同、本地权限和不可变快照继续作为执行依据。

## 1. 统一使用入口

在 MyAgent 目录运行：

```powershell
.\scripts\start-openai.ps1 -Chat
```

脚本自动读取 Windows 当前用户加密配置；不再重复输入密钥。先问“2026年9月男性订单完成占比是多少”，再问“按渠道”，即可延续上一轮指标、日期与过滤。`/new` 明确开始不继承上下文的新问题。当前没有网页UI。

若问“2026年9月销售额是多少”，系统澄清后回复“下单金额”，生成子会话并保留父问题、澄清与选择记录。不会把歧义口径自动改成其他指标。

每轮输出 session_id；关闭后可重新进入：

```powershell
.\scripts\start-openai.ps1 -Chat -Session '替换为会话ID'
```

聊天命令：`/show` 查看完整状态、事件与查询证据；`/resume` 恢复失败或中断工作；`/cancel` 取消；`/exit` 退出。终端忙于当前任务时，取消可从另一个终端执行下述命令。Ctrl+C退出不是持久取消，使用 cancel 才会写入取消标志。

```powershell
.\.venv\Scripts\python.exe -m local_agent.cli --intent-mode llm session '会话ID'
.\.venv\Scripts\python.exe -m local_agent.cli --intent-mode llm cancel '会话ID'
.\.venv\Scripts\python.exe -m local_agent.cli --intent-mode llm resume '会话ID'
.\.venv\Scripts\python.exe -m local_agent.cli skills
```

恢复已解析任务不需要再次请求模型。若中断发生在任务解析前，需要带模型配置的聊天入口恢复。会话绑定 rules/llm 模式，上述 llm 参数必须与原会话一致。

## 2. 六项 Skill 的真实执行

| Skill ID | 输入 | 依赖工具/Skill | 查询上限 |
|---|---|---|---|
| metric-query | Query | plan / execute | 1 |
| comparison | Pair | metric-query | 2 |
| drilldown | 带合法group_by的Query | plan / execute | 1 |
| quality-check | metric_id | context / release | 0 |
| anomaly-analysis | Task | comparison / drilldown / quality-check | 16 |
| evidence-report | kind + evidence | 无查询工具 | 0 |

SkillRegistry 暴露版本、输入输出 JSON Schema、前后置条件、工具依赖、权限scope、超时、重试和幂等说明；启动时检测依赖缺失、环和最大4层调用深度。SkillExecutor 校验输入、可信身份和输出，并写入开始/结束事件。具体工具调用在受限代码中，不是执行Markdown中的任意工具名。

单次 Skill 最长60秒；单会话最多16次实际查询、120秒活跃预算。注册实现的固定调用结构限制每个Skill查询次数，RuntimeTools进一步维护共享会话查询额度。没有自动模型重试、无边界Skill递归或任意工具执行。部署为远程服务时还需独立并发/流量限额。

## 3. 实际异常分析顺序

```mermaid
flowchart LR
    T[Validated Task] --> C[Comparison Skill]
    C --> P[Validate User Premise]
    P --> N[Numerator and Denominator Queries]
    N --> A[Algebraic Decomposition]
    A --> D[Dimension Drilldown Skill]
    D --> Q[Quality Check Skill]
    Q --> R[Evidence Report Skill]
    P -->|premise refuted| R
    D -->|budget / suppression / truncation| S[Stop with Partial Evidence]
    H[Harness Budget and Session Store] -. governs .-> C
    H -. governs .-> D
```

完成占比的完整路径：两个窗口比例比较；各窗口分子/分母查询，共6条逻辑查询；两个维度分别查询两个窗口的分子与分母，再增加8条，共14条。按组计算 `当前组分子/当前总分母 - 对照组分子/对照总分母`，组贡献之和必须等于总体比例差；分别核对分子和分母分组和与总体值一致。没有对分组比例直接求和或简单平均。

指标不兼容维度、查询截断、隐私小组抑制造成对账失败、分母为零都停止分析。贡献属于代数分解，不能证明渠道或用户群导致了异常。维度贡献以绝对值排序，供观察和后续假设验证；目前未把它分解为独立的因果效应。

质量Skill读取实际发布验证与目录质量；TheLook仍没有可信完整性水位和历史状态成熟度，所以正常诊断可返回 INSUFFICIENT_EVIDENCE，同时展示比较、分解和下钻证据。前提被数据反驳则返回 PREMISE_REFUTED，跳过无意义的归因。资源或工具故障保留已完成查询回执。

## 4. 持久状态与恢复机制

`data/own-agent/sessions.sqlite` 保存会话请求、状态、查询数、累计运行时间、取消标志、执行租约、事件、查询回执。保存的内容没有 API Key。它是本地受操作系统用户信任的存储，未提供企业多租户隔离或加密所有业务结果。

每个LangGraph节点完成后保存状态；查询开始前持久扣额度，查询成功后先落盘回执。崩溃后结果不确定的查询仍消耗额度。恢复重新运行确定性读流程，重新生成服务端plan_id；已完成且同权限、同语义、同release的查询复用回执。它是有界只读重放机制，不声称任意副作用工具exactly-once执行。

恢复重新验证主体、策略hash、指标hash、release ID，以及现有工具服务的快照/目录完整性和质量时效。任一版本变化拒绝旧会话恢复，需新建会话，不能把新旧数据混在一个诊断中。令牌撤销/过期仍通过权限服务拒绝。完成或明确证据缺口的会话直接返回已保存结果；带stopped_reason的中断诊断允许显式重试，但剩余额度和时间不会重置。

单个会话用180秒租约防并发重放。异常进程退出未释放租约时需等待租约到期，再恢复；租约不是分布式服务集群的生产方案。恢复只统计活跃运行预算，长时间离线不补造事件或数据；进程突然崩溃可能遗漏最后一次计时更新，但查询额度先扣且有上限。

取消标志由独立CLI写入，查询worker每约250ms检查并终止子进程；当前阻塞HTTP模型请求仍依赖45秒网络超时及节点结束后的取消检查，尚未实现网络请求实时中断。工具超时终止worker；整个会话超时停止下一步。再次 resume 不会清除取消标志，也不会刷新已消耗额度。

## 5. 证据与接口边界

`scripts/runtime-demo.py` 对真实本地快照运行完整结构化诊断，不调用模型，记录在 docs/runtime-workflow-demo.json。`docs/runtime-live-query.json` 保存真实模型经新Harness的指标查询结果。工程测试验证注册环、非法下钻、跨实例恢复不重复执行、绑定变更拒绝、额度/租约/取消、澄清续问、保留过滤的分组追问、14查询比例工作流及实际子进程取消/超时终止。

CLI的ask/query/diagnose/chat已使用持久Harness。既有 build_agent 默认入口保留兼容；stdio MCP的原8工具接口仍作为独立受控工具服务，并未新增会话远程协议。当前核心内部调用直接使用AgentTools，不必绕一圈MCP才算工具调用。

待后续扩展：远程身份与权限、浏览器交互、可靠跨主机恢复、状态压缩/清理、任意省略式追问规则、写入工具幂等与审批、完整业务事件证据。这些不影响本批本地只读核心链路的运行，也不能用本批功能宣称企业生产治理已完成。
