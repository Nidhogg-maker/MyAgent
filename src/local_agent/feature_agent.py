"""画像工具与统一入口路由。有限规则理解明确请求，不生成自由 SQL。

特征发布版本独立于指标快照，避免旧指标质量过期阻断画像读取。
画像只向本地主体开放；受限聚合令牌不因此获得用户级数据访问。
"""
import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .semantic import ROOT, file_hash
from .integrity import fingerprint
from .runtime import SessionStore, HarnessRuntime

PRODUCTS={
    'user_profile':('ads.ads_user_profile_daily',('user_id',)),
    'product_profile':('ads.ads_product_profile_daily',('product_id',)),
    'user_product':('ads.ads_user_product_features',('user_id','product_id')),
    'session':('dws.dws_session_behavior',('session_id',)),
}


class FeatureRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    kind: str='profile'
    data_product: str
    as_of: dt.date
    user_id: int | None=Field(default=None,gt=0)
    product_id: int | None=Field(default=None,gt=0)
    session_id: str | None=Field(default=None,min_length=1,max_length=128)

    @model_validator(mode='after')
    def coherent(self):
        if self.kind not in ('profile','describe') or self.data_product not in PRODUCTS:
            raise ValueError('Unsupported feature task')
        required=PRODUCTS[self.data_product][1]
        if self.kind=='profile' and any(getattr(self,k) is None for k in required):
            raise ValueError('CLARIFY: 请提供 '+', '.join(required))
        if any(getattr(self,k) is not None for k in ('user_id','product_id','session_id') if k not in required):
            raise ValueError('Conflicting entity identifiers')
        return self


def is_feature_question(question):
    return bool(re.search(r'画像|会话|用户.*商品.*(?:特征|交互)|数据产品|数据契约|user.?profile|product.?profile|session',question,re.I))


def parse_feature_question(question, previous=None):
    """支持显式实体和完整日期；澄清通过字段补丁合并，不拼接矛盾问题。"""
    if re.search(r'\b(?:select|drop|insert|update|delete)\b|对比|比较|排名|最高|最低',question,re.I):
        raise ValueError('CLARIFY: 画像入口只支持单实体与明确日期，不支持自由SQL或画像比较')
    data=dict(previous or {})
    if re.search(r'会话|session',question,re.I):data['data_product']='session'
    elif ('用户' in question and '商品' in question) or 'user_product' in question:data['data_product']='user_product'
    elif re.search(r'商品|product',question,re.I):data['data_product']='product_profile'
    elif re.search(r'用户|user',question,re.I):data['data_product']='user_profile'
    data['kind']='describe' if re.search(r'字段|契约|粒度|数据产品说明',question) else data.get('kind','profile')
    dates=re.findall(r'(?<!\d)(\d{4})[-年](\d{1,2})[-月](\d{1,2})日?(?!\d)',question)
    if len(set(dates))>1:raise ValueError('CLARIFY: 请提供一个明确的截止日期')
    if dates:
        data['as_of']=dt.date(*map(int,dates[0])).isoformat()
    for key,pattern in [('user_id',r'(?:用户|user)\s*(?:ID|编号)?\s*[:：#]?\s*(\d+)'),
                        ('product_id',r'(?:商品|product)\s*(?:ID|编号)?\s*[:：#]?\s*(\d+)')]:
        matches=re.findall(pattern,question,re.I)
        if len(set(matches))>1:raise ValueError('CLARIFY: 每次只查询一个实体')
        if matches:data[key]=int(matches[0])
    sessions=re.findall(r'(?:会话|session)\s*(?:ID|编号)?\s*[:：#]?\s*([A-Za-z0-9-]{6,128})',question,re.I)
    if sessions:
        if len(set(sessions))>1:raise ValueError('CLARIFY: 每次只查询一个会话')
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',sessions[0]):raise ValueError('CLARIFY: 请单独提供会话ID')
        data['session_id']=sessions[0]
    return data


