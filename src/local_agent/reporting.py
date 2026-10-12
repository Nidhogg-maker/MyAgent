"""用Skill输出资产组织真实证据；模板中没有模型生成的虚构结论。"""
import json
from .skill_resources import report_template

def compact(value):
    return json.dumps(value,ensure_ascii=False,default=str)

def render_report(kind,evidence,task=None):
    ledger=evidence.get('evidence',[]) if kind=='diagnose' else [evidence]
    first=ledger[0] if ledger else {}
    query=(task or {}).get('query',{})
    metric=first.get('metric_id',query.get('metric_id','未完成指标解析'))
    definition=first.get('definition','口径见权威合同')
    windows=[]
    for name,q in [('当前',query),('对照',(task or {}).get('baseline'))]:
        if q: windows.append(f"{name}：UTC [{q['start']}, {q['end']})；筛选 {compact(q.get('filters',{}))}")
    if kind=='query':
        rows=evidence.get('rows',[])
        change='列：'+compact(evidence.get('columns',[]))+'\n\n结果：'+compact(rows[:20])
        if len(rows)>20: change+=f'\n\n仅展示前20组，完整{len(rows)}组见会话证据。'
    else:
        change=compact(evidence.get('change',{}))
        if first.get('unit')=='ratio' and evidence.get('change'):
            change+=f"\n\n占比差：{evidence['change']['delta']*100:.4f} 个百分点。"
    decompositions=[]
    for d in evidence.get('decompositions',[]):
        displayed={k:v for k,v in d.items() if k!='groups'}
        decompositions.append(compact(displayed))
        if 'groups' in d:
            decompositions.append('贡献最大的前10组：'+compact(d['groups'][:10]))
    quality=evidence.get('quality_check',{'quality':evidence.get('quality',{}),'temporal':evidence.get('temporal',{})})
    pieces={'metric':f'{metric}\n\n{definition}', 'windows':'\n\n'.join(windows) or '见查询证据',
        'change':change,'decompositions':'\n\n'.join(decompositions) or '本次无分解结果',
        'quality':compact(quality),'hypotheses':compact(evidence.get('hypotheses',[])),
        'conclusion':evidence.get('conclusion','已执行指定口径，只报告观察结果；不确认因果原因'),
        'unresolved':compact(evidence.get('unresolved',evidence.get('warnings',[])))+('\n\n停止原因：'+evidence['stopped_reason'] if evidence.get('stopped_reason') else ''),
        'evidence':'\n'.join(f"- plan_id={e.get('plan_id')}；release={e.get('release_id')}" for e in ledger) or '没有完成查询'}
    report=report_template()
    if kind=='query': report=report.replace('# 指标异动证据报告','# 指标查询证据报告',1)
    for key,value in pieces.items(): report=report.replace('{{'+key+'}}',value)
    return report
