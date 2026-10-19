"""Assemble K2 evidence without turning absent hardware/owner checks into passes."""
from datetime import datetime,timezone
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RAW=Path('H:/JarvisData/diagnostics')
SUITES={
    'V-K2-01':['runtime_catalog','k2_personal_reference','memory_sources','knowledge'],
    'V-K2-02':['sample_tasks','skills','task_faults','worker'],
    'V-K2-03':['k2_control_latency','dialogue_process','task_queue'],
    'V-K2-04':['conversations','dialogue_recovery','memory','continuity','personal_core'],
    'V-K2-05':['local_model','resources','personal_core'],
    'V-K2-06':['task_faults','dialogue_recovery','documentation_admission','report_admission'],
    'V-PAL-01':['assistant_readiness','personal_core','web'],
    'V-PAL-02':['memory_sources','memory_review','rule_memory_review','personal_candidates'],
    'V-PAL-03':['memory_view','continuity','work_continuity','k2_personal_reference'],
    'V-PAL-04':['personal_core','k2_personal_reference','k2_persona_http'],
    'V-PAL-05':['dialogue_process','task_queue','k2_control_latency'],
    'V-PAL-07':['local_model','personal_core','resources'],
    'V-PAL-09':['growth_demand','evolution','runtime_start','k2_persona_http'],
    'V-PAL-10':['growth_demand','evolution','memory_answers_eval'],
}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'evals/reports/k2-completion-2026-10-19.json')
    parser.add_argument('--final',action='store_true');args=parser.parse_args()
    if args.output.exists() and json.loads(args.output.read_text(encoding='utf-8')).get('status') not in {'in_progress'}:
        parser.error('Final evidence must not be overwritten; choose a fresh output')
    paths={'regression':RAW/'k2-regression-r3.json','ui':RAW/'k2-personal-ui-r7/report.json',
        'answers':RAW/'k2-personal-answers-r1.json','contention':RAW/'k2-contention-r1.json',
        'idle':RAW/'k2-idle-r2.json','runtime':RAW/'k2-runtime-r4.json','faults':RAW/'k2-task-faults-r1.json',
        'offline_isolated':RAW/'k2-offline-isolated-r2.json','growth_repair':RAW/'k2-growth-r1.json',
        'growth_delivery':RAW/'k2-growth-delivery-r1/report.json','package_candidate':RAW/'k2-package-r2.json',
        'package':RAW/'k2-package-final.json','browser_resources':RAW/'k2-browser-resources-r3/report.json',
        'sampler_identity':RAW/'k2-sampler-tests-r1.json',
        'distribution':RAW/'k2-distribution-final.json',
        'delivery_source':RAW/'k2-delivery-source-final.json',
        'documentation':RAW/'k2-docs-final.json',
        'optional_voice':RAW/'k2-optional-voice-r1.json',
        'final_live':RAW/'k2-final-live.json',
        'deployment':RAW/'k2-deployment-r2.json','deployed_live':RAW/'k2-deployed-live-r1.json',
        'intent_calibration':ROOT/'evals/reports/dialogue-intent-v2-k2-r2-calibration-2026-10-19.json',
        'intent_heldout':ROOT/'evals/reports/dialogue-intent-v2-k2-r2-heldout-2026-10-19.json'}
    evidence={};data={}
    for name,path in paths.items():
        if path.exists():
            raw=path.read_bytes();value=json.loads(raw);data[name]=value
            hashes=value.get('source_sha256',{})
            evidence[name]={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'status':value.get('status'),'version':value.get('version',value.get('source_version')),
                'direct_bound_files':len(hashes),
                'changed_bound_files':[p for p,digest in hashes.items() if not (ROOT/p).is_file() or hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=digest]}
        else:evidence[name]={'path':str(path),'status':'missing'}
    accepted={'passed','passed_on_this_machine','passed_with_documented_limits','COMPLETED'}
    pending=[name for name,row in evidence.items() if row['status'] not in accepted]
    # Earlier feature probes do not use startup selection. Its later change is
    # independently covered by the final regression and packaged startup probe.
    allowed_changes={name:{'runtime/node-host/jarvis_core/releases.py'} for name in ['answers','contention']}
    unverified_changes={name:sorted(set(row.get('changed_bound_files',[]))-allowed_changes.get(name,set()))
                        for name,row in evidence.items()}
    unverified_changes={name:paths for name,paths in unverified_changes.items() if paths}
    if unverified_changes:pending.append('changed_evidence_sources')
    coverage={gate:['tests/test_'+name+'.py' for name in names] for gate,names in SUITES.items()}
    run_sources=data.get('regression',{}).get('source_sha256',{})
    missing_coverage=sorted({p for paths in coverage.values() for p in paths if p not in run_sources})
    if missing_coverage:pending.append('regression_coverage')
    archive_hashes=[data.get(name,{}).get(field) for name,field in [
        ('package','archive_sha256'),('distribution','sha256'),('delivery_source','archive_sha256')]]
    artifact_identity_checks={'same_tested_archive':all(archive_hashes) and len(set(archive_hashes))==1,
                              'source_version_matches':all(data.get(name,{}).get('version')=='0.1.62'
                                  for name in ['package','distribution','delivery_source'])}
    if not all(artifact_identity_checks.values()):pending.append('artifact_identity')
    runtime=data.get('runtime',{})
    runtime_integrity_checks={
        'measurement_checks_passed':bool(runtime.get('checks')) and all(runtime.get('checks',{}).values()),
        'no_final_sampling_errors':runtime.get('sample_errors')==[],
        'engine_reclaimed':runtime.get('engine_reclaimed') is True,
    }
    if not all(runtime_integrity_checks.values()):pending.append('runtime_final_integrity')
    classification_checks={}
    for name,count in [('intent_calibration',40),('intent_heldout',160)]:
        value=data.get(name,{})
        classification_checks[name]={
            'full_split':value.get('cases')==count and value.get('completed')==count,
            'macro_f1':value.get('macro_f1_present_classes',0)>=.90,
            'no_false_automatic_selection':value.get('auto_false_selections')==[],
            'source_unchanged':value.get('source_changed') is False}
        if not all(classification_checks[name].values()) and name not in pending:pending.append(name)
    if args.final and pending:parser.error('Independent evidence still unfinished/failed: '+', '.join(pending))
    summaries={}
    for name,fields in {'regression':['tests','failures','skipped','seconds','source_changed'],
        'optional_voice':['tests','failures','skipped','seconds','source_changed'],
        'runtime':['latency','checks','soak_seconds','engine_reclaimed'],
        'contention':['latency','checks','database_busy_cancel'],'idle':['summary'],
        'browser_resources':['summary','seconds','sample_errors','owned_tree_reclaimed'],
        'package':['archive','archive_sha256','personal_state_unchanged','corrupt_slot_fallback'],
        'distribution':['archive','sha256','bytes','files','candidate_runtime_identical','credential_signature_matches'],
        'delivery_source':['archive_sha256','archive_members_verified','source_members_compared','runtime_changes','post_build_documentation_changes'],
        'answers':['cost','source_unchanged'],'growth_delivery':['coding_calls','repeat_coding_calls','delivered_rows','benefit','personal_state_preserved','rollback_preserved_old_capability'],
        'intent_calibration':['cases','completed','macro_f1_present_classes','false_requested_effects','missed_requested_effects','auto_false_selections','auto_missed_selections','source_changed'],
        'intent_heldout':['cases','completed','macro_f1_present_classes','false_requested_effects','missed_requested_effects','auto_false_selections','auto_missed_selections','source_changed']}.items():
        if name in data:summaries[name]={key:data[name].get(key) for key in fields}
    if 'runtime' in data:
        value=data['runtime'];samples=value.get('samples',[]);cycles=value.get('soak',[])
        summaries['runtime'].update(sample_count=len(samples),soak_tasks=len(cycles),
            task_rate_per_minute=60*len(cycles)/value['soak_seconds'] if value.get('soak_seconds') else None,
            observed_peak_private_bytes=max((sum(p['private_bytes'] for p in row['processes']) for row in samples),default=None),
            observed_peak_working_bytes=max((sum(p['working_bytes'] for p in row['processes']) for row in samples),default=None),
            max_cycle_end_queue_depth=max((row['queue_depth'] for row in cycles),default=None),
            max_queue_wait_ms=max((row['queue_wait']['max_ms'] for row in cycles),default=None),
            load_profile='One background task overlaps one chat per cycle, paced by up to 3 seconds between cycles. Queue depth is measured at cycle ends; this is observed throughput, not saturation capacity.')
    gates=[
        ('V-K2-01','verified_bounded_sources',['regression','ui'],'No claim of general semantic knowledge indexing.'),
        ('V-K2-02','verified_fixed_task_scope',['regression','offline_isolated','runtime'],'Actual fixed artifacts and rejected plans, not arbitrary tools.'),
        ('V-K2-03','reference_device_missing',['contention','runtime'],'Current-PC measurement and 4-CPU affinity do not replace physical 8 GiB hardware.'),
        ('V-K2-04','verified_text_single_node',['regression','ui','faults','deployment'],'No simultaneous federation or arbitrary schema downgrade.'),
        ('V-K2-05','whole_machine_disconnect_pending',['offline_isolated'],'Existing run is application-isolated only.'),
        ('V-K2-06','verified_fixed_effect_scope',['regression','faults','deployment'],'Confirmed/unknown effects not blindly replayed; external irreversible effects excluded.'),
        ('V-PAL-01','owner_feedback_pending',['ui','deployed_live','intent_heldout'],'Technical paths tested; naturalness needs actual owner feedback.'),
        ('V-PAL-02','verified_bounded_memory',['regression','answers'],'No promise to retract copies already sent externally.'),
        ('V-PAL-03','bounded_verified_owner_feedback_pending',['regression','ui','answers'],'Lexical related recall and explicit source-visible selection; not broad semantic or long-term experience.'),
        ('V-PAL-04','verified_bounded_profile',['regression','ui','growth_delivery'],'Name/style/relationship choices and atomic undo; no arbitrary personas.'),
        ('V-PAL-05','reference_device_missing',['contention','runtime'],'Text/current-device evidence only.'),
        ('V-PAL-07','whole_machine_disconnect_pending',['offline_isolated'],'Personal controls degrade locally; actual link disconnect not yet tested.'),
        ('V-PAL-09','verified_compatible_package_scope',['regression','package','growth_repair','growth_delivery'],'Only measured compatible releases; reject unsupported data versions.'),
        ('V-PAL-10','objective_benefit_verified_owner_feedback_pending',['answers','growth_delivery'],'Known oracle recipe plus measured relevance improvement; no claim of unknown algorithm invention or subjective satisfaction.')]
    report={'schema_version':1,'source_version':'0.1.62','captured_at':datetime.now(timezone.utc).isoformat(),
        'status':'not_complete_external_acceptance' if args.final else 'in_progress',
        'plan':'evals/plans/k2-completion-v1.json','implementation':'deployed','entry':'http://127.0.0.1:18181/',
        'required_gates':[row[0] for row in gates],
        'gates':[{'id':ident,'status':status if args.final else 'pending_final_evidence','evidence':refs,'regression_files':coverage[ident],'limits':limits} for ident,status,refs,limits in gates],
        'evidence':evidence,'summaries':summaries,'classification_checks':classification_checks,'unfinished_independent_evidence':pending,
        'artifact_identity_checks':artifact_identity_checks,
        'runtime_integrity_checks':runtime_integrity_checks,
        'unverified_source_changes':unverified_changes,
        'external_dependencies':[{'item':'physical_reference_pc','status':'unavailable','owner_reply':'只有当前这台电脑'},
            {'item':'whole_machine_offline','status':'requires_owner_device_operation','runner':'tools/verify_k2_offline.ps1'},
            {'item':'owner_experience','status':'awaiting_actual_feedback'}],
        'retained_failures':['k2-regression-r1.log','k2-personal-ui-r1..r4','k2-control-before.log','k2-runtime-smoke-r1.json','k2-runtime-r2-interruption.json','k2-runtime-r3.json','k2-sampler-race-r1.json','k2-package-r1.json','k2-browser-resources-r1/report.json'],
        'maintenance_remainder':{'path':'C:/Users/samuel/AppData/Local/Temp/jarvis-k2-runtime-s65xb9ra',
            'state':'retained_after_automatic_approval_rejection','reason':'blocked by policy',
            'effect':'Interrupted disposable test directory only; process/engine already stopped. No runtime effect.'},
        'source_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ['runtime/node-host/jarvis_core','apps/web','adapters/computer-use'] for p in sorted((ROOT/folder).rglob('*'))
            if p.suffix in {'.py','.js','.html','.css'}},
        'authority_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in [
            'evals/plans/k2-completion-v1.json','docs/manifest.json','docs/core-bootstrap.md',
            'docs/delivery-validation.md','docs/interaction-persona.md','docs/knowledge-learning.md','docs/contracts.md']},
        'evidence_limits':['Fixture results do not score model quality; live results have small visible development corpora.',
                           'Earlier per-feature reports bind their own source hashes; final package/startup fixes have separate regression and package verification.',
                           'answers/contention differ only in releases.py, which those source-host probes do not use; current startup is covered by regression and the actual final package.',
                           'direct_bound_files=0 means the raw report uses a nested manifest/package/deployment identity; it does not mean an empty source tree was verified.',
                           'No requirement removed, no threshold relaxed, no physical device or owner feedback fabricated.']}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'pending':pending,'evidence':len(evidence)},ensure_ascii=False))


if __name__=='__main__':main()
