# CI/CD Pipeline

Wingman AI uses a two-stage build pipeline: **Core** is built first (Python via PyInstaller), then bundled as a sidecar into the **Client** (Tauri desktop app, private repo).

## Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `dev-build.yml` | Manual | Build selected platform(s) |
| `release-windows.yml` | Tag push or called by dev-build | Windows build + DigiCert signing |
| `release-macos.yml` | Called by dev-build | macOS build |
| `release-linux.yml` | Called by dev-build | Linux build |

### Build Steps

1. Checkout + install system deps + setup Python 3.11.7
2. PyInstaller builds `WingmanAiCore.spec` → `dist/WingmanAiCore/`
3. Windows: code-signed via DigiCert SSM
4. Upload to R2 staging: `core/{git-sha}/{platform}/`
5. Update `latest-{platform}.txt` pointer

### System Dependencies

- **macOS**: `portaudio`, `sdl2` (brew); `pyobjc-framework-Quartz` (pip)
- **Linux**: `portaudio19-dev`, `libsdl2-dev` (apt)

## Staging Artifacts

Core builds go to the `wingman-staging` R2 bucket (`staging.wingman-ai.com`), keyed by git SHA:

```
core/{sha}/{platform}/
  WingmanAiCore(.exe)     ← main binary
  _internal/              ← PyInstaller dependencies
latest-windows.txt        ← SHA pointer
latest-macos.txt
latest-linux.txt
```

The Client's `download-core` action resolves `latest` (or a specific SHA), downloads the binary + `_internal/`, and bundles it into the Tauri app.

## Version Management

Core version lives in `services/system_manager.py` → `LOCAL_VERSION`. Must stay in sync with the Client's `package.json` and `tauri.conf.json` versions for releases.

## Signing

- **Windows**: DigiCert SSM, signed during Core build
- **macOS/Linux**: Code signing happens in the Client pipeline, not here
