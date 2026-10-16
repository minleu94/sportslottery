"""Checksummed application backup and restore into a new directory."""
from __future__ import annotations
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import ExitStack, closing
from datetime import datetime, timezone
from pathlib import Path
from core.persistence import atomic_write_bytes, file_lock

CODE_DIRS = ('core','integrations','probability','ui','pages','scripts','config')
ROOT_FILES = ('app.py','main.py','launcher.py','sportslottery_bootstrap.py','pyproject.toml','requirements-lock.txt')


def create_backup(project: Path, output: Path) -> dict:
    from core.research_paths import research_paths
    from core.research_pipeline import ResearchPipeline
    project, output = Path(project).resolve(), Path(output).resolve()
    if any(output.is_relative_to(project / name) for name in (*CODE_DIRS, 'data')):
        raise ValueError('Backup output must be outside the backed-up directories.')
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8]
    staging, destination = output / (name + '.incomplete'), output / name
    staging.mkdir(parents=True, exist_ok=False)
    records = {}
    with ResearchPipeline._Lock(research_paths()['root'] / 'locks/pipeline.lock'):
        sources = [project / f for f in ROOT_FILES if (project / f).exists()]
        for directory in (*CODE_DIRS,'data'):
            sources.extend(p for p in (project / directory).rglob('*') if p.is_file()
                           and '__pycache__' not in p.parts and not p.name.endswith(('.lock','.tmp','-wal','-shm')))
        if not all((project / name).is_file() for name in ('app.py','main.py','config/research_pipeline.yaml')):
            raise ValueError('Workspace is missing required runtime resources.')
        with ExitStack() as frozen:
            # Hold cooperating ledger locks together and reserve every SQLite
            # writer before taking any bytes, rather than independent per-file samples.
            for source in sorted(sources):
                if source.suffix == '.jsonl':
                    frozen.enter_context(file_lock(source))
            databases = [source for source in sorted(sources) if source.suffix in {'.sqlite','.sqlite3','.db'}]
            # Snapshot databases first while all database writers are reserved.
            # Release reservations before copying thousands of public-source
            # files so normal wallet reads/writes are not blocked for minutes.
            with ExitStack() as database_writers:
                for source in databases:
                    reservation = sqlite3.connect(source, timeout=30, isolation_level=None)
                    database_writers.callback(reservation.close)
                    reservation.execute('BEGIN IMMEDIATE')
                    database_writers.callback(reservation.rollback)
                _copy_backup_sources(project, staging, databases, records)
            ledgers = [source for source in sorted(sources) if source.suffix == '.jsonl']
            _copy_backup_sources(project, staging, ledgers, records)
        _copy_backup_sources(project, staging, [source for source in sorted(sources)
                            if source.suffix not in {'.sqlite','.sqlite3','.db','.jsonl'}], records)
    manifest = {'schema':'workspace-backup-v1','created_at_utc':datetime.now(timezone.utc).isoformat(),
                'source_project':str(project),'file_count':len(records),
                'required_files':[name for name in records if name.startswith('data/') or name in ROOT_FILES or name.startswith('config/')],
                'consistency':'pipeline paused, cooperating ledger locks held, SQLite writes reserved', 'files':records}
    manifest_bytes = json.dumps(manifest,indent=2).encode('utf-8')
    atomic_write_bytes(staging / 'manifest.json', manifest_bytes)
    atomic_write_bytes(staging / 'manifest.sha256', hashlib.sha256(manifest_bytes).hexdigest().encode('ascii'))
    os.replace(staging, destination)
    return {'backup':str(destination),'file_count':len(records),'status':'COMPLETE'}


def _copy_backup_sources(project, staging, sources, records):
    for source in sources:
        if source.is_symlink():
            raise ValueError(f'Symlink is not a backup source: {source}')
        relative = source.relative_to(project)
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(source):
            if source.suffix in {'.sqlite','.sqlite3','.db'}:
                with closing(sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True)) as src:
                    with closing(sqlite3.connect(target)) as dst:
                        src.backup(dst)
            else:
                atomic_write_bytes(target, source.read_bytes())
        records[relative.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()

def restore_backup(backup: Path, destination: Path) -> dict:
    backup, destination = Path(backup).resolve(), Path(destination).resolve()
    manifest_raw = (backup / 'manifest.json').read_bytes()
    if hashlib.sha256(manifest_raw).hexdigest() != (backup / 'manifest.sha256').read_text(encoding='ascii').strip():
        raise ValueError('Backup manifest integrity failure.')
    manifest = json.loads(manifest_raw)
    if manifest.get('schema') != 'workspace-backup-v1' or not isinstance(manifest.get('files'),dict):
        raise ValueError('Invalid backup manifest.')
    if destination.exists():
        raise FileExistsError('Restore destination must be a new directory; existing data is never overwritten.')
    files = manifest['files']
    required = {'app.py','main.py','config/research_pipeline.yaml'} | set(manifest.get('required_files',[]))
    actual_inventory = {p.relative_to(backup).as_posix() for p in backup.rglob('*') if p.is_file()
                        and p.relative_to(backup).as_posix() not in {'manifest.json','manifest.sha256'}}
    if not files or not required.issubset(files) or manifest.get('file_count') != len(files) or actual_inventory != set(files):
        raise ValueError('Backup inventory is incomplete or contains unlisted files.')
    checked = []
    for relative, expected in manifest['files'].items():
        entry = Path(relative)
        source = (backup / entry).resolve()
        target = (destination / entry).resolve()
        if entry.is_absolute() or '..' in entry.parts or not source.is_relative_to(backup) or not target.is_relative_to(destination):
            raise ValueError('Backup path escapes its root.')
        if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Backup integrity failure: {relative}')
        checked.append((source, target))
    staging = destination.with_name(destination.name + '.incomplete_' + uuid.uuid4().hex[:8])
    staging.mkdir(parents=True)
    for source, target in checked:
        raw = source.read_bytes()
        relative = target.relative_to(destination)
        if hashlib.sha256(raw).hexdigest() != files[relative.as_posix()]:
            raise ValueError(f'Backup changed during restore: {relative}')
        atomic_write_bytes(staging / relative, raw)
    atomic_write_bytes(staging / 'restore-receipt.json', json.dumps({
        'backup':str(backup),'restored_at_utc':datetime.now(timezone.utc).isoformat(),
        'file_count':len(checked)},indent=2).encode('utf-8'))
    if destination.exists():
        raise FileExistsError('Restore destination was created by another process.')
    os.replace(staging, destination)
    return {'destination':str(destination),'file_count':len(checked),'status':'COMPLETE'}
