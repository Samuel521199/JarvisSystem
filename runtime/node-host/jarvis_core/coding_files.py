"""Explicit new-file snapshots and reversible writes; never discover project files."""
from . import policy
from .project_files import ProjectFiles, read_text


def snapshot(files, project, path, *, allow_missing=False):
    target = files.target(files.root(project), path)
    if allow_missing and not target.exists():
        return {'path': path, 'content': '', 'digest': None, 'bom': False, 'size_bytes': 0}
    return files.read({'project_id': project, 'path': path})


def create_parent(files, project, path):
    with files.core.effect_guard():
        root = files.root(project, ready=False)
        target = files.target(root, path)
        pending = []
        parent = target.parent
        while parent != root and not parent.exists():
            if not parent.is_relative_to(root): raise policy.CoreError('path_denied', '目录越界。')
            pending.append(parent); parent = parent.parent
        policy.safe_path(parent, directory=True)
        for directory in reversed(pending):
            policy.safe_path(directory, must_exist=False).mkdir()
        return [p.relative_to(root).as_posix() for p in reversed(pending)]


def remove_created(files, project, path, expected):
    """Only undo an exact newly created candidate; no recursive deletion."""
    with files.core.effect_guard():
        root = files.root(project, ready=False)
        target = files.target(root, path)
        if read_text(target)['digest'] != expected:
            raise policy.CoreError('file_conflict', '新增文件已被外部修改，拒绝删除。')
        policy.safe_path(target, directory=False).unlink()
