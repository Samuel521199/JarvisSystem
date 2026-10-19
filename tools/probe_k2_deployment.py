"""One authorized idle reload, metadata-only business-state preservation, served assets."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import time

from probe_dialogue_deployment import main as reload_idle,request,get,ROOT
from k2_state_fingerprint import fingerprint,EXCLUDED


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():parser.error('Existing evidence must be retained')
    data=Path('C:/Users/samuel/AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/Jarvis/data')
    report={'status':'running','captured_at':datetime.now(timezone.utc).isoformat(),'before':fingerprint(data),'excluded_tables':EXCLUDED,
            'limits':['Production business rows compared as counts/digests, no content exported. Runtime owner/queue controls legitimately change.',
                      'This verifies source deployment, not packaged-slot or schema downgrade compatibility. No production test memory is created.']}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def save():args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    try:
        report['reload']=reload_idle(None)
        token=re.search(r'<meta name="jarvis-nonce" content="([^"]+)"',request('/settings').decode())[1]
        report['assets']={}
        for name in ['persona.js','memory.js','continuity.js','modules.js','dialogue.js','resources.js','network.js']:
            digest=hashlib.sha256(request('/'+name)).hexdigest()
            assert digest==hashlib.sha256((ROOT/'apps/web'/name).read_bytes()).hexdigest(),name
            report['assets'][name]=digest
        profile=get('/api/persona',token);assert profile['schema_version']==2
        report['profile_available']=True;report['profile_revision']=profile['revision']
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            modules=get('/api/modules',token)
            if modules.get('modules') and not modules['refreshing']:break
            time.sleep(.15)
        rows={row['id']:row for row in modules['modules']}
        assert len(rows)==25 and rows['persona']['health']=='ready' and rows['continuity']['health']=='ready',[(key,value['health']) for key,value in rows.items()]
        report['module_health']={key:rows[key]['health'] for key in ['host','persona','continuity','memory','seed-catalog']}
        report['after']=fingerprint(data);report['business_state_unchanged']=report['after']==report['before']
        assert report['business_state_unchanged'],'Business-state change requires investigation; evidence retained'
        report.update(status='passed',version=get('/api/status')['version'])
    except Exception as error:report.update(status='failed',error=repr(error));raise
    finally:save()
    print(json.dumps({k:report[k] for k in ('status','version','business_state_unchanged','module_health')},ensure_ascii=False))


if __name__=='__main__':main()
