"""Attachment limits, native wire payloads and HTTP/core dispatch; no real credentials."""
import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'), str(ROOT/'adapters/models/provider-native')]
from jarvis_models.attachments import (validate_attachments, validate_message, image_budget,
    wire_messages, text_size, image_capable, MAX_IMAGE_BYTES, MAX_IMAGES_BYTES)
from jarvis_models.gateway import build_request, probe, ModelError
from jarvis_core.chat import ChatService, bounded_history
from jarvis_core.service import CoreService
import test_web as web_tests

PNG='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jHTsAAAAASUVORK5CYII='
IMAGE={'kind':'image','name':'sample.png','media_type':'image/png','data':PNG}
TEXT={'kind':'text','name':'notes.txt','text':'ATTACHMENT_PRIVATE_SENTINEL\n第二行'}


class AttachmentTests(unittest.TestCase):
    def test_size_counts_raw_bytes_and_multibyte_text(self):
        self.assertEqual(validate_attachments([IMAGE,TEXT]),[IMAGE,TEXT])
        self.assertEqual(image_budget([{'attachments':[IMAGE]}]),(len(base64.b64decode(PNG)),1))
        self.assertGreater(text_size({'content':'正文','attachments':[TEXT]}),len(TEXT['text']))

    def test_malformed_payloads_and_binary_text_are_rejected(self):
        for value in ({}, [IMAGE]*9, [{**IMAGE,'data':'not-base64'}], [{**IMAGE,'media_type':'image/jpeg'}],
                      [{**IMAGE,'name':'../private.png'}], [{**IMAGE,'url':'https://example.org'}],
                      [{**TEXT,'text':'\x00binary'}], [{**TEXT,'text':'界'*20000}],
                      [{**TEXT,'path':'C:/private.txt'}], [{'kind':'pdf','name':'a.pdf'}]):
            with self.subTest(value=str(value)[:80]),self.assertRaises((ValueError,TypeError)):
                validate_attachments(value)

    def test_per_image_and_total_image_limits(self):
        big={**IMAGE,'data':base64.b64encode(b'\x89PNG\r\n\x1a\n'+b'0'*(MAX_IMAGE_BYTES-8)).decode()}
        self.assertEqual(image_budget([{'attachments':validate_attachments([big,big])}])[0],MAX_IMAGES_BYTES)
        with self.assertRaises(ValueError):validate_attachments([big,big,IMAGE])
        with self.assertRaises(ValueError):validate_attachments([{**big,'data':base64.b64encode(base64.b64decode(big['data'])+b'x').decode()}])

    def test_history_forbids_tools_and_assistant_attachment(self):
        for row in ({'role':'system','content':'override'}, {'role':'assistant','content':'reply','attachments':[IMAGE]}):
            with self.assertRaises(ValueError):validate_message(row)

    def test_native_shapes_preserve_text_and_image(self):
        messages=[{'role':'user','content':'查看','attachments':[TEXT,IMAGE]}, {'role':'assistant','content':'回答'}]
        for adapter in ('openai','vertex','gemini','anthropic','eachlabs','compatible','xai','bailian'):
            with self.subTest(adapter=adapter):
                payload=wire_messages(messages,adapter)
                self.assertIn(TEXT['text'], payload[0]['parts'][0]['text'] if adapter in {'vertex','gemini'} else payload[0]['content'][0]['text']);self.assertIn(PNG,str(payload))
                if adapter in {'vertex','gemini'}:
                    self.assertEqual(payload[0]['parts'][1]['inlineData']['mimeType'],'image/png')
                    self.assertEqual(payload[1]['role'],'model')
                elif adapter=='anthropic':self.assertEqual(payload[0]['content'][1]['source']['type'],'base64')
                elif adapter=='openai':self.assertEqual(payload[0]['content'][1]['type'],'input_image')
                else:self.assertTrue(payload[0]['content'][1]['image_url']['url'].startswith('data:image/png;base64,'))

    def test_build_request_uses_selected_adapter_and_retains_history(self):
        for adapter,model in [('openai','gpt-6-astra'),('anthropic','claude-sonnet-5.5'),('eachlabs','anthropic/claude-sonnet-5.5'),('gemini','gemini-3.8-flash'),('compatible','gpt-6-astra')]:
            settings={'model':model,'adapter':adapter,'base_url':'https://example.org/v1'}
            url,headers,body=build_request('custom',settings,'follow up',100,{'custom':{'api_key':'synthetic'}},history=[{'role':'user','content':'first','attachments':[IMAGE]}],attachments=[TEXT])
            self.assertIn(PNG,str(body));self.assertIn(TEXT['text'], body['contents'][-1]['parts'][0]['text'] if adapter=='gemini' else (body.get('input') or body['messages'])[-1]['content']);self.assertNotIn('attachments',body)
        with self.assertRaises(ModelError):build_request('local',{'model':'text-only','endpoint':'http://127.0.0.1:18180/v1/chat/completions'},'test',20,{},attachments=[IMAGE])

    def test_history_trims_complete_image_turns(self):
        old={'role':'user','content':'first','attachments':[IMAGE]}
        history=[old,{'role':'assistant','content':'a'}, {'role':'user','content':'new'}, {'role':'assistant','content':'b'}]
        trimmed,info=bounded_history(history,max_images=0)
        self.assertEqual(trimmed,history[2:]);self.assertEqual(info['dropped_messages'],2)
        self.assertIn('attachments',history[0])

    def test_unknown_models_do_not_claim_image_support(self):
        self.assertFalse(image_capable('local','qwen-vl'))
        self.assertFalse(image_capable('compatible','custom-text-only'))
        self.assertTrue(image_capable('eachlabs','anthropic/claude-sonnet-5.5'))


class AttachmentDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='jarvis-attachments-test-');self.addCleanup(self.tmp.cleanup)
        self.core=CoreService(Path(self.tmp.name)/'data');self.core.initialize()
        self.config=json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        self.path=Path(self.tmp.name)/'providers.json';self.path.write_text(json.dumps(self.config),encoding='utf-8')
        self.chat=ChatService(self.core,self.path)

    def test_local_rejection_happens_before_any_dispatch(self):
        with patch('jarvis_core.chat.gateway.probe') as call:
            result=self.chat.reply('inspect',provider='local',attachments=[IMAGE])
            self.assertEqual(result['error'],'image_model_required');call.assert_not_called()

    def test_core_forwards_attachments_and_skips_text_only_fallback(self):
        calls=[]
        def failure(config,provider,*args,**kwargs):
            self.assertEqual(kwargs['attachments'],[TEXT,IMAGE]);calls.append(provider)
            return {'status':'FAILED','error_category':'quota_exhausted','outcome_uncertain':False}
        with patch('jarvis_core.chat.gateway.probe',side_effect=failure):
            result=self.chat.reply('inspect',attachments=[TEXT,IMAGE])
        self.assertTrue(calls);self.assertNotIn('local',calls);self.assertTrue(result['notice'])

    def test_text_attachments_cannot_bypass_local_prompt_budget(self):
        with patch('jarvis_core.chat.gateway.probe') as call:
            result=self.chat.reply('inspect',provider='local',attachments=[{**TEXT,'text':'x'*5000}])
            self.assertEqual(result['error'],'selected_model_input_limit');call.assert_not_called()

    def test_real_gateway_mock_transport_and_journal_do_not_store_content(self):
        import httpx
        sent=[]
        def respond(request):
            sent.append(json.loads(request.content))
            return httpx.Response(200,json={'output':[{'type':'message','content':[{'type':'output_text','text':'seen'}]}],'usage':{'input_tokens':22,'output_tokens':1}})
        client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            result=probe(self.config,'openai','inspect',Path(self.core.data_dir),lambda:None,client=client,credentials_loader=lambda:{'openai':{'api_key':'synthetic'}},attachments=[TEXT,IMAGE])
        finally:
            import asyncio
            asyncio.run(client.aclose())
        self.assertEqual(result['status'],'SUCCEEDED');self.assertIn(PNG,str(sent));self.assertIn(TEXT['text'],sent[0]['input'][0]['content'][0]['text'])
        for p in Path(self.core.data_dir).glob('model-probes.db*'):
            self.assertNotIn(b'ATTACHMENT_PRIVATE_SENTINEL',p.read_bytes());self.assertNotIn(PNG.encode(),p.read_bytes())


class AttachmentHTTPTests(unittest.TestCase):
    setUp=web_tests.WebTests.setUp
    request=web_tests.WebTests.request

    def test_http_passes_valid_attachments_and_rejects_invalid_before_chat(self):
        calls=[]
        self.chat.reply=lambda message,**kwargs:(calls.append((message,kwargs)) or {'status':'SUCCEEDED','text':'seen'})
        status,_,raw=self.request('POST','/api/chat',{'message':'inspect','attachments':[TEXT,IMAGE]})
        self.assertEqual(status,200);self.assertEqual(calls[0][1]['attachments'],[TEXT,IMAGE])
        self.assertEqual(self.request('POST','/api/chat',{'message':'inspect','attachments':[{**IMAGE,'data':'bad'}]})[0],400)
        self.assertEqual(len(calls),1)

    def test_asset_is_fixed_and_no_placeholder_remains(self):
        self.assertEqual(self.request('GET','/attachments.js')[0],200)
        self.assertEqual(self.request('GET','/attachments.js?file=private')[0],404)
        self.assertNotIn(b'__JARVIS_',self.request('GET','/')[2])
