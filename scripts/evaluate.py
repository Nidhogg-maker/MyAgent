"""输出可复现的规则识别、检索与真实数据执行证据，不调用远程模型。"""
import json
from local_agent.semantic import ROOT
from local_agent.service import AgentTools
from local_agent.evaluation import evaluate_rules
from local_agent.harness import build_agent

def main():
    tools = AgentTools()
    report = evaluate_rules(tools)
    # 真实数据执行与意图识别分别验收，包含成功与澄清，不混为模型正确率。
    questions = ['查询2026年9月订单量','2026年9月各国家客单价','2026年9月按品类已完成商品金额','销售额是多少','今天的转化率为什么比昨天低']
    executions = []
    agent = build_agent(tools)
    for question in questions:
        state = agent.invoke({'question':question})
        executions.append({'question':question,'status':state['status'],'trace':state['trace'],
                           'skill':state.get('skill'),'result':state.get('result'),'error':state.get('error')})
    report['real_data_rule_executions'] = executions
    report['mock_model_protocol_results'] = 'see JUnit tests/test_extensions.py; not a semantic accuracy score'
    (ROOT/'docs/evaluation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(f"Rule cases: {report['passed']}/{report['total']}; real LLM evaluated: False")
    return 0 if report['passed']==report['total'] else 1

if __name__=='__main__':
    raise SystemExit(main())
