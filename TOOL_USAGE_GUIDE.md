# Tool Usage Guide for Wingman AI Development

This document captures correct tool usage patterns learned during the Wingman AI
Linux/AppImage porting project. These notes are tool-agnostic and can be used as
reference for creating DeepSeek-Tui skills or fixes.

---

## File Writing: Use `code_execution` (Python) Instead of Shell Heredocs

**Problem:** Shell multi-line heredocs (`cat > file << 'EOF'`) are blocked by the
sandbox when submitted through `exec_shell`.

**Solution:** Use `code_execution` with Python to write file contents. Python
`open().write()` is the most reliable method for creating or modifying files.

```python
# Correct: Use code_execution for file writing
import os
content = '''multi-line
file content
here'''
with open('/path/to/file', 'w') as f:
    f.write(content)
```

**Avoid:** Shell heredocs, `tee`, or multi-line `echo` commands in `exec_shell`.

---

## File Editing: Use `sed -i` for Single-Line Changes

For simple single-line replacements, `sed` via `exec_shell` works well:

```bash
# Correct: Simple single-line sed
sed -i 's/old_text/new_text/' path/to/file
sed -i '/pattern/a new line' path/to/file
```

**Note:** The `sed -i` command must be a single logical line. Use `;` to chain
multiple sed commands on one line.

---

## Path Conventions in PyInstaller Spec Files

When writing PyInstaller `.spec` files that need to be cross-platform:

```python
import sys
IS_WINDOWS = sys.platform == 'win32'
IS_MACOS = sys.platform == 'darwin'
IS_LINUX = sys.platform.startswith('linux')

# Dynamic Python version detection (avoid hardcoding 3.11):
if IS_WINDOWS:
    SITE_PACKAGES = 'venv/Lib/site-packages'
else:
    import os
    venv_lib = os.path.join('venv', 'lib')
    python_dirs = [d for d in os.listdir(venv_lib) if d.startswith('python')]
    if python_dirs:
        SITE_PACKAGES = os.path.join(venv_lib, sorted(python_dirs)[-1], 'site-packages')
```

---

## Platform Guards in Python

For cross-platform code, use `sys.platform` checks:

```python
import sys

# sys.platform values:
#   'win32'  -> Windows
#   'darwin' -> macOS
#   'linux'  -> Linux

if sys.platform == 'win32':
    # Windows-only code
    import win32api  # noqa
elif sys.platform == 'darwin':
    # macOS-only code
    pass
else:
    # Linux and others
    pass
```

---

## YAML File Conventions (Wingman Project)

When editing YAML config files, be mindful of:
- Indentation sensitivity (2-space indent)
- Platform fields use `sys.platform` normalized names: `windows`, `darwin`, `linux`
- Skill platform filters: `platforms: [windows]` in `default_config.yaml`

---

## GitHub Actions Workflow Patterns

### Reusable Workflows (workflow_call)
```yaml
on:
  workflow_call:
    inputs:
      runner:
        type: string
        default: 'github'
    outputs:
      version:
        value: ${{ jobs.build.outputs.version }}
```

### Matrix-like Platform Dispatch
```yaml
on:
  workflow_dispatch:
    inputs:
      platform:
        type: choice
        options:
          - windows
          - macos
          - linux
          - appimage
          - all
```

---

## AppImage Creation Pipeline

### Required files:
1. **AppRun** (executable script) - Entry point that sets up environment and execs the app
2. **`.desktop` file** - Freedesktop.org desktop entry with `X-AppImage-Version`
3. **Icon** - PNG format, named to match the icon field in the desktop file
4. **Application binary** - PyInstaller output in the AppDir

### AppRun template:
```bash
#!/bin/bash
SELF=$(readlink -f "$0")
HERE=${SELF%/*}
export PATH="${HERE}:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/lib:${LD_LIBRARY_PATH}"
exec "${HERE}/WingmanAiCore" "$@"
```

### Build steps:
1. Install system deps: `portaudio19-dev`, `libsdl2-dev`, `libfuse2`
2. Set up Python venv with Python 3.11
3. Install Python dependencies (including PyInstaller)
4. Convert `.ico` to `.png` with Pillow
5. Run `pyinstaller WingmanAiCore.spec --noconfirm`
6. Create AppDir with AppRun, .desktop, icon
7. Download and run `appimagetool` to create final `.AppImage`

---

## Common Pitfalls

### 1. exec_shell Multi-Line Commands
**Error:** `BLOCKED: This command was blocked for safety reasons. Reasons: Command contains multiple lines`

**Fix:** Use `code_execution` (Python sandbox) for any operation requiring multiple lines.

### 2. Hardcoded Python Version in Spec Files
**Problem:** `SITE_PACKAGES = 'venv/lib/python3.11/site-packages'` breaks when using Python 3.10 or 3.12.

**Fix:** Dynamically detect the Python version in the venv/lib directory.

### 3. Missing Platform Guards for Skills
**Problem:** Skills like `auto_screenshot` use `pygetwindow` (Windows-only) but don't declare `platforms: [windows]`.

**Fix:** Add the `platforms` field to skill `default_config.yaml` files.

### 4. CUDA Detection Limited to Windows
**Problem:** `if platform.system() != "Windows": return` blocks CUDA on Linux where it works fine.

**Fix:** Change guard to `if platform.system() == "Darwin": return` (only macOS lacks NVIDIA CUDA).

### 5. Grep/Search Tool: Pattern Syntax
When using `grep_files`, the `pattern` parameter is a **regex**, not a plain string.
Use `include` for file type filters: `include=["*.py", "*.yaml"]`.

---

## Summary of Changes Made for Linux/AppImage Support

| File | Change | Reason |
|------|--------|--------|
| `services/system_manager.py` | Changed CUDA guard from `!= "Windows"` to `== "Darwin"` | Enable CUDA on Linux |
| `skills/auto_screenshot/default_config.yaml` | Added `platforms: [windows]` | Uses pygetwindow (Windows-only) |
| `WingmanAiCore.spec` | Dynamic Python version, platform guards for Windows deps | Cross-platform builds |
| `build_appimage.sh` | Created | AppImage build automation |
| `.github/workflows/release-appimage.yml` | Created | CI/CD for AppImage |
| `.github/workflows/dev-build.yml` | Added `appimage` option | Manual AppImage dispatch |
| `requirements.txt` | Updated comments for Linux | Platform documentation |
| `appimage/AppRun` | Created | AppImage entry point |
| `appimage/wingman-ai.desktop` | Created | Freedesktop integration |
