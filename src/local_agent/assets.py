"""Registry 唯一权威同时派生 Flat 文档和 Structured 关系；不是自由实体抽取。"""
import json
from .semantic import ROOT, file_hash


class AssetBuilder:
    def __init__(self, tools, business=None, root=ROOT):
        self.tools, self.root = tools, root
        self.business = business or json.loads((root/'knowledge/business.json').read_text(encoding='utf-8'))

    def build(self, references=None):
        contract = self.tools.registry.contract
        nodes, edges, documents = {}, set(), []
        role = self.tools.access.role()
        specs = {**contract['metrics'],**contract.get('multi_fact',{}).get('ratios',{})}
        visible = {}
        def permitted(identifier, trail=()):
            if identifier in trail or len(trail)>=8:
                raise ValueError('Cyclic/excessive asset components')
            if identifier not in specs:
                raise ValueError('Dangling registered metric component: '+identifier)
            spec = specs[identifier]
            children = [spec[k] for k in ('numerator','denominator') if k in spec]
            allowed = identifier not in contract['metrics'] or self.tools._metric_allowed(identifier)
            children_allowed = [permitted(child,trail+(identifier,)) for child in children]
            return allowed and all(children_allowed)
        for identifier in specs:
            visible[identifier] = permitted(identifier)

        def node(identifier,kind,**properties):
            nodes[identifier] = {'id':identifier,'kind':kind,**properties}
            return identifier
        def edge(source,target,kind):
            edges.add((source,target,kind))
        def field(table,column):
            if '*' not in role['dimensions'] and column in self.tools.access.policy['sensitive_fields']:
                return None
            return node('field:'+table+':'+column,'field',dataset=table,column=column,
                        provenance='registry declaration; physical schema checked separately')
        for identifier, spec in specs.items():
            if not visible[identifier]:
                continue
            mid = node('metric:'+identifier,'metric',metric_id=identifier,
                       definition=spec['definition'],unit=spec['unit'])
            for key in ('numerator','denominator'):
                if key in spec:
                    edge(mid,'metric:'+spec[key],'metric_component')
            if identifier not in contract['metrics']:
                documents.append({'id':identifier,'kind':'metric','metric_id':identifier,
                    'partition':'multi_fact','text':' '.join([identifier,spec['definition'],spec['unit'],*spec.get('aliases',[])]),
                    'source':'contracts/commerce.json#multi_fact/ratios/'+identifier})
                continue
            described = self.tools.describe(identifier)
            fact_id, fact = spec['fact'], described['fact']
            table = fact['table']
            fid = node('fact:'+fact_id,'fact',fact_id=fact_id,table=table,grain=fact['grain'],
                       time_basis=contract.get('multi_fact',{}).get('time_basis',{}).get(fact_id))
            dataset = node('dataset:'+table,'dataset',table=table)
            entity = node('entity:'+fact_id+':'+fact['grain'],'entity_key',fact_id=fact_id,key=fact['grain'],
                          provenance='declared grain key; not inferred business identity')
            edge(mid,fid,'computed_from_fact'); edge(fid,dataset,'scans_dataset'); edge(fid,entity,'grain_key')
            for column,kind in [(fact['grain'],'grain_field'),(fact['date'],'time_field')]:
                target = field(table,column)
                if target: edge(fid,target,kind)
            for key,kind in [('column','value_dependency'),('condition_column','condition_dependency')]:
                if key in spec:
                    target = field(table,spec[key])
                    if target: edge(mid,target,kind)
            dimensions = list(fact['dimensions'])
            if '*' in role['dimensions'] or 'day' in role['dimensions']:
                dimensions = dimensions + ['day']
            for dimension in dict.fromkeys(dimensions):
                did = node('dimension:'+fact_id+':'+dimension,'dimension',fact_id=fact_id,dimension=dimension)
                edge(mid,did,'allows_dimension')
                target = field(table,fact['date'] if dimension=='day' else dimension)
                if target: edge(did,target,'dimension_field')
            summary = ' '.join([spec['label'],spec['definition'],table,fact['grain'],spec.get('column',''),
                                *self.business['aliases'].get(identifier,[])])
            documents.append({'id':identifier,'kind':'metric','metric_id':identifier,'partition':fact_id,
                'embedding_text':summary,'text':' '.join([spec['label'],spec['definition'],table,fact['grain'],
                    spec.get('column',''),*fact['dimensions'],*self.business['aliases'].get(identifier,[])]),
                'source':'contracts/commerce.json#metrics/'+identifier,'allowed_dimensions':fact['dimensions']})
        for dimension,mapping in contract.get('multi_fact',{}).get('conformed_dimensions',{}).items():
            targets = ['dimension:'+f+':'+d for f,d in mapping.items() if 'dimension:'+f+':'+d in nodes]
            if len(targets)>=2:
                joint = node('conformed:'+dimension,'conformed_dimension',dimension=dimension,
                    join_policy='aggregate_then_join; explicit population required; never raw join')
                for target in targets: edge(joint,target,'registered_conformance')
        for case in self.business['cases']:
            metric = case.get('metric_id')
            if metric and not visible.get(metric,False):
                continue
            documents.append({'id':case['id'],'kind':'case','metric_id':metric,
                'partition':contract['metrics'].get(metric,{}).get('fact','knowledge'),
                'text':case['question']+' '+case['note'],'source':'knowledge/business.json#cases/'+case['id']})
        if references is None:
            references = sorted((self.root/'skills/warehouse-anomaly-attribution/references').glob('*.md'))
        for path in references:
            documents.append({'id':'reference-'+path.stem,'kind':'reference','partition':'knowledge',
                'text':path.read_text(encoding='utf-8'),'source':str(path.relative_to(self.root)),
                'source_sha256':file_hash(path)})
        return {'documents':documents,'graph':{'nodes':sorted(nodes.values(),key=lambda n:n['id']),
            'edges':[{'source':s,'target':t,'kind':k} for s,t,k in sorted(edges)],
            'scope':'registered semantic dependencies; metadata lineage remains separate',
            'implicit_join_allowed':False}}
