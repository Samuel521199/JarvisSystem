"""Small bounded Markdown-to-speech preparation, preserving supported voice tags."""
import re

from .qwen_speech_contract import validate, expression_plan, TAG, PAUSE, EMOTION_TAGS
from .speech_contract import SpeechError

MAX_RAW=16000
MAX_SPOKEN=1800
MAX_CHUNKS=24
CHUNK_CHARS=80


def prepare(payload):
    if not isinstance(payload,dict) or set(payload)-{'text','voice','emotion','language','direction'}:
        raise SpeechError('朗读只接受正文、音色、默认表达、语言与表达提示。')
    text=payload.get('text')
    if not isinstance(text,str) or not 1<=len(text)<=MAX_RAW:raise SpeechError('请选择 1–16000 字的回复正文朗读。')
    notices=[]
    def omit_code(match):
        if '代码块已略过' not in notices:notices.append('代码块已略过')
        return '\n代码块请查看文字。\n'
    text=re.sub(r'```.*?(?:```|\Z)|~~~.*?(?:~~~|\Z)',omit_code,text,flags=re.S)
    text=re.sub(r'!\[([^\]]*)\]\([^\n)]*\)',r'\1',text)
    text=re.sub(r'\[([^\]\n]+)\]\((?:https?://|/)[^\n)]*\)',r'\1',text)
    text=re.sub(r'https?://[^\s<>]+','',text)
    text=re.sub(r'<[^>\n]{1,200}>','',text)
    text=re.sub(r'(?m)^\s{0,3}(?:#{1,6}\s+|>\s*|[-*+]\s+)','',text)
    text=text.replace('**','').replace('__','').replace('`','')
    parts=[];last=0
    for match in TAG.finditer(text):
        parts.append(re.sub(r'[\[\]【】]','',text[last:match.start()]))
        name=(match[1] or match[2]).strip().lower()
        parts.append(match[0] if name in EMOTION_TAGS or PAUSE.fullmatch(name) else (match[1] or match[2]))
        last=match.end()
    parts.append(re.sub(r'[\[\]【】]','',text[last:]));text=''.join(parts).strip()
    if not text:raise SpeechError('没有可朗读的正文。')
    if len(text)>MAX_SPOKEN:raise SpeechError('可朗读正文最多 1800 字；请在朗读面板缩短后重试，没有自动截断。')
    parsed=validate(dict(payload,action='synthesize',text=text),MAX_SPOKEN);plan=expression_plan(parsed)
    chunks=[];leading=''
    def pauses(ms):
        return ''.join('[停顿'+str(min(1000,n))+'ms]' for n in range(ms,0,-1000))
    for row in plan['segments']:
        if row['type']=='pause':
            if chunks:chunks[-1]['text']+=pauses(row['milliseconds'])
            else:leading+=pauses(row['milliseconds'])
            continue
        prefix='[自然]'+('['+row['emotion']+']' if row['emotion']!='neutral' else '')
        if row['delivery']=='soft':prefix+='[轻声]'
        if row['pace']!='normal':prefix+='['+row['pace']+']'
        remaining=row['text']
        while remaining:
            if len(remaining)<=CHUNK_CHARS:piece=remaining;remaining=''
            else:
                window=remaining[:CHUNK_CHARS];matches=list(re.finditer(r'[。！？!?；;，,\n ]',window))
                end=matches[-1].end() if matches and matches[-1].end()>=20 else CHUNK_CHARS
                piece=remaining[:end];remaining=remaining[end:]
            if piece.strip():
                chunk=dict(text=leading+prefix+piece.strip(),voice=parsed['voice'],emotion='neutral',language=parsed['language'],direction=parsed['direction'])
                validate(dict(chunk,action='synthesize'));chunks.append(chunk);leading=''
    if not chunks or len(chunks)>MAX_CHUNKS:raise SpeechError('朗读分段过多，请缩短正文或减少标签切换。')
    # A trailing pause can enlarge a chunk after its initial construction.
    for chunk in chunks:validate(dict(chunk,action='synthesize'))
    return dict(chunks=chunks,spoken_chars=sum(len(r['text']) for r in plan['segments'] if r['type']=='speech'),
                notices=notices+plan['warnings'],voice=parsed['voice'],language=parsed['language'])
