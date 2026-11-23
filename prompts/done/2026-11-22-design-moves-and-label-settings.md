---
name: 2026-11-22-design-moves-and-label-settings
status: completed
created: 2026-11-22
model: opus
completed: 2026-11-22
result: "Design note docs/design/2026-11-22-moves-and-label-settings.md written (provenance columns, rev-7 label fields, move detection with keep-old-id merge, 5 phases, 15 open questions); FUTURE.md pointers added. No HISTORY line (no precedent for design notes)."
---

# Task: Design spec for STD 0.14.0: container moves and duplicates, and label-driven settings with provenance

Write a **design note**, not code: `docs/design/2026-11-22-moves-and-label-settings.md`. It
is for operator review. It covers two linked problems that have the same root cause:
operator settings get lost, or overwritten, by register.

1. **A container moves between hosts** (e.g. `foo` from docker01 to docker02).
   - STD matches register on `(host, container_name)`, so docker02 creates a brand-new
     entry.
   - The old docker01 entry stays, red for good: its Container check reads "Container
     exited", then "No update from notifier for N min". It's also down in HA/MQTT if
     published there.
   - Every UI-made setting stays on the old entry:
     - group, sort, icon, description;
     - UI-edited URLs;
     - health-check settings and service checks;
     - widget;
     - image update policy, scope and pattern, and `image_repo_url`;
     - `ha_publish`.
   - A design is already parked in `docs/FUTURE.md` → "Service identity and duplicate
     detection": a Settings → Duplicates screen with merge or dismiss, and no auto-merge
     ever.
2. **Label-driven settings.** The research in `docs/design/2026-11-22-notifier-labels.md`
   recommends these new `dockernotifier.std.*` labels, in order:
   - `description`;
   - `image_update.policy` / `.scope` / `.tag_pattern`;
   - `image_repo_url`;
   - URL-check settings as a typed nested object;
   - a display-only `attributes` pass-through.

   They need **per-field provenance** first, so a UI edit always wins. They also need the
   existing clobbers fixed: register overwrites a UI-chosen icon, and the health toggles
   (FUTURE.md "Register overwrites some operator edits").

   Labels also soften moves: settings kept in compose follow the container.

## Before you start

- **Read:**
  - `CLAUDE.md`: the Register Contract Rules (URL provenance ordering
    `ui_edit` > `explicit_label` > `synthesized`, `extra="forbid"`, the ordering rule, and
    the safe-degradation guarantee);
  - `docs/FUTURE.md`: the duplicates section, "Register overwrites some operator edits",
    and the service-checks item;
  - `docs/design/2026-11-22-notifier-labels.md` (all of it, especially §4 pitfalls);
  - `docs/decisions.md`, the recent entries.
- **Code to read, not change:**
  - `routes_api.py`: the register handler, `_UPSERT_LOCK`, the
    `register_field_ownership` modes `user_wins` / `notifier_wins`, adoption,
    resurrection of soft-deleted rows, how health toggles and `image_icon` are written,
    and the model_dump absent-vs-null behavior;
  - `models.py` (`ServiceEntry`, checks, widgets);
  - `schemas.py`, `entry_rules.py`, `mgmt_schemas.py`;
  - `streams.py`: the link offers, as a pattern for an accept/dismiss suggestion;
  - `export_format.py`: the ownership table, PRD §20.2;
  - `notify_state.py` / `notify_ha.py`: what a merge or delete must do to retained
    topics.
- **Read only:** the notifier repo, for the label handling (`main.py` ~L230-252) and the
  queued 0.6.0 prompt `prompts/2026-11-22-std-network-details-and-label-hardening.md`. It
  adds `std.skip` and fixes the label bugs; don't duplicate them.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What the design note must cover

Use `docs/design/2026-11-21-image-update-check.md` as the model for the shape: status
header, goals and non-goals, numbered sections, open questions for the operator.

1. **Goals and non-goals.** In scope: moves, renames, and label settings with provenance.
   **No auto-merge, ever.** Ask yourself whether the old row should be auto-flagged.
