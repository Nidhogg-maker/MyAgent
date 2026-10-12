"""保守解析Join/Where/Group/Having控制依赖；不能证明的列保持unresolved。"""
from sqlglot import exp, parse_one
from sqlglot.optimizer.scope import Scope, traverse_scope

def extract_control(sql, schemas):
    edges, unresolved = set(), []
    def origin(scope, column, visited=()):
        identity = (id(scope),column.table,column.name)
        if identity in visited or len(visited) >= 10:
            return set()
        selected = {alias:source for alias,(_,source) in scope.selected_sources.items()}
        candidates = [column.table] if column.table else list(selected)
        matches = []
        for alias in candidates:
            source = selected.get(alias)
            if isinstance(source,exp.Table):
                table = source.db+'.'+source.name
                if column.name in {f['name'] for f in schemas.get(table,[])}:
                    matches.append({(table,column.name)})
            elif isinstance(source,Scope) and isinstance(source.expression,exp.Select):
                projection = next((node for node in source.expression.expressions if node.alias_or_name==column.name),None)
                if projection is not None:
                    found = set()
                    for inner in projection.find_all(exp.Column):
                        found |= origin(source,inner,visited+(identity,))
                    if found:
                        matches.append(found)
        # 不带table的歧义列不随意选择，除非恰好唯一来源。
        return set.union(*matches) if len(matches)==1 else set()
    try:
        tree = parse_one(sql,read='duckdb')
        if tree.find(exp.Union):
            unresolved.append({'reason':'UNION control semantics not fully covered'})
        for scope in traverse_scope(tree):
            if not isinstance(scope.expression,exp.Select):
                unresolved.append({'reason':'Unsupported scope'})
                continue
            clauses = []
            for key,kind in [('where','filter'),('having','filter'),('qualify','filter'),('group','group')]:
                if scope.expression.args.get(key):
                    clauses.append((scope.expression.args[key],kind))
            for join in scope.expression.args.get('joins',[]):
                if join.args.get('on'):
                    clauses.append((join.args['on'],'join'))
                if join.args.get('using'):
                    # USING依赖两侧键，保守记录所有匹配源，并标记解析范围。
                    for identifier in join.args['using']:
                        found = set()
                        for alias in scope.selected_sources:
                            found |= origin(scope,exp.column(identifier.name,table=alias))
                        for table,column in found:
                            edges.add((table,column,'join'))
                        if not found:
                            unresolved.append({'column':identifier.name,'reason':'Unresolved USING'})
            for clause,kind in clauses:
                for column in clause.find_all(exp.Column):
                    ancestor = column.find_ancestor(exp.Select)
                    if ancestor is not None and ancestor is not scope.expression:
                        unresolved.append({'column':column.sql(),'reason':'Nested/correlated control expression'})
                        continue
                    found = origin(scope,column)
                    for table,name in found:
                        edges.add((table,name,kind))
                    if not found:
                        unresolved.append({'column':column.sql(),'reason':'Ambiguous or unresolved '+kind})
    except Exception as error:
        unresolved.append({'reason':'Control parse failed: '+type(error).__name__})
    return {'edges':[{'table':table,'column':column,'kind':kind} for table,column,kind in sorted(edges)],
            'unresolved':unresolved,'complete_within_supported_scope':not unresolved,
            'scope':'Row membership/control dependencies for supported Select/CTE; not universal SQL lineage'}
