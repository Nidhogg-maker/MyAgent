"""工程契约测试使用确定性替身；真实神经向量验证见独立 demo。"""
import json
import pytest
from test_multi_plan_fact import small_service
from local_agent.retrieval import KnowledgeRetriever
from local_agent.retrieval_service import RetrievalService
from local_agent.dense_retrieval import DenseIndex, publish_index, rrf, asset_id, normalized
from local_agent.runtime import HarnessRuntime


class FakeEmbedding:
    identity = {'model': 'test-only', 'revision': 'fixture'}
    def encode(self, texts, kind):
        return [[1., 0.] for _ in texts]


@pytest.fixture
def index(small_service, tmp_path):
    tools, _ = small_service
    lexical = KnowledgeRetriever(tools)
    directory = tmp_path/'index'
    manifest = publish_index(tools, lexical, FakeEmbedding(), directory)
    return tools, lexical, directory, manifest


def test_rrf_rank_only_stable_id_and_dedup():
    a = {'kind':'metric','id':'a','source':'registry/a','score':999999}
    b = {'kind':'metric','id':'b','source':'registry/b','score':.2}
    hits = rrf([a, a, b], [b, a])
    assert len(hits) == 2
    assert hits[0]['id'] == 'a'
    assert hits[0]['score'] == pytest.approx(1/61+1/62)
    assert hits[1]['ranks']['lexical'] == 2
    assert asset_id(a) != asset_id({**a, 'kind':'case'})


def test_published_dense_shape_and_authorization_before_topk(index):
    tools, lexical, directory, manifest = index
    permitted = [d for d in lexical._index[0] if d['id'] == 'order_count@1']
    hits, trace = DenseIndex(directory, lambda _: FakeEmbedding()).search('订单', tools, permitted, 1)
    assert [h['id'] for h in hits] == ['order_count@1']
    assert trace['visible_assets'] == 1 and trace['dimension'] == 2
    assert trace['snapshot_id'] == manifest['snapshot_id']


def test_corrupt_vector_file_rejected(index):
    tools, lexical, directory, _ = index
    pointer = json.loads((directory/'active.json').read_text())
    (directory/pointer['folder']/'vectors.json').write_text('[]')
    with pytest.raises(ValueError, match='checksum'):
        DenseIndex(directory).search('订单', tools, lexical._index[0])


def test_stale_index_rejected(index, monkeypatch):
    tools, lexical, directory, _ = index
    monkeypatch.setattr('local_agent.dense_retrieval.asset_version', lambda _: 'new')
    with pytest.raises(ValueError, match='stale_dense'):
        DenseIndex(directory).search('订单', tools, lexical._index[0])


def test_failed_build_keeps_old_active(index):
    tools, lexical, directory, _ = index
    before = (directory/'active.json').read_bytes()
    class Bad(FakeEmbedding):
        def encode(self, texts, kind): return [[0.,0.] for _ in texts]
    with pytest.raises(ValueError, match='normalized'):
        publish_index(tools, lexical, Bad(), directory,incremental=False)
    assert (directory/'active.json').read_bytes() == before


def test_missing_index_fallback_and_required_stop(small_service, tmp_path, monkeypatch):
    tools, _ = small_service
    monkeypatch.setenv('OWN_AGENT_DENSE_INDEX', str(tmp_path/'missing'))
    monkeypatch.setenv('OWN_AGENT_RETRIEVAL_MODE', 'hybrid')
    result = RetrievalService(tools).retrieve('订单数')
    assert result['trace']['dense']['status'] == 'fallback'
    assert result['candidates'][0]['match'] == 'exact'
    monkeypatch.setenv('OWN_AGENT_RETRIEVAL_MODE', 'hybrid-required')
    with pytest.raises(ValueError, match='required'):
        RetrievalService(tools).retrieve('订单数')


def test_fusion_reaches_broker_and_ambiguity_remains(index, monkeypatch):
    from local_agent.retrieval_service import QueryContextBroker
    tools, _, directory, _ = index
    monkeypatch.setenv('OWN_AGENT_RETRIEVAL_MODE', 'hybrid')
    monkeypatch.setenv('OWN_AGENT_DENSE_INDEX', str(directory))
    monkeypatch.setattr('local_agent.dense_retrieval.LocalEmbeddingProvider.encode', FakeEmbedding.encode)
    result = QueryContextBroker(tools).prepare('2026年9月每张订单的金额')
    assert result['version'] == 'phase2'
    assert result['discovery']['trace']['dense']['status'] == 'ready'
    assert any('dense' in h['ranks'] for h in result['discovery']['hits'])
    assert result['semantic_context'] and not result['values_loaded']
    assert QueryContextBroker(tools).prepare('销售额')['discovery']['status'] == 'CLARIFY'


def test_snapshot_change_invalidates_session_binding(index, monkeypatch):
    tools, lexical, directory, _ = index
    monkeypatch.setenv('OWN_AGENT_RETRIEVAL_MODE', 'hybrid')
    monkeypatch.setenv('OWN_AGENT_DENSE_INDEX', str(directory))
    runtime = HarnessRuntime(tools)
    before = runtime.binding()
    publish_index(tools, lexical, FakeEmbedding(), directory)
    assert before != runtime.binding()


@pytest.mark.parametrize('vectors', [[[float('nan'),0]], [[0,0]], [[1,0],[1]]])
def test_invalid_vectors_rejected(vectors):
    with pytest.raises(ValueError): normalized(vectors)


def test_hybrid_preserves_search_budget(small_service, monkeypatch):
    tools, _ = small_service
    monkeypatch.setenv('OWN_AGENT_RETRIEVAL_MODE', 'hybrid')
    with pytest.raises(ValueError, match='budget'):
        RetrievalService(tools).retrieve('订单', 0)


def test_index_switch_during_search_stops(index, monkeypatch):
    tools, lexical, directory, _ = index
    monkeypatch.setenv('OWN_AGENT_RETRIEVAL_MODE', 'hybrid')
    monkeypatch.setenv('OWN_AGENT_DENSE_INDEX', str(directory))
    def switch(self, texts, kind):
        publish_index(tools, lexical, FakeEmbedding(), directory)
        return [[1.,0.]]
    monkeypatch.setattr('local_agent.dense_retrieval.LocalEmbeddingProvider.encode', switch)
    with pytest.raises(ValueError, match='changed during search'):
        RetrievalService(tools).retrieve('订单')


def test_restricted_subject_cannot_publish(index):
    from local_agent.service import AgentTools
    tools, lexical, directory, _ = index
    restricted = AgentTools(tools.home, token=tools.access.issue('us-analyst'))
    with pytest.raises(PermissionError, match='administrator'):
        publish_index(restricted, KnowledgeRetriever(restricted), FakeEmbedding(), directory)
    restricted_lexical = KnowledgeRetriever(restricted)
    restricted_lexical.search('订单', 10)
    hits, _ = DenseIndex(directory, lambda _: FakeEmbedding()).search('订单', restricted, restricted_lexical._index[0], 10)
    assert any(h.get('metric_id') == 'order_count@1' for h in hits)
    assert all(h['metric_id'] != 'buyer_count@1' for h in hits if h['kind'] == 'metric')
    assert all('gender' not in h.get('allowed_dimensions', []) for h in hits)
