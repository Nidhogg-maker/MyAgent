"""新增指标用原始订单独立对账；语义约束和目录上下文必须可执行验证。"""
import duckdb
import pytest
from local_agent.semantic import ROOT, Query
from local_agent.service import AgentTools
from local_agent.harness import build_agent
from local_agent.retrieval_context import resolve_context

@pytest.fixture(scope='module')
def tools(tmp_path_factory):
    service = AgentTools(tmp_path_factory.mktemp('commerce-v2'))
    service.publish(ROOT/'data/thelook.duckdb',ROOT/'warehouse-commerce/target/manifest.json',ROOT/'docs/thelook-dbt-run-results.json')
    return service

@pytest.mark.parametrize('code,status',[('complete','Complete'),('cancelled','Cancelled'),('returned','Returned')])
@pytest.mark.parametrize('ratio',[False,True])
def test_status_metrics_reconcile_raw(tools,code,status,ratio):
    metric = f'{code}_order_{"rate" if ratio else "count"}@1'
    request = Query(metric_id=metric,start='2026-09-01',end='2026-10-01',filters={'gender':'M'})
    planned = tools.plan(request)
    actual = tools.execute(planned['plan_id'],planned['approval_hash'])['rows'][0][0]
    with duckdb.connect(tools.release()['database'],read_only=True) as db:
        numerator,denominator = db.execute("""SELECT count(*) FILTER(WHERE o.status=?),count(*)
            FROM raw.orders o JOIN raw.users u ON o.user_id=u.id
            WHERE cast(timezone('UTC',o.created_at) AS date)>=DATE '2026-09-01'
              AND cast(timezone('UTC',o.created_at) AS date)<DATE '2026-10-01' AND u.gender='M'""",[status]).fetchone()
    assert float(actual) == pytest.approx(numerator/denominator if ratio else numerator)

def test_rate_rejects_status_filter_and_group(tools):
    for kwargs in ({'filters':{'order_status':'Complete'}},{'group_by':['order_status']}):
        with pytest.raises(ValueError,match='Illegal dimension'):
            tools.plan(Query(metric_id='complete_order_rate@1',start='2026-09-01',end='2026-10-01',**kwargs))

def test_empty_cohort_null_ratio(tools):
    planned=tools.plan(Query(metric_id='complete_order_rate@1',start='2010-01-01',end='2010-01-02'))
    assert tools.execute(planned['plan_id'],planned['approval_hash'])['rows']==[[None]]

def test_typed_context_and_authority_conflict(tools):
    result=build_agent(tools).invoke({'query_input':{'metric_id':'complete_order_rate@1','start':'2026-09-01','end':'2026-10-01'}})
    assert result['status']=='COMPLETE'
    context=result['retrieval_context']
    assert context['semantic']['numerator']=='complete_order_count@1'
    assert 'order_status' not in context['constraints']['allowed_dimensions']
    assert context['release_id']==tools.release()['release_id']
    with pytest.raises(ValueError,match='authority conflict'):
        resolve_context(tools,'complete_order_rate@1',[{'metric_id':'complete_order_rate@1','kind':'metric','source':'untrusted'}])

def test_snapshot_ratio_diagnosis_is_not_causal(tools):
    current={'metric_id':'complete_order_rate@1','start':'2026-09-01','end':'2026-09-08','filters':{'gender':'M'}}
    baseline={**current,'start':'2026-08-01','end':'2026-08-08'}
    result=build_agent(tools).invoke({'task_input':{'kind':'diagnose','query':current,'baseline':baseline,'expected_direction':'unknown'}})
    report=result['result']
    assert report['queries_used']==6 and report['causal_claim'] is False
    assert report['status']=='INSUFFICIENT_EVIDENCE'
    assert 'snapshot_status_cohort_maturity_unverified' in report['unresolved']
    assert abs(report['decompositions'][0]['residual']) < 1e-9
