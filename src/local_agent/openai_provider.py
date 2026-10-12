"""官方 Responses 接入：模型只产出任务，SQL 和身份始终由本地系统控制。"""
import json
import os
import time
import tempfile
from .semantic import ROOT
from .resilience import CircuitBreaker, TransientFailure, retry_call, retry_after
import httpx


def task_schema():
    """严格模式要求每个属性必填；可选任务/对照窗口用 null 表达。"""
    def obj(properties):
        return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
    string = {'type':'string'}
    query = obj({'metric_id':string,'start':{'type':'string','format':'date'},
                 'end':{'type':'string','format':'date'},
                 'group_by':{'type':'array','items':string},
                 'filters':{'type':'array','items':obj({'dimension':string,'value':string})},
                 'limit':{'type':'integer'}})
    task = obj({'kind':{'type':'string','enum':['query','diagnose']},'query':query,
                'baseline':{'anyOf':[query,{'type':'null'}]},
                'expected_direction':{'type':'string','enum':['decrease','increase','unknown']},
                'diagnosis_dimensions':{'type':'array','items':string}})
    return obj({'clarify':{'type':['string','null']},'task':{'anyOf':[task,{'type':'null'}]}})


def request_task(question, instruction, transport=None, control=None, emit=None):
    """仅重试明确瞬时错误；共享熔断，日志不回显密钥或错误正文。"""
    key, model = os.getenv('OPENAI_API_KEY'), os.getenv('OPENAI_MODEL')
    if not key or not model:
        raise ValueError('WAITING_FOR_MODEL: 请在本机设置 OPENAI_API_KEY 和 OPENAI_MODEL')
    attempts=[]
    def observe(kind,payload):
        attempts.append({'kind':kind,**payload})
        if emit: emit(kind,payload)
    def perform(remaining):
        try:
            with httpx.Client(timeout=min(15,remaining),transport=transport) as client:
                response = client.post('https://api.openai.com/v1/responses',
                headers={'Authorization':'Bearer '+key},json={
                    'model':model,'store':False,'max_output_tokens':4096,'reasoning':{'effort':'low'},
                    'instructions':json.dumps(instruction,ensure_ascii=False)+
                        '\nReturn {clarify:null,task:...} or {clarify:question,task:null}. '
                        'Filters must be an array of {dimension,value}. Dates are UTC closed-open. '
                        'Use only authorized metric definitions; never invent conversion or payment metrics.',
                    'input':question,'text':{'format':{'type':'json_schema','name':'commerce_task',
                        'strict':True,'schema':task_schema()}}})
        except httpx.RequestError:
            raise TransientFailure('MODEL_NETWORK_ERROR: OpenAI 网络暂时失败') from None
        if response.status_code>=400:
            try: error=response.json().get('error',{})
            except (ValueError,AttributeError): error={}
            permanent=error.get('type')=='insufficient_quota' or error.get('code') in ('insufficient_quota','organization_spend_limit_exceeded','project_spend_limit_exceeded','organization_usage_limit_exceeded')
            transient=not permanent and (response.status_code>=500 or (response.status_code==429 and
                (error.get('code') in ('slow_down','rate_limit_exceeded') or error.get('type')=='rate_limit_error'))
                )
            if transient:
                delay=retry_after(response.headers.get('retry-after'))
                raise TransientFailure(f'MODEL_HTTP_ERROR: OpenAI HTTP {response.status_code}',delay)
            raise ValueError(f'MODEL_HTTP_ERROR: OpenAI HTTP {response.status_code}；检查模型/密钥/额度，不自动重试')
        return response
    directory=tempfile.TemporaryDirectory() if transport is not None else None
    path=__import__('pathlib').Path(directory.name)/'circuits.sqlite' if directory else ROOT/'data/own-agent/resilience.sqlite'
    try:
        remaining=control() if control else 45
        response=retry_call(perform,CircuitBreaker(path),'openai:'+model,
            deadline=time.monotonic()+min(45,remaining),check=control,emit=observe)
    finally:
        if directory: directory.cleanup()
    try:
        payload = response.json()
        if payload.get('status') != 'completed':
            raise ValueError('MODEL_INCOMPLETE: 响应未完成，停止执行')
        parts = [part for item in payload.get('output',[]) if item.get('type')=='message'
                 for part in item.get('content',[])]
        if any(p.get('type')=='refusal' for p in parts):
            raise ValueError('MODEL_REFUSAL: 模型拒绝请求，停止执行')
        body = json.loads(''.join(p['text'] for p in parts if p.get('type')=='output_text'))
        if set(body) != {'clarify','task'} or (body['clarify'] is None)==(body['task'] is None):
            raise ValueError('MODEL_INVALID_OUTPUT: 必须返回唯一任务或澄清')
        if body['task'] is not None:
            for query in (body['task']['query'],body['task']['baseline']):
                if query is not None:
                    filters=query['filters']
                    if len({f['dimension'] for f in filters}) != len(filters):
                        raise ValueError('MODEL_INVALID_OUTPUT: 重复过滤条件')
                    query['filters']={f['dimension']:f['value'] for f in filters}
        evidence={'provider':'openai','model':payload.get('model',model),
                  'request_id':response.headers.get('x-request-id'),'response_id':payload.get('id'),
                  'usage':payload.get('usage',{}),'live':transport is None,'attempts':attempts}
        return ({'clarify':body['clarify']} if body['task'] is None else body['task']), evidence
    except (KeyError,TypeError,json.JSONDecodeError):
        raise ValueError('MODEL_INVALID_OUTPUT: 无法解析模型任务，停止执行') from None
