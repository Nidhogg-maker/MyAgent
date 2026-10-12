# 文档入口与阅读顺序

## 当前学习入口

|目的|阅读文档|
|---|---|
|五分钟理解整个项目|[根目录架构导航](../ARCHITECTURE.md)|
|找到当前类、方法与行号|[源码地图](code-map.md)|
|系统学习与30道进阶问答|[整体学习手册](PROJECT-STUDY-GUIDE.md)|
|了解真实验收与未完成边界|[整体验收报告](PROJECT-ACCEPTANCE.md)|
|查看召回、规则与真实Agent正确性初测|[正确性测试报告](correctness-benchmark/REPORT.md)|
|安装与本机重建|[环境与依赖](setup-and-dependencies.md)|
|看用户输入与输出|[交互示例](user-agent-examples.md)|
|理解数据与粒度|[数据模型](data-model.md)|

学习手册及两个Word文件记录上一轮验收基线。可读性整理后的规范类名为QueryService与AgentToolRouter，旧AgentTools导入兼容；最新行号见自动生成代码地图。

## 按主题查实现

|主题|专题说明|
|---|---|
|自主决策与固定Workflow|[AgentLoop](agent-loop-guide.md)、[运行与Skill](runtime-skills-guide.md)|
|候选计划/多事实Join|[Multi Plan与Join](multi-plan-and-join-guide.md)|
|检索的当前最终状态|[双路检索设计](dual-rag-design.md)、[第四阶段](retrieval-phase4-guide.md)|
|Dense/RRF与模型准备|[第二阶段](retrieval-phase2-guide.md)|
|Cross-Encoder与IR缓存|[第三阶段](retrieval-phase3-guide.md)|
|画像/交互/会话加工|[数据产品第二阶段](feature-phase2-guide.md)|
|本机模型配置|[模型接入](openai-integration.md)|

## 证据与历史

project-final-*.json/xml为整体验收记录，retrieval-iteration-*.json为检索迭代证据，feature-phase2-*.json为特征加工和读取证据。阅读顺序应先Markdown再查JSON/XML，不用从大回执开始。

phase1/2/3/4、completion、旧项目总报告和早期Word保留历史，不是彼此叠加的当前架构。它们可能使用旧名称、旧计数、旧本机路径；不按报告日期猜测功能是否最新，因为多次迭代可能同一天完成。

未物理移动历史文件，以保留链接和脚本输出路径。若未来归档目录，应同步修改生成脚本与所有引用，不能只拖动文件。
