"""Literal task focus over retained static evidence, without model inference."""
import json
import re

from . import policy

RELATIONS = {'invokes', 'maps_to', 'handles', 'imports', 'loads'}


def project_link(edge):
    evidence = edge.get('evidence', {})
    return {'edge_id': edge.get('edge_id'), 'relation': edge['relation'], 'properties': edge.get('properties', {}),
            'location': evidence.get('location'), 'evidence_state': evidence.get('state'),
            'confidence': evidence.get('confidence'), 'limitations': evidence.get('limitations', [])}


def query(args):
    explicit = args.get('focus', '').strip()
    if explicit: return explicit, 'explicit'
    message = args.get('prompt', '')
    quoted = re.search(r'[`“「]([^`”」\n]{1,128})[`”」]', message)
    if quoted and len(quoted[1].encode('utf-8')) <= 256 and not any(ord(c)<32 for c in quoted[1]):
        return quoted[1], 'quoted_identifier'
    token = re.search(r'(?<![\w$])(?:[A-Za-z_$][\w$.-]*:[\w$:-]+|[\w./-]+\.(?:m?js|cjs))(?![\w$])', message)
    return (token[0], 'literal_identifier') if token and len(token[0].encode('utf-8')) <= 256 else ('', 'overview')


def matches(value, needle):
    pattern = re.compile(r'(?<![\w$])'+re.escape(needle)+r'(?![\w$])', re.I)
    def walk(item):
        if isinstance(item, str): return bool(pattern.search(item))
        if isinstance(item, list): return any(walk(v) for v in item)
        if isinstance(item, dict): return any(walk(v) for k,v in item.items() if k not in {'edge_id','node_id','evidence_id'})
        return False
    return walk(value)


def inspect(evidence, args):
    needle, source = query(args)
    if not needle: return {'query':'', 'source':source, 'matched':False, 'nodes':[], 'links':[]}
    graph = evidence['normalized_result']['graph']
    nodes = [n for n in graph['nodes'] if matches(n, needle)]
    links = [e for e in graph['edges'] if e.get('relation') in RELATIONS and matches(e, needle)]
    projected = [project_link(e) for e in links]
    kept, used = [], 0
    for row in projected[:30]:
        count = len(policy.canonical_json(row).encode('utf-8'))
        if used + count > 48*1024: break
        kept.append(row); used += count
    return {'query':needle, 'source':source, 'matched':bool(nodes or links), 'node_count':len(nodes),
            'link_count':len(links), 'links':kept, 'links_omitted':len(links)-len(kept),
            'nodes':[{'node_id':n.get('node_id'),'kind':n.get('kind'),
                      'labels':[str(o.get('label',''))[:256] for o in n.get('observations',[])[:4]]} for n in nodes[:20]],
            'method':'literal_identifier_match', 'runtime_verified':False}


def lines(focus):
    if not focus['query']: return []
    head = ['', '## 本次关注：'+focus['query'], '匹配方式：字面标识符检索；没有自动推断运行行为。']
    if not focus['matched']:
        return head+['当前证据没有匹配项。可能是名称不同、动态生成或输入范围不足；不能据此认定功能不存在。']
    return head+[f"相关节点 {focus['node_count']} 个、关键关系 {focus['link_count']} 条；下列展示 {len(focus['links'])} 条。",
                 *[r['relation']+'：'+json.dumps(r['properties'],ensure_ascii=False)+'\n  来源：'+json.dumps(r['location'],ensure_ascii=False)+'\n  证据：'+str(r['edge_id']) for r in focus['links']],
                 '更多匹配项可在证据浏览中按相同标识符筛选。']
