# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Cosine Companion."""

import sys
import os
from pathlib import Path

block_cipher = None

# Get the project root directory
project_root = Path.cwd()
src_dir = project_root / "src"

# Collect all package data
a = Analysis(
    [str(src_dir / 'cosine_companion.py')],
    pathex=[str(src_dir)],
    binaries=[],
    datas=[
        # Include models directory if it exists
        (str(project_root / 'models'), 'models'),
        # Include assets directory (icons, etc.)
        (str(project_root / 'assets'), 'assets'),
    ],
    hiddenimports=[
        # Core modules
        'core',
        'core.loader',
        'core.persistence',
        'core.index_builder',
        'core.duplicates',
        'core.deleted_tracks',
        # Processing modules
        'processing',
        'processing.pipeline',
        'processing.embeddings',
        'processing.xml_parser',
        # Recommendations modules
        'recommendations',
        'recommendations.engine',
        'recommendations.scoring',
        'recommendations.set_generator',
        'recommendations.models',
        'recommendations.transitions',
        'recommendations.search',
        # UI modules
        'ui',
        'ui.app',
        'ui.onboarding',
        'ui.recommendations_tab',
        'ui.set_creator_tab',
        'ui.library_tab',
        'ui.dialogs',
        'ui.settings_window',
        'ui.reindex_window',
        # Utils modules
        'utils',
        'utils.icon',
        # Config modules
        'config',
        'config.paths',
        'config.defaults',
        # Common dependencies
        'numpy',
        'pandas',
        'lxml',
        'soundfile',
        'essentia',
        'faiss',
        'typer',
        'tkinter',
        'PIL',
        'PIL.Image',
        'PIL.ImageTk',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'scipy',
        'PyQt5',
        'PySide2',
        'pytest',
        'jupyter',
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Cosine Companion',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Windowed application
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/coco_logo.icns' if sys.platform == 'darwin' else ('assets/coco_logo.ico' if Path('assets/coco_logo.ico').exists() else None),
)

# macOS app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='Cosine Companion.app',
        icon='assets/coco_logo.icns',
        bundle_identifier='com.cosinecompanion.app',
        info_plist={
            'NSPrincipalClass': 'NSApplication',
            'NSAppleScriptEnabled': False,
            'CFBundleName': 'Cosine Companion',
            'CFBundleDisplayName': 'Cosine Companion',
            'CFBundleGetInfoString': "AI-powered music companion for DJs",
            'CFBundleVersion': "1.0.0",
            'CFBundleShortVersionString': "1.0.0",
            'NSHumanReadableCopyright': "Copyright © 2024",
        },
    )
