"""从当前注册中心离线派生索引，不扫描数仓行，不改变指标定义。"""
import argparse
import json
from pathlib import Path
from local_agent.semantic import ROOT
from local_agent.service import AgentTools
from local_agent.retrieval import KnowledgeRetriever
from local_agent.dense_retrieval import LocalEmbeddingProvider, publish_index

parser = argparse.ArgumentParser()
parser.add_argument('--home', type=Path, default=ROOT/'data/own-agent')
parser.add_argument('--directory', type=Path, default=ROOT/'data/retrieval-index')
parser.add_argument('--full',action='store_true',help='重新编码全部当前资产；默认增量复用未变化向量')
args = parser.parse_args()
tools = AgentTools(args.home)
identity = json.loads((ROOT/'data/embedding-identity.json').read_text(encoding='utf-8'))
manifest = publish_index(tools, KnowledgeRetriever(tools), LocalEmbeddingProvider(identity), args.directory,incremental=not args.full)
print(json.dumps({'snapshot_id': manifest['snapshot_id'], 'count': manifest['count'],
                  'dimension': manifest['dimension'], 'model': identity['model'],'delta':manifest['delta'],
                  'partitions':manifest['partitions']}))
