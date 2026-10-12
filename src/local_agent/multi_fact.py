"""多事实先各自聚合再关联：模型选择指标与目标 Grain，不能选择物理 Join 键。"""
import datetime as dt
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlglot import exp
from .semantic import Query, SQLCompiler


class MultiFactQuery(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    kind: Literal['multi_fact'] = 'multi_fact'
    metric_ids: tuple[str, ...] = Field(min_length=2, max_length=4)
    ratio_ids: tuple[str, ...] = ()
    start: dt.date
    end: dt.date
    group_by: tuple[str, ...] = ()
    filters: dict[str, str] = Field(default_factory=dict)
    # 保留哪一侧的组是业务语义，必须明确，不能作为优化器的自由选择。
    population: Literal['union', 'intersection']
    limit: int = Field(default=100, ge=1, le=1000)

    @model_validator(mode='after')
    def bounds(self):
        Query(metric_id=self.metric_ids[0], start=self.start, end=self.end,
              group_by=self.group_by, filters=self.filters, limit=self.limit)
        if len(set(self.metric_ids)) != len(self.metric_ids):
            raise ValueError('Duplicate multi-fact metrics')
        if len(set(self.ratio_ids)) != len(self.ratio_ids) or len(self.ratio_ids) > 2:
            raise ValueError('Duplicate/excessive cross-fact ratios')
        return self

    def branch(self, metric_id):
        return Query(metric_id=metric_id, start=self.start, end=self.end,
                     group_by=self.group_by, filters=self.filters, limit=self.limit)


def parse_query(value):
    """持久计划重验时按显式类型解析，不允许通过额外字段绕过旧 Query。"""
    return MultiFactQuery.model_validate(value) if value.get('kind') == 'multi_fact' else Query.model_validate(value)


class MultiFactCompiler:
    def __init__(self, registry):
        self.registry = registry

    def compile(self, query, minimum_group_size=0):
        contract = self.registry.contract.get('multi_fact', {})
        if not contract:
            raise ValueError('Multi-fact contract is missing')
        metrics = [self.registry.describe(m) for m in query.metric_ids]
        fact_ids = [self.registry.contract['metrics'][m]['fact'] for m in query.metric_ids]
        if len(set(fact_ids)) < 2:
            raise ValueError('Multi-fact request must contain different facts')
        time_bases = {contract.get('time_basis', {}).get(f) for f in fact_ids}
        if None in time_bases or len(time_bases) != 1:
            raise ValueError('Fact time semantics are not conformed')
        conformed = contract.get('conformed_dimensions', {})
        for dimension in set(query.group_by) | set(query.filters):
            if dimension not in conformed or not set(fact_ids) <= set(conformed[dimension]):
                raise ValueError('Unregistered common dimension; no inferred join: ' + dimension)
            # 首版只支持各事实中已实体化的同名维度；day 对应各自合法日期列。
            if any(conformed[dimension][f] != ('day' if dimension == 'day' else dimension) for f in fact_ids):
                raise ValueError('Dimension mapping needs an explicit adapter')
        ratio_specs = []
        for identifier in query.ratio_ids:
            spec = contract.get('ratios', {}).get(identifier)
            if not spec or not {spec['numerator'], spec['denominator']} <= set(query.metric_ids):
                raise ValueError('Unknown/missing registered cross-fact ratio components')
            if any(self.registry.describe(spec[k])['kind'] == 'ratio' for k in ('numerator', 'denominator')):
                raise ValueError('Ratio-of-ratios is not supported')
            ratio_specs.append((identifier, spec))

        compiler = SQLCompiler(self.registry)
        branches = []
        logical = []
        for i, identifier in enumerate(query.metric_ids):
            # 分支不能先 LIMIT 再 Join：先完整聚合，最后限制展示结果。
            branch = compiler.compile(query.branch(identifier), minimum_group_size)
            # AST 由受控单事实编译器生成，不接受模型 SQL。
            import sqlglot
            sql = sqlglot.parse_one(branch['sql'], read='duckdb')
            sql.set('limit', None); sql.set('order', None)
            branches.append(exp.CTE(this=sql, alias=exp.TableAlias(this=exp.to_identifier(f'b{i}'))))
            logical.append({'metric_id': identifier, 'source_grain': metrics[i]['fact']['grain'],
                            'target_grain': list(query.group_by), 'scan': branch['table'],
                            'aggregation': branch['logical_plan']['aggregation']})

        n = len(branches)
        dims = list(query.group_by)
        selected = []
        for d in dims:
            values = [exp.column(d, table=f'b{i}') for i in range(n)]
            selected.append(exp.Coalesce(this=values[0], expressions=values[1:]).as_(d))
        selected += [exp.column('value', table=f'b{i}').as_(m, quoted=True)
                     for i, m in enumerate(query.metric_ids)]
        for identifier, spec in ratio_specs:
            numerator = exp.column('value', table=f'b{query.metric_ids.index(spec["numerator"])}')
            denominator = exp.column('value', table=f'b{query.metric_ids.index(spec["denominator"])}')
            selected.append(exp.Div(this=exp.Cast(this=numerator, to=exp.DataType.build('DOUBLE')),
                            expression=exp.Nullif(this=denominator, expression=exp.Literal.number(0))).as_(identifier, quoted=True))
        statement = exp.select(*selected).from_('b0')
        for i in range(1, n):
            if not dims:
                statement = statement.join(f'b{i}', join_type='CROSS')
            else:
                # 聚合后每组唯一；NULL 维度也能正确匹配，避免生成重复 NULL 组。
                conditions = []
                for d in dims:
                    prior = [exp.column(d, table=f'b{j}') for j in range(i)]
                    left = prior[0] if len(prior) == 1 else exp.Coalesce(this=prior[0], expressions=prior[1:])
                    conditions.append(exp.NullSafeEQ(this=left, expression=exp.column(d, table=f'b{i}')))
                statement = statement.join(f'b{i}', on=exp.and_(*conditions),
                    join_type='FULL OUTER' if query.population == 'union' else 'INNER')
        statement.set('with_', exp.With(expressions=branches))
        if dims:
            statement = statement.order_by(*[exp.column(d) for d in dims])
        statement = statement.limit(query.limit)
        tables = list(statement.find_all(exp.Table))
        allowed = {m['fact']['table'] for m in metrics} | {f'b{i}' for i in range(n)}
        if any(t.sql() not in allowed for t in tables):
            raise ValueError('Generated multi-fact SQL references an unregistered table')
        return {'sql': statement.sql(dialect='duckdb'), 'table': metrics[0]['fact']['table'],
                'tables': list(dict.fromkeys(m['fact']['table'] for m in metrics)),
                'grain': dims or ['scalar'], 'metric': list(query.metric_ids) + list(query.ratio_ids),
                'unit': {**{m: self.registry.describe(m)['unit'] for m in query.metric_ids},
                         **{m: spec['unit'] for m, spec in ratio_specs}},
                'definition': {'metrics': {m: self.registry.describe(m)['definition'] for m in query.metric_ids},
                               'ratios': dict(ratio_specs)},
                'logical_plan': {'branches': logical, 'target_grain': dims or ['scalar'],
                    'join_policy': 'aggregate each fact before joining conformed keys',
                    'population': query.population, 'null_semantics': 'missing branch stays null; not zero',
                    'timezone': self.registry.contract['timezone'], 'time_basis': next(iter(time_bases)),
                    'semantic_version': self.registry.version},
                'multi_fact': True}
