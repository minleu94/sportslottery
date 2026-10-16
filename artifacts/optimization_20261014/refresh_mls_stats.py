from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from integrations.models.espn_poisson_soccer import ESPNPoissonSoccerFallback
m=ESPNPoissonSoccerFallback(cache_dir=str(ROOT/'data/research_pipeline/cache'))
s=m._get_soccer_stats('usa.1')
r={'team_count':len(s),'metadata':m._cache_meta.get('usa.1'),'parse_audit':m._parse_audit}
Path(__file__).with_name('mls_live_preview').joinpath('standings_receipt.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(r,ensure_ascii=False))
