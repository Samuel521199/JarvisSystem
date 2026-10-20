"""Coding settings reuse the local HTTP token/origin boundary without model calls."""
import json
from unittest.mock import patch
import test_evolution as fixture


class CodingHTTPTests(fixture.EvolutionHTTPTests):
    def test_coding_settings_token_origin_and_round_trip(self):
        self.assertEqual(self.request('GET','/api/coding',headers={'X-Jarvis-Nonce':'bad'})[0],403)
        self.assertEqual(self.request('POST','/api/coding',{},headers={'Origin':'https://evil.example'})[0],403)
        with patch('jarvis_core.coding_codex.executable',return_value=None):
            code,raw=self.request('GET','/api/coding');self.assertEqual(code,200,raw)
            settings=json.loads(raw)['settings'];self.assertFalse(settings['enabled'])
            code,raw=self.request('POST','/api/coding',{**settings,'enabled':True});self.assertEqual(code,200,raw)
            self.assertTrue(json.loads(raw)['settings']['enabled'])
            self.assertNotEqual(self.request('POST','/api/coding',settings)[0],200)
            self.assertEqual(self.request('POST','/api/coding',{**settings,'command':'unsafe'})[0],400)
        self.assertEqual(self.request('GET','/coding.js')[0],200)
        self.assertIn(b'coding-view',self.request('GET','/settings')[1])


for name in dir(fixture.EvolutionHTTPTests):
    if name.startswith('test_') and name not in CodingHTTPTests.__dict__:setattr(CodingHTTPTests,name,None)
