"""Read-only business-state digests; never emit personal text or credentials."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

STORES=('control.db','safety/control.db','conversations.db','memory.db','persona.db','continuity.db',
        'extensions.db','project-sources.db','project-catalog.db','workspace.db','evolution/evolution.db','network-policy.db')
EXCLUDED={'dialogue_owner':'Host instance ownership is expected to change on restart.',
          'computer_queue_control':'The idle queue is reviewed/resumed during the authorized reload; task rows are compared separately.'}


def fingerprint(directory,*,include_evolution=True):
    result={}
    base=Path(directory).resolve(strict=True)
    for relative in STORES:
        if not include_evolution and relative.startswith('evolution/'):continue
        path=base/relative
        if not path.exists():result[relative]={'present':False};continue
        path=path.resolve(strict=True)
        if not path.is_relative_to(base):raise ValueError('Store leaves expected data root')
        tables={}
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.25)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            for name in names:
                if name in EXCLUDED:continue
                rows=db.execute('SELECT * FROM "'+name.replace('"','""')+'"').fetchall()
                encoded=[json.dumps(row,ensure_ascii=False,separators=(',',':'),default=lambda value:{'bytes':value.hex()}) for row in rows]
                tables[name]={'rows':len(rows),'sha256':hashlib.sha256('\n'.join(sorted(encoded)).encode()).hexdigest()}
            result[relative]={'present':True,'schema':db.execute('PRAGMA user_version').fetchone()[0],'tables':tables}
    return result
