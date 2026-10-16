from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.scraper import HEADERS

folder = Path(__file__).resolve().parent / "source_dom"
folder.mkdir(parents=True, exist_ok=True)

def capture(aid):
    url = f"https://www.playsport.cc/predict/scale?allianceid={aid}"
    response = requests.get(url, timeout=15, headers=HEADERS)
    path = folder / f"scale_{aid}.html"
    path.write_bytes(response.content)
    soup = BeautifulSoup(response.content, "html.parser")
    table = soup.select_one("table.predictgame-table")
    return {"alliance_id":aid,"url":url,"observed_at":datetime.now(timezone.utc).isoformat(),
            "http_status":response.status_code,"sha256":hashlib.sha256(response.content).hexdigest(),
            "table_found":table is not None,"game_set_row_count":len(soup.select('tr.game-set')),
            "table_text":table.get_text(' ',strip=True)[:1500] if table else None}

with ThreadPoolExecutor(max_workers=3) as pool:
    results = list(pool.map(capture, ("6","7","93")))
(folder / "manifest.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(results, ensure_ascii=False, indent=2))
