"""Durable, resumable multi-file application. Not a filesystem-wide atomic swap."""
from . import policy
from .coding_workflow import APPLY_LOCK
from .project_files import ProjectFiles
from .coding_bundle import validate_bundle
from .coding_build import DEPENDENCY
from .coding_dependencies import IMPORTS as DEPENDENCY_IMPORTS


def apply_bundle(core, report, action):
    value, project = report['coding'], report['output']['project_id']
    originals, candidates = value['originals'], value['candidates']
    validate_bundle(candidates,value['entrypoint'],
                    imports=DEPENDENCY_IMPORTS if value.get('build_recipe') == DEPENDENCY else None)
    if set(candidates) != {r['path'] for r in originals}: raise policy.CoreError('coding_invalid','文件清单不符。')
    files = ProjectFiles(core)
    rows = []
    for row in originals:
        if str(files.root(project)) != row['project_root']: raise policy.CoreError('file_conflict','项目位置变化，停止应用。')
        after = policy.digest((b'\xef\xbb\xbf' if row.get('bom') else b'')+candidates[row['path']].encode())
        rows.append({'path':row['path'],'before':row['digest'],'after':after,'bom':row.get('bom',False),
                     'content':candidates[row['path']] if action=='apply' else row['content']})
    binding = policy.digest(policy.canonical_json({'project':project,'roots':[r['project_root'] for r in originals],
        'files':[{k:r[k] for k in ('path','before','after','bom')} for r in rows]}).encode())
    output_id = report['output']['request_id']
    with APPLY_LOCK:
        with core.ledger.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS coding_batches(output_id TEXT PRIMARY KEY,binding TEXT,action TEXT,state TEXT,completed INTEGER)')
            prior = db.execute('SELECT * FROM coding_batches WHERE output_id=?',(output_id,)).fetchone()
        if prior and prior['binding']!=binding: raise policy.CoreError('file_conflict','恢复记录与候选不匹配。')
        snapshots={r['path']:files.read({'project_id':project,'path':r['path']}) for r in rows}
        target = 'after' if action=='apply' else 'before'
        origin = 'before' if action=='apply' else 'after'
        if all(snapshots[r['path']]['digest']==r[target] for r in rows):
            with core.ledger.transaction() as db:
                db.execute('UPDATE coding_batches SET state=?,action=?,completed=? WHERE output_id=?',('CONFIRMED_OBSERVED',action,len(rows),output_id))
            return {'status':'already_applied' if action=='apply' else 'already_restored','files':len(rows)}
        # Mixed before/after states are resumable only with a journal from this exact report.
        for r in rows:
            digest=snapshots[r['path']]['digest']
            if digest!=r[origin] and not (prior and digest==r[target]):
                raise policy.CoreError('file_conflict','文件组出现外部修改，整组未开始写入：'+r['path'])
        with core.ledger.transaction() as db:
            db.execute('INSERT INTO coding_batches VALUES(?,?,?,?,?) ON CONFLICT(output_id) DO UPDATE SET action=excluded.action,state=excluded.state,completed=0',
                       (output_id,binding,action,'PREPARED',0))
        completed = 0
        try:
            for r in rows:
                current=files.read({'project_id':project,'path':r['path']})
                if current['digest'] != r[target]:
                    if current['digest'] != r[origin]: raise policy.CoreError('file_conflict','应用期间源码被其他编辑改变。')
                    files.write({'project_id':project,'path':r['path'],'content':r['content'],'digest':r[origin],'bom':r['bom']})
                completed += 1
                with core.ledger.transaction() as db: db.execute('UPDATE coding_batches SET state=?,completed=? WHERE output_id=?',('WRITING',completed,output_id))
            if any(files.read({'project_id':project,'path':r['path']})['digest']!=r[target] for r in rows):
                raise policy.CoreError('file_conflict','写入后发现外部修改，需核对文件组。')
            with core.ledger.transaction() as db: db.execute('UPDATE coding_batches SET state=? WHERE output_id=?',('CONFIRMED',output_id))
        except Exception as exc:
            with core.ledger.transaction() as db: db.execute('UPDATE coding_batches SET state=? WHERE output_id=?',('REVIEW_REQUIRED',output_id))
            raise policy.CoreError('coding_partial','整组写入未确认完成。可能已有文件写入；恢复记录已保留，可重试继续或选择恢复，外部修改不会被覆盖。') from exc
        return {'status':'applied' if action=='apply' else 'restored','files':len(rows)}
