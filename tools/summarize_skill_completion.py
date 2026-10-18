"""Combine distinct, immutable receipts; never turn a failed probe into a pass."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core import __version__
from jarvis_core.skill_validation import fingerprint
from jarvis_core.skills import catalog
from probe_dialogue_deployment import get

def main():
    output=ROOT/'evals/reports/skills-completion-release-2026-10-19.json'
    if output.exists():raise ValueError('Refuse to overwrite release evidence')
    def read(name):return json.loads((ROOT/'evals/reports'/name).read_text(encoding='utf-8'))
    baseline=read('skills-completion-baseline-2026-10-19.json')
    delivered=read('skills-completion-deployment-r2-2026-10-19.json')
    saved=read('skills-saved-coding-delivery-r2-2026-10-19.json')
    mixed=read('skills-mixed-soak-release-2026-10-19.json')
    idle=read('skills-idle-30min-2026-10-19.json')
    ui=read('coding-workflow-release-ui-2026-10-19.json')
    interface=read('skills-interface-soak-2026-10-19.json')
    assert interface['status']=='passed' and len(interface['cycles'])==15
    assert ui['status']==saved['status']=='passed'
    assert mixed['status']==idle['status']=='passed_on_this_machine' and mixed['source_unchanged']
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha for p,sha in mixed['source_sha256'].items())
    assert delivered['apply_rollback_bom_exact'] and delivered['report']['coding']['passed']
    assert delivered['billing']['amount'] is not None and saved['task_id']==delivered['task_id']
    current=get('/api/status');assert current['version']==__version__ and current['core_ready'] and current['instance_id']==saved['current_instance']
    index=json.loads((ROOT/'config/skills/validation.json').read_text(encoding='utf-8'))
    assert all(index['skills'][item['id']]['binding']==fingerprint(item) for item in catalog()[0]['skills'] if item.get('presentation'))
    logpath=Path('H:/JarvisData/diagnostics/skills/web-queue-release-20261019.txt');log=logpath.read_text(encoding='utf-8-sig')
    match=re.search(r'Ran (\d+) tests in ([\d.]+)s',log);assert match and re.search(r'\nOK\s*$',log)
    recovery_path=Path('H:/JarvisData/diagnostics/skills/recovery-release-20261019.txt');recovery_log=recovery_path.read_text(encoding='utf-8-sig')
    recovery_match=re.search(r'Ran (\d+) tests in ([\d.]+)s',recovery_log);assert recovery_match and re.search(r'\nOK\s*$',recovery_log)
    cycles=mixed['cycles']
    data={'version':__version__,'observed_at':datetime.now(timezone.utc).isoformat(),'status':'verified_within_declared_scope_and_deployed',
        'instance_id':current['instance_id'],'main_suite':baseline['engineering_tests'],
        'additional_web_queue_suite':{'count':int(match[1]),'seconds':float(match[2]),'log_path':str(logpath),'sha256':hashlib.sha256(logpath.read_bytes()).hexdigest(),'log_tail':log.strip().splitlines()[-8:]},
        'maintenance_recovery_suite':{'count':int(recovery_match[1]),'seconds':float(recovery_match[2]),'log_path':str(recovery_path),'sha256':hashlib.sha256(recovery_path.read_bytes()).hexdigest(),'log_tail':recovery_log.strip().splitlines()[-8:]},
        'quality':baseline['quality'],'quality_method':baseline['quality_method'],
        'coding':{'conversation_url':saved['conversation_url'],'task_id':saved['task_id'],'model':delivered['cloud_route'],'frozen_cases':delivered['report']['coding']['validation']['cases'],'lpac':True,'apply_rollback_bom_exact':True,'saved_twice_same_receipt':True,'billing':delivered['billing']},
        'catalog':{'displayed':len(index['skills']),'all_validation_bindings_current':True},
        'mixed_resources':{'seconds':mixed['elapsed_seconds'],'cycles':len(cycles),'confirmed':sum(c['task_status']=='CONFIRMED' for c in cycles),'cancelled':sum(c['task_status']=='CANCELLED' for c in cycles),'paused_reopens':sum(c['reopened_paused'] for c in cycles),'source_unchanged':True,'cloud_calls':0},
        'idle_resources':idle['summary'],
        'deployed_resource_point':read('skills-deployed-resource-point-2026-10-19.json'),
        'interface_resources':{'cycles':len(interface['cycles']),'seconds':interface['elapsed_seconds'],'page_errors':interface['page_errors'],'cloud_calls':0},
        'evidence':['evals/reports/'+name for name in ['skills-completion-baseline-2026-10-19.json','skills-completion-deployment-2026-10-19.json','skills-completion-deployment-r2-2026-10-19.json','skills-saved-coding-delivery-r2-2026-10-19.json','skills-mixed-soak-release-2026-10-19.json','skills-idle-30min-2026-10-19.json','coding-workflow-release-ui-2026-10-19.json','skills-interface-soak-2026-10-19.json']],
        'debug_failures_preserved':'The first deployment probe failed to import its browser worker after a successful reload. The second completed real model execution, apply/rollback and pricing, then expected detail before explicit lazy loading. A read-only follow-up also initially forgot to open the task panel; the corrected follow-up verifies two reloads with no repeated task/model call. Early resource runs are development/source-changed evidence, not the release result.',
        'limits':['Single-file transform(data)->str only; visible cases do not prove arbitrary-input correctness.','Four fixed guidance components, not autonomous general skill composition or four independent review agents.','Quality review covers three authored scenarios per guide/model, one sample per arm, no independent blinded adjudication.','Resource load uses synthetic model text and supervised foreground process cancellation; no microphone/TTS/index/maintenance saturation matrix.','Injected 8 GiB admission counters are not a physical 8 GiB PC; no overnight or multi-day acceptance.','Documentation auto-admission retains 0.1.57 bounded Flash rule and external receipt dated 2026-10-18; no new external Context7 query in this release.','Memory deployment verifies the served asset and prior frozen fixture checks; no owner memory was changed by this verification.']}
    output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:data[k] for k in ['status','version','mixed_resources']},ensure_ascii=False))

if __name__=='__main__':main()
