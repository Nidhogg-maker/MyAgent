"""高频语义 IR 缓存：只缓存聚合表达式，不缓存日期/过滤值/完整 SQL/数据结果。"""
import json
import sqlite3
import os
from pathlib import Path
import sqlglot
from .semantic import ROOT, file_hash
from .dense_retrieval import digest


class QueryTemplateCache:
    def __init__(self, home):
        self.path = Path(home)/'query-templates.sqlite'
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS templates(
                key TEXT PRIMARY KEY, payload TEXT NOT NULL, checksum TEXT NOT NULL,
                uses INTEGER NOT NULL DEFAULT 0, touched INTEGER NOT NULL DEFAULT 0)''')

    def connect(self):
        return sqlite3.connect(self.path,timeout=5)

    def compile(self, compiler, query, minimum_group_size, binding):
        if os.environ.get('OWN_AGENT_TEMPLATE_CACHE', 'on') == 'off':
            return compiler.compile(query,minimum_group_size), {'status':'disabled'}
        value = query.model_dump(mode='json')
        metrics = list(value.get('metric_ids',[])) or [value['metric_id']]
        shape = {k:v for k,v in value.items() if k not in ('start','end','filters','limit')}
        shape['filter_fields'] = sorted(value['filters'])
        # 与数据 release 分离；缓存不含数据结果，但绑定身份、权限、语义与编译实现。
        semantic_binding = {k:v for k,v in binding.items() if k != 'release_id'}
        scope = {'shape':shape,'binding':semantic_binding,'minimum_group_size':minimum_group_size,
            'format':'aggregation-ir-v1', 'compiler':file_hash(ROOT/'src/local_agent/semantic.py'),
            'multi_compiler':file_hash(ROOT/'src/local_agent/multi_fact.py'),
            'template_implementation':file_hash(ROOT/'src/local_agent/query_templates.py'),
            'sqlglot':sqlglot.__version__}
        key = digest(scope)
        with self.connect() as db:
            row = db.execute('SELECT payload,checksum FROM templates WHERE key=?',(key,)).fetchone()
        nodes = None
        status = 'miss'
        if row:
            try:
                payload = json.loads(row[0])
                if digest(payload) != row[1] or payload['scope'] != scope or set(payload['expressions']) != set(metrics):
                    raise ValueError('Invalid cached template binding')
                nodes = {m:sqlglot.parse_one(sql,read='duckdb') for m,sql in payload['expressions'].items()}
                status = 'hit'
            except (ValueError,KeyError,sqlglot.errors.ParseError):
                status = 'rebuild_corrupt'
        if nodes is None:
            nodes = {m:compiler.expression(m) for m in metrics}
        # 时间、过滤值、展示限制始终由本次受控 Query 构造 AST；原维度/Join 校验仍执行。
        compiled = compiler.compile(query,minimum_group_size,aggregation_ir=nodes)
        payload = {'scope':scope,'expressions':{m:node.sql(dialect='duckdb') for m,node in nodes.items()}}
        with self.connect() as db:
            db.execute('''INSERT INTO templates(key,payload,checksum,uses,touched) VALUES(?,?,?,1,unixepoch())
                ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,checksum=excluded.checksum,
                uses=templates.uses+1,touched=unixepoch()''',(key,json.dumps(payload,sort_keys=True),digest(payload)))
            db.execute('''DELETE FROM templates WHERE key IN
                (SELECT key FROM templates ORDER BY touched DESC,key LIMIT -1 OFFSET 256)''')
        return compiled, {'status':status,'template_id':key,'format':'aggregation-ir-v1',
            'cached':'aggregation AST only','parameters_bound_fresh':['start','end','filters','limit'],
            'execution_recompiled':True,'results_cached':False}

    def stats(self):
        with self.connect() as db:
            count,uses = db.execute('SELECT count(*),coalesce(sum(uses),0) FROM templates').fetchone()
        return {'entries':count,'uses':uses,'capacity':256,'results_cached':False}
