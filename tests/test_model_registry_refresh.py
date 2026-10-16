from types import SimpleNamespace

from core.model_registry import ModelRegistry


def test_refresh_reloads_persisted_model_state_without_recreating_financial_components(tmp_path, monkeypatch):
    import core.model_registry as registry_module

    state = tmp_path / "state.txt"
    state.write_text("old", encoding="utf-8")

    class Adapter:
        def __init__(self):
            self.state = state.read_text(encoding="utf-8")

    config = tmp_path / "models.yaml"
    config.write_text("models:\n  example:\n    enabled: true\n    adapter: fixture.Adapter\n", encoding="utf-8")
    monkeypatch.setattr(registry_module.importlib, "import_module", lambda name: SimpleNamespace(Adapter=Adapter))
    registry = ModelRegistry(config)
    assert registry._instances["example"].state == "old"
    state.write_text("new official result state", encoding="utf-8")
    registry.refresh()
    assert registry._instances["example"].state == "new official result state"
