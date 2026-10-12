"""统一权威语义解析：候选只提供ID，定义从当前Registry重新读取。"""
from pydantic import BaseModel, ConfigDict, Field
from .semantic import ROOT, file_hash
from pathlib import Path
from .integrity import fingerprint


def asset_version(tools):
    return fingerprint({'registry': tools.registry.version,
        'knowledge': file_hash(ROOT/'knowledge/business.json'),
        'references': {p.name: file_hash(p) for p in sorted((ROOT/'skills/warehouse-anomaly-attribution/references').glob('*.md'))},
        'implementation': 'unified-assets-v1',
        'builder': file_hash(Path(__file__).with_name('assets.py'))})


class SemanticContext(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: str = 'phase1'
    binding: dict
    requested_metric_ids: list[str]
    metrics: dict
    components: dict
    common_dimensions: list[str]
    relationships: list[dict]
    constraints: dict
    metadata: dict
    dimension_values: dict = Field(default_factory=dict)
    unresolved: list[str] = Field(default_factory=list)
    index_evidence: dict = Field(default_factory=dict)


class SemanticContextResolver:
    def __init__(self, tools):
        self.tools = tools

    def binding(self):
        self.tools.access.role()
        if file_hash(self.tools.registry.path) != self.tools.registry.version:
            raise ValueError('Registry changed; restart and republish required')
        release = self.tools.release()
        from .structure import graph_binding
        return {'registry_version': self.tools.registry.version, 'release_id': release['release_id'],
                'asset_version': asset_version(self.tools), 'subject': self.tools.principal,
                'policy_hash': self.tools.access.policy_hash,'structured_index':graph_binding()}

    def resolve(self, metric_ids, requested_dimensions=(), value_dimensions=(), expected_asset_version=None):
        ids = list(dict.fromkeys(metric_ids))
        if not 1 <= len(ids) <= 6 or len(requested_dimensions) > 4 or len(value_dimensions) > 2:
            raise ValueError('Semantic context budget exceeded')
        binding = self.binding()
        if expected_asset_version and expected_asset_version != binding['asset_version']:
            raise ValueError('Stale semantic discovery; retrieve current candidates')
        registry = self.tools.registry
        metrics, components, metadata = {}, {}, {}
        def load(identifier, trail=()):
            if identifier in trail or len(trail) >= 8:
                raise ValueError('Cyclic/excessive semantic components')
            if identifier in metrics:
                return
            joint = registry.contract.get('multi_fact', {}).get('ratios', {}).get(identifier)
            if joint:
                for child in (joint['numerator'], joint['denominator']):
                    load(child, trail+(identifier,))
                metrics[identifier] = {**joint, 'metric_id': identifier, 'kind': 'cross_fact_ratio',
                    'authority': 'contracts/commerce.json#multi_fact/ratios/'+identifier}
                components[identifier] = [joint['numerator'], joint['denominator']]
                return
            metric = self.tools.describe(identifier)  # 先授权再读取Schema/Owner等元数据。
            metrics[identifier] = {**metric, 'authority': 'contracts/commerce.json#metrics/'+identifier}
            table = metric['fact']['table']
            if table not in metadata:
                metadata[table] = self.tools.access.redact_metadata(self.tools.catalog.context(table))
            children = [metric[k] for k in ('numerator', 'denominator') if k in metric]
            components[identifier] = children
            for child in children:
                load(child, trail+(identifier,))
        for identifier in ids:
            load(identifier)
        leaves = [m for m in metrics.values() if 'fact' in m]
        common = set.intersection(*(set(m['fact']['dimensions']) | {'day'} for m in leaves))
        facts = {registry.contract['metrics'][m['metric_id']]['fact'] for m in leaves}
        joint = registry.contract.get('multi_fact', {})
        relationships = []
        if len(facts) > 1:
            common &= {d for d, mapping in joint.get('conformed_dimensions', {}).items() if facts <= set(mapping)}
            relationships.append({'kind': 'aggregate_then_join', 'facts': sorted(facts),
                'common_dimensions': sorted(common),
                'time_basis': {f: joint.get('time_basis', {}).get(f) for f in sorted(facts)},
                'population_requires_explicit_choice': True,
                'raw_join_allowed': False})
        unresolved = ['incompatible_dimension:'+d for d in requested_dimensions if d not in common]
        if len(facts) > 1:
            bases = {joint.get('time_basis', {}).get(f) for f in facts}
            if None in bases or len(bases) != 1:
                unresolved.append('incompatible_fact_time_basis')
        values = {}
        if value_dimensions:
            from .dimensions import DimensionResolver
            resolver = DimensionResolver(self.tools)
            for dimension in value_dimensions:
                if dimension not in common or dimension == 'day':
                    unresolved.append('value_discovery_not_supported:'+dimension)
                    continue
                values[dimension] = {m['metric_id']: resolver.values(m['metric_id'], dimension) for m in leaves}
        from .structure import GraphService
        index_evidence = GraphService(self.tools).evidence()
        return SemanticContext(binding=binding, requested_metric_ids=ids, metrics=metrics,
            index_evidence=index_evidence,
            components=components, common_dimensions=sorted(common), relationships=relationships,
            metadata=metadata, constraints={'timezone': registry.contract['timezone'], 'maximum_window_days': 31,
                'row_scope': self.tools.access.role()['row_filters'],
                'minimum_group_size': self.tools.access.role()['minimum_group_size'],
                'formula_source': 'current registry; never search text', 'implicit_join_allowed': False},
            dimension_values=values, unresolved=unresolved).model_dump(mode='json')

    def validate(self, context, metric_ids):
        context = SemanticContext.model_validate(context)
        if context.binding != self.binding() or not set(metric_ids) <= set(context.metrics):
            raise ValueError('Semantic context binding/metric scope changed')
        current = self.resolve(context.requested_metric_ids)
        if any(getattr(context, field) != current[field] for field in (
                'metrics', 'components', 'constraints', 'common_dimensions', 'relationships')):
            raise ValueError('Semantic context authority changed or content tampered')
        return context

    def resolve_request(self, query):
        from .multi_fact import MultiFactQuery
        ids = list(query.metric_ids)+list(query.ratio_ids) if isinstance(query, MultiFactQuery) else [query.metric_id]
        context = self.resolve(ids, requested_dimensions=query.group_by)
        if context['unresolved']:
            raise ValueError('Illegal dimension in semantic context: '+','.join(context['unresolved']))
        return context
