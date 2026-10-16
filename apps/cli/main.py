"""Local core and text-chat CLI. Model text never executes tools or code."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Read-only diagnostics should not create Python cache files in the checkout.
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime" / "node-host"))

from jarvis_core.service import CoreError, CoreService


def parser():
    result = argparse.ArgumentParser(description="Jarvis local core and bounded text chat")
    result.add_argument("--data-dir", help="Control database and artifacts directory")
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("init", "status", "inventory", "cancel", "models", "chat", "preflight", "upgrade-control", "recover-workers", "recover-browsers"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir", default=argparse.SUPPRESS, help="Control database and artifacts directory")
        if name == "preflight":
            command.add_argument("--json", action="store_true", help="Emit the versioned diagnostic report")
        elif name == "init":
            command.add_argument("--allowed-root", help="Bind a sample input root at first initialization only")
        elif name == "status":
            command.add_argument("--task-id")
        elif name == "inventory":
            command.add_argument("--relative-path", default=".")
            command.add_argument("--request-id", help="Stable idempotency key; reuse only with the same arguments")
            command.add_argument("--max-files", type=int)
            command.add_argument("--max-bytes", type=int)
            command.add_argument("--prepare-only", action="store_true", help="Persist READY/PREPARED without executing")
        elif name == "cancel":
            command.add_argument("task_id")
        elif name in {"models", "chat"}:
            command.add_argument("--config", type=Path, help="Model routing configuration")
            if name == "chat":
                command.add_argument("--provider", default="auto")
                command.add_argument("--message", help="Send one message; omit to start an in-memory conversation")
                command.add_argument("--model", help="Registered model ID for the explicitly selected provider")
    return result


def show_models(chat):
    catalog = chat.models()
    for item in catalog["providers"]:
        default = "（默认）" if item["is_default"] else ""
        count = item["historical_requests"]
        print(f"{item['provider']}{default}: {item['model']}；历史请求数：{count if count is not None else '未知'}")
    print("auto 路由顺序：" + " → ".join(catalog["fallback_order"]))
    for item in catalog.get("models", []):
        print(f"  {item['provider']} / {item['model']} [{item['tier']}]；最近调用：{item['last_probe_status']}")
    print("历史请求数不限制累计使用；供应商余额未查询。")


def interactive_chat(chat, provider, model=None):
    from jarvis_core.chat import bounded_history
    history = []
    print("Jarvis 文本对话。历史仅保存在本次进程内，最多 20 条 / 32768 字节。")
    print("命令：/model <提供商或 auto> [模型ID]、/models、/clear、/exit。模型文本不会执行工具。")
    while True:
        try:
            message = input(f"你 [{provider}{' / '+model if model else ''}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已结束本次会话。")
            return 0
        if not message:
            continue
        if message == "/exit":
            return 0
        if message == "/clear":
            history = []
            print("已清空内存中的会话历史。")
            continue
        if message == "/models":
            show_models(chat)
            continue
        if message == "/model" or message.startswith("/model "):
            selected = message.partition(" ")[2].strip()
            if not selected:
                print(f"当前选择：{provider}")
                continue
            available = {item["provider"] for item in chat.models()["providers"]} | {"auto"}
            parts = selected.split()
            selected = parts[0]
            selected_model = parts[1] if len(parts) == 2 else None
            registered = {(item['provider'], item['model']) for item in chat.models().get('models', [])}
            if selected not in available or len(parts) > 2 or (selected_model and (selected, selected_model) not in registered):
                print("未知提供商；使用 /models 查看可选模型。")
                continue
            provider = selected
            model = selected_model
            print(f"已选择 {provider} / {model or '默认模型'}；后续请求携带当前有限历史，可用 /clear 清空。")
            continue
        if message.startswith("/"):
            print("未知命令；可用 /model、/models、/clear、/exit。")
            continue
        result = chat.reply(message, provider=provider, history=history, model=model)
        for item in result.get("notice", []):
            print("提示：" + item)
        attempted = [f"{item.get('provider')}/{item.get('model')}:{item.get('status')}" for item in result.get("attempts", [])]
        if attempted:
            print("本轮尝试：" + " → ".join(attempted))
        if result["status"] == "SUCCEEDED":
            print(f"Jarvis [{result['provider']} / {result['model']}]：{result['text']}")
            usage = result.get("usage")
            print("供应商用量：" + (json.dumps(usage, ensure_ascii=False) if usage else "本次未提供"))
            history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": result["text"]}])
            history, info = bounded_history(history)
            if info["truncated"]:
                print(f"提示：内存历史已移除 {info['dropped_messages']} 条旧消息。")
        else:
            print("未取得可用回复：" + result.get("user_message", "请查看模型和核心状态。"))
            if result.get("error_category") == "core_stopped":
                return 2


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "preflight":
        from jarvis_core.preflight import collect_report, format_report
        report = collect_report(args.data_dir)
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else format_report(report))
        return 1 if report["readiness"] == "blocked" else 2
    service = CoreService(args.data_dir)
    try:
        if args.command == 'recover-browsers':
            from jarvis_core.browser_recovery import recover
            result=recover()
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 1 if result['retained'] else 0
        if args.command == 'recover-workers':
            from jarvis_core.worker import workspace
            from jarvis_core.worker_recovery import recover
            parent=workspace()/'worker-staging'
            result=recover(parent) if parent.exists() else {'removed':[], 'active':[], 'retained':[]}
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 1 if result['retained'] else 0
        if args.command in {"chat", "models"}:
            # Keep init/status/inventory usable without importing the HTTP adapter.
            from jarvis_core.chat import ChatService
            chat = ChatService(service, args.config)
            if args.command == "models":
                response = chat.models()
            elif args.message is None:
                return interactive_chat(chat, args.provider, args.model)
            else:
                response = chat.reply(args.message, provider=args.provider, model=args.model)
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0 if args.command == "models" or response.get("status") == "SUCCEEDED" else 1
        if args.command == "init":
            response = service.initialize(args.allowed_root)
        elif args.command == "upgrade-control":
            control = service.ledger.upgrade_control()
            response = {"upgraded": True, "stopped": control["stopped"], "security_epoch": control["security_epoch"]}
        elif args.command == "status":
            response = service.status(args.task_id)
        elif args.command == "inventory":
            response = service.inventory(relative_path=args.relative_path, request_id=args.request_id,
                                         max_files=args.max_files, max_bytes=args.max_bytes, prepare_only=args.prepare_only)
        elif args.command == "cancel":
            response = service.cancel(args.task_id)
        else:
            raise CoreError("invalid_command", "Unsupported command")
        print(json.dumps(response, ensure_ascii=False, indent=2))
        state = response.get("task", {}).get("status")
        return 3 if state in {"FAILED", "UNKNOWN", "CANCELLED", "CANCELLING"} else 0
    except (CoreError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": getattr(exc, "code", "control_unavailable"), "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except RuntimeError:
        print(json.dumps({"ok": False, "error": "chat_unavailable", "message": "聊天配置或模型入口不可用。"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
