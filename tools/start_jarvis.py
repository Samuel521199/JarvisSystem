"""Double-click launcher: reuse the tray entry and the existing local data."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import webbrowser

ROOT = Path(__file__).resolve().parents[1]


def launch_settings(args):
    env = os.environ.copy()
    local = Path(env.get('LOCALAPPDATA', ''))
    packaged = Path(env.get('USERPROFILE', str(Path.home()))) / (
        'AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local')
    explicit = args.data_dir or env.get('JARVIS_DATA_DIR')
    if explicit:
        data = Path(explicit).expanduser().resolve()
    else:
        candidates = [packaged / 'Jarvis/data', local / 'Jarvis/data']
        data = next((p.resolve() for p in candidates if (p / 'control.db').is_file()), None)
    if data is None or not (data / 'control.db').is_file():
        raise ValueError('未找到已有的 Jarvis 数据。请设置 JARVIS_DATA_DIR 指向原数据目录；启动器不会创建空白实例。')
    # An Explorer launch has a different LOCALAPPDATA from an MSIX Codex launch.
    # Keep the same existing DPAPI store for this child process only.
    if data.parent.name.lower() == 'jarvis' and (data.parent / 'private/credentials.dpapi').is_file():
        env['LOCALAPPDATA'] = str(data.parent.parent)
    port = args.port
    if not 1024 <= port <= 65535:
        raise ValueError('端口必须是 1024—65535 之间的整数。')
    return data, env, port


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', help='已有数据目录；默认复用本机原数据')
    parser.add_argument('--port', type=int, default=os.environ.get('JARVIS_PORT', '18181'))
    parser.add_argument('--no-browser', action='store_true', help='启动后不打开浏览器')
    parser.add_argument('--check', action='store_true', help='只检查路径与端口参数，不启动服务')
    args = parser.parse_args(argv)
    try:
        data, env, port = launch_settings(args)
        url = f'http://127.0.0.1:{port}/'
        if args.check:
            print(json.dumps({'status': 'paths_checked', 'python': sys.executable,
                              'data_dir': str(data), 'url': url,
                              'service_started': False}, ensure_ascii=False))
            return 0
        print(f'正在启动 Jarvis…\n数据目录：{data}\n工作台：{url}', flush=True)
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'apps/tray/launch.py'),
                                 '--data-dir', str(data), '--port', str(port)],
                                cwd=ROOT, env=env, check=False)
        if result.returncode:
            print(f'启动失败。日志位置：{data / "diagnostics/tray/server.log"}', file=sys.stderr)
            return result.returncode
        if not args.no_browser:
            if not webbrowser.open(url, new=2):
                print(f'Jarvis 已运行，请手动打开：{url}')
        return 0
    except (OSError, ValueError) as exc:
        print(f'无法启动 Jarvis：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
