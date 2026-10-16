from pathlib import Path
import sys,json,hashlib
from datetime import datetime,timezone
from dataclasses import asdict
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from integrations.odds.playsport_taiwan_odds import PlaysportOddsAdapter
from integrations.models.espn_poisson_soccer import ESPNPoissonSoccerFallback
from core.research_pipeline import _leg_payload
out=Path(__file__).with_name('mls_live_preview');out.mkdir(exist_ok=True)
model=ESPNPoissonSoccerFallback(cache_dir=str(ROOT/'data/research_pipeline/cache'))
legs=PlaysportOddsAdapter().get_taiwan_legs(['4'],force_refresh=True)
selected=[l for l in legs if model._resolve_league_code(l.league)=='usa.1' and l.start_time_utc and datetime.fromisoformat(l.start_time_utc.replace('Z','+00:00'))>datetime.now(timezone.utc)]
rows=[]
for leg in selected:
 signal=model.evaluate_leg(leg)
 rows.append({'leg':_leg_payload(leg),'signal':signal.to_dict() if signal else None})
receipt={'observed_at_utc':datetime.now(timezone.utc).isoformat(),'scope':'manual public-source research preview; outside scheduled lead window allowed; not sealed forward observations','football_options':len(legs),'future_mls_options':len(selected),'signals':rows}
(out/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'football_options':len(legs),'future_mls_options':len(selected),'model_signals':sum(r['signal'] is not None for r in rows)},indent=2))
