"""自建 Metadata Graph：实体、Aspect、关系保存在本地 SQLite，不调用 DataHub。"""
import json
import sqlite3
from pathlib import Path
import duckdb
from sqlglot import exp
from sqlglot.lineage import lineage as resolve_lineage
from .control_lineage import extract_control


class MetadataCatalog:
    """用实体标识定位对象，用 Aspect 存属性，用有向边保存表级血缘。"""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with sqlite3.connect(path) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS entities (urn TEXT PRIMARY KEY, kind TEXT, name TEXT);
                CREATE TABLE IF NOT EXISTS aspects (urn TEXT, name TEXT, payload TEXT, PRIMARY KEY(urn,name));
                CREATE TABLE IF NOT EXISTS relationships (upstream TEXT, downstream TEXT, kind TEXT,
                    PRIMARY KEY(upstream,downstream,kind));
            ''')

    @staticmethod
    def urn(name):
        """标识采用本项目命名空间，不冒充 DataHub 已采集的实体。"""
        return 'urn:local:dataset:duckdb:' + name

    def ingest(self, database: Path, manifest: Path, owner: dict):
        """读取物理 schema 与 dbt depends_on；事务内替换，避免目录处于半更新状态。"""
        artifact = json.loads(manifest.read_text(encoding='utf-8'))
        with duckdb.connect(str(database), read_only=True) as source:
            columns = source.execute("SELECT table_schema,table_name,column_name,data_type FROM information_schema.columns WHERE table_schema IN ('raw','commerce') ORDER BY ordinal_position").fetchall()
        schemas = {}
        for schema, table, column, datatype in columns:
            schemas.setdefault(schema + '.' + table, []).append({'name': column, 'type': datatype})
        objects = {**artifact.get('sources', {}), **artifact.get('nodes', {})}
        with sqlite3.connect(self.path) as db:
            db.execute('DELETE FROM relationships')
            db.execute('DELETE FROM aspects')
            db.execute('DELETE FROM entities')
            flow='urn:local:flow:'+artifact.get('metadata',{}).get('project_name','unknown-dbt-project')
            db.execute('INSERT INTO entities VALUES (?,?,?)',(flow,'flow',artifact.get('metadata',{}).get('project_name','unknown')))
            for name, fields in schemas.items():
                urn = self.urn(name)
                db.execute('INSERT INTO entities VALUES (?,?,?)', (urn, 'dataset', name))
                for aspect, payload in {'schema': fields, 'ownership': owner}.items():
                    db.execute('INSERT INTO aspects VALUES (?,?,?)', (urn, aspect, json.dumps(payload)))
                for field in fields:
                    db.execute('INSERT INTO entities VALUES (?,?,?)', (urn + ':' + field['name'], 'field', name + '.' + field['name']))
            for node in artifact.get('nodes', {}).values():
                if node.get('resource_type') != 'model':
                    continue
                target = node['schema'] + '.' + node.get('alias', node['name'])
                for parent_id in node.get('depends_on', {}).get('nodes', []):
                    parent = objects.get(parent_id, {})
                    if parent.get('resource_type') not in ('source', 'model'):
                        continue
                    upstream = parent['schema'] + '.' + parent.get('identifier', parent.get('alias', parent['name']))
                    db.execute('INSERT OR IGNORE INTO relationships VALUES (?,?,?)', (self.urn(upstream), self.urn(target), 'data_dependency'))
                # SQLGlot 解析表达式依赖，再落为自己的关系模型；不把解析失败当完整血缘。
                resolved, unresolved = [], []
                for field in schemas.get(target, []):
                    try:
                        graph = resolve_lineage(field['name'], node['compiled_code'], schema={}, dialect='duckdb')
                        leaves = [leaf for leaf in graph.walk() if not leaf.downstream]
                        valid = bool(leaves)
                        links = []
                        for leaf in leaves:
                            if not isinstance(leaf.expression, exp.Table):
                                valid = False
                                continue
                            table = leaf.expression.db + '.' + leaf.expression.name
                            column = leaf.name.rsplit('.', 1)[-1].strip('"')
                            if column not in {item['name'] for item in schemas.get(table, [])}:
                                valid = False
                                continue
                            links.append((self.urn(table) + ':' + column, self.urn(target) + ':' + field['name'], 'field_value'))
                        for link in links:
                            db.execute('INSERT OR IGNORE INTO relationships VALUES (?,?,?)', link)
                        (resolved if valid else unresolved).append(field['name'])
                    except Exception:
                        unresolved.append(field['name'])
                db.execute('INSERT INTO aspects VALUES (?,?,?)', (self.urn(target), 'field_lineage', json.dumps({
                    'resolved_fields': resolved, 'unresolved_fields': unresolved,
                    'scope': 'value-expression dependencies; excludes join/filter control dependencies',
                    'complete': not unresolved})))
                control = extract_control(node.get('compiled_code',''),schemas)
                for edge in control['edges']:
                    db.execute('INSERT OR IGNORE INTO relationships VALUES (?,?,?)',
                        (self.urn(edge['table'])+':'+edge['column'],self.urn(target),'control_'+edge['kind']))
                db.execute('INSERT INTO aspects VALUES (?,?,?)',(self.urn(target),'control_lineage',json.dumps(control)))
                # 任务节点与数据实体分离；SQL保留在内部目录，不作为自由SQL工具暴露。
                job = 'urn:local:job:' + node['unique_id']
                db.execute('INSERT INTO entities VALUES (?,?,?)', (job, 'job', node['name']))
                db.execute('INSERT OR IGNORE INTO relationships VALUES (?,?,?)',(flow,job,'contains_job'))
                db.execute('INSERT OR IGNORE INTO relationships VALUES (?,?,?)',(job,self.urn(target),'produces_dataset'))
                db.execute('INSERT INTO aspects VALUES (?,?,?)', (job, 'transformation', json.dumps({'output': target, 'sql': node.get('compiled_code', node.get('raw_code'))})))

    def attach_quality(self, evidence):
        """质量是单独 Aspect，记录快照级验证范围，不能冒充逐字段业务质量。"""
        with sqlite3.connect(self.path) as db:
            urns = [row[0] for row in db.execute("SELECT urn FROM entities WHERE kind='dataset'")]
            for urn in urns:
                db.execute('INSERT OR REPLACE INTO aspects VALUES (?,?,?)', (urn, 'quality', json.dumps(evidence)))

    def context(self, name):
        """按表读取可验证上下文；目录不存在该表时直接失败。"""
        urn = self.urn(name)
        with sqlite3.connect(self.path) as db:
            if not db.execute('SELECT 1 FROM entities WHERE urn=?', (urn,)).fetchone():
                raise ValueError('Metadata dataset missing: ' + name)
            aspects = {k: json.loads(v) for k, v in db.execute('SELECT name,payload FROM aspects WHERE urn=?', (urn,))}
        return {'urn': urn, **aspects, 'column_lineage_complete': False}

    def field_lineage(self, name, column, max_depth=5):
        """追踪已解析的值依赖；聚合行数、过滤条件等未覆盖部分显式保留。"""
        context = self.context(name)
        if column not in {field['name'] for field in context['schema']} or not 1 <= max_depth <= 10:
            raise ValueError('Unknown field or invalid budget')
        start = self.urn(name) + ':' + column
        seen, frontier, edges = {start}, [start], []
        with sqlite3.connect(self.path) as db:
            for _ in range(max_depth):
                next_frontier = []
                for current in frontier:
                    for upstream, in db.execute("SELECT upstream FROM relationships WHERE downstream=? AND kind='field_value'", (current,)):
                        edges.append({'from': current, 'to': upstream})
                        if upstream not in seen:
                            seen.add(upstream)
                            next_frontier.append(upstream)
                frontier = next_frontier
                if not frontier:
                    break
            truncated = any(db.execute("SELECT 1 FROM relationships WHERE downstream=? AND kind='field_value'", (node,)).fetchone() for node in frontier)
        controls = []
        with sqlite3.connect(self.path) as db:
            for dataset in {node.rsplit(':',1)[0] for node in seen}:
                for upstream,kind in db.execute("SELECT upstream,kind FROM relationships WHERE downstream=? AND kind LIKE 'control_%'",(dataset,)):
                    controls.append({'from':dataset,'to':upstream,'kind':kind})
        return {'edges': edges, 'control_dependencies':controls, 'truncated': truncated, 'complete': False,
                'scope': 'Value lineage plus separately labeled row-control dependencies; unsupported SQL remains incomplete'}

    def lineage(self, name, direction='upstream', max_depth=5):
        """广度优先遍历并处理环；返回截断标记，不能把预算耗尽当成没有依赖。"""
        if direction not in ('upstream', 'downstream') or not 1 <= max_depth <= 10:
            raise ValueError('Invalid lineage traversal')
        start = self.urn(name)
        self.context(name)
        left, right = ('downstream', 'upstream') if direction == 'upstream' else ('upstream', 'downstream')
        seen, frontier, edges = {start}, [start], []
        with sqlite3.connect(self.path) as db:
            for _ in range(max_depth):
                next_frontier = []
                for current in frontier:
                    for target, in db.execute(f"SELECT {right} FROM relationships WHERE {left}=? AND kind='data_dependency'", (current,)):
                        edges.append({'from': current, 'to': target})
                        if target not in seen:
                            seen.add(target)
                            next_frontier.append(target)
                frontier = next_frontier
                if not frontier:
                    break
            truncated = any(db.execute(f"SELECT 1 FROM relationships WHERE {left}=? AND kind='data_dependency'", (node,)).fetchone() for node in frontier)
        return {'edges': edges, 'truncated': truncated, 'column_lineage_complete': False}
