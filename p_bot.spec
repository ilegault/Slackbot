# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for P-Bot (Purchasing Bot)

Build with: pyinstaller p_bot.spec
Output: dist/p_bot/p_bot.exe (runs in background, no console window)
"""
import sys
import os

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=['.', 'src'],
    binaries=[],
    datas=[d for d in [
        ('.env', '.') if os.path.exists('.env') else None,
        ('roster.json', '.') if os.path.exists('roster.json') else None,
    ] if d is not None],
    hiddenimports=[
        'src',
        'src.admin',
        'src.app',
        'src.config',
        'src.epif_parser',
        'src.heartbeat',
        'src.interview',
        'src.log_writer',
        'src.path_validator',
        'src.queue_worker',
        'src.roster',
        'src.validators',
        'slack_bolt',
        'slack_bolt.adapter',
        'slack_bolt.adapter.socket_mode',
        'slack_bolt.adapter.socket_mode.builtin',
        'slack_sdk',
        'slack_sdk.socket_mode',
        'slack_sdk.socket_mode.builtin',
        'slack_sdk.web',
        'pypdf',
        'openpyxl',
        'openpyxl.styles',
        'openpyxl.utils',
        'requests',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='p_bot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Set to False to run without console window
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='p_bot',
)
