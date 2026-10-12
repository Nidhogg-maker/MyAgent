"""无模型调用的真实工作流演示；复用本地发布快照，保存会话与全部证据。"""
import json
from local_agent.semantic import ROOT
from local_agent.service import AgentTools
from local_agent.runtime import HarnessRuntime

tools=AgentTools()
runtime=HarnessRuntime(tools)
current={'metric_id':'complete_order_rate@1','start':'2026-09-01','end':'2026-09-08','filters':{'gender':'M'}}
baseline={**current,'start':'2026-08-01','end':'2026-08-08'}
result=runtime.start({'task_input':{'kind':'diagnose','query':current,'baseline':baseline,'expected_direction':'unknown'}})
record=runtime.show(result['session_id'])
(ROOT/'docs/runtime-workflow-demo.json').write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
print(json.dumps({'session_id':result['session_id'],'status':result['status'],
    'queries_used':record['queries_used'],'change':result.get('result',{}).get('change'),
    'decompositions':len(result.get('result',{}).get('decompositions',[])),
    'error':result.get('error')},ensure_ascii=False))
