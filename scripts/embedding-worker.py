"""隔离的本地 E5 编码进程；仅输出 JSON，不记录文本或凭据。"""
import json
import sys
from pathlib import Path


def main():
    from sentence_transformers import SentenceTransformer
    request = json.load(sys.stdin)
    identity = request['identity']
    import importlib.metadata
    for package, expected in identity['packages'].items():
        if importlib.metadata.version(package) != expected:
            raise ValueError('Embedding runtime version mismatch')
    import hashlib
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
    model = SentenceTransformer(identity['local_path'], device='cpu',
                                local_files_only=True, trust_remote_code=False)
    model.max_seq_length = identity['max_tokens']
    prefix = identity['query_prefix'] if request['kind'] == 'query' else identity['passage_prefix']
    vectors = model.encode([prefix+t for t in request['texts']], batch_size=8,
                           normalize_embeddings=True, show_progress_bar=False)
    sys.stdout.write(json.dumps({'vectors': vectors.tolist()}))


if __name__ == '__main__':
    main()
