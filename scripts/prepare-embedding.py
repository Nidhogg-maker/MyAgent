"""管理员一次性下载公开模型；锁定 Hub commit 与本地文件摘要。"""
import hashlib
import json
import argparse
import importlib.metadata
from pathlib import Path
from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'intfloat/multilingual-e5-small'
parser = argparse.ArgumentParser()
parser.add_argument('--revision', default='614241f622f53c4eeff9890bdc4f31cfecc418b3')
revision = parser.parse_args().revision
if len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):
    raise ValueError('Use an immutable Hub commit SHA')
folder = ROOT/'data'/('embedding-model-'+revision)
# 同版本复用已有目录；新版本使用新路径，不覆盖仍被 active 索引引用的旧模型。
previous_identity = ROOT/'data/embedding-identity.json'
if previous_identity.exists():
    previous = json.loads(previous_identity.read_text(encoding='utf-8'))
    existing = Path(previous['local_path']).resolve()
    if previous['revision'] == revision and existing.is_relative_to((ROOT/'data').resolve()):
        folder = existing
snapshot_download(MODEL, revision=revision, local_dir=folder,
    allow_patterns=['*.json','*.txt','*.model','*.safetensors','1_Pooling/*'],
    ignore_patterns=['onnx/*','openvino/*'])
files = {}
for path in folder.rglob('*'):
    if path.is_file() and '.cache' not in path.parts:
        h = hashlib.sha256()
        with path.open('rb') as handle:
            for block in iter(lambda: handle.read(1024*1024), b''):
                h.update(block)
        files[path.relative_to(folder).as_posix()] = h.hexdigest()
identity = {'model': MODEL, 'revision': revision, 'local_path': str(folder), 'files': files,
    'query_prefix': 'query: ', 'passage_prefix': 'passage: ', 'max_tokens': 512,
    'normalized': True, 'runtime': 'sentence-transformers CPU',
    'packages': {name: importlib.metadata.version(name) for name in
                 ('sentence-transformers','torch','transformers','numpy')}}
(ROOT/'data/embedding-identity.json').write_text(json.dumps(identity, indent=2), encoding='utf-8')
print(json.dumps({'model': MODEL, 'revision': revision, 'files': len(files)}))
