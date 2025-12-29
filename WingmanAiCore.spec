# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for WingmanAI Core

This spec file bundles:
- The WingmanAI Core Python application
- NVIDIA CUDA libraries for GPU-accelerated speech recognition (FasterWhisper/ctranslate2)
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
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

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
    # Azure Speech SDK
    (f'{SITE_PACKAGES}/azure/cognitiveservices/speech', 'azure/cognitiveservices/speech'),

    # Application assets and resources
    ('assets', 'assets'),
    ('services', 'services'),
    ('wingmen', 'wingmen'),
    ('skills', 'skills'),
    ('templates/configs', 'templates/configs'),
    ('templates/migration', 'templates/migration'),
    ('audio_samples', 'audio_samples'),
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

# Collect NVIDIA CUDA DLLs for GPU support
# These are installed via pip from nvidia-* packages
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

# Collect ctranslate2 binaries
try:
    binaries += collect_dynamic_libs('ctranslate2')
    print("Collected DLLs from ctranslate2")
except Exception as e:
    print(f"Warning: Could not collect ctranslate2 DLLs: {e}")

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

    # FasterWhisper / STT dependencies
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

    # ctranslate2 for FasterWhisper
    'ctranslate2',
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
