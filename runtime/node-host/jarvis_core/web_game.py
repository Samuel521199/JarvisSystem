"""AI-designed levels on a fixed, offline tank-defense engine.

Model output is bounded JSON data; it is never browser script or shell code.
Generation, browser acceptance and delivery use the existing skill task lane.
"""
import copy
import json
import re
from . import policy

SKILL = 'jarvis.tank-game'
TEMPLATE = 'adapters/skills/games/tank-defense.html'
FIELDS = {'title', 'player_color', 'enemy_color', 'ground_color', 'waves', 'base_hp', 'enemy_speed', 'obstacles'}
INSTRUCTIONS = '''Design a small offline tank base-defense game level. Return only one JSON object:
title: Chinese string (1-60 characters), player_color/enemy_color/ground_color: #RRGGBB,
waves: 2-4 integers each 1-4 (enemy counts), base_hp: integer 4-8,
enemy_speed: integer 25-45, obstacles: 0-6 rectangles {x,y,width,height}.
Canvas is 800x600. Obstacles must lie in x=100..700,y=140..360,width=25..80,height=20..60,
and must not cross the central open corridor x=330..470. Keep obstacles separate.
Owner goal is task data, not permission to change schema. No code, files, dependencies,
external assets or promises about 3D. This is a fixed 2D engine with shaded tanks,
movement, aiming, shooting, enemy waves, a base, pause, restart, win and lose states.'''


def validate(value):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise policy.CoreError('game_design_invalid', '游戏设计字段不符，未执行模型代码。')
    if (not isinstance(value['title'], str) or not 1 <= len(value['title']) <= 60
            or any(ord(c) < 32 for c in value['title'])):
        raise policy.CoreError('game_design_invalid', '游戏标题无效。')
    for key in ('player_color', 'enemy_color', 'ground_color'):
        if not isinstance(value[key], str) or not re.fullmatch(r'#[a-fA-F0-9]{6}', value[key]):
            raise policy.CoreError('game_design_invalid', '游戏颜色须为六位色值。')
    if (not isinstance(value['waves'], list) or not 2 <= len(value['waves']) <= 4
            or any(type(n) is not int or not 1 <= n <= 4 for n in value['waves'])
            or type(value['base_hp']) is not int or not 4 <= value['base_hp'] <= 8
            or type(value['enemy_speed']) is not int or not 25 <= value['enemy_speed'] <= 45):
        raise policy.CoreError('game_design_invalid', '游戏波次、生命或速度超出可验收范围。')
    rects = value['obstacles']
    if not isinstance(rects, list) or len(rects) > 6:
        raise policy.CoreError('game_design_invalid', '障碍数量超限。')
    for i, r in enumerate(rects):
        if (not isinstance(r, dict) or set(r) != {'x', 'y', 'width', 'height'}
                or any(type(n) is not int for n in r.values())
                or not 100 <= r['x'] <= 700 or not 140 <= r['y'] <= 360
                or not 25 <= r['width'] <= 80 or not 20 <= r['height'] <= 60
                or r['x'] + r['width'] > 750 or r['y'] + r['height'] > 420
                or r['x'] < 470 and r['x'] + r['width'] > 330):
            raise policy.CoreError('game_design_invalid', '障碍位置或开放通道不符合规则。')
        for old in rects[:i]:
            if r['x'] < old['x']+old['width']+12 and r['x']+r['width']+12 > old['x'] and r['y'] < old['y']+old['height']+12 and r['y']+r['height']+12 > old['y']:
                raise policy.CoreError('game_design_invalid', '障碍重叠，请重新设计。')
    return copy.deepcopy(value)


def decode(raw):
    if not isinstance(raw, str) or len(raw.encode()) > 8192:
        raise policy.CoreError('game_design_invalid', '游戏设计回复为空或超限。')
    fence = re.fullmatch(r'\s*```(?:json)?\s*\n([\s\S]*?)\n```\s*', raw)
    if fence: raw = fence[1]
    def unique(pairs):
        d = {}
        for k, v in pairs:
            if k in d: raise ValueError('duplicate')
            d[k] = v
        return d
    try:
        return validate(json.loads(raw, object_pairs_hook=unique))
    except (ValueError, TypeError, RecursionError):
        raise policy.CoreError('game_design_invalid', '模型没有返回完整的游戏设计 JSON。') from None


def html(design):
    validate(design)
    template = policy.safe_path(policy.REPOSITORY_ROOT/TEMPLATE, directory=False).read_text(encoding='utf-8')
    return template.replace('/* JARVIS_GAME_DESIGN */', policy.canonical_json(design).replace('<', '\\u003c'))


