"""自建语义注册表与编译器：先约束 Grain，再生成受控 SQL AST。"""
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
import sqlglot
from sqlglot import exp

ROOT = Path(__file__).resolve().parents[2]

def file_hash(path):
    """流式校验大文件，避免把整个数仓加载进 Python 内存。"""
    h = hashlib.sha256()
    with Path(path).open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

class Query(BaseModel):
    """模型只能提交结构化意图；不接受 SQL、表名、任意表达式或身份参数。"""
    model_config = ConfigDict(extra='forbid', frozen=True)
    metric_id: str
    start: dt.date
    end: dt.date
    group_by: tuple[str, ...] = ()
    filters: dict[str, str] = Field(default_factory=dict)
    limit: int = Field(default=100, ge=1, le=1000)

    @model_validator(mode='after')
    def bounds(self):
        if not 0 < (self.end - self.start).days <= 31:
            raise ValueError('Window must be closed-open and at most 31 days')
        if len(self.group_by) != len(set(self.group_by)) or len(self.group_by) > 4:
            raise ValueError('Duplicate or excessive dimensions')
        return self

class SemanticRegistry:
    """指标口径唯一来源；支持受限单事实查询，拒绝隐式多事实关联。"""
    def __init__(self, path=ROOT / 'contracts/commerce.json'):
        self.path = Path(path)
        self.contract = json.loads(self.path.read_text(encoding='utf-8'))
        self.version = file_hash(self.path)

    def describe(self, metric_id):
        if metric_id not in self.contract['metrics']:
            raise ValueError('Unknown/versionless metric: ' + metric_id)
        metric = self.contract['metrics'][metric_id]
        fact = dict(self.contract['facts'][metric['fact']])
        if 'allowed_dimensions' in metric:
            fact['dimensions'] = metric['allowed_dimensions']
        return {**metric, 'metric_id': metric_id, 'fact': fact, 'contract_version': self.contract['version']}

class SQLCompiler:
    """自行实现聚合规则，SQLGlot 负责 AST；没有调用 MetricFlow 编译器。"""
    def __init__(self, registry):
        self.registry = registry

    def expression(self, metric_id, seen=()):
        """递归展开比例，检测循环；比例在聚合后计算，防止平均日均值。"""
        if metric_id in seen:
            raise ValueError('Cyclic metric definition')
        m = self.registry.describe(metric_id)
        kind = m['kind']
        column = exp.column(m['column']) if 'column' in m else None
        if kind == 'count':
            return exp.Count(this=exp.Star())
        if kind == 'sum':
            return exp.Sum(this=column)
        if kind == 'distinct':
            return exp.Count(this=exp.Distinct(expressions=[column]))
        if kind == 'conditional_count':
            # 数订单本身，而非明细行；COUNT(CASE) 在空窗口返回0。
            condition = exp.EQ(this=exp.column(m['condition_column']), expression=exp.Literal.string(m['condition_value']))
            return exp.Count(this=exp.Case(ifs=[exp.If(this=condition, true=exp.Literal.number(1))]))
        if kind == 'conditional_sum':
            condition = exp.EQ(this=exp.column(m['condition_column']), expression=exp.Literal.string(m['condition_value']))
            return exp.Sum(this=exp.Case(ifs=[exp.If(this=condition, true=column)], default=exp.Literal.number(0)))
        if kind == 'ratio':
            for child in ('numerator', 'denominator'):
                if self.registry.describe(m[child])['fact']['table'] != m['fact']['table']:
                    raise ValueError('Cross-fact ratio requires explicit planning; unsupported')
            numerator = self.expression(m['numerator'], seen + (metric_id,))
            denominator = self.expression(m['denominator'], seen + (metric_id,))
            return exp.Div(this=exp.Cast(this=numerator, to=exp.DataType.build('DOUBLE')), expression=exp.Nullif(this=denominator, expression=exp.Literal.number(0)))
        raise ValueError('Unsupported metric aggregation')

    def compile(self, query: Query, minimum_group_size=0):
        """表/字段来自受信合同；过滤值构建为 SQL 字面量，不能改变 SQL 结构。"""
        metric = self.registry.describe(query.metric_id)
        fact = metric['fact']
        allowed = set(fact['dimensions'])
        if not set(query.group_by) <= allowed | {'day'} or not set(query.filters) <= allowed:
            raise ValueError('Illegal dimension for fact grain; no implicit joins')
        dims = [exp.column(fact['date'] if d == 'day' else d) for d in query.group_by]
        selected = [node.copy().as_(label) for node, label in zip(dims, query.group_by)]
        statement = exp.select(*selected, self.expression(query.metric_id).as_('value')).from_(fact['table'])
        conditions = [exp.GTE(this=exp.column(fact['date']), expression=exp.Cast(this=exp.Literal.string(query.start.isoformat()), to=exp.DataType.build('DATE'))),
                      exp.LT(this=exp.column(fact['date']), expression=exp.Cast(this=exp.Literal.string(query.end.isoformat()), to=exp.DataType.build('DATE')))]
        conditions += [exp.EQ(this=exp.column(key), expression=exp.Literal.string(value)) for key, value in query.filters.items()]
        statement = statement.where(exp.and_(*conditions))
        if dims:
            statement = statement.group_by(*dims).order_by(*[exp.column(d) for d in query.group_by])
        if minimum_group_size:
            # 在SQL执行层抑制小组，不能只在最终自然语言回答里遮盖敏感结果。
            statement = statement.having(exp.GTE(this=exp.Count(this=exp.Star()), expression=exp.Literal.number(minimum_group_size)))
        sql = statement.limit(query.limit).sql(dialect='duckdb')
        parsed = sqlglot.parse(sql, read='duckdb')
        tables = list(parsed[0].find_all(exp.Table))
        if len(parsed) != 1 or not isinstance(parsed[0], exp.Select) or len(tables) != 1 or tables[0].sql() != fact['table']:
            raise ValueError('Generated SQL violates single-fact policy')
        return {'sql': sql, 'table': fact['table'], 'grain': fact['grain'], 'unit': metric['unit'], 'metric': query.metric_id, 'definition': metric['definition'],
                'logical_plan':{'scan':fact['table'],'grain':fact['grain'],'time_column':fact['date'],
                    'window':{'start':query.start.isoformat(),'end':query.end.isoformat(),'timezone':self.registry.contract['timezone']},
                    'filters':dict(query.filters),'group_by':list(query.group_by),'aggregation':metric['kind'],
                    'components':{name:metric[name] for name in ('numerator','denominator') if name in metric},
                    'semantic_version':self.registry.version,'join_policy':'single fact; no inferred join'}}
