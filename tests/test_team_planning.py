import copy
import json
import unittest
from unittest.mock import patch

from test_team_tasks import TeamTests, PROPOSAL, REVIEW
from jarvis_core.team_planning import allocate
from jarvis_core.resources import MIB
from jarvis_core.policy import CoreError


class DynamicTeamTests(TeamTests):
    def test_four_roles_have_one_budget_independent_calls_and_review(self):
        self.args.update(criteria=['兼容旧内容','资源有上限','可以恢复','不写记忆','逐项检查'],
                         auto_team=True,max_agents=4)
        def responses(index,response):
            review=copy.deepcopy(REVIEW)
            review['criteria']=[dict(criterion_id='c'+str(i+1),status='uncertain',reason='待实测')
                                for i in range(5)]
            response['text']=json.dumps(PROPOSAL if index<3 else review)
        self.calls.change=responses
        with patch('jarvis_core.team_tasks.allocate',return_value=allocate(self.args,lambda:{
                'available_bytes':2048*MIB,'commit_available_bytes':2048*MIB})):
            prepared,result=self.run_task()
        self.assertEqual(result['action']['status'],'CONFIRMED',result['action'].get('error'))
        self.assertEqual(prepared['task']['budget']['max_cost_units'],4)
        self.assertEqual([c['role'] for c in self.service.calls(prepared['task']['task_id'])],
                         ['planner','specialist1','specialist2','reviewer'])
        self.assertEqual(len(self.calls.requests),4)
        self.assertEqual(len(self.calls.requests[-1]['prompt']['specialist_suggestions']),2)
        self.service.run(prepared['action']['action_id'])
        self.assertEqual(len(self.calls.requests),4)

    def test_pressure_and_limits_reduce_team_without_extra_calls(self):
        args=dict(self.args,criteria=['a','b','c','d','e'],auto_team=True,max_agents=4)
        plan=allocate(args,lambda:{'available_bytes':400*MIB,'commit_available_bytes':500*MIB})
        self.assertEqual(plan['roles'],['planner','reviewer'])
        args['max_agents']=3
        self.assertEqual(len(allocate(args,lambda:{'available_bytes':4000*MIB,'commit_available_bytes':4000*MIB})['roles']),3)
        self.args['max_agents']=100
        with self.assertRaises(CoreError):self.prepare()
        self.assertFalse(self.calls.requests)


def load_tests(loader,tests,pattern):
    return unittest.TestSuite(DynamicTeamTests(n) for n in DynamicTeamTests.__dict__ if n.startswith('test_'))
