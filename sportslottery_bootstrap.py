"""Launch an installed distribution from a writable, inspectable workspace."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path

RUNTIME_PACKAGES = {'core', 'integrations', 'probability', 'ui', 'pages', 'config', 'scripts'}
RUNTIME_MODULES = {'app.py', 'main.py', 'launcher.py', 'sportslottery_bootstrap.py'}


def materialize_workspace(destination: Path) -> Path:
    from core.persistence import atomic_write_bytes, file_lock
    dist = distribution('sportslottery')
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / 'deployment-manifest.json'
    with file_lock(manifest_path):
        files = {}
        for item in dist.files or []:
            relative = Path(str(item))
            if relative.is_absolute() or '..' in relative.parts:
                continue
            if not (relative.name in RUNTIME_MODULES and len(relative.parts) == 1
                    or relative.parts[0] in RUNTIME_PACKAGES and relative.suffix in {'.py', '.yaml', '.yml', '.ps1', '.bat'}):
                continue
            raw = Path(dist.locate_file(item)).read_bytes()
            target = destination / relative
            # User configuration survives upgrades; shipped defaults remain inspectable.
            if relative.parts[0] == 'config' and target.exists() and relative.suffix != '.py':
                default = destination / 'config/defaults' / relative.name
                atomic_write_bytes(default, raw)
                files[default.relative_to(destination).as_posix()] = hashlib.sha256(raw).hexdigest()
                files[relative.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
            else:
                atomic_write_bytes(target, raw)
                files[relative.as_posix()] = hashlib.sha256(raw).hexdigest()
        if not (destination / 'app.py').is_file() or not (destination / 'config/research_pipeline.yaml').is_file():
            raise RuntimeError('Installed distribution is missing app or configuration resources.')
        requirements = '\n'.join(dist.requires or []) + '\n'
        atomic_write_bytes(destination / 'requirements-lock.txt', requirements.encode('utf-8'))
        atomic_write_bytes(manifest_path, json.dumps({'distribution':dist.metadata['Name'],
                           'version':dist.version, 'shipped_file_hashes':files}, indent=2).encode('utf-8'))
    return destination


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--workspace')
    options, arguments = parser.parse_known_args()
    requested = options.workspace or os.environ.get('SPORTSLOTTERY_WORKSPACE')
    checkout = Path(__file__).resolve().parent
    if requested:
        workspace = materialize_workspace(Path(requested))
    elif (checkout / 'pyproject.toml').is_file() and (checkout / 'app.py').is_file():
        workspace = checkout
    else:
        workspace = materialize_workspace(Path.home() / '.sportslottery/workspace')
    raise SystemExit(subprocess.call([sys.executable, str(workspace / 'main.py'), *arguments], cwd=workspace))


if __name__ == '__main__':
    main()
