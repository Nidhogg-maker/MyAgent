"""加工约束测试：不能只验证文件存在或镜像实现。"""
import datetime as dt
import duckdb
import pytest
from local_agent.feature_pipeline import TABLES, build, signatures, validate, catalog


def test_cutoff_after_source_observation_is_rejected(tmp_path):
    with pytest.raises(ValueError, match='Cutoff must'):
        build('2026-10-12',home=tmp_path)
    assert not (tmp_path/'active.json').exists()


def test_duplicate_grain_prevents_validation():
    with duckdb.connect() as db:
        db.execute('CREATE SCHEMA dwd')
        db.execute('CREATE TABLE dwd.dwd_behavior_event(event_id BIGINT)')
        db.execute('INSERT INTO dwd.dwd_behavior_event VALUES (1),(1)')
        with pytest.raises(ValueError,match='grain failed'):
            validate(db,'2026-10-11','2026-10-11T10:19:14+00:00')


def test_null_grain_prevents_validation():
    with duckdb.connect() as db:
        db.execute('CREATE SCHEMA dwd')
        db.execute('CREATE TABLE dwd.dwd_behavior_event(event_id BIGINT)')
        db.execute('INSERT INTO dwd.dwd_behavior_event VALUES (NULL)')
        with pytest.raises(ValueError,match='null_key failed'):
            validate(db,'2026-10-11','2026-10-11T10:19:14+00:00')


def test_repeat_signature_ignores_order_but_detects_changed_values():
    with duckdb.connect() as db:
        for schema in ('dwd','dws','ads'):db.execute('CREATE SCHEMA '+schema)
        for table in TABLES:
            db.execute(f'CREATE TABLE {table}(id INTEGER, feature INTEGER)')
            db.execute(f'INSERT INTO {table} VALUES (1,4),(2,7)')
        initial=signatures(db)
        for table in TABLES:
            db.execute(f'DELETE FROM {table}')
            db.execute(f'INSERT INTO {table} VALUES (2,7),(1,4)')
        assert signatures(db)==initial
        db.execute('UPDATE ads.ads_user_profile_daily SET feature=8 WHERE id=2')
        assert signatures(db)!=initial


def test_metadata_resolves_field_through_star_cte_and_marks_constant():
    with duckdb.connect() as db:
        db.execute('CREATE SCHEMA raw');db.execute('CREATE SCHEMA dwd')
        db.execute('CREATE TABLE raw.events(id BIGINT,created_at TIMESTAMPTZ)')
        db.execute('CREATE TABLE dwd.dwd_behavior_event(event_id BIGINT,event_time_utc TIMESTAMPTZ,constant_flag BOOLEAN)')
        manifest={'sources':{'source.events':{'schema':'raw','name':'events','resource_type':'source'}},
            'nodes':{'model.events':{'schema':'dwd','name':'dwd_behavior_event','resource_type':'model',
                'depends_on':{'nodes':['source.events']},
                'compiled_code':'with e as (select * from raw.events) select id event_id, created_at event_time_utc, false constant_flag from e'}}}
        result=catalog(db,manifest)['tables']['dwd.dwd_behavior_event']
        assert result['upstream']==['raw.events']
        assert result['field_value_lineage']['event_time_utc']['sources']==[{'table':'raw.events','column':'created_at'}]
        assert not result['field_value_lineage']['constant_flag']['complete']
