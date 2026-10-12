"""提交项目的独立入口：只使用自己的核心模块和通用开源库。"""
import argparse
import json
import sys
import os
from pathlib import Path
from .semantic import ROOT, SemanticRegistry
from .service import AgentTools
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
    commands.add_parser('capture-history')
    query = commands.add_parser('query')
    query.add_argument('--request', type=Path, required=True)
    ask = commands.add_parser('ask')
    ask.add_argument('question')
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
        tools = AgentTools(args.home,token=os.getenv('OWN_AGENT_TOKEN'))
        if args.command in ('chat','session','resume','cancel','reply'):
            from .feature_agent import UnifiedRuntime
            runtime=UnifiedRuntime(tools,args.intent_mode)
            if args.command=='chat':
                from .chat import chat_loop
                return chat_loop(runtime,args.session)
            result=runtime.show(args.session_id) if args.command=='session' else runtime.cancel(args.session_id) if args.command=='cancel' else runtime.followup(args.session_id,args.text) if args.command=='reply' else runtime.resume(args.session_id)
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
            from .retrieval import KnowledgeRetriever
            result = KnowledgeRetriever(tools).search(args.question)
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
