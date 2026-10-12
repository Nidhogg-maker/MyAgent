"""从当前AST生成可点击源码地图，防止手工行号随迭代过期。"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    '入口与意图': ['cli', 'chat', 'tasks', 'agent_loop', 'agent_tools', 'multi_plan', 'mcp_server'],
    '业务能力与运行': ['skills', 'skill_resources', 'harness', 'diagnosis', 'reporting', 'runtime', 'resilience', 'openai_provider'],
    '可信查询与计算': ['service', 'semantic', 'multi_fact', 'dimensions', 'query_templates', 'worker'],
    '检索与语义上下文': ['retrieval_service', 'retrieval', 'dense_retrieval', 'reranking', 'semantic_context', 'retrieval_context'],
    '资产与元数据': ['assets', 'structure', 'catalog', 'control_lineage', 'history'],
    '特征数据产品': ['feature_pipeline', 'feature_agent'],
    '共同约束与验证': ['access', 'temporal', 'integrity', 'evaluation', '__init__'],
}


def description(node):
    doc = ast.get_docstring(node)
    return doc.splitlines()[0].replace('|', '\\|') if doc else '实现细节见源码与所属类说明'


def main():
    files = {p.stem: p for p in (ROOT/'src/local_agent').glob('*.py')}
    declared = [name for members in GROUPS.values() for name in members]
    if len(declared) != len(set(declared)) or set(declared) != set(files):
        raise ValueError('源码模块增加/移除后请更新导航分组')
    lines = ['# 当前源码地图', '', '本文件由scripts/generate-code-map.py生成；行号来自当前AST。职责和调用关系见 [架构导航](../ARCHITECTURE.md)。', '',
             '规范名称：service.QueryService、agent_tools.AgentToolRouter。旧AgentTools为兼容别名，不是额外服务。', '']
    for group, members in GROUPS.items():
        lines.extend(['## '+group, ''])
        for name in members:
            path = files[name]
            tree = ast.parse(path.read_text(encoding='utf-8'))
            lines.extend(['### '+name+'.py', '', ast.get_docstring(tree) or '包入口', '',
                          '|对象/方法|源码位置|职责|', '|---|---|---|'])
            for node in tree.body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    lines.append(f'|{node.name}|[第{node.lineno}行](../src/local_agent/{name}.py#L{node.lineno})|{description(node)}|')
                    if isinstance(node, ast.ClassDef):
                        for child in node.body:
                            if isinstance(child, ast.FunctionDef) and not child.name.startswith('_'):
                                lines.append(f'|{node.name}.{child.name}|[第{child.lineno}行](../src/local_agent/{name}.py#L{child.lineno})|{description(child)}|')
                elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id=='AgentTools' for t in node.targets):
                    lines.append(f'|AgentTools兼容别名|[第{node.lineno}行](../src/local_agent/{name}.py#L{node.lineno})|沿用旧导入路径；新代码使用规范名称|')
            lines.append('')
    (ROOT/'docs/code-map.md').write_text('\n'.join(lines).rstrip()+'\n', encoding='utf-8')
    print(f'源码地图已更新：{len(files)}个模块')


if __name__ == '__main__':
    main()
