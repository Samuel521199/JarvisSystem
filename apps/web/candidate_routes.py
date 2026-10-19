"""Memory candidate requests share chat admission, cancellation and accounting."""
import queue
import threading


def post(handler, payload):
    server = handler.server
    action = handler.path.rsplit('/', 1)[-1]
    if action != 'semantic':
        try:
            service = server.semantic_candidates
            method = {'suggest': service.local.suggest, 'confirm': service.local.confirm,
                      'rule-review': service.local.review, 'rule-resolve': service.local.resolve,
                      'semantic-confirm': service.confirm, 'semantic-review': service.review,
                      'semantic-resolve': service.resolve}[action]
            handler._send(200, method(payload))
        except Exception as exc: handler._memory_error(exc)
        return
    try:
        server.semantic_candidates.validate_query(payload)
    except Exception as exc:
        handler._memory_error(exc)
        return
    if not server.slots.acquire(blocking=False):
        handler._error(429, 'chat_busy', '两个模型请求正在处理，请稍后再整理。')
        return
    request_id = payload['request_id']
    try:
        cancel = server.chat_requests.start(request_id)
    except ValueError:
        server.slots.release()
        handler._error(409, 'request_already_used', '此整理请求已经提交；不会重复调用模型，请核对或发起新的整理。')
        return
    with server.chat_requests.lock: server.chat_requests.active += 1
    metric = server.metrics.begin('chat')
    results = queue.Queue(maxsize=1)

    def release(status):
        server.metrics.finish(metric, status)
        server.chat_requests.finish(request_id)
        with server.chat_requests.lock: server.chat_requests.active -= 1
        server.slots.release()

    def work():
        status = 'FAILED'
        try:
            result = server.semantic_candidates.suggest(payload, cancel_event=cancel)
            status = result['result'].get('status', 'UNKNOWN')
            results.put((result, None))
        except Exception as exc: results.put((None, exc))
        finally: release(status)

    try: threading.Thread(target=work, daemon=True, name='jarvis-memory-extraction').start()
    except Exception:
        release('FAILED')
        handler._error(503, 'candidate_unavailable', '整理未启动，请稍后重试。')
        return
    try:
        result, error = results.get(timeout=server.reply_timeout)
        if error: handler._memory_error(error)
        else: handler._send(200, result)
    except queue.Empty:
        cancel.set()  # Retain admission slot until the actual worker exits.
        handler._error(504, 'candidate_timeout', '等待超时，已请求停止；没有保存或自动重试，远端可能已有用量。')
