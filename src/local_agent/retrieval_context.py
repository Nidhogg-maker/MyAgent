"""两路上下文保留类型和权威边界；案例不能覆盖公式和权限。"""
from pydantic import BaseModel, ConfigDict

class RetrievalContext(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: str = '1'
    metric_id: str
    semantic_version: str
    release_id: str
    knowledge_hits: list[dict]
    semantic: dict
    metadata: dict
    constraints: dict
    conflicts: list[str]
    dimension_values: dict
    metric_components: dict
    retrieval_strategy: str = 'knowledge candidates followed by authoritative structured resolution'

def resolve_context(tools, metric_id, hits):
    """结构化定义重新从授权工具读取，不信任检索副本或模型提供的公式。"""
    release = tools.release()
    context = tools.context(metric_id)
    metric = tools.describe(metric_id)
    conflicts = []
    authoritative = 'contracts/commerce.json#metrics/' + metric_id
    for hit in hits:
        if hit.get('metric_id') == metric_id and hit.get('kind') == 'metric' and hit.get('source') != authoritative:
            conflicts.append('untrusted_metric_source')
    if conflicts:
        raise ValueError('Retrieval authority conflict; stop execution')
    from .dimensions import DimensionResolver
    resolver=getattr(tools,'dimension_resolver',None)
    if resolver is None:
        resolver=DimensionResolver(tools)
        tools.dimension_resolver=resolver
    components={name:tools.describe(metric[name]) for name in ('numerator','denominator') if name in metric}
    return RetrievalContext(metric_id=metric_id,semantic_version=tools.registry.version,
        release_id=release['release_id'],knowledge_hits=hits,semantic=metric,
        metadata=context['metadata'],constraints={
            'timezone':tools.registry.contract['timezone'],
            'allowed_dimensions':metric['fact']['dimensions'],
            'temporal':release['temporal'],'authority':authoritative,
            'formula_source':'semantic registry, never retrieved case text'},conflicts=[],
        dimension_values=resolver.summary(metric_id),metric_components=components).model_dump()
