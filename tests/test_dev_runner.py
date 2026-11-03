from __future__ import annotations

import subprocess

from scripts import dev_runner


def _frontend_fixture(tmp_path):
    frontend = tmp_path / "frontend"
    for relative in (
        "node_modules/typescript/bin/tsc",
        "node_modules/vite/bin/vite.js",
        "scripts/check-theme-contract.mjs",
    ):
        target = frontend / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    node = tmp_path / "node.exe"
    node.write_text("", encoding="utf-8")
    return node


def test_build_frontend_fails_when_node_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dev_runner, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(dev_runner.shutil, "which", lambda _name: None)

    assert dev_runner.build_frontend() is False
    assert "Node.js was not found" in capsys.readouterr().out


def test_build_frontend_fails_on_vite_nonzero_exit(tmp_path, monkeypatch, capsys):
    node = _frontend_fixture(tmp_path)
    monkeypatch.setattr(dev_runner, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(dev_runner.shutil, "which", lambda _name: str(node))
    calls = 0

    def run(command, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            return subprocess.CompletedProcess(command, 2, "", "Vite compilation failed")
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr(dev_runner.subprocess, "run", run)

    assert dev_runner.build_frontend() is False
    output = capsys.readouterr().out
    assert "Vite failed with exit code 2" in output
    assert "Vite compilation failed" in output
    assert calls == 2


def test_dev_runner_does_not_kill_arbitrary_port_owners():
    assert not hasattr(dev_runner, "kill_stale_ports")
