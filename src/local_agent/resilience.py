"""共享有界重试与本地熔断；确定性错误永不重试，半开只允许一个探测。"""
import random
import math
import datetime as dt
from email.utils import parsedate_to_datetime
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from contextlib import contextmanager

class TransientFailure(ValueError):
    def __init__(self,message,retry_after=None):
        super().__init__(message)
        self.retry_after=retry_after

class CircuitOpen(ValueError): pass

def retry_after(value):
    if not value: return None
    try: seconds=float(value)
    except ValueError:
        try: seconds=(parsedate_to_datetime(value)-dt.datetime.now(dt.timezone.utc)).total_seconds()
        except (ValueError,TypeError,OverflowError): return None
    return max(0,seconds) if math.isfinite(seconds) else None

@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    threshold: int = 3
    cooldown: float = 30
    base_delay: float = .25
    maximum_delay: float = 5

class CircuitBreaker:
    def __init__(self,path,policy=None,clock=time.time):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self.policy=policy or RetryPolicy(); self.clock=clock
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS circuits(key TEXT PRIMARY KEY,failures INTEGER NOT NULL,open_until REAL NOT NULL,probe_until REAL NOT NULL)')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path)
        try:
            with db: yield db
        finally: db.close()

    def before(self,key):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT failures,open_until,probe_until FROM circuits WHERE key=?',(key,)).fetchone()
            if row is None:
                db.execute('INSERT INTO circuits VALUES(?,0,0,0)',(key,)); return 'CLOSED'
            if row[1]>self.clock(): raise CircuitOpen('CIRCUIT_OPEN: 暂时熔断，冷却后重试')
            if row[1]>0:
                if row[2]>self.clock(): raise CircuitOpen('CIRCUIT_OPEN: 恢复探测正在进行')
                db.execute('UPDATE circuits SET probe_until=? WHERE key=?',(self.clock()+120,key))
                return 'HALF_OPEN'
            return 'CLOSED'

    def success(self,key):
        with self.connect() as db:
            db.execute('UPDATE circuits SET failures=0,open_until=0,probe_until=0 WHERE key=?',(key,))

    def failure(self,key):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            failures,opened=db.execute('SELECT failures,open_until FROM circuits WHERE key=?',(key,)).fetchone()
            failures+=1
            until=self.clock()+self.policy.cooldown if failures>=self.policy.threshold or opened>0 else 0
            db.execute('UPDATE circuits SET failures=?,open_until=?,probe_until=0 WHERE key=?',(failures,until,key))

    def release_probe(self,key):
        with self.connect() as db:
            db.execute('UPDATE circuits SET probe_until=0 WHERE key=?',(key,))

    def snapshot(self):
        with self.connect() as db:
            return [{'key':k,'failures':f,'open_until':o,'probe_until':p,
                     'state':'OPEN' if o>self.clock() else 'HALF_OPEN' if o>0 else 'CLOSED',
                     'retry_in_seconds':max(0,o-self.clock())} for k,f,o,p in db.execute('SELECT * FROM circuits')]

def retry_call(operation,breaker,key,deadline,check=None,emit=None,sleep=time.sleep):
    """deadline为整个操作的monotonic截止点；取消/权限/业务错误直接传播。"""
    emit=emit or (lambda kind,payload:None)
    for attempt in range(1,breaker.policy.attempts+1):
        if check: check()
        if time.monotonic()>=deadline: raise TimeoutError('Retry operation deadline exceeded')
        try: state=breaker.before(key)
        except CircuitOpen:
            emit('circuit-open',{'operation':key})
            raise
        try:
            emit('attempt-start',{'operation':key,'attempt':attempt,'circuit':state})
            result=operation(max(.01,deadline-time.monotonic()))
        except TransientFailure as error:
            breaker.failure(key)
            emit('attempt-failed',{'operation':key,'attempt':attempt,'error_type':type(error).__name__})
            if attempt==breaker.policy.attempts: raise
            delay=error.retry_after if error.retry_after is not None else breaker.policy.base_delay*2**(attempt-1)
            # 服务端要求等待过长则停止，不能提前违反Retry-After。
            if delay>breaker.policy.maximum_delay: raise
            delay+=random.uniform(0,.05)
            if delay>=deadline-time.monotonic(): raise TimeoutError('Insufficient retry deadline') from None
            emit('retry-scheduled',{'operation':key,'attempt':attempt+1,'delay_seconds':delay})
            slept=0
            while slept<delay:
                if check: check()
                step=min(.1,delay-slept); sleep(step); slept+=step
        except Exception:
            breaker.release_probe(key)
            raise
        else:
            breaker.success(key)
            emit('attempt-succeeded',{'operation':key,'attempt':attempt})
            return result
