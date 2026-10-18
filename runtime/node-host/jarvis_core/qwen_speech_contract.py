"""Bounded expression score for CustomVoice: independent emotion/delivery/pace."""
import re

from .speech_contract import SpeechError

VOICES = {'serena':'Serena · 温柔女声','vivian':'Vivian · 明亮女声','uncle_fu':'Uncle Fu · 成熟男声',
          'dylan':'Dylan · 北京男声','eric':'Eric · 四川男声','ryan':'Ryan · 英语男声',
          'aiden':'Aiden · 阳光男声','ono_anna':'Ono Anna · 日语女声','sohee':'Sohee · 韩语女声'}
EMOTIONS = {'neutral':('自然',''), 'happy':('开心','用非常开心、兴奋的语气说话。'),
            'sad':('悲伤','用非常悲伤、难过的语气说话。'), 'angry':('生气','用非常生气、愤怒的语气说话。'),
            'soft':('温柔轻声','用温柔、轻声、安慰的语气说话。'),
            'slow':('舒缓慢速','用舒缓、缓慢的语速说话。'), 'fast':('轻快快速','用轻快、较快的语速说话。')}
LANGUAGES = {'zh':'中文','en':'English','ja':'日本語','ko':'한국어','de':'Deutsch','fr':'Français',
             'ru':'Русский','pt':'Português','es':'Español','it':'Italiano'}
EMOTION_TAGS = {**{key:key for key in EMOTIONS},
                **{value[0]:key for key,value in EMOTIONS.items()},
                '伤心':'sad','温柔':'soft','轻声':'soft','慢速':'slow','快速':'fast',
                '语速正常':'normal_pace','normal_pace':'normal_pace',
                '正常语气':'normal_delivery','normal_delivery':'normal_delivery'}
TAG = re.compile(r'\[([^\[\]\r\n]{1,30})\]|【([^【】\r\n]{1,30})】')
PAUSE = re.compile(r'(?:停顿\s*|pause\s*=\s*)([0-9]{1,4})\s*ms',re.I)
MAX_SEGMENTS=8
MAX_PAUSE_MS=3000
MAX_DIRECTION_CHARS=120


def expression_plan(parsed):
    """Parse pure text, never load a model. All spans retain the selected voice.

    [自然] resets all three dimensions. Other controls affect their own dimension
    until changed. Explicit pauses do not reset the expression state.
    """
    state={'emotion':'neutral','delivery':'normal','pace':'normal'}
    def control(value):
        if value=='neutral':state.update(emotion='neutral',delivery='normal',pace='normal')
        elif value=='soft':state['delivery']='soft'
        elif value in ('slow','fast'):state['pace']=value
        elif value=='normal_pace':state['pace']='normal'
        elif value=='normal_delivery':state['delivery']='normal'
        else:state['emotion']=value
    control(parsed['emotion'])
    pieces=[];warnings=[];pending=False
    def speech(text):
        nonlocal pending
        if any(c in text for c in '[]【】'):raise SpeechError('语音标记括号不完整；正文方括号请改用圆括号。')
        text=text.strip()
        if not text:return
        instructions=[parsed['direction']] if parsed['direction'] else []
        labels=[]
        for value in (state['emotion'],state['delivery'],state['pace']):
            if value in EMOTIONS and value!='neutral':
                labels.append(EMOTIONS[value][0]);instructions.append(EMOTIONS[value][1])
        expression=' · '.join(labels) or ('表达提示' if parsed['direction'] else '自然')
        row=dict(type='speech',text=text,**state,expression=expression,instructions=' '.join(instructions))
        # Repeated controls do not create needless inference requests.
        if pieces and pieces[-1]['type']=='speech' and all(pieces[-1][k]==row[k] for k in state):
            previous=pieces[-1]['text'];separator=' ' if previous[-1].isascii() and previous[-1].isalnum() and text[0].isascii() and text[0].isalnum() else ''
            pieces[-1]['text']+=separator+text
        else:
            previous=next((r for r in reversed(pieces) if r['type']=='speech'),None)
            if previous and previous['text'][-1] not in '。！？!?；;，,：:…' and not warnings:
                warnings.append('建议在标点后切换表达，避免把词语拆成独立语音。')
            pieces.append(row)
        pending=False
    last=0
    for match in TAG.finditer(parsed['text']):
        speech(parsed['text'][last:match.start()]);name=(match[1] or match[2]).strip().lower();pause=PAUSE.fullmatch(name)
        if pause:
            ms=int(pause[1])
            if not 50<=ms<=1000:raise SpeechError('单次停顿范围为 50–1000ms。')
            if pieces and pieces[-1]['type']=='pause':pieces[-1]['milliseconds']+=ms
            else:pieces.append(dict(type='pause',milliseconds=ms))
        elif name in EMOTION_TAGS:control(EMOTION_TAGS[name]);pending=True
        else:raise SpeechError('未知语音标记；可使用情绪、轻声、语速或 [停顿300ms]。')
        last=match.end()
    speech(parsed['text'][last:])
    count=sum(r['type']=='speech' for r in pieces);pauses=sum(r.get('milliseconds',0) for r in pieces)
    if pending or not count:raise SpeechError('表达标记后还需要填写要说的话。')
    if count>MAX_SEGMENTS:raise SpeechError('每次最多 '+str(MAX_SEGMENTS)+' 段表达，请减少切换。')
    if pauses>MAX_PAUSE_MS:raise SpeechError('每次总停顿最多 3000ms。')
    return dict(segments=pieces,speech_segments=count,pause_ms=pauses,warnings=warnings)


def preview(parsed):
    plan=expression_plan(parsed)
    return dict(plan,segments=[{k:v for k,v in row.items() if k!='instructions'} for row in plan['segments']],
                voice=parsed['voice'],language=parsed['language'],direction=parsed['direction'])


def validate(payload, limit=180):
    if not isinstance(payload,dict) or set(payload)-{'action','text','voice','emotion','language','direction'}:
        raise SpeechError('主力语音只接受文本、音色、默认表达、语言和表达提示。')
    text=payload.get('text')
    if payload.get('action')!='synthesize' or not isinstance(text,str) or not 1<=len(text.strip())<=limit:
        raise SpeechError('请输入 1–'+str(limit)+' 字的短句。')
    result={'text':text.strip()}
    for key,choices,default in [('voice',VOICES,'serena'),('emotion',EMOTIONS,'neutral'),('language',LANGUAGES,'zh')]:
        value=payload.get(key,default)
        if not isinstance(value,str) or value not in choices: raise SpeechError('不支持的语音'+key+'选项。')
        result[key]=value
    direction=payload.get('direction','')
    if not isinstance(direction,str) or len(direction)>MAX_DIRECTION_CHARS or any(ord(c)<32 and c not in '\n\t' for c in direction):
        raise SpeechError('表达提示最多 120 字，只描述语气、重音和起伏。')
    result['direction']=direction.strip()
    expression_plan(result)
    return result
