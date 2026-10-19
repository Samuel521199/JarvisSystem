"""Run named K2 regression groups, retaining failures and exact source binding."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'runtime/node-host'),str(ROOT/'apps/web'),str(ROOT/'adapters/models/provider-native')]
from jarvis_core import __version__

GROUPS={
 'personal':['k2_persona_http','k2_personal_reference','runtime_catalog','personal_core','continuity','work_continuity','memory','memory_view','memory_domains','memory_sources','memory_review','rule_memory_review','personal_candidates','semantic_candidates','memory_answers_eval','knowledge','conversations'],
 'dialogue':['intent','report_admission','documentation_admission','dialogue_turns','dialogue_process','dialogue_recovery','chat','context_assembly','assistant_readiness','web','calculator'],
 'execution':['k2_control_latency','core','sample_tasks','task_faults','task_queue','conversation_tasks','worker','worker_recovery','control','resources','resource_usage','runtime_metrics','local_model','network_policy'],
 'growth':['evolution','growth_demand','coding_workflow','skill_validation','skills','modules','runtime_start','release_bundle','preflight'],
 'optional_voice':['speech','qwen_speech','speech_expression','readout'],
}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--groups',nargs='+',choices=list(GROUPS),default=list(GROUPS))
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():parser.error('Evidence already exists; choose a new output')
    names=['test_'+name for group in args.groups for name in GROUPS[group]]
    def hashes():
        paths=[]
        for folder,suffixes in [('runtime/node-host/jarvis_core',{'.py'}),('apps/web',{'.py','.js','.html','.css'}),('adapters/models/provider-native',{'.py'})]:
            paths.extend(p for p in (ROOT/folder).rglob('*') if p.suffix in suffixes)
        paths.extend(ROOT/'tests'/f'{name}.py' for name in names)
        return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    before=hashes();start=time.monotonic()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.with_suffix('.log').open('w',encoding='utf-8') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(names))
    after=hashes()
    def identity(test):
        # Some legacy fixtures use self.id for the business record being tested.
        return test.id() if callable(getattr(test,'id',None)) else str(test)
    report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'groups':args.groups,'tests':result.testsRun,
            'status':'passed' if result.wasSuccessful() and before==after else 'source_changed' if result.wasSuccessful() else 'failed',
            'failures':[{'id':identity(t),'traceback':trace} for t,trace in result.failures+result.errors],
            'skipped':[{'id':identity(t),'reason':reason} for t,reason in result.skipped],
            'seconds':round(time.monotonic()-start,3),'source_sha256':before,'source_changed':[p for p in before if before[p]!=after.get(p)],
            'limits':'Local regression fixtures and real local Workers as specified by each test; not live model quality, physical reference PC, or subjective owner acceptance.'}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'},ensure_ascii=False))
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