class FeatureTools:
    def __init__(self,tools,home=None,pinned_release=None):
        self.inner=tools;self.home=Path(home) if home else ROOT/'data/feature-mart'
        self.pinned_release=pinned_release

    def __getattr__(self,name):return getattr(self.inner,name)

    def _allow(self):
        if not self.inner.access.role().get('publish'):
            raise ValueError('User-level profiles are not available to aggregate-only credentials')

    def release(self,as_of):
        self._allow();date=dt.date.fromisoformat(str(as_of)).isoformat()
        candidates=[]
        for path in (self.home/'releases').glob('*/release.json'):
            r=json.loads(path.read_text(encoding='utf-8'))
            if r.get('status')=='PASS' and r.get('as_of_date')==date:
                if self.pinned_release and r['release_id']!=self.pinned_release:continue
                candidates.append((path.stat().st_mtime_ns,path,r))
        if not candidates:raise ValueError('CLARIFY: 指定日期没有成功发布版本：'+date)
        _,path,r=max(candidates,key=lambda item:item[0])
        directory=path.parent.resolve()
        database=Path(r['database']).resolve()
        if not directory.is_relative_to((self.home/'releases').resolve()) or database.parent!=directory:
            raise ValueError('Feature release path escaped publication directory')
        for file,expected in [(database,r['database_sha256']),
                              (directory/'metadata.json',r.get('metadata_sha256')),
                              (directory/'table-contracts.json',r.get('table_contracts_sha256'))]:
            if not expected or file_hash(file)!=expected:raise ValueError('Feature artifact changed; rebuild required')
        return r,directory

    def read_profile(self,request):
        r,directory=self.release(request.as_of)
        table,keys=PRODUCTS[request.data_product]
        if table not in r['quality']['tables']:raise ValueError('CLARIFY: 此日期版本未构建该数据产品')
        contracts=json.loads((directory/'table-contracts.json').read_text(encoding='utf-8'))
        metadata=json.loads((directory/'metadata.json').read_text(encoding='utf-8'))
        result={'data_product':request.data_product,'as_of':str(request.as_of),'release_id':r['release_id'],
                'definition':contracts['tables'][table], 'quality':r['quality']['status'],
                'lineage':metadata['tables'][table],'source_observed_at':r['source_observed_at'],
                'warnings':['source completeness and historical ingestion availability unverified',
                    'page view is not CTR click; placed order is not payment success',
                    'session without purchase is not a verified negative label'],
                'found':None,'rows':[]}
        if request.kind=='describe':return result
        columns=list(contracts['tables'][table]['columns'])
        # Columns and tables come from a hash-bound local contract; values are bound.
        import duckdb
        from sqlglot import exp
        selected=','.join(exp.Identifier(this=c,quoted=True).sql() for c in columns)
        conditions=' AND '.join(k+'=?' for k in keys)
        params=[getattr(request,k) for k in keys]
        worker_input={'database':r['database'],'sql':f'SELECT {selected} FROM {table} WHERE {conditions} AND as_of_date=? LIMIT 2',
                      'parameters':params+[str(request.as_of)]}
        # Separate process inherits only a fixed SELECT and typed parameters.
        completed=subprocess.run([sys.executable,'-m','local_agent.worker'],input=json.dumps(worker_input),
            text=True,encoding='utf-8',capture_output=True,timeout=15,cwd=ROOT)
        if completed.returncode:raise ValueError('Feature worker terminated')
        payload=json.loads(completed.stdout)
        if 'error' in payload:raise ValueError('Feature worker failed: '+payload['error'])
        if len(payload['rows'])>1:raise ValueError('Profile grain violation')
        result.update(found=bool(payload['rows']),columns=payload['columns'],rows=payload['rows'])
        if not result['found']:result['note']='该日期没有此实体记录；没有记录不代表特征全部为零或用户未转化'
        return result


