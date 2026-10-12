"""独立写入通道：构建电商主题数据产品，不放开 Agent 的只读工具。

每次从原库复制相关 raw 表到独立目录，通过 dbt 全量重建和独立对账，
成功后才切换 active.json。没有生产者水位，不能宣称严格 PIT 完整性。
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import duckdb
from sqlglot import exp
from sqlglot.lineage import lineage
from .control_lineage import extract_control
from .semantic import ROOT, file_hash

TABLES = {
    'dwd.dwd_behavior_event': ['event_id'],
    'dwd.dwd_product_view': ['event_id'],
    'dwd.dwd_order_item': ['order_item_id'],
    'dws.dws_user_behavior_day': ['activity_date', 'user_id'],
    'dws.dws_product_behavior_day': ['activity_date', 'product_id'],
    'ads.ads_user_profile_daily': ['as_of_date', 'user_id'],
    'ads.ads_product_profile_daily': ['as_of_date', 'product_id'],
    'dws.dws_user_product_day': ['activity_date','user_id','product_id'],
    'ads.ads_user_product_features': ['as_of_date','user_id','product_id'],
    'dws.dws_session_behavior': ['as_of_date','session_id'],
}
SOURCE_TABLES = ('events', 'users', 'products', 'orders', 'order_items')


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def validate(db, as_of, observed_at):
    """独立于 dbt PASS：从 raw 重新计算计数、金额与每个用户的窗口特征。"""
    db.execute("SET TimeZone='UTC'")
    cutoff = as_of + ' 00:00:00+00'
    checks = []

    def equal(name, left, right):
        if left != right:
            raise ValueError(f'{name} failed: {left!r} != {right!r}')
        checks.append({'name': name, 'status': 'PASS', 'value': left})

    def value(sql, parameters=None):
        result = db.execute(sql, parameters or []).fetchone()[0]
        # All scalar checks here are totals; an empty eligible window is zero.
        return 0 if result is None else result

    stats = {}
    for table, grain in TABLES.items():
        # The names are a fixed server-side list, never user-supplied SQL.
        count = value(f'SELECT count(*) FROM {table}')
        unique = value(f'SELECT count(*) FROM (SELECT {",".join(grain)} FROM {table} GROUP BY ALL)')
        equal(table + ':grain', count, unique)
        equal(table + ':null_key', value(f'SELECT count(*) FROM {table} WHERE '+ ' OR '.join(k+' IS NULL' for k in grain)), 0)
        stats[table] = {'rows': count, 'grain': grain}

    equal('event_rows_preserved', value('SELECT count(*) FROM dwd.dwd_behavior_event'), value('SELECT count(*) FROM raw.events'))
    equal('order_item_rows_preserved', value('SELECT count(*) FROM dwd.dwd_order_item'), value('SELECT count(*) FROM raw.order_items'))
    equal('product_view_rows', value('SELECT count(*) FROM dwd.dwd_product_view'), value("SELECT count(*) FROM raw.events WHERE event_type='product'"))
    eligible_event = 'created_at < ?::TIMESTAMPTZ AND created_at <= ?::TIMESTAMPTZ'
    params = [cutoff, observed_at]
    equal('user_event_total', value('SELECT sum(event_count) FROM dws.dws_user_behavior_day'),
          value('SELECT count(*) FROM raw.events e JOIN raw.users u ON e.user_id=u.id WHERE '+eligible_event.replace('created_at','e.created_at'), params))
    equal('product_view_total', value('SELECT sum(product_view_count) FROM dws.dws_product_behavior_day'),
          value("SELECT count(*) FROM raw.events WHERE event_type='product' AND "+eligible_event, params))
    raw_items = '''FROM raw.order_items i JOIN raw.orders o ON i.order_id=o.order_id
        WHERE o.created_at < ?::TIMESTAMPTZ AND i.created_at < ?::TIMESTAMPTZ
          AND o.created_at <= ?::TIMESTAMPTZ AND i.created_at <= ?::TIMESTAMPTZ'''
    item_params = [cutoff, cutoff, observed_at, observed_at]
    raw_amount = value('SELECT sum(cast(i.sale_price AS DECIMAL(18,4))) '+raw_items, item_params)
    for entity in ('user', 'product'):
        equal(entity + '_booked_amount', value(f'SELECT sum(booked_amount) FROM dws.dws_{entity}_behavior_day'), raw_amount)
        equal(entity + '_placed_items', value(f'SELECT sum(placed_item_count) FROM dws.dws_{entity}_behavior_day'),
              value('SELECT count(*) '+raw_items, item_params))
    equal('user_order_count', value('SELECT sum(placed_order_count) FROM dws.dws_user_behavior_day'),
          value('SELECT count(DISTINCT i.order_id) '+raw_items, item_params))

    # ALL profiles are checked, rather than checking one representative user.
    for days in (7, 30):
        sql = f'''WITH truth AS (
          SELECT user_id,count(*) n FROM raw.events
          WHERE event_type='product' AND created_at < ?::TIMESTAMPTZ
            AND created_at <= ?::TIMESTAMPTZ
            AND created_at >= ?::TIMESTAMPTZ - INTERVAL '{days} days'
          GROUP BY user_id)
          SELECT count(*) FROM ads.ads_user_profile_daily a
          LEFT JOIN truth t USING(user_id)
          WHERE a.product_views_{days}d != coalesce(t.n,0)'''
        equal(f'all_user_views_{days}d', value(sql, [cutoff, observed_at, cutoff]), 0)
        sql = f'''WITH truth AS (
          SELECT try_cast(regexp_extract(uri,'^/product/([0-9]+)$',1) AS BIGINT) product_id,count(*) n
          FROM raw.events WHERE event_type='product'
            AND created_at < ?::TIMESTAMPTZ AND created_at <= ?::TIMESTAMPTZ
            AND created_at >= ?::TIMESTAMPTZ - INTERVAL '{days} days'
          GROUP BY 1)
          SELECT count(*) FROM ads.ads_product_profile_daily a
          LEFT JOIN truth t USING(product_id)
          WHERE a.product_views_{days}d != coalesce(t.n,0)'''
        equal(f'all_product_views_{days}d', value(sql, [cutoff, observed_at, cutoff]), 0)
    # Verify every delivered transaction feature directly against raw facts.
    for entity in ('user', 'product'):
        key = entity+'_id'
        order_expression = ', count(DISTINCT i.order_id) order_count' if entity=='user' else ''
        compare_orders = ' OR a.placed_orders_30d != coalesce(t.order_count,0)' if entity=='user' else ''
        sql = f'''WITH truth AS (
          SELECT i.{key},count(*) items,sum(cast(i.sale_price AS DECIMAL(18,4))) amount
            {order_expression}
          {raw_items} AND o.created_at >= ?::TIMESTAMPTZ - INTERVAL '30 days'
          GROUP BY i.{key})
          SELECT count(*) FROM ads.ads_{entity}_profile_daily a
          LEFT JOIN truth t USING({key})
          WHERE a.placed_items_30d != coalesce(t.items,0)
             OR a.booked_amount_30d != coalesce(t.amount,0) {compare_orders}'''
        equal(f'all_{entity}_transaction_features_30d', value(sql,item_params+[cutoff]),0)
    sql = f'''WITH truth AS (
      SELECT i.user_id,max(o.created_at) last_at {raw_items} GROUP BY i.user_id)
      SELECT count(*) FROM ads.ads_user_profile_daily a LEFT JOIN truth t USING(user_id)
      WHERE a.last_order_at IS DISTINCT FROM t.last_at
         OR a.days_since_last_order IS DISTINCT FROM
              date_diff('day',cast(timezone('UTC',t.last_at) as date),?::DATE)'''
    equal('all_user_last_order_and_recency',value(sql,item_params+[as_of]),0)
    for table in ('dws.dws_user_behavior_day','dws.dws_product_behavior_day'):
        equal(table+':cutoff', value(f'SELECT count(*) FROM {table} WHERE activity_date>=?::DATE',[as_of]), 0)
    for table in ('ads.ads_user_profile_daily','ads.ads_product_profile_daily'):
        equal(table+':as_of', value(f'SELECT count(*) FROM {table} WHERE as_of_date!=?::DATE',[as_of]), 0)
    quality = {
        'anonymous_events': value('SELECT count(*) FROM dwd.dwd_behavior_event WHERE is_anonymous'),
        'future_at_capture': value('SELECT count(*) FROM dwd.dwd_behavior_event WHERE future_at_capture'),
        'ineligible_events': value('SELECT count(*) FROM dwd.dwd_behavior_event WHERE NOT eligible_before_cutoff'),
        'unknown_users': value('SELECT count(*) FROM dwd.dwd_behavior_event WHERE unknown_user'),
        'invalid_product_references': value('SELECT count(*) FROM dwd.dwd_behavior_event WHERE invalid_product_reference'),
    }
    equal('interaction_view_total',value('SELECT sum(product_view_count) FROM dws.dws_user_product_day'),
          value("SELECT count(*) FROM raw.events WHERE user_id IS NOT NULL AND event_type='product' AND "+eligible_event,params))
    equal('interaction_amount',value('SELECT sum(booked_amount) FROM dws.dws_user_product_day'),raw_amount)
    equal('session_event_total',value('SELECT sum(event_count) FROM dws.dws_session_behavior'),
          value('SELECT count(*) FROM raw.events WHERE session_id IS NOT NULL AND '+eligible_event,params))
    session_truth='''WITH truth AS (SELECT session_id,count(*) n,
      min(created_at) first_at,max(created_at) last_at,
      count(*) FILTER(WHERE event_type='purchase') purchases
      FROM raw.events WHERE session_id IS NOT NULL AND '''+eligible_event+''' GROUP BY session_id)
      SELECT count(*) FROM truth t FULL OUTER JOIN dws.dws_session_behavior s USING(session_id)
      WHERE t.n IS DISTINCT FROM s.event_count OR t.first_at IS DISTINCT FROM s.first_observed_event_at
        OR t.last_at IS DISTINCT FROM s.last_observed_event_at OR t.purchases IS DISTINCT FROM s.purchase_event_count'''
    equal('all_session_truth',value(session_truth,params),0)
    for days in (7,30):
        sql=f'''WITH truth AS (SELECT user_id,
          try_cast(regexp_extract(uri,'^/product/([0-9]+)$',1) AS BIGINT) product_id,count(*) n
          FROM raw.events WHERE user_id IS NOT NULL AND event_type='product'
            AND {eligible_event} AND created_at>=?::TIMESTAMPTZ-INTERVAL '{days} days' GROUP BY 1,2)
          SELECT count(*) FROM ads.ads_user_product_features a LEFT JOIN truth t USING(user_id,product_id)
          WHERE a.product_views_{days}d!=coalesce(t.n,0)'''
        equal(f'all_pair_views_{days}d',value(sql,params+[cutoff]),0)
    sql=f'''WITH truth AS (SELECT i.user_id,i.product_id,count(*) items,
      count(DISTINCT i.order_id) orders,sum(cast(i.sale_price AS DECIMAL(18,4))) amount
      {raw_items} AND o.created_at>=?::TIMESTAMPTZ-INTERVAL '30 days' GROUP BY 1,2)
      SELECT count(*) FROM ads.ads_user_product_features a LEFT JOIN truth t USING(user_id,product_id)
      WHERE a.placed_items_30d!=coalesce(t.items,0) OR a.placed_orders_30d!=coalesce(t.orders,0)
        OR a.booked_amount_30d!=coalesce(t.amount,0)'''
    equal('all_pair_transaction_features',value(sql,item_params+[cutoff]),0)
    return {'status':'PASS','checks':checks,'tables':stats,'source_observations':quality}


def signatures(db):
    """重跑比对全表行数和两个交换性内容摘要，不把它冒充安全哈希。"""
    result={}
    for name in TABLES:
        columns=[row[0] for row in db.execute(f'DESCRIBE {name}').fetchall()]
        row_hash='hash('+','.join(exp.Identifier(this=c,quoted=True).sql() for c in columns)+')'
        result[name]=list(db.execute(f'SELECT count(*),bit_xor({row_hash}),sum({row_hash}::HUGEINT) FROM {name}').fetchone())
    return result


def catalog(db, manifest):
    """从 dbt 依赖与编译 SQL 输出技术血缘；COUNT(*) 等不能保证字段完整。"""
    schemas = {}; parsing_schema = {}
    for database, schema, table, column, datatype in db.execute("SELECT table_catalog,table_schema,table_name,column_name,data_type FROM information_schema.columns WHERE table_schema IN ('raw','dwd','dws','ads')").fetchall():
        schemas.setdefault(schema+'.'+table, {})[column] = datatype
        parsing_schema.setdefault(database, {}).setdefault(schema, {}).setdefault(table,{})[column] = datatype
    objects = {**manifest.get('sources',{}), **manifest['nodes']}
    result = {'storage':'JSON metadata delivery artifact','complete':False,'tables':{}}
    for node in manifest['nodes'].values():
        if node['resource_type']!='model': continue
        table = node['schema']+'.'+node.get('alias',node['name'])
        parents=[]
        for key in node['depends_on']['nodes']:
            parent=objects.get(key,{})
            if parent.get('resource_type') in ('model','source'):
                parents.append(parent['schema']+'.'+parent.get('identifier',parent.get('alias',parent['name'])))
        fields={}
        for column in schemas.get(table,{}):
            try:
                graph=lineage(column,node['compiled_code'],schema=parsing_schema,dialect='duckdb')
                sources=[];unresolved=False
                for leaf in graph.walk():
                    if leaf.downstream:continue
                    if isinstance(leaf.expression,exp.Table):
                        source=leaf.expression.db+'.'+leaf.expression.name
                        field=leaf.name.rsplit('.',1)[-1].strip('"')
                        if field in schemas.get(source,{}):sources.append({'table':source,'column':field})
                        else:unresolved=True
                    else:unresolved=True
                fields[column]={'sources':sources,'complete':bool(sources) and not unresolved}
            except Exception:
                fields[column]={'sources':[],'complete':False}
        result['tables'][table]={'grain':TABLES[table],'columns':schemas[table],
            'upstream':parents,'field_value_lineage':fields,
            'control_lineage':extract_control(node['compiled_code'],{t:[{'name':c} for c in cols] for t,cols in schemas.items()}),
            'formula_source':'dbt compiled SQL','row_count_dependencies':parents,
            'scope':'technical dependencies; no causal or full SQL coverage claim'}
    return result


def build(as_of, verify_repeat=False, home=None):
    cutoff = dt.datetime.combine(dt.date.fromisoformat(as_of), dt.time(), dt.timezone.utc)
    source=ROOT/'data/thelook.duckdb'
    source_manifest=json.loads((ROOT/'docs/thelook-source-manifest.json').read_text(encoding='utf-8'))
    # Resolve the observation field explicitly; no max(event_time) watermark inference.
    observed_text = source_manifest.get('completed_at')
    if not observed_text:
        raise ValueError('Source capture timestamp is missing; cannot invent an observation time')
    observed=dt.datetime.fromisoformat(observed_text.replace('Z','+00:00'))
    if observed.tzinfo is None or cutoff>observed:
        raise ValueError('Cutoff must be a UTC midnight no later than source observation')
    python=ROOT/'.warehouse-venv/Scripts/python.exe'
    if not python.exists():raise ValueError('Warehouse runtime is missing')
    skill=ROOT/'skills/warehouse-feature-engineering'
    resources={p.relative_to(skill).as_posix():p.read_text(encoding='utf-8') for p in [skill/'SKILL.md',skill/'references/table-contracts.md']}
    home=Path(home) if home else ROOT/'data/feature-mart'
    release_id=as_of+'-'+uuid.uuid4().hex[:12]
    directory=home/'releases'/release_id;directory.mkdir(parents=True)
    target=directory/'features.duckdb';events=[]

    def emit(stage, **values):
        row={'at':dt.datetime.now(dt.timezone.utc).isoformat(),'stage':stage,**values}
        events.append(row)
        with (directory/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        print(stage,flush=True)

    emit('skill-start',skill='warehouse-feature-engineering',resource_hash=hashlib.sha256(json.dumps(resources,sort_keys=True).encode()).hexdigest())
    try:
        before=file_hash(source)
        with duckdb.connect(str(target)) as db:
            # DuckDB ATTACH does not accept bound parameters. The path is fixed,
            # escaped as a SQL literal, and the source remains read-only.
            source_literal = exp.Literal.string(str(source)).sql(dialect='duckdb')
            db.execute(f'ATTACH {source_literal} AS original (READ_ONLY)')
            db.execute('CREATE SCHEMA raw')
            for table in SOURCE_TABLES:
                db.execute(f'CREATE TABLE raw.{table} AS SELECT * FROM original.raw.{table}')
            db.execute('DETACH original')
        if file_hash(source)!=before:raise ValueError('Source changed during copy')
        emit('raw-copy-complete',source_hash=before)
        env={**os.environ,'FEATURE_DATABASE':str(target.resolve())}
        variables=json.dumps({'feature_as_of':as_of,'source_observed_at':observed.isoformat()})

        def run_dbt(number):
            cmd=[str(python),'-m','dbt.cli.main','build','--project-dir',str(ROOT/'warehouse-features'),
                 '--profiles-dir',str(ROOT/'warehouse-features'),'--target-path',str(directory/f'dbt-run-{number}'),'--vars',variables]
            # No shell interpolation and a bounded build process; no user SQL input.
            with (directory/f'dbt-run-{number}.log').open('w',encoding='utf-8') as log:
                process=subprocess.run(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300)
            if process.returncode:raise ValueError(f'dbt failed; inspect {directory}/dbt-run-{number}.log')
            results=json.loads((directory/f'dbt-run-{number}/run_results.json').read_text(encoding='utf-8'))
            if any(row['status'] not in ('pass','success') for row in results['results']):raise ValueError('dbt results incomplete')
            emit('dbt-build-complete',run=number,checks=sum(r['unique_id'].startswith('test.') for r in results['results']))
            return results

        results=run_dbt(1)
        with duckdb.connect(str(target),read_only=True) as db:
            quality=validate(db,as_of,observed.isoformat());first=signatures(db)
        emit('independent-reconciliation-passed',checks=len(quality['checks']))
        repeat={'verified':False,'reason':'not requested'}
        if verify_repeat:
            run_dbt(2)
            with duckdb.connect(str(target),read_only=True) as db:
                quality=validate(db,as_of,observed.isoformat());second=signatures(db)
            if first!=second:raise ValueError('Repeat build changed content signatures')
            repeat={'verified':True,'method':'all tables count + xor/sum row hashes, with independent feature reconciliation','tables':len(TABLES)}
            emit('repeat-build-stable')
        manifest=json.loads((directory/'dbt-run-1/manifest.json').read_text(encoding='utf-8'))
        with duckdb.connect(str(target),read_only=True) as db:metadata=catalog(db,manifest)
        write_json(directory/'quality.json',quality);write_json(directory/'metadata.json',metadata)
        write_json(directory/'table-contracts.json',{'as_of_date':as_of,'timezone':'UTC','windows':[7,30],
            'tables':metadata['tables'],'rules':{'amount':'placed item sale price; not settled revenue',
            'event':'product page view; not click/impression','distinct':'daily viewer counts cannot be summed into monthly UV',
            'temporal':'event-time cutoff enforced; ingestion-time historical availability and producer completeness unverified',
            'catalog':'current product universe; historical availability unverified'}})
        release={'status':'PASS','release_id':release_id,'as_of_date':as_of,'source_observed_at':observed.isoformat(),
            'source_sha256':before,'database':str(target.resolve()),'database_sha256':file_hash(target),
            'quality':quality,'repeat_build':repeat,'metadata':str((directory/'metadata.json').resolve()),
            'metadata_sha256':file_hash(directory/'metadata.json'),
            'table_contracts_sha256':file_hash(directory/'table-contracts.json'),
            'temporal_completeness_verified':False,'historical_attribute_versions_verified':False,
            'source_consistency':'sequential public table reads; not a cross-table atomic snapshot'}
        write_json(directory/'release.json',release)
        temporary=home/('active-'+uuid.uuid4().hex+'.partial');write_json(temporary,release);temporary.replace(home/'active.json')
        write_json(ROOT/'docs/feature-phase2-verification.json',release)
        emit('published',release_id=release_id)
        return release
    except Exception as error:
        emit('failed',error=str(error));raise


def main():
    parser=argparse.ArgumentParser(description='Build an isolated DWD/DWS/ADS feature data product')
    parser.add_argument('--as-of',required=True,help='exclusive UTC date cutoff')
    parser.add_argument('--verify-repeat',action='store_true')
    args=parser.parse_args()
    release=build(args.as_of,args.verify_repeat)
    print(json.dumps({'status':release['status'],'release_id':release['release_id'],'database':release['database'],
        'tables':release['quality']['tables'],'repeat_build':release['repeat_build']},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
