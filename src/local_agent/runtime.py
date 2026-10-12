"""本地持久 Harness：保存状态和查询回执，恢复时重新规划并验证权限/版本。"""
import datetime as dt
import json
import sqlite3
import time
import uuid
from pathlib import Path
from .service import fingerprint
from .semantic import Query
from .harness import build_agent
from .tasks import TaskInterpreter

def encode(value):
    return json.dumps(value,ensure_ascii=False,default=str)

class SessionStore:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, binding TEXT NOT NULL, request TEXT NOT NULL,
                state TEXT NOT NULL, status TEXT NOT NULL, queries INTEGER NOT NULL DEFAULT 0,
                elapsed REAL NOT NULL DEFAULT 0, query_limit INTEGER NOT NULL,
                seconds_limit REAL NOT NULL, cancelled INTEGER NOT NULL DEFAULT 0,
                lease_until REAL NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts (
                session_id TEXT NOT NULL, query_key TEXT NOT NULL, result TEXT NOT NULL,
                PRIMARY KEY(session_id,query_key));''')

    def connect(self):
        return sqlite3.connect(self.path,timeout=15)

    def create(self,binding,request,query_limit=16,seconds_limit=120):
        if not 1<=query_limit<=16 or not 1<=seconds_limit<=120:
            raise ValueError('Runtime budget out of bounds')
        identifier=uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO sessions(id,binding,request,state,status,query_limit,seconds_limit) VALUES(?,?,?,?,?,?,?)',
                (identifier,encode(binding),encode(request),'{}','READY',query_limit,seconds_limit))
        return identifier

    def get(self,identifier):
        with self.connect() as db:
            db.row_factory=sqlite3.Row
            row=db.execute('SELECT * FROM sessions WHERE id=?',(identifier,)).fetchone()
        if row is None: raise ValueError('Unknown session')
        result=dict(row)
        for field in ('binding','request','state'): result[field]=json.loads(result[field])
        return result

    def acquire(self,identifier):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT lease_until FROM sessions WHERE id=?',(identifier,)).fetchone()
            if row is None: raise ValueError('Unknown session')
            if row[0]>time.time(): raise ValueError('Session already running; retry after lease expiry')
            db.execute('UPDATE sessions SET lease_until=?,status=? WHERE id=?',(time.time()+180,'RUNNING',identifier))

    def event(self,identifier,kind,payload):
        with self.connect() as db:
            db.execute('INSERT INTO events(session_id,at,kind,payload) VALUES(?,?,?,?)',
                (identifier,dt.datetime.now(dt.timezone.utc).isoformat(),kind,encode(payload)))

    def checkpoint(self,identifier,state,elapsed):
        with self.connect() as db:
            db.execute('UPDATE sessions SET state=?,elapsed=? WHERE id=?',(encode(state),elapsed,identifier))

    def finish(self,identifier,status,state,elapsed):
        with self.connect() as db:
            db.execute('UPDATE sessions SET status=?,state=?,elapsed=?,lease_until=0 WHERE id=?',
                (status,encode(state),elapsed,identifier))

    def reserve_query(self,identifier):
        """执行前扣预算，崩溃后的不确定查询也算已消耗，不能无限重试。"""
        with self.connect() as db:
            cursor=db.execute('UPDATE sessions SET queries=queries+1 WHERE id=? AND queries<query_limit AND cancelled=0',(identifier,))
            if cursor.rowcount != 1: raise ValueError('Query budget exhausted or session cancelled')

    def receipt(self,identifier,key):
        with self.connect() as db:
            row=db.execute('SELECT result FROM receipts WHERE session_id=? AND query_key=?',(identifier,key)).fetchone()
        return json.loads(row[0]) if row else None

    def save_receipt(self,identifier,key,result):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO receipts VALUES(?,?,?)',(identifier,key,encode(result)))

class RuntimeTools:
    """所有 Skill 共用工具预算；本地回执复用也必须先重新授权和规划。"""
    def __init__(self,tools,store,identifier,check):
        self.inner,self.store,self.identifier,self.check=tools,store,identifier,check

    def __getattr__(self,name): return getattr(self.inner,name)

    def check_execution(self): return self.check()

    def emit(self,kind,payload):
        self.check()
        self.store.event(self.identifier,kind,payload)

    def plan(self,query):
        self.check()
        return self.inner.plan(query)

    def execute(self,plan_id,approval_hash,timeout_seconds=30):
        remaining=self.check()
        plan=self.inner.plans.get(plan_id)
        if not plan or plan['approval_hash']!=approval_hash: raise ValueError('Unknown/modified runtime plan')
        if fingerprint({k:v for k,v in plan.items() if k!='approval_hash'})!=approval_hash:
            raise ValueError('Runtime plan tampered')
        # 重新规划验证原始请求及完整权限，不仅依赖调用方提供的hash。
        from .multi_fact import parse_query
        validated=self.inner.plan(parse_query(plan['requested_query']))
        if validated['sql']!=plan['sql'] or validated['query']!=plan['query']:
            raise ValueError('Runtime plan no longer valid')
        key=fingerprint({'query':validated['query'],'binding':self.store.get(self.identifier)['binding']})
        cached=self.store.receipt(self.identifier,key)
        if cached:
            self.emit('query-reused',{'query':validated['query']})
            return {**cached,'plan_id':plan_id,'receipt_reused':True}
        from .resilience import CircuitBreaker, TransientFailure, retry_call
        def perform(retry_remaining):
            self.check()
            self.store.reserve_query(self.identifier)
            self.emit('query-start',{'query':validated['query'],'transport':'in-process','mcp_tool':'execute_query'})
            def cancel_poll():
                if self.store.get(self.identifier)['cancelled']: raise ValueError('Session cancelled')
            try:
                return self.inner.execute(validated['plan_id'],validated['approval_hash'],timeout_seconds=min(timeout_seconds,retry_remaining),cancel_check=cancel_poll)
            except ValueError as error:
                if str(error)=='Query worker terminated':
                    raise TransientFailure('Query worker temporarily terminated') from None
                raise
        result=retry_call(perform,CircuitBreaker(self.inner.home/'resilience.sqlite'),
            'duckdb-worker',deadline=time.monotonic()+remaining,check=self.check,emit=self.emit)
        # 回执先落盘，进程在下一个节点前中断也能安全复用。
        self.store.save_receipt(self.identifier,key,result)
        self.emit('query-end',{'rows':len(result['rows']),'release_id':result['release_id']})
        return result

class HarnessRuntime:
    def __init__(self,tools,mode='rules',store=None,parser_factory=None):
        self.tools,self.mode=tools,mode
        self.store=store or SessionStore(tools.home/'sessions.sqlite')
        self.parser_factory=parser_factory

    def binding(self):
        self.tools.access.role()
        release=self.tools.release()
        from .skill_resources import PACKAGES,resources,report_template
        skill_hash=fingerprint({'resources':{identifier:resources(identifier,references=True)['sha256'] for identifier in PACKAGES},
                                'report_template':report_template()})
        from .semantic_context import asset_version
        from .dense_retrieval import retrieval_binding
        from .reranking import reranker_binding
        from .structure import graph_binding
        return {'subject':self.tools.principal,'policy':self.tools.access.policy_hash,
                'release':release['release_id'],'registry':self.tools.registry.version,'mode':self.mode,'skills':skill_hash,
                'retrieval_assets':asset_version(self.tools), 'retrieval_strategy':retrieval_binding(),
                'reranker_strategy':reranker_binding(),'structured_strategy':graph_binding()}

    def authorize(self,identifier):
        session=self.store.get(identifier)
        if session['binding']!=self.binding():
            raise ValueError('Session identity/policy/semantic/data version changed; create a new session')
        return session

    def start(self,request,query_limit=16,seconds_limit=120):
        if request.get('context_session'): self.authorize(request['context_session'])
        identifier=self.store.create(self.binding(),request,query_limit,seconds_limit)
        return self.resume(identifier)

    def show(self,identifier):
        session=self.authorize(identifier)
        with self.store.connect() as db:
            rows=db.execute('SELECT seq,at,kind,payload FROM events WHERE session_id=? ORDER BY seq',(identifier,)).fetchall()
            receipts=db.execute('SELECT result FROM receipts WHERE session_id=?',(identifier,)).fetchall()
        return {'session_id':identifier,'status':session['status'],'queries_used':session['queries'],
                'elapsed_seconds':session['elapsed'],'state':session['state'],
                'observation_summary':{'nodes_completed':sum(r[2]=='node-complete' for r in rows),
                    'skills_started':sum(r[2]=='skill-start' for r in rows),
                    'tool_attempts':sum(r[2]=='attempt-start' for r in rows),
                    'retries':sum(r[2]=='retry-scheduled' for r in rows),
                    'failed_attempts':sum(r[2]=='attempt-failed' for r in rows),
                    'circuits_opened':sum(r[2]=='circuit-open' for r in rows),
                    'queries_reused':sum(r[2]=='query-reused' for r in rows),
                    'model_token_usage':session['state'].get('retrieval',{}).get('model_call',{}).get('usage',{})},
                'tool_evidence':[json.loads(r[0]) for r in receipts],
                'events':[{'seq':r[0],'at':r[1],'kind':r[2],'payload':json.loads(r[3])} for r in rows]}

    def cancel(self,identifier):
        self.authorize(identifier)
        with self.store.connect() as db:
            db.execute('UPDATE sessions SET cancelled=1 WHERE id=?',(identifier,))
        self.store.event(identifier,'cancel-requested',{})
        return {'session_id':identifier,'status':'CANCEL_REQUESTED'}

    def followup(self,identifier,reply):
        """澄清回复显式保留原问题；只允许用户明确选择的指标替换歧义词。"""
        session=self.authorize(identifier)
        if session['status']!='CLARIFY': raise ValueError('Follow-up requires a clarification session')
        if not reply.strip(): raise ValueError('Empty clarification')
        original=session['request'].get('question','')
        from .retrieval import KnowledgeRetriever
        retriever=KnowledgeRetriever(self.tools)
        candidates=retriever.metric_candidates(reply)
        if len(candidates)==1:
            aliases=retriever.business['aliases'][candidates[0]]
            selected=next((a for a in sorted(aliases,key=len,reverse=True) if a.casefold() in reply.casefold()),None)
            if selected:
                for ambiguous in retriever.business['ambiguous']: original=original.replace(ambiguous,selected)
        question=original+'；'+reply
        self.store.event(identifier,'clarification-reply',{'reply':reply})
        # 新turn有新预算，旧turn保留为父证据，不覆盖旧失败/澄清记录。
        child=self.store.create(self.binding(),{'question':question,'parent_session':identifier},session['query_limit'],session['seconds_limit'])
        return self.resume(child)

    def resume(self,identifier):
        session=self.authorize(identifier)
        if session['status'] in ('COMPLETE','PREMISE_REFUTED','OBSERVATIONS_ONLY') or (session['status']=='INSUFFICIENT_EVIDENCE' and not session['state'].get('result',{}).get('stopped_reason')):
            return {'session_id':identifier,**session['state'],'already_finished':True}
        if session['status']=='CLARIFY':
            return {'session_id':identifier,**session['state'],'waiting_for_reply':True}
        self.store.acquire(identifier)
        started=time.monotonic()
        base_elapsed=session['elapsed']
        state=dict(session['state'])
        def elapsed(): return base_elapsed+time.monotonic()-started
        def check():
            current=self.authorize(identifier)
            if current['cancelled']: raise ValueError('Session cancelled')
            remaining=current['seconds_limit']-elapsed()
            if remaining<=0: raise TimeoutError('Session deadline exceeded')
            return remaining
        try:
            check()
            proxy=RuntimeTools(self.tools,self.store,identifier,check)
            # 全程只读重放；重新计划，复用已授权回执，不复用进程内plan_id。
            request=session['request']
            if session['state'].get('task'): request={'task_input':session['state']['task']}
            parser=self.parser_factory(proxy) if self.parser_factory else TaskInterpreter(proxy,mode=self.mode)
            if session['request'].get('context_session'):
                parent=self.authorize(session['request']['context_session'])
                parser.conversation_task=parent['state'].get('task')
            graph=build_agent(proxy,parser,registered_skills=True)
            state=dict(request)
            for update in graph.stream(request,stream_mode='updates'):
                check()
                for node,values in update.items():
                    state.update(values)
                    self.store.checkpoint(identifier,state,elapsed())
                    self.store.event(identifier,'node-complete',{'node':node,'status':state.get('status')})
            check()
            status=state.get('status','STOPPED')
        except Exception as error:
            state.update(status='STOPPED',error=str(error))
            status='STOPPED'
            self.store.event(identifier,'run-stopped',{'error':str(error)})
        self.store.finish(identifier,status,state,elapsed())
        return {'session_id':identifier,**state,'runtime':{
            'queries_used':self.store.get(identifier)['queries'],'elapsed_seconds':elapsed()}}
