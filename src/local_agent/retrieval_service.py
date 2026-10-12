"""阶段一：统一词法候选服务与首次决策Broker，不伪称已接入Dense/RRF。"""
import re
from pydantic import BaseModel, ConfigDict
from .retrieval import KnowledgeRetriever
from .semantic import file_hash
from .semantic_context import SemanticContextResolver, asset_version


class Discovery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: str
    hits: list[dict]
    candidates: list[dict]
    ambiguities: list[dict]
    registry_version: str
    index_version: str
    trace: dict


class RetrievalService:
    def __init__(self, tools):
        self.tools = tools
        self.lexical = KnowledgeRetriever(tools)

    def retrieve(self, question, limit=6):
        self.tools.access.role()
        if file_hash(self.tools.registry.path) != self.tools.registry.version:
            raise ValueError('Registry changed; restart and republish required')
        before = asset_version(self.tools)
        hits = self.lexical.search(question, limit)
        exact = set(self.lexical.metric_candidates(question))
        text = question.casefold()
        for identifier in self.tools.registry.contract['metrics']:
            if re.search(r'(?<![a-z0-9_@])'+re.escape(identifier.casefold())+r'(?![a-z0-9_@])', text) and self.tools._metric_allowed(identifier):
                exact.add(identifier)
        for identifier, spec in self.tools.registry.contract.get('multi_fact', {}).get('ratios', {}).items():
            if all(self.tools._metric_allowed(spec[k]) for k in ('numerator', 'denominator')) and any(a.casefold() in text for a in spec.get('aliases', [identifier])):
                exact.add(identifier)
        ranked = [h for h in hits if h.get('kind') == 'metric']
        ordered = list(sorted(exact)) + [h['metric_id'] for h in ranked if h['metric_id'] not in exact]
        version = asset_version(self.tools)
        if before != version:
            raise ValueError('Retrieval assets changed during search; retry with a current snapshot')
        candidates = [{'metric_id': identifier, 'match': 'exact' if identifier in exact else 'lexical',
            'rank': i+1, 'registry_version': self.tools.registry.version,
            'index_version': version} for i, identifier in enumerate(ordered[:6])]
        ambiguities = [{'term': term, 'options': [m for m in ids if self.tools._metric_allowed(m)]}
                       for term, ids in self.lexical.business['ambiguous'].items() if term.casefold() in text]
        for hit in hits:
            hit['registry_version'] = self.tools.registry.version
            hit['index_version'] = version
        return Discovery(status='CLARIFY' if ambiguities else 'CANDIDATES' if candidates else 'NO_MATCH',
            hits=hits, candidates=candidates, ambiguities=ambiguities,
            registry_version=self.tools.registry.version, index_version=version,
            trace={'method': 'exact + cached BM25-style lexical; no dense/RRF/reranker',
                'scope': 'authorized metric assets, cases and references',
                'index_builds': self.lexical.index_builds,
                'requires_structured_resolution': True, 'scores_are_probabilities': False}).model_dump()


class QueryContextBroker:
    def __init__(self, tools, retrieval=None):
        self.tools = tools
        self.retrieval = retrieval or get_retrieval_service(tools)
        self.resolver = SemanticContextResolver(tools)

    def prepare(self, question, previous_task=None):
        discovery = self.retrieval.retrieve(question)
        # 首次决策只看短预览；完整文本仍能通过按需检索读取。
        for hit in discovery['hits']:
            if len(hit['text']) > 1500:
                hit['text'] = hit['text'][:1500]
                hit['text_truncated'] = True
        exact = [c['metric_id'] for c in discovery['candidates'] if c['match'] == 'exact']
        ids = exact or ([previous_task['query']['metric_id']] if previous_task else
                        [c['metric_id'] for c in discovery['candidates'][:2]])
        if discovery['ambiguities']:
            ids = list(dict.fromkeys(m for a in discovery['ambiguities'] for m in a['options']))[:4]
        structured = self.resolver.resolve(ids, expected_asset_version=discovery['index_version']) if ids else None
        return {'version': 'phase1', 'discovery': discovery, 'semantic_context': structured,
                'unresolved': ['ambiguous_business_term:'+a['term'] for a in discovery['ambiguities']],
                'routing': 'exact_then_structured' if exact else 'lexical_then_structured',
                'role': 'grounded candidates for decisions; not an execution plan',
                'values_loaded': False}


def get_retrieval_service(tools):
    service = getattr(tools, 'retrieval_service', None)
    if service is None or service.tools is not tools:
        service = RetrievalService(tools)
        tools.retrieval_service = service
    return service
