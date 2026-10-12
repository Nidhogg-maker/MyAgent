# 核心源码阅读入口

本目录是一个Python包，当前采用平铺模块。职责分组见 [架构导航](../../ARCHITECTURE.md)，实时类/方法位置见 [代码地图](../../docs/code-map.md)。

## 首先读这些文件

```text
cli.py                 使用入口及模式分派
semantic.py            Query + Registry + 受控单事实编译
service.py             QueryService，可信查询与元数据服务
worker.py              最终只读执行进程
agent_loop.py          模型逐轮自主决策
agent_tools.py         AgentToolRouter，工具schema与分发
runtime.py             会话账本与执行包装
```

再根据问题进入multi_fact/multi_plan、检索、诊断或特征产品。不要从全部文件按字母顺序阅读。

## 容易混淆的职责

- **QueryService和AgentToolRouter**：前者决定查询是否合法并执行，后者把模型动作路由到合法能力。两者旧名都叫AgentTools，保留旧名仅为兼容。
- **AgentLoop和build_agent**：前者每轮模型选择工具；后者是LangGraph固定Workflow。名称中有agent不意味着自主程度相同。
- **MetadataCatalog和GraphService**：前者来自物理schema/dbt产物；后者是指标关系投影。图可达不授权Join。
- **QueryTemplateCache和会话Receipt**：前者缓存聚合AST，后者保存已执行结果，两者版本和复用范围不同。
- **FeatureRuntime和HarnessRuntime**：数据产品和指标有独立发布及运行约束。

integrity.py只放稳定摘要工具，不导入业务服务；access/temporal保存共同约束。__init__.py保持轻量，模块通过明确导入表达依赖，不提供隐藏业务装配的全量出口。
