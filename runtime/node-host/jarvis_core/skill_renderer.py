"""A pinned parameter-only renderer in the existing Windows LPAC/Job boundary."""
import json
import math
from pathlib import Path
import shutil
import sys
import uuid

from . import policy
from .skills import SkillManager, file_digest
from .worker import workspace
from .worker_recovery import StageLease, recover
from jarvis_worker.windows import run, WorkerError, require_acl_volume

ROOT = policy.REPOSITORY_ROOT
FILES = ('render_worker.py', 'lesson.js', 'iso-kit.mjs', 'LICENSE.txt')


def render(parameters, binding, checkpoint):
    node, reason = SkillManager.renderer_profile()
    if not node:
        raise policy.CoreError('skill_runtime_unavailable', reason)
    profile = json.loads((ROOT / 'config/skills/runtime.json').read_text(encoding='utf-8'))
    parent = policy.safe_path(workspace() / 'skill-staging', directory=True, must_exist=False)
    parent.mkdir(parents=True, exist_ok=True)
    require_acl_volume(parent)
    recover(parent)
    binding = {**binding, 'operation': 'skill.render.v1', 'nonce': uuid.uuid4().hex,
               'input_digest': policy.digest(policy.canonical_json(parameters).encode())}
    lease = StageLease(parent, binding)
    try:
        checkpoint()
        stage = lease.stage
        for name in FILES:
            source = ROOT / 'adapters/skills/anatomy' / name
            destination = stage / ('worker.py' if name == 'render_worker.py' else name)
            shutil.copyfile(policy.safe_path(source, directory=False), destination)
            if file_digest(destination) != profile['files'][source.relative_to(ROOT).as_posix()]:
                raise policy.CoreError('skill_content_changed', '绘图执行器复制期间发生变化。')
        (stage / 'input.json').write_text(policy.canonical_json({'binding': binding, 'parameters': parameters}), encoding='utf-8')
        checkpoint()
        result = run(node, stage,
                     profile_name=lease.profile, on_started=lease.started, checkpoint=checkpoint,
                     seconds=20, memory_limit=384 * 1024 * 1024)
        if result['exit_code']:
            raise policy.CoreError('skill_render_failed', '受限绘图执行器未返回有效结果。')
        value = json.loads(result['stdout'])
        if value.get('binding') != binding or set(value) != {'binding', 'model', 'samples', 'html', 'source', 'license'}:
            raise policy.CoreError('skill_output_invalid', '绘图结果与本次任务绑定不符。')
        if not isinstance(value['html'], str) or not 100 < len(value['html'].encode('utf-8')) <= 768 * 1024 or 'NaN' in value['html']:
            raise policy.CoreError('skill_output_invalid', '绘图产物无效或超过大小限制。')
        if value['model']['driver_teeth'] != 12 or value['model']['driven_teeth'] != 12 * parameters['ratio']:
            raise policy.CoreError('skill_output_invalid', '绘图数据模型与用户参数不符。')
        for sample in value['samples']:
            if not math.isclose(sample['driven'], -sample['driver'] / parameters['ratio'], abs_tol=1e-9):
                raise policy.CoreError('skill_output_invalid', '齿轮传动比的独立数值检查未通过。')
        checkpoint()
        return value, result['evidence']
    except WorkerError as exc:
        raise policy.CoreError(exc.code, str(exc)) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise policy.CoreError('skill_output_invalid', '绘图输出格式检查失败。') from exc
    finally:
        lease.close()


def verify_browser(html, checkpoint):
    """Known template only; block every request, use a private browser context."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise policy.CoreError('skill_browser_missing', '缺少本机浏览器检查依赖。') from exc
    sys.path.insert(0, str(ROOT / 'adapters/computer-use'))
    from jarvis_computer.browser import DriverJob
    problems, blocked = [], []
    checkpoint()
    with sync_playwright() as pw:
        job = DriverJob(pw)
        browser = None
        try:
            browser = pw.chromium.launch(channel='msedge', headless=True, chromium_sandbox=True, timeout=15000)
            context = browser.new_context(viewport={'width': 1024, 'height': 800}, accept_downloads=False)
            context.route('**/*', lambda route: (blocked.append(route.request.url), route.abort()))
            page = context.new_page()
            page.on('pageerror', lambda error: problems.append(str(error)[:200]))
            page.on('console', lambda message: problems.append(message.text[:200]) if message.type == 'error' else None)
            page.set_content(html, wait_until='domcontentloaded', timeout=10000)
            checkpoint()
            page.locator('#pause').click(timeout=3000)
            page.locator('#angle').fill('90', timeout=3000)
            page.locator('#angle').dispatch_event('input')
            page.locator('#explode').click(timeout=3000)
            state = page.evaluate('window.__jarvisLesson')
            if not state or not state['apart'] or not state['paused'] or abs(state['driven'] + 90 / state['model']['ratio']) > 1e-9:
                raise policy.CoreError('skill_browser_failed', '机械动画交互与模型检查未通过。')
            if page.locator('svg path').count() < 10 or problems or blocked:
                raise policy.CoreError('skill_browser_failed', '机械动画页面异常或请求了外部资源。')
            page.locator('#pause').click(timeout=3000)
            page.emulate_media(reduced_motion='reduce')
            page.wait_for_function('window.__jarvisLesson.paused === true', timeout=3000)
            page.set_viewport_size({'width': 390, 'height': 800})
            if page.evaluate('document.documentElement.scrollWidth > innerWidth + 1'):
                raise policy.CoreError('skill_browser_failed', '机械动画窄屏存在横向溢出。')
            checkpoint()
            return {'page_errors': 0, 'external_requests': 0, 'parts_rendered': True,
                    'angle_and_ratio_checked': True, 'explode_checked': True,
                    'phone_width': 390, 'reduced_motion_checked': True,
                    'browser_version': browser.version}
        except policy.CoreError:
            raise
        except Exception as exc:
            raise policy.CoreError('skill_browser_failed', '本机浏览器验证失败；没有提交成功产物。') from exc
        finally:
            if browser:
                browser.close()
            job.close()
