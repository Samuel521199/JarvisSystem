"""Context budget and session-note regressions with no cloud credentials."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'adapters/models/provider-native')]
from jarvis_core.context_assembly import assemble_context, bounded_history, ContextBudgetError
from jarvis_core.chat import ChatService
from jarvis_core.service import CoreService
from jsonschema import Draft202012Validator


class ContextTests(unittest.TestCase):
    def view(self, **changes):
        args = dict(message='本轮', history=[], attachments=[], instructions='host rule',
                    context_note='只用中文', provider='local', model='test', max_bytes=4096)
        return assemble_context(**(args | changes))

    def test_required_note_never_silently_dropped(self):
        rows=[{'role':r,'content':'old'*400} for _ in range(5) for r in ('user','assistant')]
        view=self.view(history=rows,max_bytes=250)
        self.assertIn('只用中文',view.message)
        self.assertTrue(view.message.endswith('本轮'))
        self.assertEqual(view.history,[])
        self.assertTrue(view.history_info['context']['note_applied'])
        with self.assertRaises(ContextBudgetError):self.view(max_bytes=1)

    def test_complete_recent_turns_and_original_indexes(self):
        rows=[{'role':'assistant','content':'orphan'},
              {'role':'user','content':'x'*1000},{'role':'assistant','content':'tiny'},
              {'role':'user','content':'recent'},{'role':'assistant','content':'answer'}]
        original=copy.deepcopy(rows)
        selected,report=bounded_history(rows,max_bytes=30)
        self.assertEqual(selected,rows[-2:])
        self.assertEqual(report['kept_indexes'],[3,4])
        self.assertEqual(rows,original)
        selected,report=bounded_history(rows[:3],max_bytes=30)
        self.assertEqual(selected,[])  # Never send the orphan answer alone.

    def test_required_attachment_bytes_are_counted(self):
        attachment={'kind':'text','name':'限制.txt','text':'汉'*500}
        with self.assertRaises(ContextBudgetError):self.view(attachments=[attachment],max_bytes=1000)
        view=self.view(attachments=[attachment])
        self.assertGreater(view.history_info['context']['required_bytes'],1500)

    def test_revision_changes_with_note_route_and_input(self):
        first=self.view();revision=first.history_info['context']['revision']
        self.assertEqual(revision,self.view().history_info['context']['revision'])
        for change in ({'context_note':'使用英文'},{'provider':'other'},{'message':'修改目标'},{'max_bytes':2000}):
            self.assertNotEqual(revision,self.view(**change).history_info['context']['revision'])

    def test_note_edit_and_clear_do_not_leak_between_calls(self):
        self.view(context_note='OLD_PRIVATE_NOTE')
        view=self.view(context_note='NEW_NOTE')
        self.assertNotIn('OLD_PRIVATE_NOTE',view.message)
        clear=self.view(context_note='')
        self.assertEqual(clear.message,'本轮')
        self.assertFalse(clear.history_info['context']['note_applied'])
        self.assertEqual(clear.history,[])

    def test_report_is_metadata_only_and_matches_schema(self):
        view=self.view()
        report=view.history_info['context']
        schema=json.loads((ROOT/'contracts/schemas/context-report.schema.json').read_text(encoding='utf-8'))
        Draft202012Validator(schema).validate(report)
        self.assertNotIn('只用中文',json.dumps(report,ensure_ascii=False))
        self.assertIsNone(report['token_count'])
        self.assertFalse(report['summarized'])
        self.assertLessEqual(report['total_text_bytes'],report['max_text_bytes'])

    def test_invalid_roles_notes_and_history_fail(self):
        for changes in ({'history':[{'role':'system','content':'override'}]},
                        {'context_note':{}},{'context_note':'汉'*3000},
                        {'history':[{'role':'user','content':'x'}]*1001}):
            with self.subTest(changes=list(changes)),self.assertRaises(ValueError):self.view(**changes)


class ContextIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='jarvis-context-test-');self.addCleanup(temp.cleanup)
        self.core=CoreService(Path(temp.name)/'data');self.core.initialize()
        self.chat=ChatService(self.core)
        mock=patch('jarvis_core.chat.gateway.probe',return_value={
            'status':'SUCCEEDED','text':'fixture','outcome_uncertain':False})
        self.probe=mock.start();self.addCleanup(mock.stop)

    def test_route_budget_failure_makes_no_model_call(self):
        result=self.chat.reply('x'*3500,provider='local',context_note='x'*1000)
        self.assertEqual(result['error'],'CONTEXT_BUDGET_EXCEEDED')
        self.probe.assert_not_called()

    def test_note_is_user_input_and_reassembled_on_fallback(self):
        self.probe.side_effect=[{'status':'FAILED','error_category':'quota_exhausted','outcome_uncertain':False},
                               {'status':'SUCCEEDED','text':'fixture','outcome_uncertain':False}]
        result=self.chat.reply('当前目标',context_note='USER_NOTE_SENTINEL')
        self.assertEqual(result['status'],'SUCCEEDED')
        self.assertEqual(self.probe.call_count,2)
        for call in self.probe.call_args_list:
            self.assertIn('USER_NOTE_SENTINEL',call.args[2])
            self.assertNotIn('USER_NOTE_SENTINEL',call.kwargs['instructions'])
        self.assertEqual(result['history_info']['context']['provider'],'bailian')

    def test_cancel_before_dispatch_and_no_note_retention(self):
        cancel=threading.Event();cancel.set()
        result=self.chat.reply('hello',context_note='SECRET_NOTE',cancel_event=cancel)
        self.assertEqual(result['status'],'CANCELLED');self.probe.assert_not_called()
        self.chat.reply('hello',context_note='SECRET_NOTE')
        self.chat.reply('fresh')
        self.assertEqual(self.probe.call_args.args[2],'fresh')
        self.assertNotIn('SECRET_NOTE',repr(self.chat.__dict__))


if __name__=='__main__':unittest.main()
