#!/bin/bash
# ==============================================================================
# Wingman AI Core - AppImage Build Script
# ==============================================================================
# This script:
# 1. Sets up a Python virtual environment
# 2. Installs all dependencies
# 3. Builds the application with PyInstaller
# 4. Creates an AppDir structure
# 5. Packages everything into an AppImage
#
# Requirements:
# - Python 3.11+ with venv
# - pip
# - Basic build tools (gcc, etc.)
# - Internet access for downloading dependencies and appimagetool
#
# Usage:
#   ./build_appimage.sh              # Build with defaults
#   VERSION=2.1.1 ./build_appimage.sh # Build with specific version
# ==============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Version detection
if [ -z "${VERSION:-}" ]; then
    VERSION=$(grep -oE 'LOCAL_VERSION\s*=\s*"[^"]+"' services/system_manager.py | sed 's/.*"\(.*\)"/\1/')
    if [ -z "$VERSION" ]; then
        VERSION="2.1.1"
    fi
fi

APP_NAME="WingmanAiCore"
APPIMAGE_NAME="WingmanAI-${VERSION}-x86_64.AppImage"
BUILD_DIR="${SCRIPT_DIR}/build/appimage"
APPDIR="${BUILD_DIR}/WingmanAI.AppDir"
PYINSTALLER_DIST="${SCRIPT_DIR}/dist/WingmanAiCore"
ICON_SOURCE="${SCRIPT_DIR}/assets/wingman-ai.ico"
ICON_PNG="${SCRIPT_DIR}/assets/wingman-ai.png"

echo "============================================"
echo " Wingman AI Core AppImage Builder"
echo "============================================"
echo " Version: ${VERSION}"
echo " AppImage: ${APPIMAGE_NAME}"
echo " Build dir: ${BUILD_DIR}"
echo "============================================"

# ---------------------------------------------------------------------------
# Step 1: System dependencies check
# ---------------------------------------------------------------------------
echo ""
echo "[1/7] Checking system dependencies..."

MISSING_PKGS=""

# Check for basic build tools
for cmd in python3 pip3 git gcc; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "  WARNING: $cmd not found"
        MISSING_PKGS="$MISSING_PKGS $cmd"
    else
        echo "  [OK] $cmd found"
    fi
done

# Check for audio dependencies (needed at build time)
if ! pkg-config --exists portaudio-2.0 2>/dev/null; then
    echo "  WARNING: portaudio-2.0 development package not found (needed for pyaudio)"
    MISSING_PKGS="$MISSING_PKGS portaudio19-dev"
else
    echo "  [OK] portaudio-2.0 found"
fi

if ! pkg-config --exists sdl2 2>/dev/null; then
    echo "  WARNING: SDL2 development package not found (needed for pygame)"
    MISSING_PKGS="$MISSING_PKGS libsdl2-dev"
else
    echo "  [OK] SDL2 found"
fi

# Check for FUSE (needed to run AppImages)
if ! command -v fusermount &>/dev/null; then
    echo "  NOTE: FUSE not found. AppImage will still be created but may need FUSE to run."
else
    echo "  [OK] FUSE found (for running AppImages)"
fi

if [ -n "$MISSING_PKGS" ]; then
    echo ""
    echo "  Some dependencies are missing. On Debian/Ubuntu, install them with:"
    echo "    sudo apt-get install -y ${MISSING_PKGS}"
    echo ""
    if [ "${SKIP_DEPS_CHECK:-0}" != "1" ]; then
        read -p "  Continue anyway? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Step 2: Convert icon from .ico to .png (if needed)
# ---------------------------------------------------------------------------
echo ""
echo "[2/7] Preparing icon..."

if [ ! -f "$ICON_PNG" ]; then
    if [ -f "$ICON_SOURCE" ]; then
        echo "  Converting wingman-ai.ico to PNG..."
        python3 -c "
from PIL import Image
img = Image.open('${ICON_SOURCE}')
# Get the largest icon from the .ico file
img.save('${ICON_PNG}', format='PNG')
print('  Icon converted to PNG')
" || {
            echo "  WARNING: Could not convert icon with Pillow."
            echo "  Using a simple placeholder icon."
            # Create a minimal PNG (1x1 transparent pixel as fallback)
            python3 -c "
import struct, zlib
def create_png():
    def chunk(chunk_type, data):
        c = chunk_type + data
        crc = struct.pack('>I', zlib.crc32(c) & 0xffffffff)
        return struct.pack('>I', len(data)) + c + crc
    header = b'\x89PNG\r\n\x1a\n'
    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', 256, 256, 8, 2, 0, 0, 0))
    raw = b''
    for y in range(256):
        raw += b'\x00' + b'\x00\x00\xff' * 256  # Blue pixels
    idat = chunk(b'IDAT', zlib.compress(raw))
    iend = chunk(b'IEND', b'')
    with open('${ICON_PNG}', 'wb') as f:
        f.write(header + ihdr + idat + iend)
create_png()
print('  Created placeholder icon')
"
        }
    else
        echo "  WARNING: No icon source found at ${ICON_SOURCE}"
    fi
else
    echo "  [OK] PNG icon already exists"
fi

# ---------------------------------------------------------------------------
# Step 3: Set up Python virtual environment
# ---------------------------------------------------------------------------
echo ""
echo "[3/7] Setting up Python virtual environment..."

