"""Explicit, isolated CPU evaluation of an emotional TTS candidate; no live routing.

--prepare fetches pinned official source and weights. The probe reuses the project's
existing CPU speech Python for evaluation, without modifying that environment.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
COMPONENT=Path('H:/JarvisData/components/emotivoice')
SOURCE=COMPONENT/'source'
MODELS=Path('H:/JarvisData/models/tts/emotivoice')
OUTPUT=Path('H:/JarvisData/research/emotivoice')
REVISION='59f0f36de4db12825f4705dd4e0780d79dd6bb01'
WEIGHT_REVISION='7e370ae7d146d1c96c8a177e536598d0714a02d9'
BERT_REVISION='8096d1f9a7f7c2d9dbd7974511c4bc4a1755932b'
PROFILE=ROOT/'config/model-profiles/emotivoice-evaluation.json'
HOSTS={'api.github.com','raw.githubusercontent.com','modelscope.cn','www.modelscope.cn','cdn-lfs-cn-1.modelscope.cn','huggingface.co'}


def check_url(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or p.hostname not in HOSTS or p.username or p.password or p.port not in (None,443):
        raise ValueError('Unreviewed evaluation origin')


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        check_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def fetch(url,limit=2_000_000):
    check_url(url)
    req=urllib.request.Request(url,headers={'User-Agent':'Jarvis-emotional-TTS-evaluation','Accept-Encoding':'identity'})
    with urllib.request.build_opener(Redirect()).open(req,timeout=45) as response:
        body=response.read(limit+1)
    if len(body)>limit:raise ValueError('Evaluation metadata exceeds bound')
    return body


def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def download(row):
    path=Path(row['local']);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.stat().st_size!=row['size_bytes'] or digest(path)!=row['sha256']:raise ValueError('Changed evaluation asset: '+path.name)
        return
    if shutil.disk_usage(path.parent).free<row['size_bytes']+2*1024**3:raise ValueError('Insufficient evaluation disk reserve')
    check_url(row['url']);part=path.with_name(path.name+'.partial')
    if part.exists():raise ValueError('Unverified partial exists; inspect before retry')
    h=hashlib.sha256();received=0;tick=time.monotonic()
    try:
        req=urllib.request.Request(row['url'],headers={'User-Agent':'Jarvis-emotional-TTS-evaluation','Accept-Encoding':'identity'})
        with urllib.request.build_opener(Redirect()).open(req,timeout=60) as response,part.open('xb') as out:
            if response.status!=200:raise ValueError('Unexpected download status')
            while block:=response.read(min(1024**2,row['size_bytes']-received+1)):
                received+=len(block)
                if received>row['size_bytes']:raise ValueError('Download exceeds fixed size')
                h.update(block);out.write(block)
                if time.monotonic()-tick>15:print('PROGRESS',path.name,received,'/',row['size_bytes'],flush=True);tick=time.monotonic()
        if received!=row['size_bytes'] or h.hexdigest()!=row['sha256']:raise ValueError('Evaluation asset checksum differs')
        part.rename(path);print('VERIFIED',path.name,received,flush=True)
    finally:part.unlink(missing_ok=True)


def prepare():
    SOURCE.mkdir(parents=True,exist_ok=True);MODELS.mkdir(parents=True,exist_ok=True)
    tree=json.loads(fetch(f'https://api.github.com/repos/netease-youdao/EmotiVoice/git/trees/{REVISION}?recursive=1'))
    roots=('models/','config/joint/','data/youdao/text/','data/inference/','lexicon/','text/','cn2an/')
    singles={'frontend.py','frontend_cn.py','frontend_en.py','inference_am_vocoder_joint.py','LICENSE'}
    records=[]
    def source_file(row):
        name=row['path'];path=SOURCE/name
        if path.exists():raw=path.read_bytes()
        else:raw=fetch(f'https://raw.githubusercontent.com/netease-youdao/EmotiVoice/{REVISION}/{name}',row['size'])
        if len(raw)!=row['size'] or hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=row['sha']:
            raise ValueError('Source differs from pinned Git object: '+name)
        path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():path.write_bytes(raw)
        return dict(path=name,size_bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    selected=[r for r in tree['tree'] if r['type']=='blob' and (r['path'].startswith(roots) or r['path'] in singles)]
    with ThreadPoolExecutor(max_workers=4) as pool:records=list(pool.map(source_file,selected))
    (MODELS/'simbert').mkdir(exist_ok=True)
    assets=[]
    for name in ('config.json','vocab.txt'):
        url=f'https://huggingface.co/WangZeJun/simbert-base-chinese/resolve/{BERT_REVISION}/{name}'
        raw=fetch(url);path=MODELS/'simbert'/name;path.write_bytes(raw)
        assets.append(dict(local=str(path),url=url,size_bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
    for path,size,sha in [('prompt_tts_open_source_joint/ckpt/g_00140000',213240309,'2dcb15a9ed634be57bcd9054cf29f02a9f27557919427c4d6d36e561ebd9d94f'),
                          ('style_encoder/ckpt/checkpoint_163431',1159371361,'d51e39fb36c6ba784d8e3436e5b5057cf1867be24e0bdea42f5e7bf1a863e1b1')]:
        url=f'https://modelscope.cn/api/v1/models/syq163/outputs/repo?Revision={WEIGHT_REVISION}&FilePath='+urllib.parse.quote(path,safe='')
        assets.append(dict(local=str(MODELS/Path(path).name),url=url,size_bytes=size,sha256=sha))
    assert sum(a['size_bytes'] for a in assets)<1_500_000_000
    profile=dict(status='evaluation_only',source_revision=REVISION,weight_revision=WEIGHT_REVISION,bert_revision=BERT_REVISION,
                 source_files=records,assets=assets,production_integrated=False,python='H:/JarvisData/envs/cosyvoice3/Scripts/python.exe',
                 dependency_overlay=str(COMPONENT/'probe-packages'))
    PROFILE.write_text(json.dumps(profile,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(download,assets))
    print('Prepared',len(records),'verified source files; models',sum(a['size_bytes'] for a in assets),flush=True)


def evaluate():
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['CUDA_VISIBLE_DEVICES']=''
    sys.path[:0]=[str(COMPONENT/'probe-packages'),str(SOURCE),str(ROOT/'runtime/node-host')]
    import numpy as np
    import torch
    import soundfile as sf
    from transformers import AutoConfig,AutoModel,AutoTokenizer
    from unittest.mock import patch
    from yacs.config import CfgNode
    from jarvis_core.process_memory import process_memory
    profile=json.loads(PROFILE.read_text(encoding='utf-8'))
    for row in profile['assets']:
        if digest(Path(row['local']))!=row['sha256']:raise ValueError('Model hash differs')
    for row in profile['source_files']:
        if digest(SOURCE/row['path'])!=row['sha256']:raise ValueError('Source hash differs')
    os.chdir(SOURCE);torch.set_num_threads(4);torch.set_num_interop_threads(1)
    spec=importlib.util.spec_from_file_location('emoti_config',SOURCE/'config/joint/config.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    config=module.Config();config.bert_path=str(MODELS/'simbert')
    from models.prompt_tts_modified.simbert import StyleEncoder
    from models.prompt_tts_modified.jets import JETSGenerator
    from frontend_cn import g2p_cn
    baseline_memory=process_memory();started=time.monotonic();phases={}
    # The official style checkpoint includes the complete trained BERT. Construct
    # from config and require all state keys, instead of downloading it twice.
    with patch.object(AutoModel,'from_pretrained',side_effect=lambda *_a,**_k:AutoModel.from_config(AutoConfig.from_pretrained(config.bert_path,local_files_only=True))):
        style=StyleEncoder(config)
    state=torch.load(MODELS/'checkpoint_163431',map_location='cpu',weights_only=True)
    phases['style_checkpoint_loaded']=process_memory()
    style_state={k.removeprefix('module.'):v for k,v in state['model'].items()}
    # Older Transformers persisted this deterministic buffer; newer versions do
    # not. Check its exact value before omitting it; all learned keys stay strict.
    positions=style_state.pop('bert.embeddings.position_ids',None)
    if positions is not None and not torch.equal(positions,torch.arange(positions.shape[-1]).unsqueeze(0)):
        raise ValueError('Unexpected legacy BERT position buffer')
    style.load_state_dict(style_state,strict=True);del state,style_state;style.eval()
    with (SOURCE/'config/joint/config.yaml').open() as f:cfg=CfgNode.load_cfg(f)
    cfg.n_vocab=config.n_symbols;cfg.n_speaker=config.speaker_n_labels
    generator=JETSGenerator(cfg)
    state=torch.load(MODELS/'g_00140000',map_location='cpu',weights_only=True)
    phases['generator_checkpoint_loaded']=process_memory()
    generator.load_state_dict(state['generator'],strict=True);del state;generator.eval()
    tokenizer=AutoTokenizer.from_pretrained(config.bert_path,local_files_only=True)
    token2id={t.strip():i for i,t in enumerate((SOURCE/'data/youdao/text/tokenlist').read_text(encoding='utf-8').splitlines())}
    speaker2id={t.strip():i for i,t in enumerate((SOURCE/'data/youdao/text/speaker2').read_text(encoding='utf-8').splitlines())}
    def embedding(text):
        out=style(**tokenizer([text],return_tensors='pt'));return out['pooled_output']
    OUTPUT.mkdir(parents=True,exist_ok=True)
    report=dict(status='RUNNING',backend='official EmotiVoice CPU; native generator/forward; config-only BERT init followed by strict full state load',
                load_seconds=time.monotonic()-started,baseline_memory=baseline_memory,load_phases=phases,loaded_memory=process_memory(),speaker_count=len(speaker2id),threads=4,cases=[],paid_calls=0,
                scope='Isolated evaluation; no production routing, microphone, cloning or perceptual pass claim')
    # Same sentence across emotions, then a longer sentence: distinguish style
    # effects from different wording and avoid judging by nonempty WAV alone.
    for name,prompt,text in [('neutral','普通','你好，我是贾维斯，很高兴见到你。'),('happy','开心','你好，我是贾维斯，很高兴见到你。'),
                             ('sad','悲伤','你好，我是贾维斯，很高兴见到你。'),('angry','生气','你好，我是贾维斯，很高兴见到你。'),
                             ('soft','温柔','我在，有什么可以帮你？'),('reply','普通','我可以陪你聊天，也可以帮你处理事情。我们先从哪一件开始？'),
                             ('male','普通','你好，我是贾维斯，很高兴见到你。'),
                             ('balanced-neutral','普通','今天下午我们会在这里见面。'),
                             ('balanced-happy','开心','今天下午我们会在这里见面。'),
                             ('balanced-sad','悲伤','今天下午我们会在这里见面。'),
                             ('balanced-angry','生气','今天下午我们会在这里见面。'),
                             ('balanced-happy-en','Happy','今天下午我们会在这里见面。'),
                             ('balanced-sad-en','Sad','今天下午我们会在这里见面。'),
                             ('balanced-angry-en','Angry','今天下午我们会在这里见面。')]:
        speaker='9017' if name=='male' else '8051'
        start=time.monotonic();cpu=time.process_time()
        phones=g2p_cn(text).split();sequence=torch.tensor([[token2id[p] for p in phones]],dtype=torch.long)
        with torch.inference_mode():
            result=generator(inputs_ling=sequence,inputs_style_embedding=embedding(prompt),inputs_content_embedding=embedding(text),
                input_lengths=torch.tensor([len(phones)]),inputs_speaker=torch.tensor([speaker2id[speaker]]),alpha=1.0)
        audio=result['wav_predictions'].detach().numpy().reshape(-1)
        if not np.isfinite(audio).all() or not 0<len(audio)<config.sampling_rate*30:raise ValueError('Invalid generated waveform')
        elapsed=time.monotonic()-start;path=OUTPUT/(name+'.wav');sf.write(path,audio,config.sampling_rate,subtype='PCM_16')
        row=dict(name=name,prompt=prompt,text=text,speaker=speaker,seconds=elapsed,cpu_seconds=time.process_time()-cpu,
                 audio_seconds=len(audio)/config.sampling_rate,rtf=elapsed/(len(audio)/config.sampling_rate),memory=process_memory(),
                 artifact=str(path),sha256=digest(path),sample_rate=config.sampling_rate)
        report['cases'].append(row);print(name,round(elapsed,3),row['audio_seconds'],flush=True)
    report.update(status='SUCCEEDED',peak_memory=process_memory(),
                  asset_sha256={a['local']:a['sha256'] for a in profile['assets']},
                  source_revision=profile['source_revision'],emotion_acceptance='not_verified',naturalness_acceptance='not_verified')
    (ROOT/'evals/reports/emotivoice-candidate-2026-10-18.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Saved evaluation',report['status'],flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--prepare',action='store_true');args=parser.parse_args()
    prepare() if args.prepare else evaluate()
