"""仅对授权候选(query, passage)打分；不执行检索文本中的指令。"""
import json
import sys
from pathlib import Path
import importlib.metadata
import hashlib


def main():
    request = json.load(sys.stdin)
    identity = request['identity']
    for package, expected in identity['packages'].items():
        if importlib.metadata.version(package) != expected:
            raise ValueError('Reranker runtime mismatch')
    for name, expected in identity['files'].items():
        path = (Path(identity['local_path'])/name).resolve()
        if not path.is_relative_to(Path(identity['local_path']).resolve()):
            raise ValueError('Invalid model path')
        checksum = hashlib.sha256()
        with path.open('rb') as handle:
            for block in iter(lambda: handle.read(1024*1024), b''):
                checksum.update(block)
        if checksum.hexdigest() != expected:
            raise ValueError('Model checksum mismatch')
    from sentence_transformers import CrossEncoder
    import torch
    model = CrossEncoder(identity['local_path'], device='cpu', max_length=identity['max_tokens'],
        local_files_only=True, trust_remote_code=False, activation_fn=torch.nn.Identity())
    scores = model.predict(request['pairs'], batch_size=8, show_progress_bar=False)
    sys.stdout.write(json.dumps({'scores':scores.tolist()}))


if __name__ == '__main__':
    main()
