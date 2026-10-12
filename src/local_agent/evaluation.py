"""离线评测只衡量本地规则；模拟模型测协议，真实LLM成绩必须独立记录。"""
import datetime as dt
import json
from .semantic import ROOT
from .tasks import TaskInterpreter

def load_cases():
    return [json.loads(line) for line in (ROOT/'evaluation/intent-cases.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]

def evaluate_rules(tools):
    """固定UTC时钟，逐字段验证指标、窗口、分组、方向和Skill路由。"""
    reference = dt.datetime(2026,10,11,12,tzinfo=dt.timezone.utc)
    rows = []
    for case in load_cases():
        interpreter = TaskInterpreter(tools,mode='rules',now=reference)
        actual,task,error = None,None,None
        try:
            task = interpreter.parse(case['question'])
            actual = task.kind
        except Exception as exc:
            error = str(exc)
            actual = 'CLARIFY' if error.startswith('CLARIFY:') else 'STOPPED'
        passed = actual==case['expected']
        if task:
            checks = {'metric':task.query.metric_id,'start':str(task.query.start),'end':str(task.query.end),
                      'groups':list(task.query.group_by),'direction':task.expected_direction,
                      'baseline_start':str(task.baseline.start) if task.baseline else None}
            passed &= all(checks[key]==case[key] for key in checks if key in case)
        rows.append({'id':case['id'],'question':case['question'],'expected':case['expected'],'actual':actual,
                     'passed':passed,'task':task.model_dump(mode='json') if task else None,'error':error})
    retriever = TaskInterpreter(tools,now=reference).retriever
    retrieval = []
    for case in load_cases():
        if case.get('metric') and case['expected'] in ('query','diagnose'):
            hits = retriever.search(case['question'],limit=3)
            retrieval.append({'id':case['id'],'target':case['metric'],'hit_at_3':any(h.get('metric_id')==case['metric'] for h in hits)})
    return {'scope':'Curated local rule subset; not LLM accuracy or unseen language benchmark',
            'reference_clock':reference.isoformat(),'total':len(rows),'passed':sum(row['passed'] for row in rows),
            'cases':rows,'retrieval':retrieval,'real_llm_evaluated':False}
