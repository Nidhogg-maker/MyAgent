"""画像路由、契约篡改、数据缺失与会话标签的实际约束验证。"""
import json
from pathlib import Path
import duckdb
import pytest
from local_agent.semantic import ROOT,file_hash
from local_agent.service import AgentTools
from local_agent.feature_agent import FeatureRequest,FeatureTools,UnifiedRuntime,parse_feature_question,is_feature_question


@pytest.fixture
def feature_env(tmp_path):
    directory=tmp_path/'features/releases/test-release';directory.mkdir(parents=True)
    database=directory/'features.duckdb'
    with duckdb.connect(str(database)) as db:
        db.execute('CREATE SCHEMA ads')
        db.execute('CREATE TABLE ads.ads_user_profile_daily(user_id BIGINT,as_of_date DATE,product_views_7d INTEGER)')
        db.execute("INSERT INTO ads.ads_user_profile_daily VALUES (42,DATE '2026-10-11',5)")
    table='ads.ads_user_profile_daily'
    definition={'columns':{'user_id':'BIGINT','as_of_date':'DATE','product_views_7d':'INTEGER'},'grain':['as_of_date','user_id']}
    for name,data in [('metadata.json',{'tables':{table:definition}}),('table-contracts.json',{'tables':{table:definition}})]:
        (directory/name).write_text(json.dumps(data),encoding='utf-8')
    release={'status':'PASS','release_id':'test-release','as_of_date':'2026-10-11',
        'database':str(database),'database_sha256':file_hash(database),
        'metadata_sha256':file_hash(directory/'metadata.json'),
        'table_contracts_sha256':file_hash(directory/'table-contracts.json'),
        'quality':{'status':'PASS','tables':{table:{'rows':1}}},'source_observed_at':'2026-10-11T10:00:00+00:00'}
    (directory/'release.json').write_text(json.dumps(release),encoding='utf-8')
    return AgentTools(tmp_path/'agent'),tmp_path/'features',directory


def test_natural_and_structured_requests_return_same_feature(feature_env):
    tools,home,_=feature_env
    runtime=UnifiedRuntime(tools,feature_home=home)
    natural=runtime.start({'question':'查看用户42截至2026-10-11的画像'})
    structured=runtime.start({'feature_input':{'data_product':'user_profile','user_id':42,'as_of':'2026-10-11'}})
    assert natural['status']==structured['status']=='COMPLETE'
    assert natural['answer']['evidence']['rows']==structured['answer']['evidence']['rows']==[[42,'2026-10-11',5]]
    assert runtime.show(natural['session_id'])['queries_used']==1
    assert runtime.resume(natural['session_id'])['answer']==natural['answer']


def test_clarification_resumes_with_field_patch(feature_env):
    tools,home,_=feature_env;runtime=UnifiedRuntime(tools,feature_home=home)
    first=runtime.start({'question':'查看用户42的画像'})
    assert first['status']=='CLARIFY'
    result=runtime.followup(first['session_id'],'截至2026-10-11')
    assert result['status']=='COMPLETE'
    assert result['feature_task']['user_id']==42


def test_missing_record_not_fabricated_zero(feature_env):
    tools,home,_=feature_env
    result=FeatureTools(tools,home).read_profile(FeatureRequest(data_product='user_profile',user_id=99,as_of='2026-10-11'))
    assert result['found'] is False and result['rows']==[] and '没有记录' in result['note']


def test_unknown_date_does_not_fallback(feature_env):
    tools,home,_=feature_env
    with pytest.raises(ValueError,match='没有成功发布版本'):
        FeatureTools(tools,home).read_profile(FeatureRequest(data_product='user_profile',user_id=42,as_of='2026-10-10'))


def test_contract_tampering_stops_query(feature_env):
    tools,home,directory=feature_env
    (directory/'table-contracts.json').write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='artifact changed'):
        FeatureTools(tools,home).read_profile(FeatureRequest(data_product='user_profile',user_id=42,as_of='2026-10-11'))


def test_cached_session_rechecks_artifact_integrity(feature_env):
    tools,home,directory=feature_env;runtime=UnifiedRuntime(tools,feature_home=home)
    result=runtime.start({'question':'查看用户42截至2026-10-11的画像'})
    assert result['status']=='COMPLETE'
    (directory/'metadata.json').write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='artifact changed'):
        runtime.resume(result['session_id'])


def test_aggregate_identity_cannot_read_user_profile(feature_env):
    tools,home,_=feature_env
    restricted=AgentTools(tools.home,token=tools.access.issue('us-analyst'))
    with pytest.raises(ValueError,match='aggregate-only'):
        FeatureTools(restricted,home).read_profile(FeatureRequest(data_product='user_profile',user_id=42,as_of='2026-10-11'))


def test_parser_rejects_multiple_dates_and_preserves_two_ids():
    question='查看用户42和商品123截至2026-10-11的交互特征'
    assert is_feature_question(question)
    data=parse_feature_question(question)
    assert data['data_product']=='user_product' and data['user_id']==42 and data['product_id']==123
    with pytest.raises(ValueError,match='一个明确的截止日期'):
        parse_feature_question('用户42画像2026-10-10与2026-10-11')


def test_session_crosses_midnight_without_false_negative():
    sql=(ROOT/'warehouse-features/models/dws/dws_session_behavior.sql').read_text(encoding='utf-8')
    sql=sql.replace("{{ ref('dwd_behavior_event') }}",'dwd.events').replace('{{ var("feature_as_of") }}','2026-10-11')
    with duckdb.connect() as db:
        db.execute('CREATE SCHEMA dwd')
        db.execute('''CREATE TABLE dwd.events(session_id VARCHAR,event_time_utc TIMESTAMPTZ,event_type VARCHAR,
           invalid_product_reference BOOLEAN,product_id BIGINT,user_id BIGINT,is_anonymous BOOLEAN,eligible_before_cutoff BOOLEAN)''')
        db.execute("""INSERT INTO dwd.events VALUES
          ('session_a','2026-09-30 23:59:00+00','product',false,123,42,false,true),
          ('session_a','2026-10-01 00:01:00+00','cart',false,NULL,42,false,true),
          ('session_a','2026-10-11 01:00:00+00','purchase',false,NULL,42,false,false),
          ('session_b','2026-10-10 12:00:00+00','purchase',false,NULL,42,false,true)""")
        cursor=db.execute(sql);rows={r[0]:dict(zip([c[0] for c in cursor.description],r)) for r in cursor.fetchall()}
        assert rows['session_a']['event_count']==2 and rows['session_a']['observed_duration_seconds']==120
        assert rows['session_a']['purchase_observation']=='UNKNOWN_NOT_VERIFIED_NEGATIVE'
        assert not rows['session_a']['session_closure_verified']
        assert rows['session_b']['has_observed_purchase_event']
        assert not rows['session_b']['payment_success_verified']
