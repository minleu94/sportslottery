from scripts.check_tracked_file_policy import find_prohibited_paths


def test_local_data_secrets_and_build_outputs_are_rejected():
    assert find_prohibited_paths(
        [
            "data/wallet.sqlite3",
            "backups/ledger.db",
            "config/odds_api.yaml",
            "config/private.local.yaml",
            ".env.production",
            "dist/app.exe",
            "frontend/node_modules/package/index.js",
        ]
    )


def test_public_templates_and_versioned_evidence_remain_allowed():
    assert find_prohibited_paths(
        [
            ".env.example",
            "config/odds_api.example.yaml",
            "config/line_notifier.example.yaml",
            "artifacts/research_completion_20261014/manifest.json",
            "tests/fixtures/market/replay.json",
        ]
    ) == []
