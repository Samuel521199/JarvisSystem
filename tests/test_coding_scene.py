"""Real QuickJS/LPAC, generated geometry, trusted browser and reversible source."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from test_coding_workflow import CodingTests
from jarvis_core import coding_js,coding_scene,policy
from jarvis_core.coding_build import bytes_from
from jarvis_core.coding_workflow import apply_result
from jarvis_core.evolution.runner import IsolatedRunner

SOURCE='''function transform(data) {
  return JSON.stringify({parts:[
    {id:"rail",kind:"line",color:"#55ccee",x:100,y:300,x2:900,y2:300},
    {id:"slider",kind:"rect",color:"#a088ff",x:200+data.phase,y:275,width:50,height:50}
  ]});
}'''


def expected(phase):
    return json.dumps({'parts':[{'id':'rail','kind':'line','color':'#55ccee','x':100,'y':300,'x2':900,'y2':300},
        {'id':'slider','kind':'rect','color':'#a088ff','x':200+phase,'y':275,'width':50,'height':50}]},separators=(',',':'))


class SceneTests(CodingTests):
    def setUp(self):
        super().setUp()
        def generate(prompt,instructions,guard):
            guard();self.calls.append(json.loads(prompt));self.assertLessEqual(len(instructions.encode()),4096)
            return {'status':'SUCCEEDED','text':json.dumps({'code':SOURCE,'notes':'fixture'})}
        self.manager.skills.coding_generate=generate
    def submit(self,**kw):
        return super().submit(**{'paths':['scene.js'],'new_paths':['scene.js'],'entrypoint':'scene.js','build_recipe':coding_js.RECIPE,
            'cases':[{'input':{'phase':p},'expected':expected(p)} for p in (0,90)],
            'heldout_cases':[{'input':{'phase':p},'expected':expected(p)} for p in (45,180)],**kw})
    def test_generated_scene_full_workflow_and_restore(self):
        report=self.report(self.submit());v=report['coding'];self.assertTrue(v['passed'],v)
        self.assertTrue(v['scene_browser']['scrub']);self.assertTrue(v['scene_worker']['lpac']);self.assertEqual(v['build']['filename'],'candidate-scene.zip')
        self.assertNotIn(SOURCE,v['scene_html']);bytes_from(v['build'])
        apply_result(self.core,report,'apply');self.assertEqual((self.source/'scene.js').read_text(),SOURCE)
        apply_result(self.core,report,'rollback');self.assertFalse((self.source/'scene.js').exists())
    def test_engine_denies_ambient_capabilities_and_limits_work(self):
        runner=coding_js.Runner()
        cases=['return process.env.SECRET;','return require("fs").readFileSync("input.json");',
               'return fetch("https://example.invalid");','return document.cookie;',
               'while(true){}','return "x".repeat(100000000);','data.phase=42;return "ok";']
        for body in cases:
            with self.subTest(body=body),self.assertRaises(policy.CoreError):
                runner.run({'scene.js':'function transform(data){'+body+'}'},'scene.js',[{'phase':0}],lambda:None)
        values,evidence=runner.run({'scene.js':'function transform(data){return [typeof process,typeof std,typeof os,typeof fetch,typeof window,typeof require].join(",");}'},'scene.js',[{'phase':0}],lambda:None)
        self.assertEqual(values,['undefined,undefined,undefined,undefined,undefined,undefined']);self.assertTrue(evidence['lpac'])
    def test_forged_frame_rejected_by_actual_rebuild(self):
        runner=coding_js.Runner();sources={'scene.js':SOURCE};frames,evidence=coding_scene.compile_frames(runner,sources,'scene.js',lambda:None)
        frames[0]['parts'][1]['x']+=1
        artifact=coding_scene.build(sources,'scene.js','sha256:'+'0'*64,frames)
        with self.assertRaises(policy.CoreError) as caught:IsolatedRunner().run_build(artifact,[{'phase':0}],lambda:None)
        self.assertEqual(caught.exception.code,'coding_build_invalid')
    def test_missing_engine_refused_before_model_and_geometry_rejected(self):
        with patch.object(coding_js,'SHA256','0'*64),self.assertRaises(policy.CoreError):self.submit()
        self.assertFalse(self.calls)
        bad=[json.loads(expected(0)) for _ in coding_scene.SAMPLES];bad[0]['parts'][0]['color']='url(https://example.invalid)'
        with self.assertRaises(ValueError):coding_scene.validate_frames(bad)
    def test_literal_credentials_rejected_before_outbound_and_receipt(self):
        (self.source/'calc.py').write_text('API_KEY = "sk-proj-'+('x'*30)+'"\ndef transform(data):\n    return "x"\n')
        with self.assertRaises(policy.CoreError) as caught:super().submit()
        self.assertEqual(caught.exception.code,'coding_sensitive_material');self.assertFalse(self.calls)
    def test_anatomy_guidance_policy_does_not_expand_fixed_renderer(self):
        self.assertFalse(self.skills.select('创建曲柄滑块交互',{'explicit':'anatomy.explainer'},purpose='task')['selected'])
        self.assertTrue(self.skills.select('创建曲柄滑块交互',{'explicit':'anatomy.explainer'},purpose='scene-guidance')['selected'])
        self.skills.put_policy({'skill_id':'anatomy.explainer','scope':'global','revision':0,'mode':'disabled'})
        with self.assertRaises(policy.CoreError):self.submit()
        self.assertFalse(self.calls)
    def test_preview_comes_from_verified_archive_and_rechecks_project_output(self):
        import sys
        from types import SimpleNamespace
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/web'))
        from skill_routes import confirmed
        item=self.submit();report=self.report(item)
        host=SimpleNamespace(conversation_tasks=self.bridge,workspace=self.workspace)
        raw=confirmed(host,self.cid,item['task_id']);self.assertIn(b'JARVIS / SCENE LAB',raw)
        report['coding']['scene_html']='<script>malicious()</script>'
        with patch.object(self.bridge,'artifact',return_value=json.dumps(report)):
            self.assertEqual(confirmed(host,self.cid,item['task_id']),raw)
        report['coding']['build']['sha256']='sha256:'+'0'*64
        with patch.object(self.bridge,'artifact',return_value=json.dumps(report)),self.assertRaises(policy.CoreError):confirmed(host,self.cid,item['task_id'])
        Path(report['output']['path']).write_text('externally edited')
        with self.assertRaises(policy.CoreError):confirmed(host,self.cid,item['task_id'])

for name in dir(CodingTests):
    if name.startswith('test_') and name not in SceneTests.__dict__:setattr(SceneTests,name,None)
del CodingTests
if __name__=='__main__':unittest.main()
