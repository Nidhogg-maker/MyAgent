"""使用真实本地发布验证自然语言、结构化工具及 MCP，不请求模型。"""
import asyncio
import json
import os
import sys
from pathlib import Path
import duckdb
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from local_agent.semantic import ROOT
from local_agent.service import AgentTools
from local_agent.feature_agent import UnifiedRuntime


async def main():
    release=json.loads((ROOT/'data/feature-mart/active.json').read_text(encoding='utf-8'))
    date=release['as_of_date']
    with duckdb.connect(release['database'],read_only=True) as db:
        user,product=db.execute('SELECT user_id,product_id FROM ads.ads_user_product_features ORDER BY booked_amount_30d DESC LIMIT 1').fetchone()
        session=db.execute('SELECT session_id FROM dws.dws_session_behavior WHERE purchase_event_count=0 LIMIT 1').fetchone()[0]
    runtime=UnifiedRuntime(AgentTools())
    questions=[f'查看用户{user}截至{date}的画像',f'查看商品{product}截至{date}的画像',
        f'查看用户{user}和商品{product}截至{date}的交互特征',
        f'查看会话{session}截至{date}的行为',f'说明截至{date}的用户画像字段']
    results=[runtime.start({'question':q}) for q in questions]
    assert all(r['status']=='COMPLETE' for r in results),[(q,r.get('error')) for q,r in zip(questions,results)]
    structured=runtime.start({'feature_input':{'data_product':'user_profile','user_id':user,'as_of':date}})
    assert structured['answer']['evidence']['rows']==results[0]['answer']['evidence']['rows']
    server=StdioServerParameters(command=sys.executable,args=['-m','local_agent.mcp_server'],env={**os.environ,'OWN_AGENT_HOME':str(ROOT/'data/own-agent')})
    async with stdio_client(server) as (reader,writer):
        async with ClientSession(reader,writer) as client:
            await client.initialize();listed=await client.list_tools()
            response=await client.call_tool('get_user_profile',{'user_id':user,'as_of':date})
            assert not response.isError
            mcp_result=json.loads(response.content[0].text)
            assert mcp_result['rows']==results[0]['answer']['evidence']['rows']
    record={'mode':'local bounded rules, no model call','release_id':release['release_id'],
        'questions':questions,'results':results,'structured':structured,
        'mcp':{'transport':'stdio','tool_count':len(listed.tools),'result':mcp_result}}
    (ROOT/'docs/feature-phase2-live-demo.json').write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'status':'PASS','natural_requests':5,'structured_matches':True,'mcp_tools':len(listed.tools),
        'user_id':user,'product_id':product,'session_id':session},ensure_ascii=False))


if __name__=='__main__':asyncio.run(main())
