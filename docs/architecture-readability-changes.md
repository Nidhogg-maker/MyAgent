# 架构可读性整理

本次整理基于整体项目验收版本 `18a8e97`，目标是让读者能够区分入口、业务服务、工具适配和权威定义。没有增加指标、修改 SQL 规则或重新设计 Agent 行为。

## 已完成的整理

|原来的阅读障碍|当前处理|
|---|---|
|两个模块都定义 AgentTools|业务服务规范名为 QueryService；模型动作路由器规范名为 AgentToolRouter|
|通用摘要函数放在业务服务中|抽出 integrity.fingerprint；运行、特征、规划和语义上下文显式依赖该模块|
|README 不断追加阶段说明|改成当前能力、运行入口、目录职责和操作入口；阶段记录从文档索引进入|
|旧架构正文与后续更新冲突|修正 Dense/重排、自主工具选择、多事实 Join 的早期描述|
|源码地图行号依赖手工维护|通过 generate-code-map.py 从 AST 生成 39 个模块的对象/方法位置|
|Workflow、自主 Agent、画像混在一起|架构导航分别说明三条路径，提供 Mermaid 与文字调用链|

新增阅读入口：[整体架构](../ARCHITECTURE.md)、[文档索引](INDEX.md)、[源码地图](code-map.md)、[源码目录说明](../src/local_agent/README.md)、[脚本索引](../scripts/README.md)。

## 兼容与约束

`service.AgentTools` 仍指向 QueryService；`agent_tools.AgentTools` 仍指向 AgentToolRouter。原 `service.fingerprint` 导入仍可使用，摘要序列化与算法保持一致。CLI、MCP、自主 Agent 使用规范名称；历史脚本与测试继续验证旧路径。

未移动核心文件，没有将平铺包包装成虚假的严格分层架构。源码中的动态依赖、指标/画像的独立发布以及不同恢复能力仍存在，导航明确记录这些边界。

旧 Word、JSON 和 XML 是冻结验收证据，不覆盖为新的执行结果。学习手册添加版本说明；当前类名和行号以源码地图为准。

## 验证记录

兼容别名、旧/新摘要结果一致性、模块编译与 CLI Skill 入口检查已通过。39 个模块生成成功，292 处本地文档链接及源码位置验证通过，Git 差异格式检查通过。

完整回归为 **228 项通过、1 项失败**，0 错误、0 跳过，用时约 323.5 秒。失败是比例诊断期望 INSUFFICIENT_EVIDENCE，实际因超过原有 60 秒 Skill 上限返回 STOPPED。当前源码单独复查完成 14 次查询，但总耗时约 62.56 秒；使用 `git show 18a8e97` 加载整理前模块的同条件对照也失败，完成 13 次查询后约 63.25 秒停止，原因同为 Skill deadline exceeded。

这证明该场景在当前环境存在既有耗时限制，不能把本次结果写成 229 项全通过，也不能据此承诺任意机器都能在 60 秒内完成诊断。本轮没有放宽预算或关闭安全检查。下一步若处理性能，应单独分析 SQLite 事件写入、版本检查和只读进程启动耗时，避免混入名称整理。

证据：[完整回归](architecture-readability-regression.xml)、[当前源码复查](architecture-readability-targeted.xml)、[整理前源码对照](architecture-readability-baseline.xml)、[验证摘要与源码 SHA256](architecture-readability-validation.json)。旧版 229 项通过记录仍作为此前验收结果保留，两次验收不能混为一谈。

维护时新增或移除 Python 模块，须更新生成脚本的职责分组；重新生成源码地图后检查本地文档链接。历史阶段文档不作为当前能力清单。
