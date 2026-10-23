# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification file for Taiwan Sports Lottery Standalone Distribution.

Bundles Python 3.11, Streamlit frontend assets, application modules, and all
required dependencies into a standalone directory ready for installer creation.
"""

from __future__ import annotations
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, copy_metadata, collect_submodules

block_cipher = None
PROJECT_ROOT = Path(SPECPATH).resolve()

# 1. Collect Streamlit & third-party data files and metadata
datas = []
datas += collect_data_files('streamlit')
datas += copy_metadata('streamlit')
try:
    datas += collect_data_files('penaltyblog', False)
    datas += copy_metadata('penaltyblog')
except Exception:
    pass

# 2. Add application internal files & directories
datas += [
    ('app.py', '.'),
    ('pages', 'pages'),
    ('config', 'config'),
    ('core', 'core'),
    ('integrations', 'integrations'),
    ('probability', 'probability'),
    ('ui', 'ui'),
]

if (PROJECT_ROOT / 'app_icon.ico').exists():
    datas.append(('app_icon.ico', '.'))

# 3. Collect hidden imports
hiddenimports = [
    'streamlit',
    'streamlit.web.cli',
    'streamlit.runtime.scriptrunner.magic_expressions',
    'altair',
    'pydeck',
    'tornado',
    'tornado.web',
    'tornado.websocket',
    'watchdog',
    'click',
    'yaml',
    'requests',
    'bs4',
    'numpy',
    'scipy',
    'penaltyblog',
]

# Collect submodules for core packages
hiddenimports += collect_submodules('core')
hiddenimports += collect_submodules('ui')
hiddenimports += collect_submodules('integrations')
hiddenimports += collect_submodules('probability')

a = Analysis(
    ['desktop_launcher.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pytest',
        'tests',
        'torch',
        'torchvision',
        'torchaudio',
        'tensorboard',
        'triton',
        'IPython',
        'jupyter',
        'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Sportslottery',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Keeps console open for diagnostic logs and status display
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / 'app_icon.ico') if (PROJECT_ROOT / 'app_icon.ico').exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Sportslottery',
)
