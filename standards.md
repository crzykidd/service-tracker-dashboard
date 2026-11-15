# Standards implemented

This project implements the following [standards](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards)
from the crzynet `homelab-configs` repo. Each row pins the **version** that this
project has actually wired up.

| Standard | Version | Adopted | Notes |
|---|---|---|---|
| [handoff-prompt-workflow](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/handoff-prompt-workflow/README.md) | 2.0.0 | 2026-11-15 | `prompts/TEMPLATE.md` copied verbatim; snippet pasted verbatim into `CLAUDE.md`; decision log at `docs/decisions.md`. |
| ~~[vexp-context-engine](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/vexp-context-engine/README.md)~~ | 3.0.0 _(sunset)_ | de-adopted 2026-11-15 | Removed per the v3.0.0 removal guide: guard hook, `.claude/settings.json` hook + `mcp__vexp__*` allows, vexp-generated `.claude/CLAUDE.md` and `.github/copilot-instructions.md`, `.gitignore` entry. Host install was already gone (no host teardown needed here — owned by `ansible`). Was wired at vexp v2.0.17 but never recorded as a standards adoption. |
| [code-checkin-and-pr](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/code-checkin-and-pr/README.md) | 1.2.0 | 2026-11-15 | CI checks in `.github/workflows/ci.yml` (Lint, Config validation, Migration check, Compose validation). **Tests exempt** — no test suite yet (`scripts/test_widget.py` is a manual script). SAST via CodeQL default setup. Image build check satisfied by `publish.yml`'s PR build (job `build`). Registry retention on GHCR only (`retention.yml`); Docker Hub is no longer published (last image v0.6.7) and gets none. `refactor:` commit prefix is a project extension. |
| [release-prep-and-cut](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/release-prep-and-cut/README.md) | 1.1.0 | 2026-11-15 | `VERSION` file added (bare semver, source of truth; Dockerfile writes `version.txt` from it); `publish.yml` guards release tag == `VERSION`; commands in `.claude/commands/`. First used for v0.6.8. The bare `0.6.5` historical tag is a known, un-fixable deviation. |
