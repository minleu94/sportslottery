import hashlib
import json
from datetime import datetime
from pathlib import Path


def test_original_public_response_bodies_match_recorded_evidence():
    folder = Path(__file__).parent / "fixtures" / "playsport_public_sources_20261012"
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    responses = manifest["responses"]
    assert len(responses) == 10  # Two boards, one public killer rank, seven member pages.
    for response in responses:
        body = (folder / response["file"]).read_bytes()
        assert len(body) == response["bytes"]
        assert hashlib.sha256(body).hexdigest() == response["sha256"]
        assert response["response_status"] == 200
        assert response["url"].startswith("https://www.playsport.cc/")
        assert datetime.fromisoformat(response["retrieved_at_utc"]).tzinfo is not None
    public_rows = [pick for response in responses for pick in response.get("parsed_public_picks", [])]
    assert len(public_rows) == 4
    assert all(pick["pick_date"] is None and pick["publication_time_precision"] == "UNKNOWN" for pick in public_rows)
    assert all(pick.get("event_id") is None for pick in public_rows)
