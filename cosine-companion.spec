# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Cosine Companion."""

import sys
import os
from pathlib import Path

block_cipher = None

# Get the project root directory
project_root = Path.cwd()
src_dir = project_root / "src"

# Collect data files for numpy and other packages
from PyInstaller.utils.hooks import collect_all, collect_submodules

# Use collect_all to get everything from numpy (data, binaries, submodules)
numpy_datas, numpy_binaries, numpy_hiddenimports = collect_all('numpy')
pandas_datas, pandas_binaries, pandas_hiddenimports = collect_all('pandas')

# Collect all package data
a = Analysis(
    [str(src_dir / 'cosine_companion.py')],
    pathex=[str(src_dir)],
    binaries=numpy_binaries + pandas_binaries,
    datas=[
        # Include models directory if it exists
        (str(project_root / 'models'), 'models'),
        # Include assets directory (icons, etc.)
        (str(project_root / 'assets'), 'assets'),
    ] + numpy_datas + pandas_datas,
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
        'ui.playlist_export_tab',
        'ui.track_selector_dialog',
        # Utils modules
        'utils',
        'utils.icon',
        # Config modules
        'config',
        'config.paths',
        'config.defaults',
        # Recommendations - playlist export
        'recommendations.playlist_exporter',
        # Common dependencies
        'numpy',
        'numpy.core',
        'numpy.core._multiarray_umath',
        'numpy.random',
        'numpy.linalg',
        'pandas',
        'pandas.core',
        'pandas.io',
        'lxml',
        'lxml.etree',
        'soundfile',
        'essentia',
        'faiss',
        'typer',
        'click',  # Required by typer
        'tkinter',
        'PIL',
        'PIL.Image',
        'PIL.ImageTk',
    ] + numpy_hiddenimports + pandas_hiddenimports,
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

# Use onedir mode for all platforms for better reliability
# Onedir avoids bootloader extraction issues and gives faster startup
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # Keep binaries separate for onedir
    name='Cosine Companion',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Disable UPX - can cause issues and inconsistent builds
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/coco_logo.ico' if sys.platform == 'win32' and Path('assets/coco_logo.ico').exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,  # Disable UPX - can cause issues and inconsistent builds
    upx_exclude=[],
    name='Cosine Companion',
)

# macOS app bundle (wraps onedir distribution)
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,  # Use COLLECT output for onedir mode
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
