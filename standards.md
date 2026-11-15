# Standards implemented

This project implements the following [standards](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards)
from the crzynet `homelab-configs` repo. Each row pins the **version** that this
project has actually wired up.

| Standard | Version | Adopted | Notes |
|---|---|---|---|
| ~~[vexp-context-engine](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/vexp-context-engine/README.md)~~ | 3.0.0 _(sunset)_ | de-adopted 2026-11-15 | Removed per the v3.0.0 removal guide: guard hook, `.claude/settings.json` hook + `mcp__vexp__*` allows, vexp-generated `.claude/CLAUDE.md` and `.github/copilot-instructions.md`, `.gitignore` entry. Host install was already gone (no host teardown needed here — owned by `ansible`). Was wired at vexp v2.0.17 but never recorded as a standards adoption. |