2. **Move and duplicate detection.**
   - **Candidate rules:** revisit the FUTURE.md criteria against today's data. There are
     now `image_ref`, `stack_name`, `networks`, published ports, exposure hostnames,
     `stale_after_minutes`, soft delete and stream entries.
   - **When it is computed:** at register time (a new row is created and a likely old
     twin exists) and/or on demand.
   - **Where it surfaces:**
     - a notice on the new entry, "looks like `foo` on docker01, stale: merge?", in the
       same accept/dismiss shape as stream link offers;
     - the Settings → Duplicates list;
     - a count badge.
   - **Merge semantics, field by field:**
     - which fields move from old to new and which are kept;
     - widget and widget values;
     - health checks and their history;
     - service checks;
     - URLs by provenance;
     - image update fields;
     - `ha_publish`;
     - retained MQTT/HA topics: purge the old entry's, publish the new one's;
     - the audit log;
     - the old row is soft-deleted, not hard-deleted.
   - **Dismiss:** a "not the same" record, with the active-active false-positive case.
   - **Alternative for keeping history:** keep the old entry's id and re-point it to the
     new host. Weigh that against "merge into the new row".
   - **Rename** (the same host, a new container name): does the same flow cover it?
3. **Per-field provenance.**
   - **Which fields get it:** the URL pattern extended to icon, the health toggles,
     description, the image update fields, `image_repo_url`, and the check settings.
   - **Storage:** `<field>_source` columns vs one JSON provenance map. Recommend one, with
     the migration shape.
   - **The rules:**
     - a UI edit wins;
     - an absent label means "leave alone";
     - whether removing a label clears a label-owned value (today a removed URL label
       sticks forever);
     - how `register_field_ownership` (`user_wins` / `notifier_wins`) maps onto
       provenance, or whether it's retired;
     - "Reset to label/auto" in the UI, so an operator can hand a field back;
     - absent vs null: use `model_fields_set`, not `in canonical`.
   - **Fixing the existing clobbers:** the icon and the health toggles, including that a
     new row with an absent toggle creates a disabled check.
   - **Export/import:** how provenance round-trips (PRD §20.2).
4. **The new register fields and labels.** For each recommended label:
   - the label name;
   - the payload key and type;
   - validation, the same as the management API;
   - provenance behavior;
   - the `/api/v1/meta` FEATURES flag;
   - the `API_REVISION` (7).

   Then the notifier 0.7.0 follow-up, which the ordering rule says ships after STD:
   the notifier sends a field only when STD advertises it, through the per-feature gate
   that 0.6.0 adds.
5. **How the two parts interact.** Merge must respect provenance: a label-owned value on
   the new row beats a UI value on the old one? Decide, or ask.
6. **Phasing.** Propose an order of implementation prompts, each one a Sonnet build
   prompt sized for one session.
   - Example order: (a) provenance plus fixing the clobbers; (b) the new label fields
     plus API revision 7; (c) move detection and merge.
   - For each phase: the CHANGELOG/PRD impact and the tests, including query-count
     guards for any per-row duplicate computation on dashboard views.
7. **Open questions for the operator,** numbered, each with your recommendation.

Keep it tight: decisions and rules, not prose. Cite `file:line` for every claim about
current behavior. Where the code and FUTURE.md disagree, trust the code and say so.

## Also

- `docs/FUTURE.md`: add a one-line pointer from the duplicates section and the
  "Register overwrites some operator edits" section to the new design note. Don't
  remove them until they ship.
- `docs/decisions.md` is only for decisions already made. The design's choices stay in
  the note until the operator approves.
- This is docs-only, so it gets no CHANGELOG entry (CLAUDE.md "Always", item 1). Add a
  `docs/HISTORY.md` line only if that file records design notes; check the precedent.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `mv` it (it's untracked) into `prompts/done/` or `prompts/failed/`.
3. **You are a spawned agent: do not commit.** Report back:
   - the file list;
   - a proposed one-line message (e.g. `docs: design for 0.14.0: container moves and
     duplicates, label settings with provenance`);
   - a summary of the recommendations and the open questions, so the orchestrator can
     relay them.
