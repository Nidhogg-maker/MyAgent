"""离线语义资产快照与在线 Dense/RRF。索引不是指标口径权威。"""
import json
import math
import os
from pathlib import Path
import subprocess
import uuid
from typing import Protocol
from .semantic import ROOT, file_hash
from .semantic_context import asset_version


def digest(value):
    import hashlib
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def asset_id(doc):
    # kind 防止案例 ID 与指标 ID 相同；source 防止不同文件重名。
    return doc['kind'] + ':' + doc['id'] + ':' + digest(doc['source'])[:16]


class EmbeddingProvider(Protocol):
    identity: dict
    def encode(self, texts: list[str], kind: str) -> list[list[float]]: ...


class LocalEmbeddingProvider:
    """独立 CPU 子进程；在线只读本地模型，超时终止，不调用付费 API。"""
    def __init__(self, identity):
        self.identity = identity

    def encode(self, texts, kind):
        executable = Path(os.environ.get('OWN_AGENT_EMBEDDING_PYTHON',
                          str(ROOT/'.retrieval-venv/Scripts/python.exe')))
        payload = {'identity': self.identity, 'texts': texts, 'kind': kind}
        result = subprocess.run([str(executable), str(ROOT/'scripts/embedding-worker.py')],
            input=json.dumps(payload), capture_output=True, text=True, encoding='utf-8',
            timeout=60 if kind == 'query' else 300)
        if result.returncode:
            # 不把模型下载/进程完整 stderr 放入用户上下文。
            raise RuntimeError('embedding_worker_failed')
        return json.loads(result.stdout)['vectors']


def normalized(vectors, dimension=None):
    if not vectors:
        raise ValueError('empty_vectors')
    dimension = dimension or len(vectors[0])
    for vector in vectors:
        if len(vector) != dimension or not dimension or not all(math.isfinite(x) for x in vector):
            raise ValueError('invalid_vector_shape_or_value')
        norm = math.sqrt(sum(x*x for x in vector))
        if abs(norm-1) > .001:
            raise ValueError('vectors_must_be_normalized')
    return dimension


