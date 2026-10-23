# CI/CD Pipeline

Wingman AI uses a two-stage build pipeline: **Core** is built first (Python via PyInstaller), then bundled as a sidecar into the **Client** (Tauri desktop app, private repo).

## Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `dev-build.yml` | Manual | Build selected platform(s) |
| `tests.yml` | Pull request, push to main/develop, manual | pytest on Linux (`python -m pytest`) |
| `release-windows.yml` | Called by dev-build.yml and by the Client's release run (never by a tag) | Windows build + DigiCert signing |
| `release-macos.yml` | Called by dev-build | macOS build |
| `release-linux.yml` | Called by dev-build | Linux build |

### Build Steps

1. Checkout + install system deps + setup Python 3.11.7
2. PyInstaller builds `WingmanAiCore.spec` → `dist/WingmanAiCore/`
3. Windows: code-signed via DigiCert SSM
4. Upload to R2 staging: `core/{git-sha}/{platform}/` (platform is `windows-x86_64`, `darwin-aarch64` or `linux-x86_64`)
5. Update `latest-{platform}.txt` pointer

### System Dependencies

- **macOS**: `portaudio`, `sdl2` (brew); `pyobjc-framework-Quartz` (pip)
- **Linux**: `portaudio19-dev`, `libsdl2-dev` (apt). Linux installs the CPU build of torch before `requirements.txt` and runs `scripts/ensure_onnxruntime_gpu.py` after.

## Staging Artifacts

Core builds go to the `wingman-staging` R2 bucket (`staging.wingman-ai.com`), keyed by git SHA:

```
core/{sha}/{windows-x86_64|darwin-aarch64|linux-x86_64}/
  WingmanAiCore(.exe)     ← main binary
  _internal/              ← PyInstaller dependencies
core/latest-windows.txt   ← SHA pointer
core/latest-macos.txt
core/latest-linux.txt
```

The Client's `download-core` action resolves `latest` (or a specific SHA), downloads the binary + `_internal/`, and bundles it into the Tauri app.

## Version Management

Core version lives in `services/system_manager.py` → `LOCAL_VERSION`. Change it with `python scripts/bump_version.py X.Y.Z`. That updates `LOCAL_VERSION` and the Client files and writes the migration skeleton. `python scripts/bump_version.py --check` reports disagreement.

## Signing

- **Windows**: DigiCert SSM, signed during Core build
- **macOS/Linux**: Code signing happens in the Client pipeline, not here
