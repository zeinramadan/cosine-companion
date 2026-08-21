# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Cosine Companion."""

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import (
    collect_submodules,
    collect_data_files,
    collect_dynamic_libs,
    collect_all,
)

block_cipher = None

# Get the project root directory
project_root = Path.cwd()
src_dir = project_root / "src"

# Collect all package data and dependencies that need explicit collection
pandas_hidden = collect_submodules('pandas')
numpy_hidden = collect_submodules('numpy')
lxml_hidden = collect_submodules('lxml')
pil_hidden = collect_submodules('PIL')
essentia_hidden = collect_submodules('essentia')
dateutil_hidden = collect_submodules('dateutil')
pytz_hidden = collect_submodules('pytz')
pyarrow_hidden = collect_submodules('pyarrow')

# Collect everything from pandas and numpy (modules, data files, binaries)
pandas_all_datas, pandas_all_bins, pandas_all_hidden = collect_all('pandas')
numpy_all_datas, numpy_all_bins, numpy_all_hidden = collect_all('numpy')

pandas_datas = collect_data_files('pandas')
pil_datas = collect_data_files('PIL')
lxml_datas = collect_data_files('lxml')
pyarrow_datas = collect_data_files('pyarrow')

soundfile_bins = collect_dynamic_libs('soundfile')
essentia_bins = collect_dynamic_libs('essentia')
pyarrow_bins = collect_dynamic_libs('pyarrow')
numpy_bins = collect_dynamic_libs('numpy')
pandas_bins = collect_dynamic_libs('pandas')
a = Analysis(
    [str(src_dir / 'cosine_companion.py')],
    pathex=[str(src_dir)],
    binaries=soundfile_bins + essentia_bins + numpy_bins + pandas_bins + numpy_all_bins + pandas_all_bins + pyarrow_bins,
    datas=[
        # Include LICENSE for distributions (AGPL compliance)
        (str(project_root / 'LICENSE'), '.'),
        # Include models directory if it exists
        (str(project_root / 'models'), 'models'),
        # Include assets directory (icons, etc.)
        (str(project_root / 'assets'), 'assets'),
        # Include the no-build web frontend where web.assets expects it under
        # sys._MEIPASS in a frozen process.
        (str(project_root / 'src' / 'web' / 'static'), 'web/static'),
    ] + pandas_datas + pil_datas + lxml_datas + pandas_all_datas + numpy_all_datas + pyarrow_datas,
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
        'typer',
        'tkinter',
        'PIL',
        'PIL.Image',
        'PIL.ImageTk',
        # Top-level deps to ensure inclusion
        'pandas',
        'numpy',
        'lxml',
        'PIL',
        'essentia',
        'dateutil',
        'pytz',
        'pyarrow',
    ] + pandas_hidden + numpy_hidden + lxml_hidden + pil_hidden + essentia_hidden + dateutil_hidden + pytz_hidden + pyarrow_hidden + pandas_all_hidden + numpy_all_hidden,
    hookspath=[str(project_root / 'hooks')],
    hooksconfig={},
    runtime_hooks=[str(project_root / 'hooks' / 'rthook_macos_env.py')],
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
    [],
    exclude_binaries=True,
    name='Cosine Companion',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx= False if sys.platform == 'darwin' else True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Windowed application
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / 'assets' / 'coco_logo.icns') if sys.platform == 'darwin' else str(project_root / 'assets' / 'coco_logo.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False if sys.platform == 'darwin' else True,
    upx_exclude=[],
    name='Cosine Companion',
)

# macOS app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Cosine Companion.app',
        icon=str(project_root / 'assets' / 'coco_logo.icns'),
        bundle_identifier='com.cosinecompanion.app',
        info_plist={
            'NSPrincipalClass': 'NSApplication',
            'NSAppleScriptEnabled': False,
            'CFBundleName': 'Cosine Companion',
            'CFBundleDisplayName': 'Cosine Companion',
            'CFBundleIconFile': 'coco_logo.icns',
            'CFBundleGetInfoString': "AI-powered music companion for DJs",
            'CFBundleVersion': "1.0.0",
            'CFBundleShortVersionString': "1.0.0",
            'LSMinimumSystemVersion': '10.13',
            'NSHighResolutionCapable': True,
            'NSRequiresAquaSystemAppearance': False,
            'NSAppTransportSecurity': { 'NSAllowsArbitraryLoads': True },
            'NSHumanReadableCopyright': "Copyright © 2024",
        },
    )