class FeatureRuntime:
    """画像小任务也保存状态和证据；不调用过期的指标 release。"""
    def __init__(self,tools,home=None):
        self.tools=tools;self.store=SessionStore(tools.home/'feature-sessions.sqlite')
        self.feature_home=home

    def base_binding(self):
        self.tools.access.role()
        package=ROOT/'skills/warehouse-profile-query'
        return {'subject':self.tools.principal,'policy':self.tools.access.policy_hash,
            'skill':fingerprint({p.name:file_hash(p) for p in package.rglob('*.md')})}

    def authorize(self,identifier):
        s=self.store.get(identifier.removeprefix('feature-'))
        if s['binding']!=self.base_binding():raise ValueError('Feature session identity/policy/Skill changed')
        # Cached answers must retain the same integrity checks as fresh reads.
        if s['state'].get('feature_release_id') and s['state'].get('feature_task'):
            FeatureTools(self.tools,home=self.feature_home,pinned_release=s['state']['feature_release_id']).release(s['state']['feature_task']['as_of'])
        return s

    def start(self,request,**kwargs):
        identifier=self.store.create(self.base_binding(),request,query_limit=1,seconds_limit=60)
        return self.resume('feature-'+identifier)

    def resume(self,identifier):
        s=self.authorize(identifier);key=identifier.removeprefix('feature-')
        if s['status'] in ('COMPLETE','CLARIFY'):return {'session_id':identifier,**s['state']}
        self.store.acquire(key);started=time.monotonic();state={}
        try:
            if s['cancelled']:raise ValueError('Feature session cancelled')
            data=s['request'].get('feature_input') or parse_feature_question(s['request'].get('question',''),s['request'].get('previous'))
            state['feature_partial']=data
            missing=[x for x in ('data_product','as_of') if x not in data]
            if missing:raise ValueError('CLARIFY: 请提供数据产品和完整截止日期 YYYY-MM-DD；缺少 '+', '.join(missing))
            task=FeatureRequest.model_validate(data);state['feature_task']=task.model_dump(mode='json')
            feature_tools=FeatureTools(self.tools,home=self.feature_home,pinned_release=s['state'].get('feature_release_id'))
            r,_=feature_tools.release(task.as_of);state['feature_release_id']=r['release_id']
            self.store.checkpoint(key,state,time.monotonic()-started)
            receipt_key=fingerprint({'request':state['feature_task'],'release':r['release_id'],'binding':s['binding']})
            cached=self.store.receipt(key,receipt_key)
            if cached:result=cached;self.store.event(key,'query-reused',{'release_id':r['release_id']})
            else:
                if task.kind=='profile':self.store.reserve_query(key)
                from .skills import SkillExecutor
                self.store.event(key,'skill-start',{'skill':'profile-query','mode':'bounded rules; no model request'})
                result=SkillExecutor(feature_tools).run('profile-query',state['feature_task'])['result']
                self.store.save_receipt(key,receipt_key,result)
                self.store.event(key,'skill-end',{'skill':'profile-query','release_id':r['release_id']})
            if self.store.get(key)['cancelled']:raise ValueError('Feature session cancelled')
            if time.monotonic()-started>60:raise TimeoutError('Feature session deadline exceeded')
            lines=['# 数据产品查询',f"数据产品：{task.data_product}",f"截止：UTC {task.as_of} 00:00",f"版本：{r['release_id']}",
                json.dumps(dict(zip(result.get('columns',[]),result['rows'][0])) if result.get('rows') else result.get('note','字段和粒度见结构化证据'),ensure_ascii=False),
                '限制：完整性与历史可用性未验证；purchase事件不代表支付成功。']
            if task.kind=='describe':
                lines.insert(4,'粒度：'+', '.join(result['definition']['grain']))
                lines.insert(5,'字段：\n'+'\n'.join('- '+name+' ('+datatype+')' for name,datatype in result['definition']['columns'].items()))
            state.update(status='COMPLETE',answer={'kind':'profile','summary':'已按指定版本读取数据产品','evidence':result,'markdown':'\n\n'.join(lines)})
        except Exception as error:
            message=str(error);state.update(status='CLARIFY' if 'CLARIFY:' in message else 'STOPPED',error=message)
        self.store.finish(key,state['status'],state,time.monotonic()-started)
        return {'session_id':identifier,**state}

    def show(self,identifier):
        s=self.authorize(identifier);key=identifier.removeprefix('feature-')
        with self.store.connect() as db:events=db.execute('SELECT kind,payload FROM events WHERE session_id=? ORDER BY seq',(key,)).fetchall()
        return {'session_id':identifier,'status':s['status'],'state':s['state'],'queries_used':s['queries'],
                'events':[{'kind':k,'payload':json.loads(v)} for k,v in events]}

    def cancel(self,identifier):
        self.authorize(identifier)
        with self.store.connect() as db:db.execute('UPDATE sessions SET cancelled=1 WHERE id=?',(identifier.removeprefix('feature-'),))
        return {'session_id':identifier,'status':'STOPPED','error':'已请求取消'}

    def followup(self,identifier,reply):
        s=self.authorize(identifier)
        if s['status']!='CLARIFY':raise ValueError('Only clarification sessions accept reply')
        return self.start({'question':reply,'previous':s['state'].get('feature_partial',{})})


class UnifiedRuntime:
    """同一 ask/chat 入口分派指标任务和画像任务，持久化各自的证据。"""
    def __init__(self,tools,mode='rules',feature_home=None):
        self.tools=tools;self.metric=HarnessRuntime(tools,mode);self.feature=FeatureRuntime(tools,feature_home)
        class StoreRouter:
            def get(_,identifier):
                return self.feature.store.get(identifier.removeprefix('feature-')) if identifier.startswith('feature-') else self.metric.store.get(identifier)
        self.store=StoreRouter()

    def target(self,identifier):return self.feature if identifier.startswith('feature-') else self.metric
    def authorize(self,identifier):return self.target(identifier).authorize(identifier)
    def show(self,identifier):return self.target(identifier).show(identifier)
    def resume(self,identifier):return self.target(identifier).resume(identifier)
    def cancel(self,identifier):return self.target(identifier).cancel(identifier)
    def followup(self,identifier,reply):return self.target(identifier).followup(identifier,reply)
    def start(self,request,**kwargs):
        context=request.get('context_session')
        if request.get('feature_input') or is_feature_question(request.get('question','')):
            return self.feature.start(request,**kwargs)
        if context and context.startswith('feature-'):request={k:v for k,v in request.items() if k!='context_session'}
        return self.metric.start(request,**kwargs)
