"""Synthetic, bounded project corpus resource measurement; no model calls."""
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core import __version__
from jarvis_core.knowledge import KnowledgeStore
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService


def main():
    with tempfile.TemporaryDirectory(prefix='jarvis-knowledge-resource-') as directory:
        base=Path(directory);project=base/'project';project.mkdir()
        core=CoreService(base/'data');core.initialize(project)
        pid=WorkspaceService(core).open_project({'path':str(project)})['id'];store=KnowledgeStore(core)
        total=0
        for number in range(32):
            text='\n'.join(f'## 离线部署章节 {section}\n'+('断网时使用本机资料，恢复网络后再按同步范围检查。'*15) for section in range(20))
            path=f'file-{number:02}.md';(project/path).write_text(text,encoding='utf-8');total+=(project/path).stat().st_size
            store.put(uuid.uuid4().hex,{'revision':0,'document':{'project_id':pid,'path':path,'providers':[]}})
        request={'enabled':True,'project_id':pid};samples=[]
        for _ in range(15):
            started=time.perf_counter();snapshot=store.snapshot(request,'local');_,result=store.context(snapshot,'如何离线部署')
            samples.append((time.perf_counter()-started)*1000)
            assert not result['issues'] and result['citations'] and result['bytes']<=8192
        tracemalloc.start();snapshot=store.snapshot(request,'local');store.context(snapshot,'如何离线部署')
        _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'status':'observed',
                'fixture':{'documents':32,'sections':640,'utf8_bytes':total},'registration_db_bytes':store.path.stat().st_size,
                'retrieval':{'samples':len(samples),'median_ms':round(statistics.median(samples),3),'p95_ms':round(sorted(samples)[14],3),
                'read_bytes':result['read_bytes'],'matched_chunks':result['matches'],'selected_chunks':len(result['citations']),'context_bytes':result['bytes']},
                'python_peak_allocated_bytes':peak,'new_dependencies':[],'new_background_services':0,
                'limits':['Warm-cache synthetic corpus on this PC, including current file reads and hashing. Not a hardware-independent SLA.',
                'Python allocation peak is not process RSS; no model, GPU, concurrent retrieval or semantic-quality measurement.',
                'Read/parse budgets are cooperative, not OS-enforced filesystem timeouts.']}
    (ROOT/'evals/reports/knowledge-resources.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
