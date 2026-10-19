"""Compile generated JS into validated frames and a trusted offline scene viewer."""
import base64
import io
import json
import math
import re
import zipfile
from . import policy, coding_js

VIEWER = 'adapters/skills/anatomy/candidate-viewer.html'
SAMPLES = [{'phase':angle} for angle in range(0,360,5)]
SHAPES={'line':{'x','y','x2','y2'},'circle':{'x','y','r'},'rect':{'x','y','width','height'}}


def validate_frames(frames):
    if not isinstance(frames,list) or len(frames)!=len(SAMPLES):raise ValueError('frames')
    topology=None
    for frame in frames:
        if not isinstance(frame,dict) or set(frame)!={'parts'}:raise ValueError('frame')
        parts=frame['parts']
        if not isinstance(parts,list) or not 2<=len(parts)<=24:raise ValueError('parts')
        names=[]
        for p in parts:
            if not isinstance(p,dict) or p.get('kind') not in SHAPES:raise ValueError('shape')
            fields=SHAPES[p['kind']]
            if set(p)!=fields|{'id','kind','color'}:raise ValueError('fields')
            if not isinstance(p['id'],str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9 -]{0,31}',p['id']):raise ValueError('id')
            if not isinstance(p['color'],str) or not re.fullmatch(r'#[a-fA-F0-9]{6}',p['color']):raise ValueError('color')
            if any(type(p[k]) not in (float,int) or not math.isfinite(p[k]) or not 0<=p[k]<=1000 for k in fields):raise ValueError('geometry')
            if any(p[k]<=0 for k in fields & {'r','width','height'}):raise ValueError('empty geometry')
            names.append((p['id'],p['kind']))
        if len({n for n,k in names})!=len(names) or topology is not None and names!=topology:raise ValueError('changing topology')
        topology=names


def html(frames):
    validate_frames(frames)
    text=policy.safe_path(policy.REPOSITORY_ROOT/VIEWER,directory=False).read_text(encoding='utf-8')
    return text.replace('/* JARVIS_FRAMES */',policy.canonical_json(frames).replace('<','\\u003c'))


