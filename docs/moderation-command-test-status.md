# Moderation command test status

**Implementation:** 45/45 specified command names are registered across the nine moderation cogs. Every command response path uses the shared moderation embed helpers; the shared embed manager supplies the configured custom emoji markup.

**Automated coverage:** command registration, all 45 command embed previews, and embed color/usage/permission behavior are covered. Twenty-eight commands have command/service behavior tests. The remaining 17 command handlers are implemented but still need dedicated behavior tests before they can be marked behavior-tested.

**Latest verification:** `python -m compileall -q .` passed; `python -m pytest -q tests` — 102 passed, 6 warnings, 83 subtests passed. The full repository suite includes moderation and community tests. Source audit found 45 unique moderation command names and no command send path without an embed.

**Scope:** tests are unit-level and do not call a live Discord server, ban/kick members, change channel permissions, or delete real messages.

## Implemented commands without dedicated behavior tests

`warninfo`, `purgeinvites`, `purgeimages`, `purgefiles`, `purgeembeds`, `purgementions`, `purgecontains`, `purgeafter`, `lock`, `unlock`, `lockall`, `unlockall`, `slowmode`, `nick`, `resetnick`, `jail`, and `unjail`.
