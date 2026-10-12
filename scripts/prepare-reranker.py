"""离线准备多语言 Cross-Encoder；固定版本，不覆盖已有模型。"""
import hashlib
import importlib.metadata
import json
from pathlib import Path
from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'cross-encoder/mmarco-mMiniLMv2-L12-H384-v1'
REVISION = '1427fd652930e4ba29e8149678df786c240d8825'
folder = ROOT/'data'/('reranker-model-'+REVISION)
snapshot_download(MODEL, revision=REVISION, local_dir=folder,
    allow_patterns=['*.json','*.txt','*.model','model.safetensors'],
    ignore_patterns=['onnx/*','openvino/*'])
files = {}
for path in folder.rglob('*'):
    if path.is_file() and '.cache' not in path.parts:
        checksum = hashlib.sha256()
        with path.open('rb') as handle:
            for block in iter(lambda: handle.read(1024*1024), b''):
                checksum.update(block)
        files[path.relative_to(folder).as_posix()] = checksum.hexdigest()
identity = {'model':MODEL,'revision':REVISION,'local_path':str(folder),'files':files,
    'max_tokens':512,'score_type':'raw_logit_not_probability',
    'packages':{name:importlib.metadata.version(name) for name in
                ('sentence-transformers','torch','transformers','numpy')}}
(ROOT/'data/reranker-identity.json').write_text(json.dumps(identity, indent=2), encoding='utf-8')
print(json.dumps({'model':MODEL,'revision':REVISION,'files':len(files)}))
