"""离线语义资产快照与在线 Dense/RRF。索引不是指标口径权威。"""
import json
import math
import os
from pathlib import Path
import subprocess
import uuid
from collections import OrderedDict
from typing import Protocol
from .semantic import ROOT, file_hash
from .semantic_context import asset_version

_QUERY_VECTORS = OrderedDict()


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

    def validate_identity(self):
        root = Path(self.identity['local_path']).resolve()
        for name, expected in self.identity['files'].items():
            path = (root/name).resolve()
            if not path.is_relative_to(root) or file_hash(path)!=expected:
                raise ValueError('Embedding model checksum mismatch')

    def encode(self, texts, kind):
        cache_key = digest({'identity':self.identity,'texts':texts,'kind':kind,
            'worker':file_hash(ROOT/'scripts/embedding-worker.py')})
        if kind == 'query' and cache_key in _QUERY_VECTORS:
            # 缓存不依赖事实数据；命中前确认实际模型仍与身份一致。
            root = Path(self.identity['local_path']).resolve()
            for name, expected in self.identity['files'].items():
                path = (root/name).resolve()
                if not path.is_relative_to(root) or file_hash(path) != expected:
                    raise ValueError('Embedding model checksum mismatch')
            _QUERY_VECTORS.move_to_end(cache_key)
            return [list(v) for v in _QUERY_VECTORS[cache_key]]
        executable = Path(os.environ.get('OWN_AGENT_EMBEDDING_PYTHON',
                          str(ROOT/'.retrieval-venv/Scripts/python.exe')))
        payload = {'identity': self.identity, 'texts': texts, 'kind': kind}
        result = subprocess.run([str(executable), str(ROOT/'scripts/embedding-worker.py')],
            input=json.dumps(payload), capture_output=True, text=True, encoding='utf-8',
            timeout=60 if kind == 'query' else 300)
        if result.returncode:
            # 不把模型下载/进程完整 stderr 放入用户上下文。
            raise RuntimeError('embedding_worker_failed')
        vectors = json.loads(result.stdout)['vectors']
        if kind == 'query':
            normalized(vectors)
            if len(vectors) != len(texts):
                raise ValueError('Query vector count mismatch')
            _QUERY_VECTORS[cache_key] = tuple(tuple(v) for v in vectors)
            while len(_QUERY_VECTORS) > 32:
                _QUERY_VECTORS.popitem(last=False)
        return vectors


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


def read_snapshot(directory):
    """查询和增量构建共用快照完整性检查；不在此接受旧快照作为当前语义。"""
    directory = Path(directory)
    pointer = json.loads((directory/'active.json').read_text(encoding='utf-8'))
    folder = (directory/pointer['folder']).resolve()
    if folder.parent != directory.resolve() or not folder.name.startswith('snapshot-'):
        raise ValueError('invalid_snapshot_path')
    if file_hash(folder/'manifest.json') != pointer['manifest_sha256']:
        raise ValueError('manifest_checksum_mismatch')
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    identity = manifest['snapshot_id']
    payload = {k:v for k,v in manifest.items() if k!='snapshot_id'}
    if digest(payload)!=identity or identity!=pointer['snapshot_id'] or manifest['format'] not in (2,3):
        raise ValueError('invalid_manifest')
    names = ['documents.json','vectors.json'] + (['structured.sqlite','tombstones.json'] if manifest['format']==3 else [])
    for name in names:
        if file_hash(folder/name)!=manifest['files'][name]:
            raise ValueError('index_checksum_mismatch')
    docs = json.loads((folder/'documents.json').read_text(encoding='utf-8'))
    vectors = json.loads((folder/'vectors.json').read_text(encoding='utf-8'))
    if len(docs)!=len(vectors) or len(docs)!=manifest['count'] or len({d['asset_id'] for d in docs})!=len(docs):
        raise ValueError('index_count_or_id_mismatch')
    normalized(vectors,manifest['dimension'])
    return folder, manifest, docs, vectors


