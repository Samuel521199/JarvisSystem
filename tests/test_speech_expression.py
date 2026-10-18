"""Expression score semantics, total budgets and atomic native composition."""
from array import array
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
import wave

from jarvis_core.qwen_speech_contract import validate, expression_plan
from jarvis_core.speech_audio import SpeechAudio
from jarvis_core.speech_contract import SpeechError


class ExpressionTests(unittest.TestCase):
    def plan(self,text,**kwargs): return expression_plan(validate(dict(action='synthesize',text=text,**kwargs)))

    def test_light_voice_and_slow_selector_compose_instead_of_overriding_each_other(self):
        row=self.plan('【轻声】别担心，我在这里。',emotion='slow')['segments'][0]
        self.assertEqual((row['emotion'],row['delivery'],row['pace']),('neutral','soft','slow'))
        self.assertIn('温柔',row['instructions']);self.assertIn('缓慢',row['instructions'])

    def test_layered_tags_persist_per_dimension_and_natural_resets_everything(self):
        plan=self.plan('[轻声][慢速]别担心。[开心]你做到了！[语速正常]一起走吧。[正常语气]再见。[自然]你好。')
        rows=plan['segments'];self.assertEqual(plan['speech_segments'],5)
        self.assertEqual((rows[1]['emotion'],rows[1]['delivery'],rows[1]['pace']),('happy','soft','slow'))
        self.assertEqual((rows[2]['emotion'],rows[2]['delivery'],rows[2]['pace']),('happy','soft','normal'))
        self.assertEqual((rows[3]['emotion'],rows[3]['delivery']),('happy','normal'))
        self.assertEqual((rows[4]['emotion'],rows[4]['delivery'],rows[4]['pace']),('neutral','normal','normal'))

    def test_explicit_pause_and_direction_are_not_spoken_or_sent_as_dialogue(self):
        plan=self.plan('[慢速]我在。[停顿300ms][自然][开心]我们一起试试看！',direction='像朋友聊天，重点强调“我们”。')
        self.assertEqual(plan['pause_ms'],300);self.assertEqual(plan['speech_segments'],2)
        self.assertEqual(plan['segments'][1],{'type':'pause','milliseconds':300})
        self.assertEqual(plan['segments'][0]['text'],'我在。')
        self.assertIn('像朋友聊天',plan['segments'][0]['instructions'])
        self.assertIn('像朋友聊天',plan['segments'][2]['instructions'])

    def test_repeated_equivalent_controls_merge_and_warn_when_switch_splits_a_word(self):
        plan=self.plan('[happy]Hello [开心]world!');self.assertEqual(plan['speech_segments'],1)
        self.assertEqual(plan['segments'][0]['text'],'Hello world!')
        self.assertTrue(self.plan('欢[开心]迎')['warnings'])

    def test_budgets_and_incomplete_score_fail_before_any_model_execution(self):
        for text in ['[停顿49ms]你好','你好[pause=1001ms]','你好'+('[停顿1000ms]'*4),
                     ('[开心]好。[悲伤]好。'*5),'[停顿300ms]','你好[开心]']:
            with self.subTest(text=text),self.assertRaises(SpeechError): self.plan(text)
        for direction in ([], '好'*121, '\0'):
            with self.subTest(direction=str(direction)[:20]),self.assertRaises(SpeechError):self.plan('你好',direction=direction)

    def test_pcm_join_keeps_words_length_and_exact_pause_but_removes_boundary_steps(self):
        audio=SpeechAudio(2);samples=array('h',[1000]*2400).tobytes()
        audio.speech(samples,{'type':'speech','text':'甲'},fade=True);audio.pause(300)
        audio.speech(samples,{'type':'speech','text':'乙'},fade=True)
        data=array('h');data.frombytes(audio.pcm)
        self.assertEqual(len(data),12000);self.assertEqual(data[0],0);self.assertEqual(data[2399],0)
        self.assertEqual(data[1200],1000);self.assertEqual(set(data[2400:9600]),{0})
        self.assertEqual(audio.timeline[1]['start_sample'],2400);self.assertEqual(audio.timeline[1]['end_sample'],9600)
        self.assertEqual(audio.timeline[-1]['end_seconds'],.5)
        with self.assertRaises(SpeechError):audio.pause(2000)

    def worker(self,path,fail=False):
        module_path=Path(__file__).resolve().parents[1]/'adapters/speech/qwen/worker.py'
        spec=importlib.util.spec_from_file_location('qwen_expression_worker',module_path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        obj=module.Inference.__new__(module.Inference);obj.cfg={'max_text_chars':180,'max_output_seconds':20,'request_timeout_seconds':60}
        obj.data=path;obj.lock=threading.Lock();obj.count=0;obj.process=SimpleNamespace(stdin=io.BytesIO());calls=[]
        def synth(ident,maximum,timeout):
            calls.append((ident,maximum,timeout))
            if fail and len(calls)==2:raise SpeechError('damaged second segment')
            return array('h',[1000]*2400).tobytes(),.01
        obj.protocol=SimpleNamespace(audio=synth)
        return obj,calls

    def test_worker_same_voice_distinct_protocol_ids_one_wav_and_total_timeline(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);(path/'audio').mkdir();worker,calls=self.worker(path)
            result=worker.synthesize(dict(id='a'*32,text='[轻声][慢速]我在。[停顿300ms][自然][开心]一起走吧。',voice='serena',emotion='neutral',language='zh',direction='自然聊天'))
            requests=[json.loads(row) for row in worker.process.stdin.getvalue().splitlines()]
            self.assertEqual(len(calls),2);self.assertEqual(len({r['id'] for r in requests}),2)
            self.assertTrue(all(r['voice']=='serena' and r['seed']==42 for r in requests))
            self.assertEqual([r['text'] for r in requests],['我在。','一起走吧。'])
            self.assertIn('自然聊天',requests[0]['instructions']);self.assertEqual(result['audio_seconds'],.5)
            self.assertEqual(result['pause_ms'],300);self.assertEqual(result['segments'][-1]['end_sample'],12000)
            with wave.open(str(path/'audio'/('a'*32+'.wav')),'rb') as wav:self.assertEqual(wav.getnframes(),12000)

    def test_failed_later_segment_never_publishes_a_partial_success_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);(path/'audio').mkdir();worker,_=self.worker(path,fail=True)
            with self.assertRaises(SpeechError):worker.synthesize(dict(id='a'*32,text='[轻声]我在。[开心]一起走吧。',voice='serena',emotion='neutral',language='zh'))
            self.assertEqual(list((path/'audio').iterdir()),[]);self.assertEqual(worker.count,0)

    def test_summary_keeps_the_return_to_a_previous_expression(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);(path/'audio').mkdir();worker,_=self.worker(path)
            result=worker.synthesize(dict(id='b'*32,text='[开心]你好！[悲伤]再见。[开心]明天见！',voice='serena',emotion='neutral',language='zh'))
            self.assertEqual(result['expression'],'开心 → 悲伤 → 开心')
