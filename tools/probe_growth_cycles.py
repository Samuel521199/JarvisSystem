"""Three real-model growth cycles with frozen domains and real observation time."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use'),str(ROOT/'tests')]
from test_growth_cycles import GrowthCycleTests
from jarvis_core import __version__
from jarvis_core.dialogue_process import DialogueProcesses
from jarvis_core.evolution.growth_domains import DOMAINS, specification
from jarvis_core.evolution.maintenance import LedgerMaintenance
from jarvis_core.evolution.provider import default_route
from jarvis_core.evolution.catalog import runtime_binding
from jarvis_core.conversations import ConversationStore


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    # Freeze before any candidate request. Expectations stay outside model prompts.
    frozen={d:specification(d) for d in DOMAINS}
    raw=json.dumps(frozen,ensure_ascii=False,sort_keys=True,indent=2).encode()
    (args.output/'frozen-domains.json').write_bytes(raw)
    report={'version':__version__,'status':'running','runtime_binding':runtime_binding(),
            'frozen_sha256':hashlib.sha256(raw).hexdigest(),'tasks':[],
            'scope':'Three selected pure transformation domains; actual cloud coder and normal cloud baseline; no prewritten candidate.',
            'observation_window_seconds':30,'minimum_samples':6,'baseline':'same-input normal model transformation; all results must independently pass',
            'limitations':['short controlled window, not longitudinal user benefit','no claim of universal business semantics','temporary project, not owner data']}
    def save():(args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save()
    for domain in DOMAINS:
        f=GrowthCycleTests();f.setUp();row={'domain':domain,'status':'running'};report['tasks'].append(row);save()
        try:
            original={p.name:p.read_bytes() for p in f.source.iterdir() if p.is_file()}
            calls=DialogueProcesses(f.core,capacity=1);f.addCleanup(calls.close)
            f.manager.skills.model_calls=calls;del f.manager.skills.coding_generate
            f.grant(model=default_route())
            c=f.launch(domain=domain,goal='我希望每天重复整理我的清单或统计资料，请把这项明确需求做成可复用能力：'+frozen[domain]['contract'])
            begin=time.monotonic();deadline=begin+900;last=None;continued=False
            while time.monotonic()<deadline:
                f.cycles.tick();c=f.cycles.stored(f.cid,c['id'])
                if c['status']!=last:
                    last=c['status'];print(domain,last,flush=True)
                    row.update(phase=last,elapsed_seconds=round(time.monotonic()-begin,2));save()
                if not continued and c['status']=='BASELINE':
                    # Independent conversation save/read during background growth.
                    store=ConversationStore(f.core);existing=store.get(f.cid)
                    doc=existing['document'];doc['title']='个人助手的清单整理'
                    store.put(f.cid,{'revision':existing['revision'],'document':doc})
                    assert store.get(f.cid)['document']['title']==doc['title'];continued=True
                if c['status'] in {'COMPLETE','PAUSED','CANCELLED','INTERRUPTED'}:break
                time.sleep(.25)
            row.update(cycle=c,elapsed_seconds=round(time.monotonic()-begin,3),
                       concurrent_conversation_saved=continued,
                       source_unchanged=all((f.source/name).read_bytes()==raw for name,raw in original.items()),
                       new_python_files=[p.name for p in f.source.glob('*.py') if p.name not in original],
                       delivered_files=[p.name for p in f.source.iterdir() if p.is_file() and p.name not in original])
            assert c['status']=='COMPLETE',c.get('stop_reason',c['status'])
            assert row['source_unchanged'] and not row['new_python_files'] and continued
            assert f.cycles.start(f.cid,c['submission'])['id']==c['id']
            # Durable reload reads the same complete receipt; no new dispatch.
            from jarvis_core.evolution.growth_cycle import GrowthCycles
            reloaded=GrowthCycles(f.evolution,f.bridge)
            assert reloaded.stored(f.cid,c['id'])['assessment']==c['assessment']
            before=len(c['events']);reloaded.tick()
            assert len(reloaded.stored(f.cid,c['id'])['events'])==before
            maintenance=LedgerMaintenance(f.evolution).preview()
            row['maintenance_available']=isinstance(maintenance,dict)
            row['status']='passed';save()
        except Exception as exc:
            row.update(status='failed',error=type(exc).__name__+': '+str(exc));report['status']='failed';save();raise
        finally:f.doCleanups()
    report.update(status='passed',paid_model_calls=sum(x['cycle']['assessment']['experiment_model_calls'] for x in report['tasks']))
    save();print(json.dumps({'status':'passed','paid_model_calls':report['paid_model_calls'],'report':str(args.output/'report.json')}))


if __name__=='__main__':main()