def publish_index(tools, lexical, provider, directory, incremental=True):
    """先构建、校验完整不可变快照，最后原子替换 active；失败保留旧索引。"""
    if not tools.access.role()['publish']:
        raise PermissionError('Index publication requires administrator')
    before = asset_version(tools)
    starting_pointer = file_hash(Path(directory)/'active.json') if (Path(directory)/'active.json').exists() else None
    lexical.search('资产', 1)  # 使用同一 Registry 派生资产，不另维护公式。
    documents = [{**d, 'asset_id': asset_id(d)} for d in lexical._index[0]]
    previous = read_snapshot(directory) if (Path(directory)/'active.json').exists() else None
    old = {d['asset_id']:(d,v) for d,v in zip(previous[2],previous[3])} if previous else {}
    reusable = incremental and previous is not None and previous[1]['embedding']==provider.identity
    if hasattr(provider,'validate_identity'):
        provider.validate_identity()
    changed = [d for d in documents if not reusable or d['asset_id'] not in old or
               d.get('embedding_text',d['text'])!=old[d['asset_id']][0].get('embedding_text',old[d['asset_id']][0]['text'])]
    fresh = provider.encode([d.get('embedding_text',d['text']) for d in changed],'passage') if changed else []
    if len(fresh)!=len(changed):
        raise ValueError('vector_count_mismatch')
    new_vectors = {d['asset_id']:v for d,v in zip(changed,fresh)}
    vectors = [new_vectors[d['asset_id']] if d['asset_id'] in new_vectors else old[d['asset_id']][1] for d in documents]
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
    current = {d['asset_id'] for d in documents}
    tombstones = json.loads((previous[0]/'tombstones.json').read_text(encoding='utf-8')) if previous and previous[1]['format']==3 else []
    tombstones = {d['asset_id']:d for d in tombstones if d['asset_id'] not in current}
    for identifier,(doc,_) in old.items():
        if identifier not in current:
            tombstones[identifier] = {k:doc[k] for k in ('asset_id','id','kind','metric_id','partition') if k in doc}
            tombstones[identifier]['deleted_in_asset_version'] = before
    (folder/'tombstones.json').write_text(json.dumps(list(tombstones.values()),sort_keys=True),encoding='utf-8')
    from .structure import write_graph
    graph_delta = write_graph(folder/'structured.sqlite',lexical.projection_graph,
        previous[0]/'structured.sqlite' if previous and previous[1]['format']==3 else None)
    if before!=asset_version(tools) or not tools.access.role()['publish']:
        raise ValueError('Assets/authority changed before index publication')
    if previous and read_snapshot(directory)[1]['snapshot_id']!=previous[1]['snapshot_id']:
        raise ValueError('Concurrent index publication; rebuild from current active')
    manifest = {'format': 3, 'projection': 'canonical-metric-summary-v1', 'asset_version': before, 'registry_version': tools.registry.version,
        'embedding': provider.identity, 'dimension': dimension, 'count': len(documents),
        'subject': tools.principal, 'policy_hash': tools.access.policy_hash,
        'partitions': {p:sum(d.get('partition')==p for d in documents) for p in sorted({d.get('partition','knowledge') for d in documents})},
        'delta': {'encoded':len(changed),'reused':len(documents)-len(changed),
            'added':len(current-set(old)),'removed':len(set(old)-current),'tombstones':len(tombstones),
            'graph':graph_delta,'previous_snapshot':previous[1]['snapshot_id'] if previous else None},
        'files': {name: file_hash(folder/name) for name in ('documents.json','vectors.json','structured.sqlite','tombstones.json')}}
    manifest['snapshot_id'] = digest(manifest)
    (folder/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    pointer = {'folder': folder.name, 'manifest_sha256': file_hash(folder/'manifest.json'),
               'snapshot_id': manifest['snapshot_id']}
    temporary = directory / ('active-' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(pointer), encoding='utf-8')
    import sqlite3
    # 多个本地发布者也只能逐个切换指针；计算期间不占锁。
    with sqlite3.connect(directory/'publication.sqlite',timeout=10) as lock:
        lock.execute('BEGIN IMMEDIATE')
        active_hash = file_hash(directory/'active.json') if (directory/'active.json').exists() else None
        if active_hash!=starting_pointer or before!=asset_version(tools) or not tools.access.role()['publish']:
            raise ValueError('Concurrent publication or assets changed before active switch')
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
        folder,manifest,documents,vectors = read_snapshot(self.directory)
        snapshot_id = manifest['snapshot_id']
        if manifest['asset_version'] != asset_version(tools):
            raise ValueError('stale_dense_index')
        if manifest['registry_version'] != tools.registry.version or manifest['policy_hash'] != tools.access.policy_hash:
            raise ValueError('incompatible_index_scope')
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
