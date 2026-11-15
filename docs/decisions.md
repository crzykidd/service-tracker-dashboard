# Decisions

Non-obvious decisions — approach changes, rejected alternatives,
workarounds — newest at top. One entry per decision.

---

## 2026-11-15 — vexp removal recorded in HISTORY, not CHANGELOG

CLAUDE.md requires a CHANGELOG entry for every change, but CHANGELOG is
operator-facing and is rendered in the in-app "What's new" popup. The vexp
removal is developer tooling with no operator-visible effect, so it was
recorded in `docs/HISTORY.md` instead. Same reasoning applies to future
tooling-only changes (agent guidance, `.claude/` config).

## 2026-11-15 — Docker Hub → GHCR via a banner-only final Docker Hub release

v0.6.7 was published to both registries from one workflow, with the
in-app "moved to GHCR" banner gated on a `REGISTRY_NOTICE=dockerhub`
build arg so only the Docker Hub image shows it. Rejected: a Docker
Hub-only final release (GHCR would have had nothing to switch to) and
an unconditional banner (users who had already moved would keep seeing
it). Driver: GHCR retention runs on `GITHUB_TOKEN`; Docker Hub retention
would need a delete-scoped token and a custom cleanup job. Docker Hub
publishing, the build arg, and the banner are removed in the next
release; Docker Hub tags stay frozen on the v0.6.7 banner build.

## 2026-11-15 — The `0.6.5` tag stays un-prefixed

v0.6.5 was tagged `0.6.5` (no `v`), unlike every other release. It is
left as-is: re-tagging a published release is never done (moving a tag
under consumers breaks pins and image provenance). CHANGELOG's link
reference already points at `releases/tag/0.6.5`. All new tags use the
`vX.Y.Z` form.
