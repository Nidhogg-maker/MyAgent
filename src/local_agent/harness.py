"""自主 Harness：确定性约束负责正确性，模型仅负责受限意图转换。"""
from typing import TypedDict
from langgraph.graph import START, END, StateGraph
from .semantic import Query, ROOT
from .tasks import Task, TaskInterpreter
from .retrieval import KnowledgeRetriever
from .diagnosis import DiagnosisEngine

class State(TypedDict, total=False):
    query_input: dict
    question: str
    query: dict
    context: dict
    plan: dict
    result: dict
    trace: list
    status: str
    error: str
    task_input: dict
    task: dict
    retrieval: dict
    schema_link: dict
    skill: str
    answer: dict
    retrieval_context: dict

def build_agent(tools, parser=None, registered_skills=False):
    """有界分支图：任务理解与目录共享，随后选择查询或诊断Skill；失败停止。"""
    parser = parser or TaskInterpreter(tools, mode='rules')
    from .skills import SkillExecutor
    executor = SkillExecutor(tools) if registered_skills else None
    def guarded(name, fn):
        def call(state):
            trace = state.get('trace', []) + [name]
            try:
                return {**fn(state), 'trace': trace}
            except Exception as error:
                message = str(error)
                return {'status': 'CLARIFY' if message.startswith('CLARIFY:') else 'STOPPED', 'error': message, 'trace': trace,
                        **({'retrieval':getattr(parser,'last_evidence',{})} if name=='intent' else {})}
        return call
    def intent(state):
        tools.access.role()
        if 'task_input' in state:
            task = Task.model_validate(state['task_input'])
        elif 'query_input' in state:
            task = Task(kind='query',query=Query.model_validate(state['query_input']))
        else:
            parsed = parser.parse(state['question'])
            task = parsed if isinstance(parsed,Task) else Task(kind='query',query=parsed)
        tools.describe(task.query.metric_id)
        return {'query':task.query.model_dump(mode='json'),'task':task.model_dump(mode='json'),
                'skill':'commerce-diagnosis' if task.kind=='diagnose' else 'commerce-query',
                'retrieval':getattr(parser,'last_evidence',{'mode':'structured'})}
    def context(state):
        from .retrieval_context import resolve_context
        return {'context': tools.context(state['query']['metric_id']), 'schema_link':KnowledgeRetriever(tools).link(state['query']['metric_id']),
                'retrieval_context':resolve_context(tools,state['query']['metric_id'],state.get('retrieval',{}).get('retrieved',[]))}
    def plan(state):
        return {'plan': tools.plan(Query.model_validate(state['query']))}
    def execute(state):
        if executor:
            return {'result':executor.run('metric-query',state['query'])['result']}
        plan = state['plan']
        return {'result': tools.execute(plan['plan_id'], plan['approval_hash'])}
    def diagnose(state):
        if executor:
            return {'result':executor.run('anomaly-analysis',state['task'])['result']}
        return {'result':DiagnosisEngine(tools).run(Task.model_validate(state['task']))}
    def answer(state):
        diagnostic = state['task']['kind']=='diagnose'
        result = state['result']
        status = result['status'] if diagnostic else 'COMPLETE'
        if executor:
            report=executor.run('evidence-report',{'kind':state['task']['kind'],'evidence':result,'task':state['task']})['result']
            report['metric_id']=state['query']['metric_id']
            return {'status':status,'answer':report}
        return {'status':status, 'answer':{'kind':state['task']['kind'], 'causal_claim':False,
                    'summary':result.get('conclusion','已按指定口径执行，结果和质量/权限/时间范围见证据'),
                    'metric_id':state['query']['metric_id'], 'evidence':result}}
    graph = StateGraph(State)
    nodes = [('intent', intent), ('metadata', context), ('quality_and_plan', plan), ('execute', execute), ('diagnosis',diagnose), ('answer',answer)]
    for name, fn in nodes:
        graph.add_node(name, guarded(name, fn))
    graph.add_edge(START, 'intent')
    graph.add_conditional_edges('intent',lambda state:END if state.get('status') in ('STOPPED','CLARIFY') else 'metadata')
    graph.add_conditional_edges('metadata',lambda state:END if state.get('status') in ('STOPPED','CLARIFY') else 'diagnosis' if state['task']['kind']=='diagnose' else 'quality_and_plan')
    for name,target in [('quality_and_plan','execute'),('execute','answer'),('diagnosis','answer'),('answer',END)]:
        graph.add_conditional_edges(name,lambda state,target=target:END if state.get('status') in ('STOPPED','CLARIFY') else target)
    return graph.compile()
