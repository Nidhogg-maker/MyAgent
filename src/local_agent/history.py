"""本地快照观察历史：支持变化/迟到记录，但不捏造真实业务生效时间。"""
import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path
import duckdb

class SnapshotHistory:
    def __init__(self,path:Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS versions(
                entity TEXT, entity_key TEXT, observed_from TEXT, observed_to TEXT, payload TEXT, digest TEXT,
                PRIMARY KEY(entity,entity_key,observed_from));
                CREATE UNIQUE INDEX IF NOT EXISTS one_current ON versions(entity,entity_key) WHERE observed_to IS NULL;
                CREATE TABLE IF NOT EXISTS captures(observed_at TEXT PRIMARY KEY, evidence_ref TEXT);''')

    def capture(self,entity,records,observed_at,evidence_ref):
        """幂等实体版本；晚到的业务记录从本次观察时刻出现，不回写成过去已知。"""
        at = dt.datetime.fromisoformat(observed_at)
        if at.tzinfo is None:
            raise ValueError('Observation requires timezone')
        if at>dt.datetime.now(dt.timezone.utc):
            raise ValueError('Future observation not allowed')
        timestamp = at.astimezone(dt.timezone.utc).isoformat()
        changed,unchanged = 0,0
        with sqlite3.connect(self.path) as db:
            latest = db.execute('SELECT max(observed_from) FROM versions WHERE entity=?',(entity,)).fetchone()[0]
            if latest and timestamp < latest:
                raise ValueError('Observation chronology must not move backward')
            active = {key:(start,digest) for key,start,digest in db.execute('SELECT entity_key,observed_from,digest FROM versions WHERE entity=? AND observed_to IS NULL',(entity,))}
            seen = set()
            for record in records:
                if record.get('id') is None:
                    raise ValueError('Entity key cannot be null')
                key = str(record['id'])
                if key in seen:
                    raise ValueError('Duplicate entity key in snapshot')
                seen.add(key)
                payload = json.dumps(record,sort_keys=True,default=str)
                digest = hashlib.sha256(payload.encode()).hexdigest()
                previous = active.get(key)
                if previous and previous[1]==digest:
                    unchanged += 1
                    continue
                if previous and previous[0]==timestamp:
                    raise ValueError('Conflicting snapshots at same observation time')
                db.execute('UPDATE versions SET observed_to=? WHERE entity=? AND entity_key=? AND observed_to IS NULL',(timestamp,entity,key))
                db.execute('INSERT INTO versions VALUES (?,?,?,?,?,?)',(entity,key,timestamp,None,payload,digest))
                changed += 1
            # 源快照缺失不能自动推断实体删除：记录数变化需要额外删除事件契约。
            db.execute('INSERT OR IGNORE INTO captures VALUES (?,?)',(timestamp,evidence_ref))
        return {'changed':changed,'unchanged':unchanged,'deleted_inferred':False,'history_kind':'observation-time, not source business-valid-time'}

    def as_of(self,entity,key,observed_at):
        """按当时本地已知的版本查询；时间前无记录返回None，不推测历史状态。"""
        at = dt.datetime.fromisoformat(observed_at)
        if at.tzinfo is None:
            raise ValueError('Observation requires timezone')
        timestamp = at.astimezone(dt.timezone.utc).isoformat()
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT payload FROM versions WHERE entity=? AND entity_key=? AND observed_from<=? AND (observed_to IS NULL OR observed_to>?)',(entity,str(key),timestamp,timestamp)).fetchone()
        return json.loads(row[0]) if row else None

    def capture_warehouse(self,database,observed_at,evidence_ref):
        """只保留订单状态和业务用户属性，不把姓名/邮箱写入历史库。"""
        results = {}
        with duckdb.connect(str(database),read_only=True) as source:
            for entity,sql in [('orders','SELECT order_id AS id,status,created_at FROM raw.orders'),
                               ('users','SELECT id,country,traffic_source FROM raw.users')]:
                cursor = source.execute(sql)
                names = [item[0] for item in cursor.description]
                def records():
                    while rows:=cursor.fetchmany(10000):
                        for row in rows:
                            yield dict(zip(names,row))
                results[entity] = self.capture(entity,records(),observed_at,evidence_ref)
        return results
