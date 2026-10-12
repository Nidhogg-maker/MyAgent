"""从实际回执统一评分并生成报告；检索失败不冒充召回未命中，超时不冒充正确拒绝。"""
import importlib.util
import json
import math
import shutil
import statistics
from pathlib import Path
from collections import Counter
import duckdb
from local_agent.semantic import ROOT,file_hash
from local_agent.service import QueryService

spec=importlib.util.spec_from_file_location('benchmark',ROOT/'scripts/correctness-benchmark.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
OUT=b.OUT


def percent(n,d):return f'{n}/{d} ({n/d:.1%})' if d else '不适用'


def main():
    cases=b.cases();labels={c['id']:c for c in cases}
    # 用人工可确定的小样例检查评分器的名次、缺失和相关资产分母。
    trial={'relevant_asset_ids':['metric:truth:x']}
    assert b.ranking([{'kind':'metric','id':'truth','source':'x'}],trial)['top1'] is False
    doc={'kind':'metric','id':'truth','source':'x'}
    assert b.ranking([doc],{'relevant_asset_ids':[b.asset_id(doc)]})['top1'] is True
    def score(ids,truth):
        ranks=[i+1 for i,x in enumerate(ids) if x in truth]
        return {'hit5':any(r<=5 for r in ranks),'rr':1/min(ranks) if ranks else 0,
            'top1':bool(ids and ids[0] in truth),'recall5':len(set(ids[:5])&truth)/len(truth) if truth else None}
    assert score(['bad','ok'],{'ok'})=={'hit5':True,'rr':.5,'top1':False,'recall5':1}
    assert score([],{'ok'})['rr']==0
    assert score(['a'],{'a','b'})['recall5']==.5
    case=cases[0]
    actual={k:case[k] for k in ('metric','start','end','groups','filters')}
    assert b.task_matches(actual,case)
    assert not b.task_matches({**actual,'filters':{'country':'United States'}},case)
    assert not b.task_matches({**actual,'start':'2026-08-01'},case)
    dataset=OUT/'golden-draft.jsonl'
    dataset.write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in cases),encoding='utf-8')
    offline=json.loads((OUT/'offline-results.json').read_text(encoding='utf-8'))
    shutil.copy2(OUT/'offline-results.json',ROOT/'data/correctness-offline-pregrading.json')
    for row in offline['cases']:
        c=labels[row['id']]
        for name,r in row['ranking'].items():r.update(score(r['ids'],set(c['relevant_asset_ids'])))
    offline['dataset_sha256']=file_hash(dataset)
    offline['grading_note']='Final grading resolves contract metric labels to stable asset IDs; no Top1 used as a label; scoring fixture checks passed'
    (OUT/'offline-results.json').write_text(json.dumps(offline,ensure_ascii=False,indent=2),encoding='utf-8')
    agent=json.loads((OUT/'agent-results.json').read_text(encoding='utf-8'))
    tools=QueryService();database=tools.release()['database']
    for row in agent['cases']:
        c=labels[row['id']];response=row.get('response',{})
        if c['id']=='g40' and row.get('intent_match'):
            with duckdb.connect(database,read_only=True) as db:
                expected=dict(db.execute("select u.country,count(*) from raw.orders o left join raw.users u on o.user_id=u.id where o.created_at>=timestamptz '2026-09-01 00:00:00+00' and o.created_at<timestamptz '2026-10-01 00:00:00+00' group by u.country").fetchall())
            numeric=[o for o in response.get('observations',[]) if o.get('status')=='OK' and o['tool']=='run_query']
            row['numeric_match']=any(dict(o['result'].get('rows',[]))==expected for o in numeric)
            row['pass']=row.get('status')=='COMPLETE' and row['intent_match'] and row['numeric_match']
        if c['behavior']!='query':
            reason=response.get('error','')
            runtime_failure=any(t in reason.lower() for t in ('deadline','budget exhausted','model_','network','worker terminated','quality evidence expired','stale_'))
            row['pass']=row.get('status') in ('CLARIFY','STOPPED') and not row.get('has_numeric_evidence') and not runtime_failure
            row['refusal_reason_requires_review']=row['pass']
    agent['grading_note']='Grouped orders independently reconciled against raw orders/users; infrastructure stops not counted as correct refusal; refusal wording and final prose need manual review'
    (OUT/'agent-results.json').write_text(json.dumps(agent,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    rankrows=[r for r in offline['cases'] if labels[r['id']]['relevant_asset_ids']]
    lines=['# MyAgent 正确性与召回测试报告','',
        '执行日期：2026-10-12。测试对象为当前本地合同、已发布 TheLook 数据与真实 E5/Cross-Encoder、真实 API Agent。未调参、未修改核心代码。', '',
        '## 结论与可信范围','',
        f"完成 {len(cases)} 条合同标注初版测试、{len(offline['execution'])} 项 raw 独立数值对账和 {len(agent['cases'])} 条真实模型自主 Agent 测试。测试集由开发助手依据合同编写，未经独立人工业务复核；所谓保留集只是暂定分层，不能宣称外部泛化成绩。",'',
        f"语义资产：{offline['asset_count']} 份；快照 `{offline['snapshot_id']}`。模型 `{agent['model']}`，每题只运行一次。",'',
        '## 检索对比','',
        f'下表分母为有明确相关指标资产的 {len(rankrows)} 条题。无相关资产题不计算 Hit/MRR，另外通过行为检查判断是否正确拒绝。相关资产限定为权威指标文档，不把其他可能有帮助的案例/参考文档自动标为相关。MRR 在 Top10 内计算，未召回记 0。','',
        '|方案|Hit@5|MRR@10|Asset Top-1|Top6内首个指标命中|平均 Recall@5|','|---|---|---|---|---|---|']
    aggregates={}
    for name in ['A0','A1','A2','A3','A4']:
        valid=[r for r in rankrows if not (name=='A4' and r.get('rerank_error'))]
        n=len(valid); hit=sum(r['ranking'][name]['hit5'] for r in valid);top=sum(r['ranking'][name]['top1'] for r in valid)
        rr=sum(r['ranking'][name]['rr'] for r in valid)/n if n else 0
        recall=sum(r['ranking'][name]['recall5'] for r in valid)/n if n else 0
        metric_top=sum(next((x for x in r['ranking'][name]['ids'][:6] if x.startswith('metric:')),None) in labels[r['id']]['relevant_asset_ids'] for r in valid)
        aggregates[name]={'n':n,'hit5':hit,'top1':top,'metric_top1_in_pool6':metric_top,'mrr':rr,'recall5':recall}
        lines.append(f'|{name}|{percent(hit,n)}|{rr:.3f}|{percent(top,n)}|{percent(metric_top,n)}|{recall:.1%}|')
    lines+=['','A0=Exact Alias（含跨事实注册别名）；A1=当前 BM25-style + Alias Boost，包含对精确别名额外加20分、参考文档降权，不是纯BM25；A2=E5 Dense；A3=A1+A2+RRF(k=60)，两路各Top10；A4=A3+条件Cross-Encoder。统一使用授权后的同一资产集。A0没有召回不是“拒绝正确”的证明。','',
        '统一服务会将精确匹配指标前置到 candidates；这里测的是资产 hits 排序，没有把前置后的指标候选成绩冒充原始检索成绩。“Top6内首个指标”仅筛去非指标资产，不追加精确匹配，因此也不等于实际 candidates 成绩。候选指标准确率尚未单独完整测量。Dense/RRF若把案例或通用规范排第一，在严格指标文档标签下属于Asset Top1失败，但不能直接推出Agent必然选错指标。','',
        f"重排状态：{dict(Counter(r['rerank']['status'] for r in offline['cases']))}。错误从A4有效排名分母中剔除并必须计为运行失败；本报告不允许降级偷偷当成功。",'',
        f"E5 实际批量编码 60 个 Query，耗时 {offline['batch_embedding_seconds']:.2f} 秒；之后使用同批真实向量评分。该优化只用于离线评测，不修改生产 Dense。评分秒数排除了批量编码，因此不能当线上端到端 P95；初轮不报告看似精确的线上检索 P95。Agent 下表耗时则包含真实模型、检索与执行。",'',
        '## 理解与执行','',
        f"规则理解/行为检查：{percent(sum(r['rules']['pass'] for r in offline['cases']),len(offline['cases']))}。查询题逐字段比较 metric/start/end/group_by/filters；非查询题只检查没有生成可执行Task，这不是模型理解准确率，也没有严格验证澄清文字是否足够。",'',
        f"13个注册指标的结构化查询与 raw 独立对账：{percent(sum(r['pass'] for r in offline['execution']),len(offline['execution']))}。订单状态来自原始 orders，金额来自原始 order_items 的decimal价格，订单日期使用 orders.created_at，跨事实比例独立用商品件数/订单数。全部同一UTC九月窗口；不能推导所有维度组合均已对账。",'',
        '## 真实自主 Agent','',
        f"任务与数值证据联合通过：{percent(sum(r['pass'] for r in agent['cases']),len(agent['cases']))}。合法查询必须COMPLETE、实际执行目标及日期/分组/过滤正确，并与raw数值对账。拒绝/澄清题必须未执行数值查询，超时、模型错误或预算耗尽不算正确拒绝。",'',
        '|案例|用户输入|实际状态|意图匹配|数值对账|通过|耗时秒|','|---|---|---|---|---|---|---|']
    for r in agent['cases']:
        lines.append(f"|{r['id']}|{labels[r['id']]['question']}|{r.get('status',r.get('error'))}|{r.get('intent_match')}|{r.get('numeric_match')}|{r['pass']}|{r['elapsed_seconds']:.1f}|")
    elapsed=sorted(r['elapsed_seconds'] for r in agent['cases'])
    calls=sum(len(r.get('response',{}).get('model_calls',[])) for r in agent['cases'])
    lines+=['',f'真实模型调用共{calls}次；任务耗时中位数{statistics.median(elapsed):.1f}秒，最大{max(elapsed):.1f}秒。只有12个样本，不据此声称稳定线上P95或吞吐。', '',
        '检索结果不支持“增加组件就一定更准”的结论：A4的Hit@5比A1多命中1题，但本轮MRR低于A1；A3没有提高Hit@5，且严格指标文档Top1明显下降。应先复核相关资产标注，并分别测指标候选、案例证据与Structured Resolver，而不是仅凭混合架构名称宣称更优。']
    lines+=['','## 分层统计','',
        '13条标准表达作为开发样例，另外47条暂作保留集。本轮没有使用这些成绩调整参数；近义表达仍可能共享资产中的词语，需要业务人员复核泄漏风险。下面按表达类型统计，不能把规则对长尾的限制与真实模型能力混在一起。','',
        '|类别|题数|规则通过|A1 Hit@5（有相关资产）|A4 Hit@5（有相关资产）|','|---|---|---|---|---|']
    for category in sorted({c['category'] for c in cases}):
        subset=[r for r in offline['cases'] if r['category']==category]
        ranksubset=[r for r in subset if labels[r['id']]['relevant_asset_ids']]
        lines.append(f"|{category}|{len(subset)}|{percent(sum(r['rules']['pass'] for r in subset),len(subset))}|{percent(sum(r['ranking']['A1']['hit5'] for r in ranksubset),len(ranksubset))}|{percent(sum(r['ranking']['A4']['hit5'] for r in ranksubset),len(ranksubset))}|")
    lines+=['','g38有特殊解释：真实Agent分别查询商品件数9238与订单量6319，并在回答中给出9238/6319≈1.462。两个组件和展示的比值均与独立raw计算一致，但未执行注册items_per_order@1的确定性派生查询。因此本轮严格“注册目标及数值回执”评分不通过；这属于派生计算证据链缺口，不能描述为已证明业务答案算错。若未来接受组件路线，应明确添加确定性计算工具和该路线的Golden契约，不能在看见结果后放宽全部评分。','',
        '本轮没有自动证明所有最终自然语言摘要数字、拒绝解释、业务原因或引用完整性正确。回答保留summary_verified:false；即使任务通过，也不等于整段回答都可信。12题单次运行不能估计稳定模型准确率。未测Task模型Workflow、多轮澄清、完整异常反证、不同权限主体及模型重复运行稳定性。','',
        '## 失败案例与诊断','', '|案例|层次|用户输入|实际失败信息|','|---|---|---|---|']
    for r in offline['cases']:
        if not r['rules']['pass']:
            text=r['rules'].get('error',json.dumps(r['rules'].get('actual'),ensure_ascii=False)).replace('|','\\|').replace('\n',' ')
            lines.append(f"|{r['id']}|规则理解|{labels[r['id']]['question']}|{text}|")
    for r in agent['cases']:
        if not r['pass']:
            response=r.get('response',{});reason=response.get('error') or response.get('answer',{}).get('summary') or r.get('error') or '目标/证据未通过'
            lines.append(f"|{r['id']}|自主Agent|{labels[r['id']]['question']}|{str(reason).replace('|','/').replace(chr(10),' ')}|")
    lines+=['','## 下一步与复现','',
        '先逐题业务复核与修正 Golden Label，再优先处理真实失败，不依据保留集反复调参后仍称其保留集。补全多轮、约束理由、诊断前提反证和非管理员权限；再扩展到全部60题真实模型及3次重复运行。若需要检索线上P95，必须增加真实单题冷/热链路计时，不能拿批量向量评分耗时代替。','',
        '现有60秒诊断超时问题没有在本轮放宽；本轮诊断测试集中是应澄清案例，未完成全诊断正确性验收。','',
        '复现：`python scripts/correctness-benchmark.py`；配置本机环境凭据后 `python scripts/correctness-benchmark.py --stage agent`；最后 `python scripts/report-correctness-benchmark.py`。凭据只能从本机DPAPI或环境加载，不能写入测试集。','',
        '文件：[初版标注](golden-draft.jsonl)、[离线逐题证据](offline-results.json)、[真实Agent完整回执](agent-results.json)。','']
    (OUT/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    summary={'ranking':aggregates,'rules_pass':sum(r['rules']['pass'] for r in offline['cases']), 'rules_total':len(offline['cases']),
        'execution_pass':sum(r['pass'] for r in offline['execution']),'execution_total':len(offline['execution']),
        'agent_pass':sum(r['pass'] for r in agent['cases']),'agent_total':len(agent['cases']), 'dataset_sha256':file_hash(dataset)}
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8');print(json.dumps(summary))


if __name__=='__main__':main()
