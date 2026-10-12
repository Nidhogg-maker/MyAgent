"""SQLite 结构投影与有界关系遍历；路径可达不是 Join 授权。"""
import json
import os
import shutil
import sqlite3
from pathlib import Path
from .semantic import ROOT,file_hash


def write_graph(path, graph, previous=None):
    if previous:
        shutil.copyfile(previous,path)
    nodes = {n['id']:json.dumps(n,sort_keys=True,ensure_ascii=False) for n in graph['nodes']}
    edges = {(e['source'],e['target'],e['kind']) for e in graph['edges']}
    if any(s not in nodes or t not in nodes for s,t,_ in edges):
        raise ValueError('Dangling graph relationship')
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS edges(source TEXT,target TEXT,kind TEXT,PRIMARY KEY(source,target,kind));
            CREATE INDEX IF NOT EXISTS incoming ON edges(target,kind);
            CREATE INDEX IF NOT EXISTS outgoing ON edges(source,kind);''')
        old = dict(db.execute('SELECT id,payload FROM nodes'))
        old_edges = set(db.execute('SELECT source,target,kind FROM edges'))
        for identifier in set(old)-set(nodes):
            db.execute('DELETE FROM nodes WHERE id=?',(identifier,))
        changed = [identifier for identifier,payload in nodes.items() if old.get(identifier)!=payload]
        db.executemany('INSERT OR REPLACE INTO nodes VALUES(?,?)',[(i,nodes[i]) for i in changed])
        db.executemany('DELETE FROM edges WHERE source=? AND target=? AND kind=?',list(old_edges-edges))
        db.executemany('INSERT OR IGNORE INTO edges VALUES(?,?,?)',list(edges-old_edges))
    return {'nodes':len(nodes),'edges':len(edges),'nodes_upserted':len(changed),
            'nodes_removed':len(set(old)-set(nodes)),'edges_added':len(edges-old_edges),'edges_removed':len(old_edges-edges)}


def graph_binding():
    from .dense_retrieval import configuration
    mode = os.environ.get('OWN_AGENT_STRUCTURED_MODE','auto')
    if mode not in ('off','auto','required'):
        raise ValueError('Unknown structured index mode')
    _,directory = configuration()
    pointer = directory/'active.json'
    return {'mode':mode,'directory':str(directory.resolve()),
        'active_hash':file_hash(pointer) if mode!='off' and pointer.exists() else None,
        'implementation':file_hash(Path(__file__))}


class GraphService:
    def __init__(self,tools):
        self.tools = tools

    def load(self):
        from .dense_retrieval import read_snapshot
        from .semantic_context import asset_version
        binding = graph_binding()
        self.tools.access.role()
        if binding['mode']=='off':
            raise ValueError('Structured index disabled')
        folder,manifest,_,_ = read_snapshot(binding['directory'])
        if manifest['format']!=3:
            raise ValueError('Structured index missing; publish unified assets')
        if (manifest['asset_version']!=asset_version(self.tools) or
            manifest['registry_version']!=self.tools.registry.version or
            file_hash(self.tools.registry.path)!=self.tools.registry.version or
            manifest['policy_hash']!=self.tools.access.policy_hash):
            raise ValueError('Stale structured index; republish required')
        return folder,manifest,binding

    def evidence(self):
        binding = graph_binding()
        if binding['mode']=='off':
            return {'status':'disabled','binding':binding,'authority':'current Registry'}
        try:
            _,manifest,binding = self.load()
            from .assets import AssetBuilder
            visible = AssetBuilder(self.tools).build()['graph']
            return {'status':'ready','snapshot_id':manifest['snapshot_id'],'binding':binding,
                'scope':'registered semantic graph; no inferred raw Join',
                'counts':{'nodes':len(visible['nodes']),'edges':len(visible['edges'])},'authority':'current Registry'}
        except (OSError,ValueError,KeyError,sqlite3.Error):
            if binding['mode']=='required':
                raise ValueError('Structured index required but unavailable')
            return {'status':'registry_fallback','binding':binding,'authority':'current Registry',
                    'reason':'missing_stale_or_corrupt_projection'}

    def query(self,node_id,direction='dependencies',max_depth=3,max_nodes=80):
        if direction not in ('dependencies','impact') or not 1<=max_depth<=6 or not 1<=max_nodes<=200:
            raise ValueError('Graph traversal budget exceeded')
        folder,manifest,binding = self.load()
        from .assets import AssetBuilder
        # 每次从当前授权 Registry 重建可见集合；不能遍历隐含不可见节点再过滤结果。
        live = AssetBuilder(self.tools).build()['graph']
        allowed = {n['id']:n for n in live['nodes']}
        if node_id not in allowed:
            raise ValueError('Unknown or unauthorized graph node')
        seen,frontier,links = {node_id},[node_id],set()
        truncated = False
        with sqlite3.connect((folder/'structured.sqlite').as_uri()+'?mode=ro',uri=True) as db:
            for _ in range(max_depth):
                following = []
                for current in frontier:
                    field = 'source' if direction=='dependencies' else 'target'
                    for source,target,kind in db.execute(f'SELECT source,target,kind FROM edges WHERE {field}=? ORDER BY source,target,kind',(current,)):
                        neighbor = target if direction=='dependencies' else source
                        if source not in allowed or target not in allowed:
                            continue
                        if neighbor not in seen and len(seen)>=max_nodes:
                            truncated = True; continue
                        links.add((source,target,kind))
                        if neighbor not in seen:
                            seen.add(neighbor); following.append(neighbor)
                frontier = following
                if not frontier: break
            if frontier: truncated = True
        self.tools.access.role()
        from .semantic_context import asset_version
        if binding!=graph_binding() or manifest['asset_version']!=asset_version(self.tools) or file_hash(self.tools.registry.path)!=self.tools.registry.version:
            raise ValueError('Structured snapshot changed during traversal')
        return {'start':node_id,'direction':direction,'nodes':[allowed[i] for i in sorted(seen)],
            'edges':[{'source':s,'target':t,'kind':k} for s,t,k in sorted(links)],
            'affected_metrics':sorted(n['metric_id'] for i,n in allowed.items() if i in seen and n['kind']=='metric'),
            'truncated':truncated,'snapshot_id':manifest['snapshot_id'],
            'asset_version':manifest['asset_version'],'subject':self.tools.principal,
            'implicit_join_allowed':False,'scope':'semantic projection; metadata lineage queried separately'}
