"""Read official BigQuery tables without query jobs; preserve raw pages and provenance."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
TABLES = ('distribution_centers', 'products', 'users', 'orders', 'order_items', 'inventory_items', 'events')
BASE = 'https://bigquery.googleapis.com/bigquery/v2/projects/bigquery-public-data/datasets/thelook_ecommerce/tables/'

def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

class Reader:
    def __init__(self):
        self.token = None
        self.expires = 0

    def get(self, url):
        for attempt in range(5):
            if time.monotonic() >= self.expires:
                # Prefer an explicit SDK path; otherwise resolve from PATH on a fresh machine.
                sdk = os.environ.get('THELOOK_GCLOUD', 'gcloud.cmd' if os.name == 'nt' else 'gcloud')
                result = subprocess.run([sdk, 'auth', 'print-access-token'], capture_output=True, text=True)
                if result.returncode:
                    raise RuntimeError('Google Cloud credential unavailable; authenticate locally before retrying.')
                self.token = result.stdout.strip()
                self.expires = time.monotonic() + 2400
            request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + self.token})
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code == 401:
                    self.expires = 0
                elif error.code not in (429, 500, 502, 503, 504):
                    raise RuntimeError(f'Official source HTTP {error.code}: {url.split("?")[0]}') from None
                time.sleep(2 ** attempt)
        raise RuntimeError('Official API retry budget exhausted')

def decode_row(schema, row):
    values = {field['name']: item.get('v') for field, item in zip(schema, row['f'], strict=True)}
    for field in schema:
        value = values[field['name']]
        if value is not None:
            if field['type'] == 'INTEGER':
                values[field['name']] = int(value)
            elif field['type'] in ('FLOAT', 'NUMERIC', 'BIGNUMERIC'):
                values[field['name']] = float(value)
            elif field['type'] == 'TIMESTAMP':
                values[field['name']] = dt.datetime.fromtimestamp(float(value), dt.timezone.utc).isoformat()
    return json.dumps(values, ensure_ascii=False) + '\n'

def parallel_events(reader, output, schema, total):
    # Disjoint stable row offsets; source version must still pass before/after checks.
    ranges = [(start, min(start + 40000, total)) for start in range(0, total, 40000)]
    def fetch(bounds):
        start, end = bounds
        part = output / f'events.part-{start}'
        index = start
        with part.open('w', encoding='utf-8', newline='\n') as file:
            while index < end:
                params = urllib.parse.urlencode({'startIndex': index, 'maxResults': end - index})
                page = reader.get(BASE + 'events/data?' + params)
                rows = page.get('rows', [])
                if not rows or len(rows) > end - index:
                    raise RuntimeError('Event range incomplete or unexpectedly oversized')
                for row in rows:
                    file.write(decode_row(schema, row))
                index += len(rows)
        print(f'events: range {start}-{end} complete', flush=True)
        return part
    with ThreadPoolExecutor(max_workers=4) as pool:
        parts = list(pool.map(fetch, ranges))
    target = output / 'events.partial'
    with target.open('wb') as combined:
        for part in parts:
            with part.open('rb') as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    combined.write(chunk)
            part.unlink()
    return total

def download(output):
    output.mkdir(parents=True, exist_ok=True)
    reader = Reader()
    manifest_path = output / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {
        'source': 'bigquery-public-data.thelook_ecommerce', 'synthetic': True,
        'started_at': stamp(), 'acquisition': 'BigQuery tables.get + tabledata.list; no query jobs',
        'consistency': 'Sequential table reads, not a cross-table atomic snapshot; compare source metadata before/after.',
        'license': 'Public availability confirmed; dataset-specific redistribution license not independently established.',
        'tables': {},
    }
    for table in TABLES:
        destination = output / (table + '.jsonl')
        if table in manifest['tables'] and destination.exists() and digest(destination) == manifest['tables'][table]['sha256']:
            print(f'{table}: verified existing download', flush=True)
            continue
        before = reader.get(BASE + table)
        schema = before['schema']['fields']
        (output / (table + '.schema.json')).write_text(json.dumps(before, indent=2), encoding='utf-8')
        temporary = destination.with_suffix('.partial')
        page_token = None
        rows = 0
        if table == 'events':
            rows = parallel_events(reader, output, schema, int(before['numRows']))
        else:
          with temporary.open('w', encoding='utf-8', newline='\n') as file:
            while True:
                params = {'maxResults': 100000}
                if page_token:
                    params['pageToken'] = page_token
                page = reader.get(BASE + table + '/data?' + urllib.parse.urlencode(params))
                for row in page.get('rows', []):
                    file.write(decode_row(schema, row))
                    rows += 1
                page_token = page.get('pageToken')
                print(f'{table}: {rows} / {before.get("numRows", "?")}', flush=True)
                if not page_token:
                    break
        after = reader.get(BASE + table)
        if before['lastModifiedTime'] != after['lastModifiedTime'] or rows != int(before['numRows']):
            raise RuntimeError(f'{table}: source changed or row count mismatch; partial file retained, not activated')
        temporary.replace(destination)
        manifest['tables'][table] = {
            'rows': rows, 'sha256': digest(destination), 'source_last_modified_ms': before['lastModifiedTime'],
            'downloaded_at': stamp(), 'bytes': destination.stat().st_size,
            'source_unchanged_during_read': True,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    manifest['completed_at'] = stamp()
    manifest['source_versions_still_current_at_completion'] = all(
        reader.get(BASE + name)['lastModifiedTime'] == manifest['tables'][name]['source_last_modified_ms']
        for name in TABLES
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')

def build(output):
    import duckdb
    manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
    database = output.parent / 'thelook.duckdb'
    connection = duckdb.connect(str(database))
    connection.execute('CREATE SCHEMA IF NOT EXISTS raw')
    profile = {'source_manifest': str(output / 'manifest.json'), 'profiled_at': stamp(), 'tables': {}, 'relationships': []}
    mapping = {'INTEGER': 'BIGINT', 'FLOAT': 'DOUBLE', 'STRING': 'VARCHAR', 'TIMESTAMP': 'TIMESTAMPTZ', 'BOOLEAN': 'BOOLEAN', 'DATE': 'DATE', 'NUMERIC': 'DECIMAL(38,9)', 'GEOGRAPHY': 'VARCHAR'}
    for table in TABLES:
        path = output / (table + '.jsonl')
        if digest(path) != manifest['tables'][table]['sha256']:
            raise RuntimeError(f'{table}: raw file checksum mismatch')
        fields = json.loads((output / (table + '.schema.json')).read_text(encoding='utf-8'))['schema']['fields']
        columns = ', '.join(f"'{f['name']}': '{mapping[f['type']]}'" for f in fields)
        escaped = path.as_posix().replace("'", "''")
        connection.execute(f"CREATE OR REPLACE TABLE raw.{table} AS SELECT * FROM read_json('{escaped}', format='newline_delimited', columns={{{columns}}})")
        count = connection.execute(f'SELECT count(*) FROM raw.{table}').fetchone()[0]
        if count != manifest['tables'][table]['rows']:
            raise RuntimeError(f'{table}: import row count mismatch')
        pk = 'order_id' if table == 'orders' else 'id'
        checks = connection.execute(f'SELECT count(*)-count(DISTINCT {pk}), count(*) FILTER (WHERE {pk} IS NULL) FROM raw.{table}').fetchone()
        details = {'rows': count, 'primary_key': pk, 'duplicate_or_null_key_rows': checks[0], 'null_key_rows': checks[1], 'columns': {}}
        for field in fields:
            name = field['name']
            missing = connection.execute(f'SELECT count(*) FILTER (WHERE "{name}" IS NULL) FROM raw.{table}').fetchone()[0]
            entry = {'type': field['type'], 'nulls': missing}
            if field['type'] == 'TIMESTAMP':
                bounds = connection.execute(f'SELECT min("{name}"), max("{name}") FROM raw.{table}').fetchone()
                entry.update(min=str(bounds[0]), max=str(bounds[1]))
            if name in ('status', 'country', 'traffic_source', 'event_type', 'department'):
                entry['values'] = connection.execute(f'SELECT "{name}", count(*) FROM raw.{table} GROUP BY 1 ORDER BY 2 DESC').fetchall()
            details['columns'][name] = entry
        profile['tables'][table] = details
    edges = [('orders','user_id','users','id'), ('order_items','order_id','orders','order_id'), ('order_items','user_id','users','id'), ('order_items','product_id','products','id'), ('order_items','inventory_item_id','inventory_items','id'), ('inventory_items','product_id','products','id'), ('products','distribution_center_id','distribution_centers','id'), ('events','user_id','users','id')]
    for child, fk, parent, pk in edges:
        missing, nulls = connection.execute(f'SELECT count(*) FILTER (WHERE c.{fk} IS NOT NULL AND p.{pk} IS NULL), count(*) FILTER (WHERE c.{fk} IS NULL) FROM raw.{child} c LEFT JOIN raw.{parent} p ON c.{fk}=p.{pk}').fetchone()
        profile['relationships'].append({'child': child, 'foreign_key': fk, 'parent': parent, 'missing_parent_rows': missing, 'null_foreign_key_rows': nulls})
    profile['order_item_count_mismatches'] = connection.execute('SELECT count(*) FROM raw.orders o LEFT JOIN (SELECT order_id,count(*) n FROM raw.order_items GROUP BY 1) i USING(order_id) WHERE o.num_of_item != coalesce(i.n,0)').fetchone()[0]
    profile['order_item_user_mismatches'] = connection.execute('SELECT count(*) FROM raw.order_items i JOIN raw.orders o USING(order_id) WHERE i.user_id != o.user_id').fetchone()[0]
    profile['events'] = {
        'sessions': connection.execute('SELECT count(DISTINCT session_id) FROM raw.events').fetchone()[0],
        'anonymous_events': connection.execute('SELECT count(*) FROM raw.events WHERE user_id IS NULL').fetchone()[0],
        'duplicate_session_sequence_groups': connection.execute('SELECT count(*) FROM (SELECT session_id,sequence_number FROM raw.events GROUP BY 1,2 HAVING count(*)>1)').fetchone()[0],
        'future_events_at_profile': connection.execute('SELECT count(*) FROM raw.events WHERE created_at > current_timestamp').fetchone()[0],
    }
    profile['orders_shipped_before_created'] = connection.execute('SELECT count(*) FROM raw.orders WHERE shipped_at < created_at').fetchone()[0]
    profile['orders_delivered_before_shipped'] = connection.execute('SELECT count(*) FROM raw.orders WHERE delivered_at < shipped_at').fetchone()[0]
    profile['items_negative_price'] = connection.execute('SELECT count(*) FROM raw.order_items WHERE sale_price < 0').fetchone()[0]
    connection.close()
    profile['database_sha256'] = digest(database)
    target = ROOT / 'docs' / 'thelook-profile.json'
    target.write_text(json.dumps(profile, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    # 后续刷新源数据时同步观测证据，避免发布流程继续使用首次下载的旧时间。
    # 这只是来源观测记录，不会自动生成完整性水位。
    (ROOT / 'docs' / 'thelook-source-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'Imported and profiled: {database}', flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['download', 'build', 'all'])
    parser.add_argument('--snapshot', default=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d'))
    args = parser.parse_args()
    output = ROOT / 'data' / ('thelook-' + args.snapshot)
    if args.action in ('download', 'all'):
        download(output)
    if args.action in ('build', 'all'):
        build(output)
