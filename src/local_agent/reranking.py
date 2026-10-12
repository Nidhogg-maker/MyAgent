"""有界、按需重排；模型分数只调整名次，不授权、不定义公式。"""
import json
import math
import os
import subprocess
from pathlib import Path
from collections import OrderedDict
from .semantic import ROOT, file_hash
from .dense_retrieval import digest, asset_id

_SCORES = OrderedDict()


def reranker_binding():
    mode = os.environ.get('OWN_AGENT_RERANK_MODE', 'off')
    if mode not in ('off','auto','required'):
        raise ValueError('Unknown rerank mode')
    path = Path(os.environ.get('OWN_AGENT_RERANKER_IDENTITY', str(ROOT/'data/reranker-identity.json')))
    return {'mode':mode,'identity_path':str(path.resolve()),
            'identity_hash':file_hash(path) if mode != 'off' and path.exists() else None,
            'implementation':digest({'provider':file_hash(Path(__file__)),
                'worker':file_hash(ROOT/'scripts/reranker-worker.py')}),
            'routing':'exact-and-ambiguity-skip; competition-or-longtail-v1'}


class LocalReranker:
    def score(self, question, hits, identity):
        # 检查实际模型摘要再读取分数缓存，手工替换权重不会沿用旧分数。
        root = Path(identity['local_path']).resolve()
        for name, expected in identity['files'].items():
            path = (root/name).resolve()
            if not path.is_relative_to(root) or file_hash(path) != expected:
                raise ValueError('Reranker model checksum mismatch')
        pairs = [[question, h.get('embedding_text',h['text'])] for h in hits]
        key = digest({'identity':identity, 'pairs':pairs,
            'worker':file_hash(ROOT/'scripts/reranker-worker.py')})
        if key in _SCORES:
            _SCORES.move_to_end(key)
            return list(_SCORES[key]), True
        executable = os.environ.get('OWN_AGENT_EMBEDDING_PYTHON',str(ROOT/'.retrieval-venv/Scripts/python.exe'))
        result = subprocess.run([executable,str(ROOT/'scripts/reranker-worker.py')],
            input=json.dumps({'identity':identity,'pairs':pairs}),capture_output=True,text=True,
            encoding='utf-8',timeout=45)
        if result.returncode:
            raise RuntimeError('reranker_worker_failed')
        scores = json.loads(result.stdout)['scores']
        if len(scores) != len(hits) or not all(isinstance(s,(int,float)) and math.isfinite(s) for s in scores):
            raise ValueError('Invalid rerank score shape')
        _SCORES[key] = tuple(scores)
        while len(_SCORES) > 32:
            _SCORES.popitem(last=False)
        return scores, False


def rerank(question, hits, exact, ambiguous, provider=None):
    binding = reranker_binding()
    metric_ids = {h['metric_id'] for h in hits if h.get('kind') == 'metric'}
    reason = 'disabled' if binding['mode'] == 'off' else 'ambiguous' if ambiguous else 'exact' if exact else \
             'insufficient_candidates' if len(hits)<2 else None
    if reason:
        return hits, {'status':'skipped','reason':reason,'binding':binding}
    # 没有唯一精确指标时，候选竞争与长尾进入相同有界打分接口。
    route = 'candidate_competition' if len(metric_ids)>1 else 'long_tail'
    try:
        identity = json.loads(Path(binding['identity_path']).read_text(encoding='utf-8'))
        scores, cache_hit = (provider or LocalReranker()).score(question,hits,identity)
        if len(scores)!=len(hits) or not all(math.isfinite(s) for s in scores):
            raise ValueError('Invalid rerank scores')
        rows = [{**h,'rerank_score':s,'retrieval_rank':i+1} for i,(h,s) in enumerate(zip(hits,scores))]
        rows.sort(key=lambda h:(-h['rerank_score'],h['retrieval_rank'],asset_id(h)))
        return rows, {'status':'ready','route':route,'count':len(rows),'cache_hit':cache_hit,
            'model':identity['model'],'revision':identity['revision'],'score_type':'raw_logit_not_probability',
            'binding':binding}
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.TimeoutExpired) as error:
        if binding['mode'] == 'required':
            raise ValueError('Reranker required but unavailable') from error
        return hits, {'status':'fallback','reason':type(error).__name__,'binding':binding}
