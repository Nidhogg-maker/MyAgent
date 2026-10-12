"""提交项目的独立入口：只使用自己的核心模块和通用开源库。"""
import argparse
import json
import sys
import os
from pathlib import Path
from .semantic import ROOT, SemanticRegistry
from .service import QueryService
from .harness import build_agent
from .tasks import TaskInterpreter

def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='自主电商 Data Agent')
    parser.add_argument('--home', type=Path, default=ROOT / 'data/own-agent')
    parser.add_argument('--intent-mode',choices=['rules','llm'],default='rules')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('metrics')
    commands.add_parser('skills')
    commands.add_parser('health')
    commands.add_parser('template-cache', help='查看本地主体语义IR缓存；不显示数据结果')
    chat = commands.add_parser('chat')
    chat.add_argument('--session')
    for action in ('session','resume','cancel'):
        command=commands.add_parser(action)
        command.add_argument('session_id')
    reply=commands.add_parser('reply')
    reply.add_argument('session_id')
    reply.add_argument('text')
    publication = commands.add_parser('publish')
    publication.add_argument('--coverage',type=Path)
    identity = commands.add_parser('issue-token')
    identity.add_argument('subject')
    diagnosis = commands.add_parser('diagnose')
    diagnosis.add_argument('--task',type=Path,required=True)
    search = commands.add_parser('search')
    search.add_argument('question')
    search.add_argument('--partition')
    relations = commands.add_parser('relations',help='查询注册语义依赖或影响范围；不是Join授权')
    relations.add_argument('node_id')
    relations.add_argument('--direction',choices=['dependencies','impact'],default='dependencies')
    relations.add_argument('--depth',type=int,default=3)
    relations.add_argument('--max-nodes',type=int,default=80)
    resolve = commands.add_parser('resolve-semantics', help='解析权威指标、组件、共同维度与按需枚举')
    resolve.add_argument('--metric', action='append', required=True)
    resolve.add_argument('--dimension', action='append', default=[])
    resolve.add_argument('--values', action='append', default=[])
    commands.add_parser('capture-history')
    query = commands.add_parser('query')
    query.add_argument('--request', type=Path, required=True)
    multi_query = commands.add_parser('multi-query', help='执行显式多事实语义请求')
    multi_query.add_argument('--request', type=Path, required=True)
    ask = commands.add_parser('ask')
    ask.add_argument('question')
    agent = commands.add_parser('agent', help='有界自主工具选择与 Workflow 执行')
    agent.add_argument('question')
    agent.add_argument('--max-steps', type=int, default=6)
    agent.add_argument('--max-searches', type=int, default=3)
    agent.add_argument('--multi-plan', action='store_true', help='候选计划、选择和逐步执行模式')
    profile = commands.add_parser('profile')
    profile.add_argument('--product',choices=['user_profile','product_profile','user_product','session'],required=True)
    profile.add_argument('--as-of',required=True)
    profile.add_argument('--user-id',type=int)
    profile.add_argument('--product-id',type=int)
    profile.add_argument('--session-id')
    profile.add_argument('--describe',action='store_true')
    lineage = commands.add_parser('lineage')
    lineage.add_argument('table')
    lineage.add_argument('--column')
    args = parser.parse_args(argv)
    try:
        tools = QueryService(args.home,token=os.getenv('OWN_AGENT_TOKEN'))
        if args.command in ('chat','session','resume','cancel','reply'):
            from .feature_agent import UnifiedRuntime
            runtime=UnifiedRuntime(tools,args.intent_mode)
            if args.command=='chat':
                from .chat import chat_loop
                return chat_loop(runtime,args.session)
            if not args.session_id.startswith('feature-'):
                from .runtime import SessionStore
                saved = SessionStore(tools.home/'sessions.sqlite').get(args.session_id)
                if saved['binding'].get('mode') == 'agent':
                    from .agent_loop import AgentLoop
                    runtime = AgentLoop(tools)
            result=runtime.show(args.session_id) if args.command=='session' else runtime.cancel(args.session_id) if args.command=='cancel' else runtime.followup(args.session_id,args.text) if args.command=='reply' else runtime.resume(args.session_id)
        elif args.command=='agent':
            from .agent_loop import AgentLoop
            result = AgentLoop(tools).start(args.question, max_steps=args.max_steps,
                                           max_searches=args.max_searches, multi_plan=args.multi_plan)
        elif args.command == 'multi-query':
            from .multi_fact import MultiFactQuery
            query = MultiFactQuery.model_validate(json.loads(args.request.read_text(encoding='utf-8')))
            plan = tools.plan(query)
            result = {'status': 'COMPLETE', 'plan': plan,
                      'result': tools.execute(plan['plan_id'], plan['approval_hash'])}
        elif args.command=='template-cache':
            from .query_templates import QueryTemplateCache
            tools.access.role()
            result = QueryTemplateCache(tools.home).stats()
        elif args.command=='health':
            from .resilience import CircuitBreaker
            result={'circuits':CircuitBreaker(tools.home/'resilience.sqlite').snapshot(),'scope':'local observation only'}
        elif args.command=='skills':
            from .skills import SkillRegistry
            result=[spec.model_dump() for spec in SkillRegistry().specs.values()]
        elif args.command == 'publish':
            result = tools.publish(ROOT / 'data/thelook.duckdb', ROOT / 'warehouse-commerce/target/manifest.json', ROOT / 'docs/thelook-dbt-run-results.json',args.coverage)
        elif args.command == 'issue-token':
            result = {'token':tools.access.issue(args.subject),'subject':args.subject,'scope':'local capability; not enterprise SSO'}
        elif args.command == 'metrics':
            result = [tools.describe(m) for m in tools.registry.contract['metrics'] if tools._metric_allowed(m)]
        elif args.command == 'lineage':
            tools.release()
            result = tools.lineage(args.table,args.column)
        elif args.command == 'search':
            from .retrieval_service import get_retrieval_service
            result = get_retrieval_service(tools).retrieve(args.question,partition=args.partition)
        elif args.command=='relations':
            from .structure import GraphService
            result = GraphService(tools).query(args.node_id,args.direction,args.depth,args.max_nodes)
        elif args.command == 'resolve-semantics':
            from .semantic_context import SemanticContextResolver
            result = SemanticContextResolver(tools).resolve(args.metric, args.dimension, args.values)
        elif args.command == 'capture-history':
            from .history import SnapshotHistory
            import datetime as dt
            if not tools.access.role()['publish']:
                raise ValueError('History capture requires trusted administrator')
            release = tools.release()
            result = SnapshotHistory(args.home/'history.sqlite').capture_warehouse(release['database'],dt.datetime.now(dt.timezone.utc).isoformat(),release['release_id'])
        else:
            if args.command=='profile':
                data={'kind':'describe' if args.describe else 'profile','data_product':args.product,'as_of':args.as_of}
                data.update({k:getattr(args,k) for k in ('user_id','product_id','session_id') if getattr(args,k) is not None})
                request={'feature_input':data}
            else:
                request = {'query_input':json.loads(args.request.read_text(encoding='utf-8'))} if args.command=='query' else {'task_input':json.loads(args.task.read_text(encoding='utf-8'))} if args.command=='diagnose' else {'question':args.question}
            from .feature_agent import UnifiedRuntime
            result = UnifiedRuntime(tools,args.intent_mode).start(request)
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
        return 2 if isinstance(result, dict) and result.get('status') in ('STOPPED', 'CLARIFY','INSUFFICIENT_EVIDENCE') else 0
    except Exception as error:
        print(json.dumps({'status': 'STOPPED', 'error': str(error)}, ensure_ascii=False))
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
