# OpenAI 真实模型接入

选择模型 `gpt-6.1-sol`，Responses API，reasoning effort=low，最多4096输出tokens。每次问题最多一次模型调用，不自动重试；请求超时45秒。实际价格与账号权限以控制台为准。

## 本机启动

在 NL2SQL 工作区的 PowerShell 终端运行：

```powershell
./scripts/start-openai.ps1
```

首次运行 `./scripts/configure-openai.ps1` 隐藏输入新密钥并持久化。配置保存在 `%LOCALAPPDATA%/OwnDataAgent/openai.json`，密钥使用 Windows DPAPI 当前用户加密，项目仓库之外；同一 Windows 用户运行的程序可解密，这不是隔离于本机用户的保险库。启动脚本自动读取加密配置，默认问题为“2026年9月订单数是多少”。解密后的密钥只进入当前脚本进程环境，结束后恢复原有环境变量；文件只保存密文。模型默认 gpt-6.1-sol。已经出现在聊天中的密钥应先在控制台撤销，再生成新密钥。

```powershell
./scripts/start-openai.ps1 -Question '2026年9月下单金额为什么比2026年8月低'
```

已有安全环境变量配置时，也可使用：

```powershell
./.venv/Scripts/python.exe -m local_agent.cli --intent-mode llm ask '2026年9月订单数是多少'
```

必需 OPENAI_API_KEY、OPENAI_MODEL；不自动加载 .env。配置 OPENAI_API_KEY 后优先官方接入，缺少模型时明确停止，不悄悄回退规则。原有 LLM_* 兼容适配保留，适用于已有模拟测试。

## 数据流与约束

用户问题 → 按权限检索业务上下文 → OpenAI 严格结构化任务 → Task/Query 校验 → 指标、日期与权限校验 → LangGraph Skill 路由 → 本地 SQL 编译 → DuckDB → 带证据结果。

发送到 OpenAI 的内容包括用户问题、已授权检索结果、UTC时钟、任务Schema及两个Skill说明；不会发送数仓原始记录或查询结果。store=false 不等于承诺平台零保留，具体数据处理按官方政策与账户配置。

模型输出只允许任务或澄清，过滤条件用键值数组传输，本地转换为字典并拒绝重复键。SQL、任意工具名和身份参数不在任务接口中。语法约束不能证明业务正确，仍需运行时校验和工程评测。

明确的指标、时间与模型任务不一致时停止；歧义口径先澄清。拒绝响应、不完整响应、网络错误、HTTP错误均停止，不泄露接口错误正文。模型调用证据位于检索证据 model_call，记录模型、请求ID、用量和是否真实网络调用。

## 验收边界

已实现官方协议与模拟测试；未使用聊天中暴露的密钥，尚未进行真实付费调用。需用户在本机填写新密钥后，才能确认账户模型访问、真实任务理解及端到端执行。

首轮真实验收：订单数查询、美国过滤查询、销售额歧义澄清、今日不完整窗口、两月异常诊断。诊断仍可能返回 INSUFFICIENT_EVIDENCE：TheLook 快照没有可信完整性水位，接入模型不能补造质量证据。

官方依据：[模型说明](https://developers.openai.com/api/docs/models/gpt-6.1-sol)、[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)。


## 配置流程更新：独立窗口（v2）

运行 `./scripts/configure-openai.ps1` 后保持输入窗口打开，去 OpenAI 页面复制密钥，再回窗口粘贴并点击“保存配置”。无需隐藏终端输入或剪贴板参数。旧 FromClipboard 参数仅为命令兼容而接受，也会打开窗口，不读取剪贴板。

配置使用 Windows DPAPI 字节加密，version=2；保存前验证加密解密一致，临时文件只包含密文。旧版配置需在窗口重新保存，避免继续使用异常旧值。取消或输入错误不会覆盖旧配置。启动脚本不再询问密钥。Windows PowerShell 下已验证输入框内容保持、加密持久化、文件无明文、无效输入不覆盖和三脚本语法。尚需用户完成真实输入并验收接口调用。
