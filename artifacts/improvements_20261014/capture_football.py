from pathlib import Path
import requests,json,hashlib
from datetime import datetime,timezone
root=Path(__file__).resolve().parent/'football_sources';root.mkdir(exist_ok=True)
records=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
for league in ('col.1','crc.1'):
    for kind in ('scoreboard',):
        url=f'https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/{kind}'+('?dates=20261013' if kind=='scoreboard' else '')
        r=requests.get(url,timeout=25); name=f'{league}_{kind}_20261013.json';(root/name).write_bytes(r.content)
        record={'url':url,'file':name,'http_status':r.status_code,'sha256':hashlib.sha256(r.content).hexdigest(),'observed_at_utc':datetime.now(timezone.utc).isoformat()}
        try:record['events']=len(r.json().get('events',[]))
        except ValueError:pass
        records.append(record)
(root/'manifest.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
print(json.dumps(records))
