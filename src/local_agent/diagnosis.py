"""有界假设验证与反证；数值变化、代数贡献、因果证据分别报告。"""
import time
from .semantic import Query, ROOT
from .tasks import Task

class DiagnosisEngine:
    def __init__(self, tools, max_queries=8, deadline_seconds=60, executor=None):
        self.tools, self.max_queries, self.deadline = tools, max_queries, deadline_seconds
        self.executor = executor

    def run(self, task: Task):
        """最多8查询、2维度；失败保留已有证据，不输出未经验证的根因。"""
        if task.kind != 'diagnose':
            raise ValueError('Not a diagnosis task')
        from .skill_resources import resources
        skill = resources('anomaly-analysis',references=True)['instructions']
        start = time.monotonic()
        ledger, hypotheses, decompositions = [], [], []
        result = {'status':'INSUFFICIENT_EVIDENCE','causal_claim':False,'skill':'commerce-diagnosis',
                  'skill_loaded':bool(skill),'evidence':ledger,'hypotheses':hypotheses,'decompositions':decompositions}
        snapshot = self.tools.release()
        def query(source, metric=None, dimension=None):
            if len(ledger) >= self.max_queries or time.monotonic()-start >= self.deadline:
                raise ValueError('Diagnosis budget exhausted')
            request = Query.model_validate({**source.model_dump(mode='json'), 'metric_id':metric or source.metric_id,
                                           'group_by':[dimension] if dimension else [], 'limit':1000})
            if self.executor:
                envelope = self.executor.run('drilldown' if dimension else 'metric-query',request.model_dump(mode='json'))['result']
            else:
                plan = self.tools.plan(request)
                envelope = self.tools.execute(plan['plan_id'],plan['approval_hash'],timeout_seconds=min(30,max(1,self.deadline-(time.monotonic()-start))))
            ledger.append({'query':request.model_dump(mode='json'), **envelope})
            if envelope['release_id'] != snapshot['release_id']:
                raise ValueError('Snapshot changed during diagnosis')
            if envelope['result_may_be_truncated']:
                raise ValueError('Truncated diagnostic evidence')
            return envelope
        def scalar(envelope):
            if len(envelope['rows']) != 1 or envelope['rows'][0][-1] is None:
                raise ValueError('Missing/suppressed scalar or zero denominator')
            return float(envelope['rows'][0][-1])
        try:
            metric = self.tools.registry.describe(task.query.metric_id) if hasattr(self.tools,'registry') else {}
            family = metric.get('diagnosis_family')
            is_ratio = task.query.metric_id == 'average_order_value@1' or family == 'ratio'
            if task.query.metric_id not in ('order_count@1','booked_amount@1','average_order_value@1') and family not in ('ratio','additive'):
                raise ValueError('No validated hypothesis family for this metric')
            if self.executor:
                comparison=self.executor.run('comparison',{'baseline':task.baseline.model_dump(mode='json'),'current':task.query.model_dump(mode='json')})['result']
                for source,envelope in zip((task.baseline,task.query),comparison['evidence']):
                    ledger.append({'query':source.model_dump(mode='json'),**envelope})
                    if envelope['release_id'] != snapshot['release_id']: raise ValueError('Snapshot changed during comparison')
                old,new = [scalar(e) for e in comparison['evidence']]
            else:
                old, new = scalar(query(task.baseline)), scalar(query(task.query))
            delta = new-old
            result['change'] = {'baseline':old,'current':new,'delta':delta,'relative_change':delta/old if old else None}
            premise = (task.expected_direction == 'decrease' and delta < 0) or (task.expected_direction == 'increase' and delta > 0) or task.expected_direction == 'unknown'
            hypotheses.append({'id':'user-premise','status':'SUPPORTED_OBSERVATION' if premise else 'REFUTED', 'evidence_indexes':[0,1]})
            if not premise:
                result.update(status='PREMISE_REFUTED', conclusion='用户声称的变化方向未被这两个窗口的数据支持；不继续归因')
                return result
            verified = snapshot.get('temporal',{}).get('verified',False)
            hypotheses.append({'id':'data-completeness','status':'SUPPORTED_ATTESTATION' if verified else 'UNVERIFIED',
                               'evidence':snapshot.get('temporal',{}), 'note':'缺完整性水位不能排除迟到/数据未到齐'})
            if task.query.metric_id == 'booked_amount@1':
                counts = [scalar(query(window,'order_count@1')) for window in (task.baseline,task.query)]
                if not all(counts):
                    raise ValueError('Cannot factor amount with zero order count')
                prices = [old/counts[0],new/counts[1]]
                volume = (counts[1]-counts[0]) * (prices[0]+prices[1])/2
                basket = (prices[1]-prices[0]) * (counts[0]+counts[1])/2
                decompositions.append({'kind':'symmetric-algebraic','volume_contribution':volume,'basket_value_contribution':basket,
                                       'residual':delta-volume-basket,'causal':False})
                for name, value in [('order-volume',counts[1]-counts[0]),('basket-value',prices[1]-prices[0])]:
                    hypotheses.append({'id':name,'status':'OBSERVED_CHANGE' if value else 'REFUTED_NO_CHANGE','delta':value,'evidence_indexes':list(range(4))})
            elif is_ratio:
                amounts = [scalar(query(window,metric.get('numerator','booked_amount@1'))) for window in (task.baseline,task.query)]
                counts = [scalar(query(window,metric.get('denominator','order_count@1'))) for window in (task.baseline,task.query)]
                if not all(counts):
                    raise ValueError('Zero diagnostic denominator')
                if any(abs(amount/count-value) > 1e-7 for amount,count,value in zip(amounts,counts,(old,new))):
                    raise ValueError('Ratio components do not reconcile')
                numerator = (amounts[1]-amounts[0])*(1/counts[0]+1/counts[1])/2
                denominator = (amounts[0]+amounts[1])*(1/counts[1]-1/counts[0])/2
                decompositions.append({'kind':'ratio-algebraic','numerator_contribution':numerator,'denominator_contribution':denominator,
                                       'residual':delta-numerator-denominator,'causal':False})
                hypotheses.append({'id':'ratio-components','status':'VALIDATED_IDENTITY','evidence_indexes':list(range(6))})
            if not is_ratio:
                for dimension in task.diagnosis_dimensions:
                    grouped = [query(window,dimension=dimension) for window in (task.baseline,task.query)]
                    maps = [{row[0]:float(row[1]) for row in envelope['rows'] if row[1] is not None} for envelope in grouped]
                    if any(abs(sum(mapping.values())-total) > max(1e-6,abs(total)*1e-9) for mapping,total in zip(maps,(old,new))):
                        raise ValueError('Grouped evidence does not reconcile; possible suppression/omissions')
                    contributions = [{'group':key,'delta':maps[1].get(key,0)-maps[0].get(key,0)} for key in maps[0].keys() | maps[1].keys()]
                    decompositions.append({'kind':'additive-group-delta','dimension':dimension,'groups':sorted(contributions,key=lambda item:-abs(item['delta'])),'causal':False})
                    hypotheses.append({'id':'mix-'+dimension,'status':'OBSERVED_DISTRIBUTION_CHANGE' if any(item['delta'] for item in contributions) else 'REFUTED_NO_CHANGE',
                                       'evidence_indexes':[len(ledger)-2,len(ledger)-1],'note':'分组差值不是业务事件导致变化的证明'})
            if is_ratio and self.executor:
                # 不能相加各组比例；用总分母加权后的组分子贡献保证汇总恒等式。
                for dimension in task.diagnosis_dimensions:
                    if dimension not in metric['fact']['dimensions'] and dimension != 'day':
                        raise ValueError('Illegal ratio diagnosis dimension')
                    grouped_n=[query(w,metric.get('numerator','booked_amount@1'),dimension) for w in (task.baseline,task.query)]
                    grouped_d=[query(w,metric.get('denominator','order_count@1'),dimension) for w in (task.baseline,task.query)]
                    nm=[{r[0]:float(r[1]) for r in e['rows'] if r[1] is not None} for e in grouped_n]
                    dm=[{r[0]:float(r[1]) for r in e['rows'] if r[1] is not None} for e in grouped_d]
                    for maps,totals in ((nm,amounts),(dm,counts)):
                        if any(abs(sum(m.values())-t)>max(1e-6,abs(t)*1e-9) for m,t in zip(maps,totals)):
                            raise ValueError('Ratio groups do not reconcile; suppression or missing groups')
                    contributions=[{'group':key,'baseline_numerator':nm[0].get(key,0),
                        'current_numerator':nm[1].get(key,0),'baseline_denominator':dm[0].get(key,0),
                        'current_denominator':dm[1].get(key,0),
                        'contribution':nm[1].get(key,0)/counts[1]-nm[0].get(key,0)/counts[0]}
                        for key in nm[0].keys()|nm[1].keys()|dm[0].keys()|dm[1].keys()]
                    residual=delta-sum(g['contribution'] for g in contributions)
                    if abs(residual)>1e-7: raise ValueError('Ratio contribution residual exceeded')
                    decompositions.append({'kind':'weighted-ratio-group-contribution','dimension':dimension,
                        'groups':sorted(contributions,key=lambda g:-abs(g['contribution'])),
                        'residual':residual,'causal':False,'evidence_indexes':list(range(len(ledger)-4,len(ledger)))})
            if self.executor:
                result['quality_check']=self.executor.run('quality-check',{'metric_id':task.query.metric_id,
                    'current':task.query.model_dump(mode='json'),'baseline':task.baseline.model_dump(mode='json')})['result']
            result.update(status='OBSERVATIONS_ONLY' if verified else 'INSUFFICIENT_EVIDENCE',
                          conclusion='已验证数值与代数贡献；缺少独立业务事件/完整性反证，不能确认因果根因',
                          unresolved=['no_independent_business_event_evidence'] + (['snapshot_status_cohort_maturity_unverified'] if metric.get('time_semantics') else []) + (['ratio_dimension_drilldown_not_implemented'] if is_ratio and task.diagnosis_dimensions and not self.executor else []) + ([] if verified else ['completeness_unverified']),
                          queries_used=len(ledger))
        except Exception as error:
            result.update(status='INSUFFICIENT_EVIDENCE', stopped_reason=str(error), queries_used=len(ledger))
        return result
