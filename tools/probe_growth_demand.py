"""Isolated demand-to-result probe, optionally using the configured live coding model."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tests'), str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use')]
from test_growth_demand import GrowthDemandTests
from jarvis_core import __version__
from jarvis_core.evolution import EvolutionManager
from jarvis_core.evolution.demand import ConversationGrowth


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--live', action='store_true', help='Sends up to two paid coding requests; owner authorization required.')
    parser.add_argument('--route', help='Configured provider::model, only with --live')
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    if args.route and not args.live: parser.error('--route requires --live')
    fixture = GrowthDemandTests(); jobs = []
    try:
        fixture.setUp(); fixture.manager.close()
        manager = EvolutionManager(fixture.core, provider=None if args.live else fixture.provider, monitor=False)
        fixture.addCleanup(manager.close)
        if args.route: manager.configure({'enabled':False, 'route':args.route, 'target_revision':1})
        bridge = ConversationGrowth(fixture.core, manager, fixture.bridge.tasks)
        def fulfill(prompt):
            proposal = bridge.propose(fixture.cid, {'request_id':__import__('uuid').uuid4().hex,'prompt':prompt})
            started = time.monotonic(); bridge.start(fixture.cid, proposal['id'], {})
            while manager.busy and time.monotonic()-started < 240: time.sleep(.1)
            if manager.busy: manager.cancel(proposal['id']); raise RuntimeError('bounded probe deadline')
            job = manager.store.job(proposal['id']); jobs.append(job)
            (args.output/(str(len(jobs))+'-job.json')).write_text(json.dumps(job, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            if job['status'] == 'SUCCEEDED':
                raw, fmt = bridge.artifact(fixture.cid, job['id'])
                (args.output/('result.'+fmt)).write_bytes(raw)
            return job
        first = fulfill('把本会话最近的目录报告导出为 TSV')
        if first['status'] == 'SUCCEEDED':
            second = fulfill('导出 CSV')
            assert second['proposal']['decision'] == 'reuse' and not second['attempts']
        report = {'version':__version__, 'captured_at':datetime.now(timezone.utc).isoformat(),
            'status':'passed' if len(jobs)==2 and all(j['status']=='SUCCEEDED' for j in jobs) else 'failed',
            'live_coding_model':args.live, 'route':manager.store.settings()['route'],
            'coding_attempts':sum(len(j['attempts']) for j in jobs),
            'jobs':[{'id':j['id'],'status':j['status'],'error':j.get('error'),'decision':j['proposal']['decision'],
                'attempts':j['attempts'], 'result':j.get('result')} for j in jobs],
            'limits':['Source planner uses a fixture; source files and conversation are synthetic, isolated and temporary.',
                'Actual LPAC and Host oracle verify generated code and real source input; existing production data/settings are untouched.',
                'Known inventory-export recipe only; does not prove arbitrary novel skill or general self-modification.']}
        (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({k:report[k] for k in ('version','status','live_coding_model','route','coding_attempts')},ensure_ascii=False))
        return 0 if report['status']=='passed' else 1
    finally: fixture.doCleanups()


if __name__ == '__main__': raise SystemExit(main())
