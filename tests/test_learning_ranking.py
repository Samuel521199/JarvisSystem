import json
import time
import unittest
import uuid
from unittest.mock import patch

from test_ranking_modules import RankingModuleTests, SOURCE
from test_conversations import document
from jarvis_core.conversations import ConversationStore
from jarvis_core.evolution.learning_loop import LearningLoop


class LearningRankingTests(RankingModuleTests):
    def test_evidence_reaches_generator_trial_and_exact_withdrawal(self):
        cid=uuid.uuid4().hex
        ConversationStore(self.core).put(cid,{'revision':0,'document':document()})
        class Tasks:
            pass
        loop=LearningLoop(self.manager,Tasks()); lid=uuid.uuid4().hex
        loop.create(dict(id=lid,goal='提高多关键词资料检索的覆盖质量。',conversation_id=cid))
        loop.evidence(lid,dict(source='项目检索对照案例',notes='覆盖不同关键词优于只重复一个词。',task_id=None))
        loop.review(lid,'已核对查询覆盖问题，仍使用宿主独立测试，不能扩大模块权限。')
        prompts=[]
        class Transport:
            def probe(self,*args,**kwargs):
                args[4]()
                prompts.append(json.loads(args[2]))
                return {'status':'SUCCEEDED','text':json.dumps({'code':SOURCE,'notes':'Improve term coverage'}),
                        'outcome_uncertain':False}
        self.service.model_calls=Transport()
        payload=dict(target='ranking',model='fixture::model',domain='',policy_revision=0)
        with patch.object(self.manager.provider,'configuration',return_value=({},'fixture')),patch.object(
                self.manager.provider,'receipt',return_value={'status':'SUCCEEDED'}):
            loop.start(lid,payload)
            end=time.monotonic()+45
            while self.manager.busy and time.monotonic()<end:time.sleep(.05)
            out=loop.view(lid)
            self.assertEqual(out['outcome']['status'],'SUCCEEDED',out)
            again=loop.start(lid,payload)
        self.assertEqual(len(prompts),1)
        self.assertIn('覆盖不同关键词',prompts[0]['untrusted_research_context'])
        version=out['outcome']['result']['candidate_id']
        self.assertTrue(out['outcome']['result']['eligible'])
        self.put();self.action('trial',version);self.observe();self.action('confirm',version)
        self.assertEqual(self.service.snapshot()['selection']['active'],version)
        loop.withdraw(lid)
        self.assertIsNone(self.service.snapshot()['selection']['active'])
        self.assertEqual(loop.read(lid)['state'],'WITHDRAWN')
        self.assertFalse((self.core.data_dir/'memory.db').exists())


def load_tests(loader,tests,pattern):
    return unittest.TestSuite([LearningRankingTests('test_evidence_reaches_generator_trial_and_exact_withdrawal')])
