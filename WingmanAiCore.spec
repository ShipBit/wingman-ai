# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for WingmanAI Core

This spec file bundles:
- The WingmanAI Core Python application
- NVIDIA CUDA libraries for GPU-accelerated speech recognition (Parakeet via onnxruntime-gpu)
- All required data files and dependencies

NVIDIA CUDA Libraries:
- nvidia-cublas-cu12: cuBLAS for matrix operations
- nvidia-cudnn-cu12: cuDNN for deep learning primitives
- nvidia-cuda-runtime-cu12: CUDA runtime
- nvidia-cuda-nvrtc-cu12: NVRTC for runtime compilation

These libraries enable GPU acceleration without requiring users to install CUDA separately.
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, collect_all

# Determine the venv site-packages path based on the platform
if sys.platform == 'win32':
    SITE_PACKAGES = 'venv/Lib/site-packages'
else:
    # For local development on macOS/Linux
    SITE_PACKAGES = 'venv/lib/python3.11/site-packages'

# ============================================================================
# DATA FILES
# ============================================================================
# Format: (source, destination_folder)
datas = [
    # The Azure Speech SDK used to be bundled here. It went out with the provider
    # on 2026-09-11 and `azure-cognitiveservices-speech` is no longer in
    # requirements.txt. Leaving the entry would have failed the first CI build:
    # PyInstaller aborts on an --add-data source that does not exist, and CI
    # installs the venv from requirements.txt, so the path is simply not there.
    # It survived locally only because the old package is still in the dev venv.

    # Application assets and resources
    ('assets', 'assets'),
    ('services', 'services'),
    ('wingmen', 'wingmen'),
    ('skills', 'skills'),
    ('templates/configs', 'templates/configs'),
    # Vocabulary presets for the speech correction, one text file per game.
    ('templates/vocabulary', 'templates/vocabulary'),
    ('audio_samples', 'audio_samples'),
    # Silero VAD, runs on the onnxruntime that Parakeet already needs.
    ('audio_models', 'audio_models'),
    ('prompts', 'prompts'),
    ('LICENSE', '.'),
]

# Automatically bundle all contents from explicit_deps/
# Add any dependencies that need manual bundling to explicit_deps/ and they'll be copied to _internal/
if os.path.exists('explicit_deps'):
    for item in os.listdir('explicit_deps'):
        item_path = os.path.join('explicit_deps', item)
        if os.path.isdir(item_path):
            datas.append((item_path, item))
            print(f"Adding explicit dependency: {item}")
        elif os.path.isfile(item_path):
            datas.append((item_path, '.'))
            print(f"Adding explicit file: {item}")

# Add python3.dll if it exists (Windows only)
if os.path.exists('lib/python3.dll'):
    datas.append(('lib/python3.dll', '.'))

# ============================================================================
# BINARY FILES (DLLs)
# ============================================================================
binaries = []

# Collect NVIDIA CUDA DLLs for GPU support (Windows/Linux only — macOS uses Metal)
if sys.platform != 'darwin':
    nvidia_packages = [
        'nvidia.cublas',
        'nvidia.cuda_runtime',
        'nvidia.cudnn',
        'nvidia.nvrtc',
        'nvidia.cuda_nvrtc',
    ]

    for pkg in nvidia_packages:
        try:
            binaries += collect_dynamic_libs(pkg)
            print(f"Collected DLLs from {pkg}")
        except Exception as e:
            print(f"Warning: Could not collect {pkg} DLLs: {e}")

# ============================================================================
# HIDDEN IMPORTS
# ============================================================================
# Modules that PyInstaller cannot detect automatically
hiddenimports = [
    # Standard library modules
    'urllib',
    'urllib.robotparser',
    'sqlite3',
    'json',
    'email.mime.text',
    'email.mime.multipart',

    # Scientific computing
    'scipy._lib.array_api_compat.numpy.fft',
    'scipy.special._cdflib',

    # setuptools vendored dependencies (required by pkg_resources)
    'backports',
    'backports.tarfile',
    'jaraco',
    'jaraco.context',
    'jaraco.text',
    'jaraco.functools',

    # MCP (Model Context Protocol)
    'mcp',
    'mcp.client',
    'mcp.client.stdio',
    'mcp.client.sse',
    'mcp.client.streamable_http',
    'mcp.types',
    'anyio',
    'anyio._backends',
    'anyio._backends._asyncio',
    'httpx_sse',
    'sse_starlette',
    'pydantic_settings',
    'typing_inspection',

    # Google GenAI
    'google.genai',
    'google.genai.types',

    # Hume TTS
    'hume',
    'hume.tts',

    # Pedalboard audio effects
    'pedalboard',

    # Skills dependencies
    # api_request / audio_device_changer
    'aiohttp',
    # vision_ai / auto_screenshot
    'PIL',
    'PIL.Image',
    'mss',
    'pygetwindow',
    'pyrect',
    # spotify
    'spotipy',
    # file_manager
    'pdfminer',
    'pdfminer.six',
    'pdfminer.high_level',
    'cryptography',
    # control_windows
    'clipboard',
    # msfs2020_control
    'SimConnect',
    'SimConnect.SimConnect',
    'SimConnect.Enum',
    'SimConnect.RequestList',
    'SimConnect.dll_handle',
    # ats_telemetry
    'truck_telemetry',
    'pyproj',

    # STT dependencies
    'numba',
    'llvmlite',
    'tokenizers',
    'onnxruntime',
    'huggingface_hub',

    # NVIDIA packages (ensure they're included even if DLL collection fails)
    'nvidia',
    'nvidia.cublas',
    'nvidia.cuda_runtime',
    'nvidia.cudnn',
    'nvidia.cuda_nvrtc',

	# for pocket-tts
	'engineio.async_drivers.threading',
    'torch',
    'torchaudio',
    'soundfile',
]

