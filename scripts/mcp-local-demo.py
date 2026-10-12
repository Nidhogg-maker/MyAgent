"""只演示本地MCP真实调用，不部署远程服务或增加企业治理设施。"""
import asyncio
import json
import os
import sys
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from local_agent.semantic import ROOT

async def main():
    parameters=StdioServerParameters(command=sys.executable,args=['-m','local_agent.mcp_server'],
        env={**os.environ,'OWN_AGENT_HOME':str(ROOT/'data/own-agent')})
    async with stdio_client(parameters) as (reader,writer):
        async with ClientSession(reader,writer) as client:
            await client.initialize()
            discovered=await client.list_tools()
            request={'metric_id':'order_count@1','start':'2026-09-01','end':'2026-10-01'}
            planned=await client.call_tool('plan_query',{'query':request})
            if planned.isError: raise ValueError('Local MCP plan failed')
            plan=json.loads(planned.content[0].text)
            executed=await client.call_tool('execute_query',{'plan_id':plan['plan_id'],'approval_hash':plan['approval_hash']})
            if executed.isError: raise ValueError('Local MCP execution failed')
            result=json.loads(executed.content[0].text)
            record={'transport':'stdio','steps':['initialize','list_tools','plan_query','execute_query'],
                    'discovered_tools':[tool.name for tool in discovered.tools],'request':request,
                    'logical_plan':plan['logical_plan'],'result':result}
            (ROOT/'docs/mcp-local-call.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'transport':'stdio','rows':result['rows'],'tools':len(discovered.tools)},ensure_ascii=False))

if __name__=='__main__': asyncio.run(main())
