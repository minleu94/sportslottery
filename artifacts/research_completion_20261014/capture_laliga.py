from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import requests

if hasattr(sys.stdout,"reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parents[2]
folder = Path(__file__).resolve().parent / "laliga_sources"
folder.mkdir(parents=True, exist_ok=True)
sources = {
    "scoreboard_20261012": "https://site.api.espn.com/apis/site/v2/sports/soccer/esp.1/scoreboard?dates=20261012",
    "teams": "https://site.api.espn.com/apis/site/v2/sports/soccer/esp.1/teams",
}
manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
for name, url in sources.items():
    response = requests.get(url,timeout=20,headers={"User-Agent":"sportslottery-research/1.0"})
    response.raise_for_status()
    payload = response.json()
    (folder / f"{name}.json").write_bytes(response.content)
    manifest.append({"url":url,"observed_at":datetime.now(timezone.utc).isoformat(),
                     "file":f"{name}.json","sha256":hashlib.sha256(response.content).hexdigest(),
                     "events":len(payload.get("events",[])),"http_status":response.status_code})
(folder / "manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
training = json.loads((root / "data/research_pipeline/cache/models/penaltyblog_dixon_coles/real_matches_esp.1.json").read_text(encoding="utf-8"))
clubs = sorted({row[side] for row in training["matches"] for side in ("home_team","away_team")})
print(json.dumps({"sources":manifest,"football_data_club_names":clubs},ensure_ascii=False,indent=2))
