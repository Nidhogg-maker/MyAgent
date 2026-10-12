# 安装、依赖、数据构建与复现

## 支持范围

当前完整脚本主要针对 Windows / PowerShell 与 Python 3.12+。核心 Python 可移植，但 dbt 构建器使用 `.warehouse-venv/Scripts/python.exe`，Windows DPAPI 配置也是平台限定；尚未验收 Linux/macOS 全流程。

项目应保留仓库目录结构，使用 editable 安装。合同、知识、配置与 Skill 通过源码计算仓库根目录加载；不要只复制 site-packages 或假设 wheel 自动包含所有资源。

## 环境依赖表

|依赖|用途|是否必需|
|---|---|---|
|Python 3.12+ / Git|运行与获取源码|是|
|DuckDB|本地数仓、聚合与只读执行|是|
|SQLGlot|受控 AST、血缘解析|是|
|Pydantic|Query、Task、画像契约|是|
|LangGraph|固定任务状态流程|指标流程使用|
|HTTPX|模型 HTTP 请求|运行环境包含；规则模式无需模型网络|
|MCP SDK|本地 stdio 工具适配|运行环境包含；CLI 主链不需要 MCP 客户端|
|dbt-core / dbt-duckdb|数据开发、发布重验|在独立 `.warehouse-venv` 中|
|Google Cloud CLI / 公共表访问账号|下载 TheLook|仅真实公开数据采集时|
|OpenAI API 账号与有效 API 模型|真实指标任务理解|可选|

直接依赖版本见 `pyproject.toml`/`requirements.txt`；Agent 锁定环境见 `requirements.lock.txt`。数仓依赖见 `requirements-warehouse.txt`。dbt 可能传递安装 MetricFlow，但 Agent 运行代码不导入或调用它；不要把两套环境混装。

## 从空目录到可查询

### 1. 安装运行环境

```powershell
git clone https://github.com/Nidhogg-maker/MyAgent.git
cd MyAgent
.\scripts\bootstrap.ps1
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest
```

测试包含临时 fixture、模拟接口和依赖真实本地发布数据的集成检查。空机器没有数据时部分检查会跳过；有数据库但 dbt 质量凭证过期时，发布类 fixture 会明确失败，应先真实重跑 build-warehouse.ps1，再运行全量回归。不能用修改 generated_at 或删除24小时校验来制造通过。测试不能代替真实源采集。依赖安装失败时保留原始错误，禁止静默升级后声称同一验收环境。

### 2. 采集公开数据

在本机安装 Google Cloud CLI，完成 `gcloud auth login`。程序调用 `gcloud auth print-access-token`，仅在内存请求头使用令牌，不写入仓库。公共表读取仍需有效身份/API 访问环境；鉴权失败应检查自己的账号配置。

```powershell
# 若已在 PATH，无需设置。否则使用本机真实路径。
# $env:THELOOK_GCLOUD = 'C:\path\to\gcloud.cmd'
.\.venv\Scripts\python.exe scripts\thelook_ingest.py all --snapshot 20261012
```

来源为 `bigquery-public-data.thelook_ecommerce` 七表。脚本下载原始分页数据，校验源版本/文件 hash/行数并导入 `data/thelook.duckdb` 的 raw schema。默认 snapshot 标签采用运行日；它是目录标签，不证明源端当天原子快照。七表顺序读取不构成跨表一致事务。

导入更新 `docs/thelook-source-manifest.json` 与 `docs/thelook-profile.json`；本次快照与仓库保存的历史记录可能不同。数据默认不提交 Git。

### 3. 指标数仓与发布

```powershell
.\scripts\build-warehouse.ps1
.\.venv\Scripts\python.exe -m local_agent.cli metrics
.\.venv\Scripts\python.exe -m local_agent.cli query --request config\commerce-query.example.json
```

脚本创建 `.warehouse-venv`，构建 `warehouse-commerce`、保留成功 run_results、生成 dbt catalog，再调用 publish。publish 重跑质量检查、独立键/金额验证，创建快照和目录。质量证据超过 24 小时需重新执行构建/发布；不是绕过 TTL。

### 4. 特征主题加工

```powershell
.\scripts\build-feature-mart.ps1 -AsOf 2026-10-11 -VerifyRepeat
.\.venv\Scripts\python.exe -m local_agent.cli profile --product user_profile --as-of 2026-10-11 --user-id 76706
```

截止日期取 UTC 零点，需不晚于源观测时间。独立复制 raw 到候选 features 库，dbt 构建十表，独立对账；VerifyRepeat 重建并比较内容摘要。成功才切 active 指针，失败候选目录留下日志、旧成功 release 保留。每个 release 仅对应一个截止日期，不会自动发布其他日期。

发布目录包含 features.duckdb、release.json、quality.json、metadata.json、table-contracts.json、events.jsonl 与 dbt 产物。这些全部位于 `data/feature-mart/`，不上传 Git。

### 5. 模型（可选）

规则模式不需要密钥。真实模型用 `scripts/configure-openai.ps1` 的本机输入窗口，再用 `scripts/start-openai.ps1 -Chat`。加密配置绑定 Windows 当前用户，不能复制配置到其他账户保证可解密。

环境变量入口为 `OPENAI_API_KEY` 与 `OPENAI_MODEL`（OpenAI provider）。旧通用配置见源码与模型说明；CLI **不会自动加载 .env**。`.env.example` 仅提示变量，不代表执行它就有凭据。

模型输出是受限 Task，不是任意 SQL。画像当前还是规则理解。API 接入成功只证明一条真实请求完成，不等于系统准确率验收。

## 演示与运维命令

```powershell
.\.venv\Scripts\python.exe scripts\feature-query-demo.py
.\.venv\Scripts\python.exe scripts\mcp-local-demo.py
.\.venv\Scripts\python.exe -m local_agent.cli health
.\.venv\Scripts\python.exe -m local_agent.cli session <session-id>
.\.venv\Scripts\python.exe -m local_agent.cli reply <session-id> "截至2026-10-11"
.\.venv\Scripts\python.exe -m local_agent.cli resume <session-id>
.\.venv\Scripts\python.exe -m local_agent.cli cancel <session-id>
```

实际使用时将 `<session-id>` 替换为返回值；尖括号是占位说明，不应原样粘贴。指标演示需要有效发布质量，画像演示需要相应日期 release。MCP 启动入口是 `.venv/Scripts/python.exe -m local_agent.mcp_server`；工具发现与调用示例在 `scripts/feature-query-demo.py`。

## 常见停止情况

|情况|处理|
|---|---|
|没有 data/thelook.duckdb|先采集并导入；仓库故意不打包数据库|
|Warehouse runtime is missing|先运行 build-warehouse.ps1 创建独立环境|
|发布质量过期|重跑 commerce 构建与发布|
|画像日期没有成功 release|构建指定日期，或明确选择已发布日期|
|CLARIFY|通过 chat 或 reply 补足口径/日期/实体条件|
|PREMISE_REFUTED|问题所称下降不成立，检查基准与定义|
|INSUFFICIENT_EVIDENCE|已有数值不等于因果证据；阅读 warnings/unresolved|
|模型 401/403/额度/模型不可用|检查本机凭据与 API 账号，不回显密钥|
|发布 hash 不一致|停止读取，重新验证产物，不删除校验绕过|

## 证据与 Git 边界

历史 docs JSON 回执用于解释运行结果，绝对本机路径不是可移植配置。新机器必须自己构建数据库和 release；不能拿历史 release.json 复制一个不存在的路径执行。运行会话、签名凭据、环境、数据库、生成布局缓存都在 Git 忽略范围。
