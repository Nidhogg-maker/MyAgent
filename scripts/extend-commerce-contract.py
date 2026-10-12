"""把真实订单状态转为可核验指标，不将状态冒充支付、转化或历史结算事件。"""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root/'contracts/commerce.json'
contract = json.loads(path.read_text(encoding='utf-8'))
contract['version'] = 'commerce-v2'
aliases = {}
for status, code, name in [('Complete','complete','完成'),('Cancelled','cancelled','取消'),('Returned','returned','退货')]:
    count_id = f'{code}_order_count@1'
    rate_id = f'{code}_order_rate@1'
    contract['metrics'][count_id] = {
        'label':f'{name}订单数','fact':'orders','kind':'conditional_count',
        'condition_column':'order_status','condition_value':status,'unit':'orders',
        'definition':f'UTC下单日窗口内，本次快照订单状态为{status}的订单数；非历史当日状态或支付结果',
        'time_semantics':'created-date cohort / current snapshot status',
        'diagnosis_family':'additive','verification_status':'local-study-defined'}
    contract['metrics'][rate_id] = {
        'label':f'订单{name}占比','fact':'orders','kind':'ratio','numerator':count_id,
        'denominator':'order_count@1','unit':'ratio',
        'allowed_dimensions':['country','gender','age_band','traffic_source'],
        'definition':f'同UTC下单日窗口及用户筛选内，本次快照{status}订单数/全部状态订单数；零分母null；不是支付成功率、历史{name}率或成熟 cohort 估计',
        'time_semantics':'created-date cohort / current snapshot status',
        'diagnosis_family':'ratio','verification_status':'local-study-defined'}
    aliases[count_id] = [f'{name}订单数',f'{name}订单量']
    aliases[rate_id] = [f'订单{name}占比',f'{name}订单占比',f'订单{name}率']
path.write_text(json.dumps(contract,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
path = root/'knowledge/business.json'
business = json.loads(path.read_text(encoding='utf-8'))
business['aliases'].update(aliases)
business['filter_value_aliases']['gender'] = {'男性':'M','男':'M','male':'M','女性':'F','女':'F','female':'F'}
business['cases'] = [case for case in business['cases'] if case['id'] != 'case-snapshot-status']
business['cases'].append({'id':'case-snapshot-status','metric_id':'complete_order_rate@1',
    'question':'男性订单完成占比为什么变化','note':'先明确等时长基准。新近下单 cohort 尚未成熟，当前快照状态不能证明历史完成或支付成功；不得做因果归因。'})
path.write_text(json.dumps(business,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
