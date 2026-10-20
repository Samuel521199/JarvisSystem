"""Real local filesystem, bounded model protocol and actual game acceptance."""
import copy
import json
from pathlib import Path
import sys
import time
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from test_skills import Fixture
from test_web import FakeChat
from jarvis_core.policy import CoreError
from jarvis_core.project_files import ProjectFiles
from jarvis_core.conversation_tasks import ConversationTasks
from jarvis_computer.web import ComputerWeb
from jarvis_core.web_game import SKILL,decode,validate,html,verify_browser
from jarvis_core.chat import ChatService,response_budgets
from jarvis_core.assistant_context import chat_instructions
from jarvis_core.dialogue_process import DialogueProcesses

DESIGN={'title':'装甲前线 · 基地守卫','player_color':'#a6b96d','enemy_color':'#ad765c',
        'ground_color':'#25332b','waves':[2,3],'base_hp':6,'enemy_speed':32,
        'obstacles':[{'x':160,'y':190,'width':60,'height':35},{'x':590,'y':280,'width':55,'height':30}]}


class GameTests(Fixture):
    def test_create_project_and_subfolder_preserve_existing_contents(self):
        destination=self.root/'new project'
        self.assertFalse(destination.exists())
        one=self.workspace.create_project({'path':str(destination)});self.assertTrue(one['created'])
        (destination/'keep.txt').write_text('keep')
        two=self.workspace.create_project({'path':str(destination)})
        self.assertEqual(one['id'],two['id']);self.assertFalse(two['created'])
        self.assertEqual((destination/'keep.txt').read_text(),'keep')
        files=ProjectFiles(self.core)
        req={'project_id':one['id'],'path':'assets'}
        self.assertTrue(files.mkdir(req)['created']);self.assertFalse(files.mkdir(req)['created'])
        for path in ('../escape','.git/x','assets/../../escape','C:/outside'):
            with self.assertRaises(CoreError):files.mkdir({**req,'path':path})
        for path in (str(self.core.data_dir/'bad'),str(self.root/'absent'/'child'),'relative',str(self.source/'calc.py')):
            with self.assertRaises((CoreError,OSError)):self.workspace.create_project({'path':path})
        self.assertFalse((self.core.data_dir/'bad').exists())

    def test_design_protocol_rejects_code_and_keeps_config_escaped(self):
        self.assertEqual(decode('```json\n'+json.dumps(DESIGN)+'\n```'),DESIGN)
        for change in ({'script':'alert(1)'},{'base_hp':True},{'waves':[0,99]},
                       {'player_color':'url(https://evil.invalid)'},{'obstacles':[{'x':390,'y':200,'width':40,'height':40}]}):
            with self.assertRaises(CoreError):validate({**DESIGN,**change})
        with self.assertRaises(CoreError):decode(json.dumps(DESIGN)[:-1]+',"title":"duplicate"}')
        unsafe={**DESIGN,'title':'</script><script>alert(1)</script>'}
        self.assertNotIn(unsafe['title'],html(unsafe));self.assertIn('\\u003c/script>',html(unsafe))

    def test_frontier_wait_is_bounded_and_unknown_never_falls_back(self):
        self.assertEqual(response_budgets({'model':'gemini-4-argon'}),(150.,120.))
        self.assertEqual(response_budgets({'model':'gemini-3.8-flash'}),(90.,60.))
        chat=ChatService(self.core)
        with patch('jarvis_core.chat.gateway.probe',return_value={'status':'UNKNOWN','outcome_uncertain':True,'text':''}) as probe:
            result=chat.reply('hello',provider='vertex',model='gemini-4-argon')
            self.assertEqual(probe.call_count,1);self.assertEqual(probe.call_args.kwargs['deadline_seconds'],120.)
            self.assertEqual(result['status'],'UNKNOWN')
        pool=DialogueProcesses(self.core)
        try:
            with patch.object(pool,'_run',return_value={}) as run:
                pool.probe({},'vertex','x',self.core.data_dir,self.core.assert_running,deadline_seconds=120)
                self.assertEqual(run.call_args.args[-1],140.)
        finally:pool.close()
        self.assertIn('browser and desktop',chat_instructions('local','small'))

    def test_real_skill_game_delivery_is_idempotent_and_scoped(self):
        manager=ComputerWeb(self.core,FakeChat());self.addCleanup(manager.close)
        bridge=ConversationTasks(self.core,manager)
        request={'mode':'skill','request_id':'web-'+uuid.uuid4().hex,'prompt':'制作一个简单的坦克守卫基地游戏',
                 'project_id':self.project['id'],'skill_id':SKILL,'paths':[],
                 'model':'vertex::gemini-3.8-flash','output_path':'tank-game.html'}
        with patch('jarvis_core.evolution.provider.gateway.probe',return_value={'status':'SUCCEEDED','text':json.dumps(DESIGN),'outcome_uncertain':False}) as model:
            item=bridge.submit(self.cid,request)
            end=time.monotonic()+45
            while time.monotonic()<end:
                result=bridge.detail(self.cid,item['task_id'])
                if result['task']['status'] not in {'READY','RUNNING','CANCELLING'}:break
                time.sleep(.05)
            self.assertEqual(result['task']['status'],'SUCCEEDED',result)
            report=json.loads(bridge.artifact(self.cid,item['task_id']))
            self.assertTrue(report['checks']['browser']['win']);self.assertTrue(report['checks']['browser']['base_damage_and_loss'])
            self.assertFalse(report['checks']['generated_code_executed'])
            self.assertEqual(Path(report['output']['path']).read_text(encoding='utf-8'),report['html'])
            same=bridge.submit(self.cid,request);self.assertEqual(same['task_id'],item['task_id']);self.assertEqual(model.call_count,1)
            with self.assertRaises(CoreError):bridge.artifact(uuid.uuid4().hex,item['task_id'])
            self.assertEqual((self.source/'calc.py').read_text(),'def divide(a, b):\n    return a / b\n')

    def test_invalid_or_unknown_design_never_delivers_or_retries(self):
        from jarvis_core.web_game import generate
        from types import SimpleNamespace
        service=SimpleNamespace(core=self.core,config_path=None,model_calls=None)
        args={'prompt':'制作坦克游戏','model':'vertex::gemini-3.8-flash'}
        for response in ({'status':'UNKNOWN','outcome_uncertain':True},
                         {'status':'SUCCEEDED','text':'{}'},
                         {'status':'SUCCEEDED','text':json.dumps(DESIGN),'output_incomplete':True}):
            with patch('jarvis_core.evolution.provider.gateway.probe',return_value=response) as model:
                with self.assertRaises(CoreError):generate(service,args,lambda:None,None)
                self.assertEqual(model.call_count,1)
        self.assertFalse(list(self.source.glob('*.html')))