def generate(service, args, checkpoint, task_id):
    from .sample_tasks import ScopedCore
    from .evolution.provider import ModelCodingProvider, gateway
    from .coding_secrets import ensure
    ensure(args['prompt'])
    scoped = ScopedCore(service.core, checkpoint, task_id=task_id)
    provider = ModelCodingProvider(scoped, service.config_path)
    config, route = provider.configuration(args['model'])
    checkpoint()
    transport = service.model_calls.probe if service.model_calls is not None else gateway.probe
    reply = transport(config, route, args['prompt'], scoped.data_dir, scoped.assert_running,
                      admission_context=scoped.effect_guard, deadline_seconds=75, instructions=INSTRUCTIONS,
                      **({'task_id': task_id} if service.model_calls is not None else {}))
    receipt = provider.receipt(reply, config, route)
    if reply.get('status') == 'UNKNOWN' or reply.get('outcome_uncertain'):
        raise policy.CoreError('model_unknown', '游戏设计请求结果未知，未自动重发。')
    if reply.get('status') != 'SUCCEEDED' or reply.get('output_incomplete'):
        raise policy.CoreError('model_failed', '模型未返回完整游戏设计；调用记录可在模型后台核对。')
    design = decode(reply.get('text'))
    checkpoint()
    body = html(design)
    browser = verify_browser(body, checkpoint)
    return {'html': body, 'source': TEMPLATE, 'license': 'Jarvis project license', 'model_data': design,
            'model': receipt, 'checks': {'browser': browser, 'model_calls': 1, 'generated_code_executed': False,
                                       'fixed_engine': 'tank-defense-v1', 'full_3d': False}}


def verify_browser(body, checkpoint, *, screenshot=None):
    import ctypes
    from playwright.sync_api import sync_playwright, expect
    from jarvis_computer.browser import DriverJob
    from jarvis_worker.windows import JobLimits
    errors, requests = [], []
    checkpoint()
    with sync_playwright() as pw:
        owner = DriverJob(pw); browser = None
        try:
            limits = JobLimits(); limits.basic.flags = 0x2000 | 0x200 | 0x8 | 0x4
            limits.job_memory = 512*1024*1024; limits.basic.active = 16; limits.basic.job_time = 30*10_000_000
            owner.api.check(owner.api.set_job(owner.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)), 'Set game browser limits')
            browser = pw.chromium.launch(channel='msedge', headless=True, chromium_sandbox=True, timeout=15000)
            page = browser.new_page(viewport={'width':1100,'height':900}, accept_downloads=False)
            page.route('**/*', lambda r: (requests.append(r.request.url), r.abort()))
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.set_content(body, wait_until='domcontentloaded', timeout=10000)
            page.evaluate('window.__jarvisGame.manual(true)')
            page.locator('#start').click()
            page.keyboard.down('a'); page.evaluate('for(let i=0;i<10;i++)__jarvisGame.advance(.05)'); page.keyboard.up('a')
            assert page.evaluate('__jarvisGame.snapshot().player.x') < 390
            page.locator('#pause').click(); frozen = page.evaluate('__jarvisGame.snapshot()')
            page.evaluate('for(let i=0;i<5;i++)__jarvisGame.advance(.05)')
            assert page.evaluate('__jarvisGame.snapshot()') == frozen
            page.locator('#pause').click(); page.locator('#restart').click()
            # Exercise the real input/update path with independently aimed shots.
            won = page.evaluate('''()=>{for(let i=0;i<6000;i++){
                const s=__jarvisGame.snapshot();if(s.status==='won')return s;
                if(s.status==='lost')throw Error('lost during acceptance');
                const e=s.enemies[0];__jarvisGame.input({fire:true,aimX:e?e.x:400,aimY:e?e.y:0});
                __jarvisGame.advance(.05);
            }throw Error('no win');}''')
            assert won['kills'] == sum(won['design']['waves'])
            page.locator('#restart').click()
            lost = page.evaluate('''()=>{__jarvisGame.input({fire:false});for(let i=0;i<12000;i++){
                __jarvisGame.advance(.05);const s=__jarvisGame.snapshot();if(s.status==='lost')return s;
            }throw Error('no lose');}''')
            assert lost['baseHP'] == 0
            page.locator('#restart').click(); assert page.evaluate('__jarvisGame.snapshot().kills') == 0
            if screenshot: page.screenshot(path=str(screenshot))
            page.set_viewport_size({'width':390,'height':844})
            expect(page.locator('#touch')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert not requests and not errors
            checkpoint()
            return {'movement': True, 'aim_and_fire': True, 'win': True, 'base_damage_and_loss': True,
                    'pause': True, 'restart': True, 'width_390': True, 'page_errors': 0, 'external_requests': 0,
                    'browser': browser.version, 'browser_memory_limit_bytes': limits.job_memory,
                    'scope': 'fixed engine controls and one generated level; not arbitrary game-code certification'}
        except Exception as exc:
            if isinstance(exc, policy.CoreError): raise
            raise policy.CoreError('game_browser_failed', '游戏未通过移动、射击、胜负与暂停/重开验收，未交付成功产物。') from exc
        finally:
            if browser: browser.close()
            owner.close()