if [ ! -d "venv" ]; then
    echo "  Creating venv..."
    python3 -m venv venv
else
    echo "  Using existing venv..."
fi

source venv/bin/activate
echo "  Upgrading pip..."
python -m pip install --upgrade pip --quiet

# ---------------------------------------------------------------------------
# Step 4: Install Python dependencies
# ---------------------------------------------------------------------------
echo ""
echo "[4/7] Installing Python dependencies..."

# Create a temporary requirements file without CUDA version caps
# (PyInstaller needs to resolve these, and Linux handles CUDA differently)
pip install -r requirements.txt 2>&1 | tail -5

echo "  [OK] Dependencies installed"

# ---------------------------------------------------------------------------
# Step 5: Build with PyInstaller
# ---------------------------------------------------------------------------
echo ""
echo "[5/7] Building with PyInstaller..."

# Clean previous build
rm -rf "${PYINSTALLER_DIST}" build/__pycache__ 2>/dev/null || true

pyinstaller WingmanAiCore.spec --noconfirm 2>&1 | tail -20

if [ ! -d "${PYINSTALLER_DIST}" ]; then
    echo "  ERROR: PyInstaller build failed - dist directory not found"
    exit 1
fi

echo "  [OK] PyInstaller build complete"

# ---------------------------------------------------------------------------
# Step 6: Create AppDir structure
# ---------------------------------------------------------------------------
echo ""
echo "[6/7] Creating AppDir structure..."

# Clean and create AppDir
rm -rf "${APPDIR}"
mkdir -p "${APPDIR}"

# Copy all PyInstaller output to AppDir
echo "  Copying application files..."
cp -r "${PYINSTALLER_DIST}"/* "${APPDIR}/"

# Copy AppRun script
cp "${SCRIPT_DIR}/appimage/AppRun" "${APPDIR}/AppRun"
chmod +x "${APPDIR}/AppRun"

# Copy desktop file with version substitution
sed "s/@@VERSION@@/${VERSION}/g" "${SCRIPT_DIR}/appimage/wingman-ai.desktop" > "${APPDIR}/wingman-ai.desktop"

# Copy icon (AppImage looks for .png icon matching the desktop file name)
if [ -f "$ICON_PNG" ]; then
    cp "$ICON_PNG" "${APPDIR}/wingman-ai.png"
elif [ -f "${APPDIR}/assets/wingman-ai.ico" ]; then
    # Try to convert from bundled assets
    python3 -c "
from PIL import Image
img = Image.open('${APPDIR}/assets/wingman-ai.ico')
img.save('${APPDIR}/wingman-ai.png', format='PNG')
" 2>/dev/null || echo "  WARNING: Could not create icon"
fi

# Copy the .desktop file to the root (required by AppImage spec)
cp "${APPDIR}/wingman-ai.desktop" "${APPDIR}/$(basename ${APPDIR}).desktop" 2>/dev/null || true

# Create a symlink for the desktop file at the expected location
ln -sf wingman-ai.desktop "${APPDIR}/$(basename ${APPDIR}).desktop" 2>/dev/null || true

echo "  [OK] AppDir created at ${APPDIR}"

# ---------------------------------------------------------------------------
# Step 7: Package as AppImage
# ---------------------------------------------------------------------------
echo ""
echo "[7/7] Packaging AppImage..."

# Download appimagetool if not present
APPIMAGETOOL="${BUILD_DIR}/appimagetool-x86_64.AppImage"
if [ ! -f "${APPIMAGETOOL}" ]; then
    echo "  Downloading appimagetool..."
    mkdir -p "${BUILD_DIR}"
    wget -q -O "${APPIMAGETOOL}"         "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"         || {
        echo "  WARNING: Could not download appimagetool. Trying alternative URL..."
        wget -q -O "${APPIMAGETOOL}"             "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"             || {
            echo "  ERROR: Could not download appimagetool."
            echo "  The AppDir is ready at: ${APPDIR}"
            echo "  You can manually package it with appimagetool."
            exit 1
        }
    }
    chmod +x "${APPIMAGETOOL}"
fi

# Build the AppImage
echo "  Building AppImage..."
ARCH=x86_64 "${APPIMAGETOOL}" "${APPDIR}" "${SCRIPT_DIR}/${APPIMAGE_NAME}" 2>&1 | tail -10

if [ -f "${SCRIPT_DIR}/${APPIMAGE_NAME}" ]; then
    chmod +x "${SCRIPT_DIR}/${APPIMAGE_NAME}"
    echo ""
    echo "============================================"
    echo " SUCCESS!"
    echo "============================================"
    echo " AppImage created: ${SCRIPT_DIR}/${APPIMAGE_NAME}"
    echo " Size: $(du -h "${SCRIPT_DIR}/${APPIMAGE_NAME}" | cut -f1)"
    echo ""
    echo " To run:"
    echo "   ./${APPIMAGE_NAME}"
    echo ""
    echo " Or install with:"
    echo "   ./${APPIMAGE_NAME} --appimage-extract"
    echo "============================================"
else
    echo ""
    echo "============================================"
    echo " AppImage creation may have failed."
    echo " But the AppDir is ready at: ${APPDIR}"
    echo " You can try running the app directly:"
    echo "   ${APPDIR}/AppRun"
    echo "============================================"
    exit 1
fi
