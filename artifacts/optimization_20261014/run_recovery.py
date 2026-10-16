from pathlib import Path
import sys,json,sqlite3,hashlib
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from scripts.workspace_backup import create_backup,restore_backup
out=ROOT/'backups/opt_20261016';out.mkdir(parents=True,exist_ok=True)
created=create_backup(ROOT,out/'backups')
restored=restore_backup(Path(created['backup']),out/'restored_workspace')
checks={}
for p in (out/'restored_workspace/data').rglob('*'):
 if p.is_file() and p.suffix in {'.sqlite','.sqlite3','.db'}:
  with sqlite3.connect(f'file:{p.resolve().as_posix()}?mode=ro',uri=True) as db:checks[str(p.relative_to(out))]=db.execute('PRAGMA integrity_check').fetchall()
receipt={'observed_at_utc':datetime.now(timezone.utc).isoformat(),'backup':created,'restore':restored,'sqlite_integrity':checks,'scope':'real local workspace backup and restore to new directory; original files preserved'}
(out/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(receipt,ensure_ascii=True,indent=2))

