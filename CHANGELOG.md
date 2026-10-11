# Changelog

## 0.2.0 — Unreleased

- Replace the single-playlist script with a shared engine, configurable named profiles and an installed command.
- Use configurable duration thresholds for arbitrary channels; keep channel-specific personal rules outside the public source and distribution.
- Make first-run selection explicit: future publications, resume after the latest selected source video, full history, or an inclusive calendar date.
- Persist decisions and destination-specific completion; reconcile uncertain writes, resume partial additions and respect manual removals.
- Confirm successful insertions from their API receipts, tolerate delayed playlist reads, and persist pending-write checkpoints to avoid duplicate retries after lost responses or interruptions.
- Add arrow-key review menus, offline demos, access checks and simulations.
- Support external configuration paths and configurable time zones.
- Add explicit state imports without overwriting active selections or modifying playlists.
- Provide public configuration examples and keep personal configuration/documentation out of Git.
- Add Origami Beats and ego example playlist links with standalone configurations, and clarify publication boundaries for older states.

Breaking changes from 0.1.0: Python 3.11+, TOML configuration, new OAuth/state paths, and a new entry point. See the README upgrade instructions. Existing unified-updater version 2 states remain compatible.
