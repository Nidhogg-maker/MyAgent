# MyAgent · 电商数据开发与证据驱动分析 Agent

基于 TheLook 公共模拟电商数据，打通数仓加工、版本化指标、双路语义检索、自主工具选择和只读查询。核心实现是本项目自己的代码；MetricFlow、DataHub、WrenAI 是研究参考，不是运行服务依赖。

## 从哪里开始阅读

1. [整体架构导航](ARCHITECTURE.md)：各层为什么存在、三个运行入口、真实调用链和模块职责。
2. [当前源码地图](docs/code-map.md)：39 个模块的类、方法与当前行号，由 AST 自动生成。
3. [文档索引](docs/INDEX.md)：区分当前指南、操作手册、验收证据和历史阶段记录。
4. [完整学习手册](docs/PROJECT-STUDY-GUIDE.md)：原理、核心代码和 30 个进阶面试回答。

学习手册与 [整体项目验收报告](docs/PROJECT-ACCEPTANCE.md) 的执行证据基于整理前的验收版本。Word 同样是该版本的快照：[学习手册](docs/MyAgent-整体项目学习手册.docx)、[验收报告](docs/MyAgent-整体项目验收报告.docx)。本次名称整理与兼容关系见 [整理说明](docs/architecture-readability-changes.md)，当前行号以源码地图为准。

## 当前能力与使用入口

|入口|执行方式|适用问题|
|---|---|---|
|`ask` / `chat`|规则或模型理解任务 → LangGraph → 注册 Skill|指标查询、比较、下钻、质量与有界异常分析|
|`agent`|模型逐轮选择动作 → AgentToolRouter → 受控业务工具|自主检索、查询与证据整理；可开启 Multi Plan|
|`profile` 或画像提问|规则解析 → FeatureRuntime → 固定数据产品查询|用户、商品、交互与会话画像|
|本地 stdio MCP|协议适配 → 查询或画像服务|工具发现与调用；自主 Agent 主流程使用进程内工具|

语义层维护 12 个标准指标及一个注册多事实比例指标。多事实先聚合到合法共同维度再关联，拒绝任意明细 Join。Flat 检索支持词法、真实 Dense、RRF 与条件重排；Structured 检索使用同一 Registry 派生的 SQLite 关系，关系可达不授予 Join 权限。

数仓侧包括 commerce 两维度、两事实、一汇总，以及独立 features 的十张 DWD/DWS/ADS 表。读取回执附带口径、版本、质量与血缘；数值贡献不等于业务因果。

## 目录职责

```text
MyAgent/
├── src/local_agent/       执行代码；内部阅读说明见该目录 README
├── contracts/            权威指标与数据契约
├── knowledge/            业务检索资料与别名
├── config/               配置、访问策略与请求样例
├── warehouse-commerce/   dbt 指标事实、维度与汇总
├── warehouse-features/   dbt DWD/DWS/ADS 数据产品
├── skills/               Skill 指令、领域参考与报告模板
├── scripts/              安装、加工、模型与验收入口；有独立索引
├── tests/                临时数据、模拟模型与边界回归
├── docs/                 当前指南、历史报告与运行证据；有独立索引
└── data/                 本机数据、索引、会话与日志；不提交 Git
```

代码仍保留一个 Python 包，通过职责导航组织阅读。本次没有强行迁移文件，原导入路径、脚本和历史证据链接保持兼容。

## 本地运行

需要 Python 3.12+、Git；采集公共数据还需要 Google Cloud CLI 及有读取权限的账号。Agent 与 dbt 分别使用独立环境。数据、向量模型、密钥和会话不随仓库分发。

```powershell
git clone https://github.com/Nidhogg-maker/MyAgent.git
cd MyAgent
.\scriptsootstrap.ps1
.\.venv\Scripts\python.exe -m local_agent.cli skills
.\.venv\Scripts\python.exe -m pytest
```

获取数据并发布，详见 [环境与依赖](docs/setup-and-dependencies.md)：

```powershell
.\.venv\Scripts\python.exe scripts	helook_ingest.py all
.\scriptsuild-warehouse.ps1
# 示例截止日期来自历史快照，新数据须选可用日期
.\scriptsuild-feature-mart.ps1 -AsOf 2026-10-11 -VerifyRepeat
```

commerce 质量有效期为 24 小时，过期需重新验证与发布。工程测试主要使用临时数据和模拟接口，不代表真实模型准确率。

```powershell
# 规则/Workflow 入口
.\.venv\Scripts\python.exe -m local_agent.cli chat
.\.venv\Scripts\python.exe -m local_agent.cli query --request config\commerce-query.example.json
# 配置本机加密凭据，再启动自主选择工具的入口
.\scripts\configure-openai.ps1
.\scripts\start-agent.ps1 -Question "2026年9月平均每张订单的金额是多少"
# 多事实查询
.\.venv\Scripts\python.exe -m local_agent.cli multi-query --request config\multi-fact-query.example.json
```

普通 CLI 默认词法检索；真实 Agent 启动脚本默认 hybrid + auto 重排，需要先准备本地检索模型与索引，操作见 [脚本索引](scripts/README.md)。模型配置存于 `%LOCALAPPDATA%/OwnDataAgent/openai.json`，不在仓库内。安装使用 editable 模式，运行仍依赖仓库中的合同与 Skill 资源。

## 用户问题如何落地

`查看用户76706的画像` → 澄清截止日期 → `截至2026-10-11` → 校验发布产物 → 返回画像、release 与证据。

`今天的转化率为什么比昨天低` 需要先确定转化口径和日期完整性；Workflow 有任务校验，自主 Agent 的澄清仍部分依赖模型决策，不能宣称所有自然语言输入都有硬性保障。TheLook 没有真实支付与曝光点击链路，不能虚构支付成功率或 CTR。

完整示例见 [用户输入与输出](docs/user-agent-examples.md)。自主 Agent、Workflow、画像路径的恢复与预算并不完全相同，详见架构导航和学习手册。

## 已验证范围与边界

整理前整体验收完成 229 项工程回归，并留存真实模型、E5/Cross-Encoder、原始数据对账、画像和 MCP 证据。真实模型仅冒烟验证，不代表准确率。本次可读性整理的验证单独保存，不覆盖历史验收。

当前没有生产增量、迟到修正、幂等补数、企业 SSO、多租户、可信源端水位或推荐训练。画像与指标仍采用不同发布机制；SQLite 语义关系图与物理血缘目录也是不同对象。使用方式、设计约束与历史迭代统一从 [文档索引](docs/INDEX.md) 进入。