def publish_index(tools, lexical, provider, directory):
    """先构建、校验完整不可变快照，最后原子替换 active；失败保留旧索引。"""
    if not tools.access.role()['publish']:
        raise PermissionError('Index publication requires administrator')
    before = asset_version(tools)
    lexical.search('资产', 1)  # 使用同一 Registry 派生资产，不另维护公式。
    documents = [{**d, 'asset_id': asset_id(d)} for d in lexical._index[0]]
    vectors = provider.encode([d.get('embedding_text', d['text']) for d in documents], 'passage')
    if len(vectors) != len(documents):
        raise ValueError('vector_count_mismatch')
    dimension = normalized(vectors)
    if not tools.access.role()['publish']:
        raise PermissionError('Index publication authority changed')
    if before != asset_version(tools):
        raise ValueError('Assets changed during index build')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    folder = directory / ('snapshot-' + uuid.uuid4().hex)
    folder.mkdir()
    for name, value in [('documents.json', documents), ('vectors.json', vectors)]:
        (folder/name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    manifest = {'format': 2, 'projection': 'canonical-metric-summary-v1', 'asset_version': before, 'registry_version': tools.registry.version,
        'embedding': provider.identity, 'dimension': dimension, 'count': len(documents),
        'subject': tools.principal, 'policy_hash': tools.access.policy_hash,
        'files': {name: file_hash(folder/name) for name in ('documents.json','vectors.json')}}
    manifest['snapshot_id'] = digest(manifest)
    (folder/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    pointer = {'folder': folder.name, 'manifest_sha256': file_hash(folder/'manifest.json'),
               'snapshot_id': manifest['snapshot_id']}
    temporary = directory / ('active-' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(pointer), encoding='utf-8')
    os.replace(temporary, directory/'active.json')
    return manifest


def configuration():
    mode = os.environ.get('OWN_AGENT_RETRIEVAL_MODE', 'lexical')
    if mode not in ('lexical', 'hybrid', 'hybrid-required'):
        raise ValueError('Unknown retrieval mode')
    directory = Path(os.environ.get('OWN_AGENT_DENSE_INDEX', str(ROOT/'data/retrieval-index')))
    return mode, directory


def retrieval_binding():
    mode, directory = configuration()
    pointer = directory/'active.json'
    return {'mode': mode, 'directory': str(directory.resolve()),
            'active_hash': file_hash(pointer) if mode != 'lexical' and pointer.exists() else None,
            'algorithm': 'rrf-k60-v1'}


class DenseIndex:
    def __init__(self, directory, provider_factory=LocalEmbeddingProvider):
        self.directory = Path(directory)
        self.provider_factory = provider_factory

    def search(self, question, tools, authorized_docs, limit=10):
        pointer = json.loads((self.directory/'active.json').read_text(encoding='utf-8'))
        folder = (self.directory/pointer['folder']).resolve()
        if folder.parent != self.directory.resolve() or not folder.name.startswith('snapshot-'):
            raise ValueError('invalid_snapshot_path')
        if file_hash(folder/'manifest.json') != pointer['manifest_sha256']:
            raise ValueError('manifest_checksum_mismatch')
        manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        snapshot_id = manifest.pop('snapshot_id')
        if digest(manifest) != snapshot_id or snapshot_id != pointer['snapshot_id'] or manifest['format'] != 2:
            raise ValueError('invalid_manifest')
        if manifest['asset_version'] != asset_version(tools):
            raise ValueError('stale_dense_index')
        if manifest['registry_version'] != tools.registry.version or manifest['policy_hash'] != tools.access.policy_hash:
            raise ValueError('incompatible_index_scope')
        for name in ('documents.json','vectors.json'):
            if file_hash(folder/name) != manifest['files'][name]:
                raise ValueError('index_checksum_mismatch')
        documents = json.loads((folder/'documents.json').read_text(encoding='utf-8'))
        vectors = json.loads((folder/'vectors.json').read_text(encoding='utf-8'))
        if len(documents) != len(vectors) or len(documents) != manifest['count']:
            raise ValueError('index_count_mismatch')
        normalized(vectors, manifest['dimension'])
        # 在线授权资产重新从 Registry 构建；先取可见集合再 top-k。
        allowed = {asset_id(d): d for d in authorized_docs}
        eligible = [(allowed[d['asset_id']], vector) for d, vector in zip(documents, vectors)
                    if d['asset_id'] in allowed and d.get('embedding_text', d['text']) ==
                        allowed[d['asset_id']].get('embedding_text', allowed[d['asset_id']]['text'])]
        if not eligible:
            return [], {'status': 'ready', 'snapshot_id': snapshot_id, 'visible_assets': 0}
        query = self.provider_factory(manifest['embedding']).encode([question], 'query')
        if len(query) != 1:
            raise ValueError('query_vector_count_mismatch')
        normalized(query, manifest['dimension'])
        hits = [{**doc, 'asset_id': asset_id(doc), 'score': sum(x*y for x,y in zip(query[0], vector))}
                for doc, vector in eligible]
        hits.sort(key=lambda d: (-d['score'], d['asset_id']))
        return hits[:limit], {'status': 'ready', 'snapshot_id': snapshot_id,
            'embedding': manifest['embedding'], 'visible_assets': len(eligible),
            'dimension': manifest['dimension']}


def rrf(lexical, dense, limit=6, k=60):
    """只融合名次，不相加 BM25 与 cosine；同一资产每路只投一票。"""
    merged = {}
    for name, branch in [('lexical', lexical), ('dense', dense)]:
        seen = set()
        rank = 0
        for doc in branch:
            key = asset_id(doc)
            if key in seen:
                continue
            seen.add(key)
            rank += 1
            row = merged.setdefault(key, {**doc, 'asset_id': key, 'score': 0., 'ranks': {}, 'branch_scores': {}})
            row['score'] += 1/(k+rank)
            row['ranks'][name] = rank
            row['branch_scores'][name] = doc['score']
    return sorted(merged.values(), key=lambda d: (-d['score'], d['asset_id']))[:limit]
