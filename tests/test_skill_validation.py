import json
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import test_skills as fixture
from jarvis_core import skill_validation as v
from jarvis_core.skills import catalog

class ValidationTests(fixture.Fixture):
    def test_source_change_and_missing_evidence(self):
        item=next(x for x in catalog()[0]['skills'] if x['id']==fixture.REVIEW);path=self.root/'validation.json'
        with patch.object(v,'INDEX',path):
            self.assertEqual(v.statuses(self.core,[item])[item['id']]['state'],'unverified')
            path.write_text(json.dumps({'schema_version':1,'skills':{item['id']:{'binding':v.fingerprint(item),'status':'passed'}}}))
            self.assertEqual(v.statuses(self.core,[item])[item['id']]['state'],'verified_scope')
            changed={**item,'guide':item['guide']+' more'}
            self.assertEqual(v.statuses(self.core,[changed])[item['id']]['state'],'stale')
    def test_last_success_is_not_quality_approval(self):
        item=catalog()[0]['skills'][0]
        with self.core.ledger.transaction() as db:v.confirmed(db,item,'task-example','old','delivery_checks')
        with patch.object(v,'INDEX',self.root/'missing'):
            result=v.statuses(self.core,[item])[item['id']]
            self.assertEqual(result['state'],'unverified');self.assertFalse(result['latest_success']['current'])
    def test_unrelated_name_does_not_invalidate_content(self):
        item=catalog()[0]['skills'][0];self.assertEqual(v.fingerprint(item),v.fingerprint({**item,'name':'display only'}))
