# CI/CD Pipeline

Wingman AI uses a two-stage build pipeline: **Core** is built first (Python via PyInstaller), then bundled as a sidecar into the **Client** (Tauri desktop app, private repo).

## Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `dev-build.yml` | Manual | Build selected platform(s) |
| `tests.yml` | Pull request, push to main/develop, manual | pytest on Linux (`python -m pytest`) |
| `release-windows.yml` | Called by dev-build.yml and by the Client's release run (never by a tag) | Windows build + signing (Azure Artifact Signing) |
| `release-macos.yml` | Called by dev-build | macOS build |
| `release-linux.yml` | Called by dev-build | Linux build |

### Build Steps

1. Checkout + install system deps + setup Python 3.11.7
2. PyInstaller builds `WingmanAiCore.spec` → `dist/WingmanAiCore/`
3. Windows: code-signed via Azure Artifact Signing
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
  WingmanAiInput.exe      ← Windows only: presses keys in games that run as administrator
  _internal/              ← PyInstaller dependencies
core/{channel}/latest-windows.txt   ← SHA pointers per channel
core/{channel}/latest-macos.txt
core/{channel}/latest-linux.txt
```

Each channel keeps its newest five builds and the ones its pointers name; older ones of that channel are deleted after every upload. The Client's `download-core` action takes the channel and `latest` or a specific SHA. For a release, pass the SHA of the tag.

## Version Management

Core version lives in `services/system_manager.py` → `LOCAL_VERSION`. Change it with `python scripts/bump_version.py X.Y.Z`. That updates `LOCAL_VERSION` and the Client files and writes the migration skeleton. `python scripts/bump_version.py --check` reports disagreement.

## Signing

- **Windows**: Azure Artifact Signing, signed during Core build (`.github/actions/code-sign`). `WingmanAiInput.exe` is signed too: Windows gives it the UIAccess right only with a valid signature and only when it is installed under Program Files, next to `WingmanAiCore.exe`.
- **macOS/Linux**: Code signing happens in the Client pipeline, not here

### Azure Artifact Signing

The certificate is issued to ShipBit GmbH. Azure renews it by itself: each one lives three days, and the timestamp keeps a signature valid after that. What does expire is the identity validation behind it, on 2029-02-26. Renew it in the Azure portal before that day, or signing stops.

The sign job logs in to Azure with OIDC, so no signing secret is stored. The Entra app registration has a federated credential for the GitHub environment `signing` of this repo, and the role `Artifact Signing Certificate Profile Signer` on the signing account. The credential's subject carries the organization and repository IDs (GitHub's immutable subject format), so it survives a rename. The repo is older than that format and was opted in to it once:

```
gh api -X PUT repos/ShipBit/wingman-ai/actions/oidc/customization/sub \
  -F use_default=true -F use_immutable_subject=true
```

The environment holds:

- Secrets: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`
- Variables: `ARTIFACT_SIGNING_ENDPOINT` (of the account's region, e.g. `https://weu.codesigning.azure.net`), `ARTIFACT_SIGNING_ACCOUNT_NAME`, `ARTIFACT_SIGNING_PROFILE_NAME`

A workflow that calls `release-windows.yml` has to grant `id-token: write` and `actions: write` to that job, as `dev-build.yml` does.
