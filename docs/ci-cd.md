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
4. Upload to R2 staging: `core/{channel}/{git-sha}/{platform}/` (platform is `windows-x86_64`, `darwin-aarch64` or `linux-x86_64`)
5. Update the `core/{channel}/latest-{os}.txt` pointer and prune old builds of the same channel

### System Dependencies

- **macOS**: `portaudio`, `sdl2` (brew); `pyobjc-framework-Quartz` (pip)
- **Linux**: `portaudio19-dev`, `libsdl2-dev` (apt). Linux installs the CPU build of torch before `requirements.txt` and runs `scripts/check_onnxruntime_gpu.py` after.

## Channels

Every build is for one update channel, `unstable` or `production`, chosen when it is started (`channel` in Dev Build). Before PyInstaller runs, `scripts/set_build_channel.py` writes it into `services/build_channel.py`; a source checkout says `unstable`. `services/features.py` decides by it which features the build offers, so the same commit can ship a feature on unstable and leave it out of production. Where a feature is not released, its code ships but does not run, and the client shows nothing of it.

The usual ways to release:

- **A test version:** build develop for `unstable`.
- **That version for everyone:** build the same tag for `production`. Same commit, same version; only the features differ.
- **With last fixes:** bump the version, then build it for `production` (and for `unstable` too, so testers get the fixes).
- **A feature stays on unstable longer:** it stays in `RELEASED_ON` with `("unstable",)` only. Remove it there to release it.

The two channels never touch each other's files, so their builds run in any order or at the same time.

## Staging Artifacts

Core builds go to the `wingman-staging` R2 bucket (`staging.wingman-ai.com`), keyed by channel and git SHA (`.github/scripts/stage-core.sh`):

```
core/{channel}/{sha}/{windows-x86_64|darwin-aarch64|linux-x86_64}/
  WingmanAiCore(.exe)     ← main binary
  _internal/              ← PyInstaller dependencies
core/{channel}/latest-windows.txt   ← SHA pointers per channel
core/{channel}/latest-macos.txt
core/{channel}/latest-linux.txt
```

Each channel keeps its newest five builds and the ones its pointers name; older ones of that channel are deleted after every upload. The Client's `download-core` action takes the channel and `latest` or a specific SHA. For a release, pass the SHA of the tag.

## Version Management

Core version lives in `services/system_manager.py` → `LOCAL_VERSION`. Change it with `python scripts/bump_version.py X.Y.Z`. That updates `LOCAL_VERSION` and the Client files and writes the migration skeleton. `python scripts/bump_version.py --check` reports disagreement.

## Signing

- **Windows**: DigiCert SSM, signed during Core build
- **macOS/Linux**: Code signing happens in the Client pipeline, not here