# Ensure Pillow (PIL) is fully bundled.
# Custom skills may rely on Core-provided Pillow, and Pillow has many submodules and
# compiled extensions (e.g., freetype) that PyInstaller may not find automatically.
try:
    hiddenimports += collect_submodules('PIL')
except Exception as e:
    print(f"Warning: Could not collect PIL submodules: {e}")

try:
    datas += collect_data_files('PIL')
except Exception as e:
    print(f"Warning: Could not collect PIL data files: {e}")

try:
    binaries += collect_dynamic_libs('PIL')
except Exception as e:
    print(f"Warning: Could not collect PIL dynamic libs: {e}")


# Collect all pocket-tts
ptts_datas, ptts_binaries, ptts_hidden = collect_all('pocket_tts')
datas += ptts_datas
binaries += ptts_binaries
hiddenimports += ptts_hidden

# Collect all torchao — required by pocket-tts for int8 quantization.
# Without it, pocket-tts falls back to torch.ao.quantize_dynamic, which
# wraps nn.Linear such that .weight is a bound method instead of a tensor
# and breaks voice cloning (AttributeError on .device in init_state).
try:
    torchao_datas, torchao_binaries, torchao_hidden = collect_all('torchao')
    datas += torchao_datas
    binaries += torchao_binaries
    hiddenimports += torchao_hidden
except Exception as e:
    print(f"Warning: Could not collect torchao: {e}")

# Collect tiktoken encoding data (e.g. cl100k_base BPE ranks)
tiktoken_datas, tiktoken_binaries, tiktoken_hidden = collect_all('tiktoken')
datas += tiktoken_datas
binaries += tiktoken_binaries
hiddenimports += tiktoken_hidden

# Collect tiktoken_ext (namespace package that registers encodings like cl100k_base)
tiktoken_ext_datas, tiktoken_ext_binaries, tiktoken_ext_hidden = collect_all('tiktoken_ext')
datas += tiktoken_ext_datas
binaries += tiktoken_ext_binaries
hiddenimports += tiktoken_ext_hidden
hiddenimports += ['tiktoken_ext.openai_public']

# rapidfuzz picks its compiled module (plain, AVX2) at import time inside a
# try/except. The static analysis usually sees through that, but the wingman
# name match in services/tower.py must not depend on "usually".
rf_datas, rf_binaries, rf_hidden = collect_all('rapidfuzz')
datas += rf_datas
binaries += rf_binaries
hiddenimports += rf_hidden

# Collect all onnx-asr (Parakeet STT)
onnx_asr_datas, onnx_asr_binaries, onnx_asr_hidden = collect_all('onnx_asr')
datas += onnx_asr_datas
binaries += onnx_asr_binaries
hiddenimports += onnx_asr_hidden

# Config migration modules (services/migrations/migration_*.py) are discovered
# from the filesystem and imported via importlib at runtime, so static analysis
# never traces them — or anything only they import. 3.1.5 shipped without the
# stdlib module 'filecmp' (imported only by migration_313_to_314), which broke
# the 3.1.3 -> 3.1.5 upgrade chain in every packaged build while working fine
# from source. Feed every migration module to the analysis so its imports are
# bundled like normal code.
migration_hidden = sorted(
    f"services.migrations.{mig_file[:-3]}"
    for mig_file in os.listdir(os.path.join('services', 'migrations'))
    if mig_file.startswith('migration_') and mig_file.endswith('.py')
)
if len(migration_hidden) < 14:
    raise SystemExit(
        f"Migration module enumeration looks incomplete ({len(migration_hidden)} found, "
        "expected at least 14) — refusing to ship a bundle that cannot migrate user configs."
    )
hiddenimports += migration_hidden

# ============================================================================
# ANALYSIS
# ============================================================================
a = Analysis(
    ['main.py'],
    pathex=[SITE_PACKAGES],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# Verify the analyzed module graph contains every migration module and the one
# dependency that has already bitten us. A module missing here means the frozen
# build would fail to load a migration at runtime and break the upgrade chain.
pure_names = {entry[0] for entry in a.pure}
missing_migration_modules = [
    mod for mod in migration_hidden + ['filecmp'] if mod not in pure_names
]
if missing_migration_modules:
    raise SystemExit(
        "Migration modules/dependencies missing from the analyzed bundle: "
        f"{', '.join(missing_migration_modules)} — refusing to ship a build "
        "that cannot migrate user configs."
    )

# ============================================================================
# PACKAGING
# ============================================================================
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WingmanAiCore',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Keep console for logging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/wingman-ai.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WingmanAiCore',
)
