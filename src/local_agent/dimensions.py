"""维度值链接：业务别名→真实快照枚举，未知值澄清而不是伪零结果。"""
import json
import re
import duckdb
from .semantic import ROOT, Query

class DimensionResolver:
    def __init__(self,tools):
        self.tools=tools
        self.aliases=json.loads((ROOT/'knowledge/business.json').read_text(encoding='utf-8')).get('filter_value_aliases',{})
        self.cache={}

    def values(self,metric_id,dimension):
        metric=self.tools.describe(metric_id)
        if dimension not in metric['fact']['dimensions']: raise ValueError('Illegal dimension')
        role=self.tools.access.metric(metric_id)
        if '*' not in role['dimensions'] and dimension not in role['dimensions']:
            raise ValueError('Dimension access denied')
        release=self.tools.release()
        key=(release['release_id'],metric['fact']['table'],dimension)
        if key not in self.cache:
            # 表/列只来自合同，不拼接用户字符串；输出仅为业务维度枚举。
            scope=''.join(f' AND {field}=?' for field in role['row_filters'])
            with duckdb.connect(release['database'],read_only=True) as db:
                rows=db.execute(f"SELECT DISTINCT CAST({dimension} AS VARCHAR) FROM {metric['fact']['table']} WHERE {dimension} IS NOT NULL{scope} ORDER BY 1 LIMIT 201",list(role['row_filters'].values())).fetchall()
            self.cache[key]={'values':[row[0] for row in rows[:200]],'truncated':len(rows)>200}
        return self.cache[key]

    def resolve(self,metric_id,dimension,value):
        described=self.tools.describe(metric_id)
        canonical=self.aliases.get(dimension,{}).get(value,value)
        options=self.values(metric_id,dimension)
        matching=[v for v in options['values'] if v.casefold()==canonical.casefold()]
        if not matching and options['truncated']:
            release=self.tools.release()
            role=self.tools.access.metric(metric_id)
            scope=''.join(f' AND {field}=?' for field in role['row_filters'])
            with duckdb.connect(release['database'],read_only=True) as db:
                matching=[r[0] for r in db.execute(f"SELECT DISTINCT CAST({dimension} AS VARCHAR) FROM {described['fact']['table']} WHERE lower(CAST({dimension} AS VARCHAR))=lower(?){scope} LIMIT 2",[canonical,*role['row_filters'].values()]).fetchall()]
        if len(matching)!=1:
            raise ValueError(f'CLARIFY: 维度 {dimension} 的值 {value!r} 无法唯一链接到本地数据；可选值示例：'+', '.join(options['values'][:8]))
        return matching[0]

    def query(self,query):
        # 先检查维度与身份，然后链接值；不向无权限主体披露维度枚举。
        role=self.tools.access.metric(query.metric_id)
        if '*' not in role['dimensions'] and not (set(query.group_by)|set(query.filters))<=set(role['dimensions']):
            raise ValueError('Dimension access denied')
        self.tools.compiler.compile(query)
        filters={dimension:self.resolve(query.metric_id,dimension,value) for dimension,value in query.filters.items()}
        resolved=Query.model_validate({**query.model_dump(mode='json'),'filters':filters})
        self.tools.access.enforce(resolved)
        return resolved

    def summary(self,metric_id):
        metric=self.tools.describe(metric_id)
        return {dimension:{'values':data['values'][:30],'truncated':data['truncated'] or len(data['values'])>30}
            for dimension in metric['fact']['dimensions']
            for data in [self.values(metric_id,dimension)]}

    def explicit_filters(self,question,metric_id):
        """保护明确的国家/性别词，防止模型遗漏或偷偷替换用户筛选。"""
        result={}
        for dimension in ('country','gender'):
            if dimension not in self.tools.describe(metric_id)['fact']['dimensions']: continue
            aliases=self.aliases.get(dimension,{})
            found=set()
            for alias,canonical in aliases.items():
                if len(alias)==1: continue
                pattern=r'\b'+re.escape(alias)+r'\b' if alias.isascii() else re.escape(alias)
                if re.search(pattern,question,re.IGNORECASE): found.add(canonical)
            if len(found)==1: result[dimension]=found.pop()
            elif len(found)>1:
                raise ValueError('CLARIFY: 当前只支持单值筛选；请明确比较或分组方式')
        return result
