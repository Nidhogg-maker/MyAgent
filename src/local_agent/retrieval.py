"""本地业务检索与Schema Linking：词法、别名、图上下文组合，不伪称向量检索。"""
import json
import math
import re
from collections import Counter
from .semantic import ROOT, file_hash

def tokens(text):
    """中文用字符二元组，英文按词；轻量方案无需下载embedding模型。"""
    text = text.casefold()
    chinese = ''.join(re.findall(r'[\u4e00-\u9fff]', text))
    return re.findall(r'[a-z0-9_@]+', text) + [chinese[i:i+2] for i in range(len(chinese)-1)]

class KnowledgeRetriever:
    def __init__(self, tools):
        self.tools = tools
        self.business = json.loads((ROOT / 'knowledge/business.json').read_text(encoding='utf-8'))
        self._index_key = None
        self._index = None
        self.index_builds = 0

    def metric_candidates(self, question):
        """优先匹配最长别名，避免'平均订单金额'同时被识别成'订单金额'。"""
        text = question.casefold()
        matches = [(match.start(), match.end(), metric) for metric, aliases in self.business['aliases'].items()
                   if self.tools._metric_allowed(metric) for alias in aliases
                   for match in re.finditer(re.escape(alias.casefold()), text)]
        return sorted({metric for start,end,metric in matches if not any(
            other_start <= start and end <= other_end and other_end-other_start > end-start
            for other_start,other_end,_ in matches)})

    def search(self, question, limit=6):
        """先做授权过滤再评分；返回权威来源定位，不把检索文档当执行指令。"""
        if not 1 <= limit <= 10:
            raise ValueError('Retrieval budget exceeded')
        self.tools.access.role()
        references = list((ROOT/'skills/warehouse-anomaly-attribution/references').glob('*.md'))
        key = (self.tools.registry.version, file_hash(ROOT/'knowledge/business.json'),
               self.tools.principal, self.tools.access.policy_hash,
               tuple((str(p), file_hash(p)) for p in references))
        if key != self._index_key:
            self.business = json.loads((ROOT/'knowledge/business.json').read_text(encoding='utf-8'))
            self._index = self._build_index(references)
            self._index_key = key
            self.index_builds += 1
        docs, corpus, lengths, avg, frequency = self._index
        query_tokens = Counter(tokens(question))
        hits = []
        direct = self.metric_candidates(question)
        for doc, counts, length in zip(docs, corpus, lengths):
            score = 0.0
            for term in query_tokens:
                tf = counts[term]
                idf = math.log(1 + (len(docs)-frequency[term]+0.5)/(frequency[term]+0.5))
                score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / (avg or 1)))
            if doc.get('metric_id') in direct:
                score += 20
            if doc['kind']=='reference': score *= .15
            if score:
                hits.append({**doc, 'score':round(score, 4)})
        return sorted(hits, key=lambda doc: (-doc['score'], doc['id']))[:limit]

    def _build_index(self, references):
        """只在资产或权限绑定变化时重建词法索引；始终先过滤再索引。"""
        docs = []
        for metric_id, metric in self.tools.registry.contract['metrics'].items():
            if not self.tools._metric_allowed(metric_id):
                continue
            described = self.tools.describe(metric_id)
            docs.append({'id':metric_id, 'kind':'metric', 'metric_id':metric_id,
                'text':' '.join([metric['label'],metric['definition'],described['fact']['table'],described['fact']['grain'],metric.get('column',''),*described['fact']['dimensions'],*self.business['aliases'].get(metric_id, [])]),
                'source':'contracts/commerce.json#metrics/' + metric_id, 'allowed_dimensions':described['fact']['dimensions']})
        for case in self.business['cases']:
            if case.get('metric_id') and not self.tools._metric_allowed(case['metric_id']):
                continue
            docs.append({'id':case['id'],'kind':'case','text':case['question']+' '+case['note'], 'source':'knowledge/business.json#cases/' + case['id']})
        for identifier, metric in self.tools.registry.contract.get('multi_fact', {}).get('ratios', {}).items():
            if all(self.tools._metric_allowed(metric[k]) for k in ('numerator', 'denominator')):
                docs.append({'id':identifier,'kind':'metric','metric_id':identifier,
                    'text':' '.join([identifier,metric['definition'],metric['unit'],*metric.get('aliases',[])]),
                    'source':'contracts/commerce.json#multi_fact/ratios/'+identifier})
        # 领域参考属于知识路径，公式与约束仍从结构化合同读取。
        for path in references:
            docs.append({'id':'reference-'+path.stem,'kind':'reference','text':path.read_text(encoding='utf-8'),
                         'source':str(path.relative_to(ROOT)),'source_sha256':file_hash(path)})
        corpus = [Counter(tokens(doc['text'])) for doc in docs]
        lengths = [sum(doc.values()) for doc in corpus]
        avg = sum(lengths) / max(len(lengths), 1)
        frequency = Counter(token for doc in corpus for token in doc)
        return docs, corpus, lengths, avg, frequency

    def paths(self,question,hits):
        """两种路径的数据类型独立，权威结构不参与RRF文本投票。"""
        exact=self.metric_candidates(question)
        return {'knowledge_hits':[h for h in hits if h['kind']!='metric'],
            'semantic_candidates':[h for h in hits if h['kind']=='metric'],
            'routing':'exact-id-then-structured' if exact else 'lexical-candidates-then-structured',
            'knowledge_version':file_hash(ROOT/'knowledge/business.json'),
            'semantic_version':self.tools.registry.version,'exact_metric_ids':exact}

    def link(self, metric_id):
        """从指标走到物理事实与列，字段血缘由目录读取，不让LLM猜表名。"""
        metric = self.tools.describe(metric_id)
        context = self.tools.context(metric_id)
        column = metric.get('column')
        lineage = self.tools.lineage(metric['fact']['table'], column) if column else context['lineage']
        return {'metric_id':metric_id, 'dataset':metric['fact']['table'], 'grain':metric['fact']['grain'],
                'column':column, 'schema':context['metadata']['schema'], 'lineage':lineage,
                'source':'contracts/commerce.json', 'owner':context['metadata']['ownership']}
