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

Platform support:
- Windows: Full support with CUDA, code signing
- macOS: No CUDA (Apple Silicon/Metal not supported by ctranslate2)
- Linux: Full support with CUDA, built as AppImage
"""

import os
import sys
import glob as glob_mod
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, collect_all

IS_WINDOWS = sys.platform == 'win32'
IS_MACOS = sys.platform == 'darwin'
IS_LINUX = sys.platform.startswith('linux')

# Determine the venv site-packages path dynamically
if IS_WINDOWS:
    SITE_PACKAGES = 'venv/Lib/site-packages'
else:
    # Dynamically find the Python version in venv
    venv_lib = os.path.join('venv', 'lib')
    if os.path.isdir(venv_lib):
        python_dirs = [d for d in os.listdir(venv_lib) if d.startswith('python')]
    else:
        python_dirs = []
    if python_dirs:
        # Use the first python directory found (e.g., python3.11)
        SITE_PACKAGES = os.path.join(venv_lib, sorted(python_dirs)[-1], 'site-packages')
    else:
        # Fallback for common Python versions
        for ver in ['3.12', '3.11', '3.10', '3.9']:
            candidate = os.path.join(venv_lib, f'python{ver}', 'site-packages')
            if os.path.exists(candidate):
                SITE_PACKAGES = candidate
                break
        else:
            raise RuntimeError("Could not find Python site-packages in venv/lib/")

print(f"Using SITE_PACKAGES: {SITE_PACKAGES}")

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

# Automatically bundle all contents from explicit_deps/ (Windows-only: SimConnect, etc.)
if IS_WINDOWS and os.path.exists('explicit_deps'):
    for item in os.listdir('explicit_deps'):
        item_path = os.path.join('explicit_deps', item)
        if os.path.isdir(item_path):
            datas.append((item_path, item))
            print(f"Adding explicit dependency: {item}")
        elif os.path.isfile(item_path):
            datas.append((item_path, '.'))
            print(f"Adding explicit file: {item}")

# Add python3.dll if it exists (Windows only)
if IS_WINDOWS and os.path.exists('lib/python3.dll'):
    datas.append(('lib/python3.dll', '.'))

# ============================================================================
# BINARY FILES (DLLs / .so files)
# ============================================================================
binaries = []

# Collect NVIDIA CUDA shared libraries for GPU support
# On macOS, skip CUDA entirely (Apple Silicon/Metal not supported by ctranslate2)
if not IS_MACOS:
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
            print(f"Collected shared libs from {pkg}")
        except Exception as e:
            print(f"Warning: Could not collect {pkg} shared libs: {e}")

    # Collect ctranslate2 binaries
    try:
        binaries += collect_dynamic_libs('ctranslate2')
        print("Collected shared libs from ctranslate2")
    except Exception as e:
        print(f"Warning: Could not collect ctranslate2 shared libs: {e}")

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

    # Skills dependencies (cross-platform)
    # api_request / audio_device_changer
    'aiohttp',
    # vision_ai / auto_screenshot (mss is cross-platform)
    'PIL',
    'PIL.Image',
    'mss',
    # spotify
    'spotipy',
    # file_manager
    'pdfminer',
    'pdfminer.six',
    'pdfminer.high_level',
    'cryptography',

    # FasterWhisper / STT dependencies
    'numba',
    'llvmlite',
    'tokenizers',
    'onnxruntime',
    'huggingface_hub',

    # NVIDIA packages (ensure they're included even if shared lib collection fails)
    'nvidia',
    'nvidia.cublas',
    'nvidia.cuda_runtime',
    'nvidia.cudnn',
    'nvidia.cuda_nvrtc',

    # ctranslate2 for FasterWhisper
    'ctranslate2',

    # for pocket-tts
    'engineio.async_drivers.threading',
    'torch',
    'torchaudio',
    'soundfile',
]

# Windows-only hidden imports (skills with platform-specific deps)
if IS_WINDOWS:
    windows_only_imports = [
        # auto_screenshot / control_windows
        'pygetwindow',
        'pyrect',
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
    ]
    hiddenimports += windows_only_imports

# Ensure Pillow (PIL) is fully bundled.
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
try:
    ptts_datas, ptts_binaries, ptts_hidden = collect_all('pocket_tts')
    datas += ptts_datas
    binaries += ptts_binaries
    hiddenimports += ptts_hidden
except Exception as e:
    print(f"Warning: Could not collect pocket_tts: {e}")

# ============================================================================
# ICON HANDLING
# ============================================================================
# Use .ico on Windows, .png on Linux/macOS
if IS_WINDOWS:
    icon_path = 'assets/wingman-ai.ico'
else:
    # Check for PNG icon first (for AppImage / Linux builds)
    png_icon = 'assets/wingman-ai.png'
    ico_icon = 'assets/wingman-ai.ico'
    if os.path.exists(png_icon):
        icon_path = png_icon
    elif os.path.exists(ico_icon):
        icon_path = ico_icon
    else:
        icon_path = None  # No icon available

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

exe_kwargs = dict(
    pyz=pyz,
    a_scripts=a.scripts,
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
)

# icon is optional on Linux (PyInstaller may not support all formats)
if icon_path and os.path.exists(icon_path):
    exe_kwargs['icon'] = icon_path

exe = EXE(**exe_kwargs)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WingmanAiCore',
)