def build(sources,entry,cases_digest,frames):
    coding_js.validate(sources,entry);validate_frames(frames)
    viewer=html(frames)
    manifest={'kind':'jarvis.javascript-scene','version':1,'recipe':coding_js.RECIPE,'entry':entry,
              'files':{entry:policy.digest(sources[entry].encode())},'cases_digest':cases_digest,
              'engine':coding_js.lock(),'frames_digest':policy.digest(policy.canonical_json(frames).encode()),
              'viewer_digest':policy.digest(viewer.encode()),'samples':SAMPLES,'engineering_verified':False}
    members={entry:sources[entry],'scene.html':viewer,'frames.json':policy.canonical_json(frames),
             'jarvis-build.json':policy.canonical_json(manifest),
             'README.txt':'Open scene.html in a browser, offline. Generated JavaScript was executed only in the Jarvis LPAC worker.\nThe viewer uses validated numeric frames, not generated executable code.\nIllustration and sampled tests only; not engineering certification.\nRebuild with tools/coding_build.py and the pinned optional QuickJS wheel.\n'}
    if entry in {'scene.html','frames.json','jarvis-build.json','README.txt'}:raise ValueError('collision')
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        for name,value in sorted(members.items()):
            info=zipfile.ZipInfo(name,(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,value.encode())
    raw=out.getvalue()
    if len(raw)>65536:raise policy.CoreError('coding_scene_invalid','场景包超过 64 KiB，未交付。')
    return {'manifest':manifest,'sha256':policy.digest(raw),'size_bytes':len(raw),
            'filename':'candidate-scene.zip','base64':base64.b64encode(raw).decode()}


def inspect(raw,expected_digest=None):
    try:
        if not isinstance(raw,bytes) or not 1<=len(raw)<=65536 or expected_digest and policy.digest(raw)!=expected_digest:raise ValueError('digest')
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            infos=z.infolist()
            if len(infos)!=5 or len({i.filename for i in infos})!=5 or sum(i.file_size for i in infos)>1024*1024 or any(i.flag_bits&1 for i in infos):raise ValueError('members')
            manifest=json.loads(z.read('jarvis-build.json'));entry=manifest['entry']
            if set(z.namelist())!={entry,'scene.html','frames.json','jarvis-build.json','README.txt'}:raise ValueError('members')
            sources={entry:z.read(entry).decode()};frames=json.loads(z.read('frames.json'))
            rebuilt=build(sources,entry,manifest['cases_digest'],frames)
            if base64.b64decode(rebuilt['base64'])!=raw:raise ValueError('rebuild')
            return sources,entry,rebuilt
    except (ValueError,TypeError,KeyError,UnicodeError,zipfile.BadZipFile,policy.CoreError) as exc:
        raise policy.CoreError('coding_build_invalid','JavaScript 场景包与固定配方不符；未执行。') from exc


def compile_frames(runner,sources,entry,checkpoint):
    outputs,evidence=runner.run(sources,entry,SAMPLES,checkpoint)
    try:
        frames=[json.loads(s) for s in outputs];validate_frames(frames)
        return frames,evidence
    except (ValueError,TypeError,KeyError) as exc:
        raise policy.CoreError('candidate_invalid','生成的场景帧不是有效、稳定的有限几何数据。') from exc


def verify_browser(viewer,checkpoint):
    import ctypes,time
    from jarvis_worker.windows import JobLimits
    from playwright.sync_api import sync_playwright, expect
    from jarvis_computer.browser import DriverJob
    errors=[];requests=[];started=time.monotonic()
    checkpoint()
    with sync_playwright() as pw:
        owner=DriverJob(pw);browser=None
        try:
            limits=JobLimits();limits.basic.flags=0x2000|0x200|0x8|0x4
            limits.job_memory=512*1024*1024;limits.basic.active=16;limits.basic.job_time=30*10_000_000
            owner.api.check(owner.api.set_job(owner.job,9,ctypes.byref(limits),ctypes.sizeof(limits)),'Set scene browser limits')
            browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True,timeout=15000)
            context=browser.new_context(viewport={'width':1024,'height':800},accept_downloads=False)
            context.route('**/*',lambda route:(requests.append(route.request.url),route.abort()))
            page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            page.set_content(viewer,wait_until='domcontentloaded',timeout=10000)
            page.locator('#pause').click(timeout=3000);page.locator('#phase').fill('18');page.locator('#phase').dispatch_event('input')
            normal=page.locator('#parts').inner_html();page.locator('#explode').click()
            state=page.evaluate('window.__jarvisScene')
            assert state['paused'] and state['frame']==18 and state['apart'] and page.locator('#parts').inner_html()!=normal
            assert page.locator('#parts > g').count()>=2 and not errors and not requests
            page.locator('#pause').click();page.emulate_media(reduced_motion='reduce')
            expect(page.locator('#pause')).to_have_text('播放',timeout=3000)
            page.set_viewport_size({'width':390,'height':800});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
            checkpoint()
            measured=JobLimits();owner.api.check(owner.api.query_job(owner.job,9,ctypes.byref(measured),ctypes.sizeof(measured),None),'Read scene browser limits')
            return {'page_errors':0,'external_requests':0,'play_pause':True,'scrub':True,'explode':True,
                    'reduced_motion':True,'width_390':True,'browser':browser.version,'generated_script_in_browser':False,
                    'peak_job_memory_bytes':measured.peak_job,'memory_limit_bytes':limits.job_memory,
                    'active_process_limit':16,'cpu_seconds_limit':30,'elapsed_seconds':round(time.monotonic()-started,3)}
        except Exception as exc:
            if isinstance(exc,policy.CoreError):raise
            raise policy.CoreError('coding_scene_browser_failed','场景交互未通过浏览器检查，未交付成功产物。') from exc
        finally:
            if browser:browser.close()
            owner.close()
