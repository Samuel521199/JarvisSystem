"""Trusted broker for the first fixed-operation, isolated Windows Worker.

The host enumerates metadata and commits artifacts. Only a bounded metadata
snapshot is staged; worker replies cannot authorize effects or change inputs.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

from . import policy

WORKER_ROOT = policy.REPOSITORY_ROOT / 'runtime/worker-host'
sys.path.insert(0, str(WORKER_ROOT))
from jarvis_worker.windows import WorkerError, require_acl_volume, run


def workspace():
    if os.name != 'nt':
        raise WorkerError('worker_unavailable', 'No verified Worker backend for this platform')
    return policy.safe_path(Path(os.environ['USERPROFILE']) / '.jarvis', must_exist=False, directory=True)


def verify_bundle():
    """Read and hash on every dispatch; no silent download, update or fallback."""
    profile_path = policy.safe_path(policy.REPOSITORY_ROOT / 'config/worker-profile.json', directory=False)
    try:
        profile = json.loads(profile_path.read_text(encoding='utf-8'))
        if set(profile) != {'schema_version', 'backend', 'runtime_directory', 'manifest_sha256'} or \
                type(profile['schema_version']) is not int or profile['schema_version'] != 1 or profile['backend'] != 'windows-lpac-job':
            raise ValueError('Unsupported profile')
        name = profile['runtime_directory']
        if not isinstance(name, str) or not name.startswith('worker-python-') or Path(name).name != name or '/' in name or '\\' in name:
            raise ValueError('Invalid bundle name')
        bundled = policy.REPOSITORY_ROOT / 'runtime-bundle' / name
        root = policy.safe_path(bundled if bundled.exists() else workspace() / 'worker-runtimes' / name, directory=True)
        require_acl_volume(root)
        manifest_path = policy.safe_path(root / 'bundle.json', directory=False)
        if manifest_path.stat().st_size > 32768:
            raise ValueError('Manifest too large')
        raw = manifest_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != profile['manifest_sha256']:
            raise ValueError('Bundle manifest does not match pinned profile')
        manifest = json.loads(raw)
        files = manifest['files']
        if not isinstance(files, dict) or not 1 <= len(files) <= 100:
            raise ValueError('Invalid file manifest')
        if not {'python.exe', 'python313.dll', 'python313._pth', 'stdlib.zip'} <= set(files):
            raise ValueError('Runtime entry files missing')
        actual = {path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file()}
        if actual != set(files) | {'bundle.json'}:
            raise ValueError('Unexpected or missing runtime files')
        total = 0
        for relative, expected in files.items():
            file = policy.safe_path(root / relative, directory=False)
            if not file.is_relative_to(root):
                raise ValueError('Bundle path outside runtime')
            total += file.stat().st_size
            if total > 64 * 1024 * 1024:
                raise ValueError('Runtime quota exceeded')
            if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
                raise ValueError('Runtime file digest mismatch')
        return root, {'backend': profile['backend'], 'manifest_sha256': profile['manifest_sha256'], 'runtime_bytes': total}
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise WorkerError('worker_bundle_invalid', 'Worker runtime missing or invalid; run prepare_worker and review its pin') from exc


def validate_reply(raw, binding, inventory):
    try:
        if len(raw) > policy.MAX_OUTPUT_BYTES:
            raise ValueError('Reply exceeds quota')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate reply key')
                result[key] = value
            return result
        reply = json.loads(raw, object_pairs_hook=unique)
        # Canonical bytes also distinguish bool/int and forbid a worker from
        # changing metadata, injecting paths or returning an earlier task reply.
        expected = {'binding': binding, 'inventory': inventory}
        if policy.canonical_json(reply) != policy.canonical_json(expected):
            raise ValueError('Reply does not match task/epoch/nonce/input')
        return reply['inventory']
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise WorkerError('worker_protocol_invalid', 'Worker reply failed binding or metadata validation') from exc


def compute_inventory(inventory, *, record, node_id, host_id, epoch, checkpoint):
    try:
        checkpoint()
        runtime, bundle = verify_bundle()
        binding = {'version': 1, 'operation': 'inventory.metadata.v1', 'node_id': node_id,
                   'host_instance_id': host_id, 'security_epoch': epoch,
                   'task_id': record['task']['task_id'], 'action_id': record['action']['action_id'],
                   'attempt_id': record['action']['attempt_id'], 'owner_epoch': record['action']['owner_epoch'],
                   'arguments_digest': record['action']['arguments_digest'],
                   'nonce': uuid.uuid4().hex,
                   'input_sha256': hashlib.sha256(policy.canonical_json(inventory).encode()).hexdigest()}
        payload = policy.canonical_json({'binding': binding, 'inventory': inventory}).encode()
        if len(payload) > policy.MAX_OUTPUT_BYTES:
            raise WorkerError('worker_input_limit', 'Worker input quota exceeded')
        parent = policy.safe_path(workspace() / 'worker-staging', must_exist=False, directory=True)
        parent.mkdir(parents=True, exist_ok=True)
        policy.safe_path(parent, directory=True)
        require_acl_volume(parent)
        from .worker_recovery import StageLease, recover
        recover(parent)
        lease = StageLease(parent, binding)
        stage = lease.stage
        try:
            (stage / 'input.json').write_bytes(payload)
            entry = policy.safe_path(WORKER_ROOT / 'worker.py', directory=False)
            shutil.copyfile(entry, stage / 'worker.py')
            result = run(runtime, stage, checkpoint=checkpoint, profile_name=lease.profile, on_started=lease.started)
            checkpoint()
            if result['exit_code'] != 0:
                raise WorkerError('worker_failed', f"Worker exited without a valid reply ({result['exit_code']})")
            return validate_reply(result['stdout'], binding, inventory), {**bundle, **result['evidence']}
        finally:
            # The launcher kills/waits for the job before this owned directory
            # is removed. Never recursively clean a user-selected directory.
            lease.close()
    except WorkerError as exc:
        raise policy.CoreError(exc.code, str(exc)) from exc
