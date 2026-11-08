# Moderation command test status

**Status:** 28 implemented commands have automated test coverage and pass the current suite.

“PASS” means repository/service/permission/registration tests passed locally. It does
not mean a live Discord server was used; these tests do not issue real moderation
actions or delete real messages.

## Latest verification

- `pytest -q`: 72 passed, 83 subtests passed
- `compileall`: passed
- Registration: 28 unique implemented command names; no duplicate names or aliases
- Embed preview generator: 45 preview entries rendered; preview entries are not
  evidence that pending commands are implemented

| # | Command | Status | Test evidence |
|---:|---|---|---|
| 1 | `ban` | PASS — tested and checked | `test_ban_records_case_and_calls_discord_without_deleting_messages` |
| 2 | `unban` | PASS — tested and checked | `test_unban_records_case_and_calls_discord` |
| 3 | `softban` | PASS — tested and checked | `test_softban_unbans_after_cleanup_ban`; `test_softban_marks_partial_if_automatic_unban_fails` |
| 4 | `tempban` | PASS — tested and checked | `test_tempban_persists_expiry_and_bans_without_deleting_history`; expiry-worker tests |
| 5 | `kick` | PASS — tested and checked | `test_kick_records_case_and_calls_discord` |
| 6 | `massban` | PASS — tested and checked | partial-result and invalid-target service tests |
| 7 | `masskick` | PASS — tested and checked | `test_masskick_returns_actual_success_and_failure_counts` |
| 8 | `timeout` | PASS — tested and checked | `test_timeout_records_expiry_and_calls_discord` |
| 9 | `untimeout` | PASS — tested and checked | `test_untimeout_clears_timeout_and_records_case` |
| 10 | `mute` | PASS — tested and checked | shared timeout-service action-type test |
| 11 | `unmute` | PASS — tested and checked | shared timeout-service action-type test |
| 12 | `voicemute` | PASS — tested and checked | connected-member voice-mute service test |
| 13 | `voiceunmute` | PASS — tested and checked | connected-member voice-unmute service test |
| 14 | `deafen` | PASS — tested and checked | `test_deafen_applies_to_connected_voice_member` |
| 15 | `undeafen` | PASS — tested and checked | service test and Batch 1 command-wiring test |
| 16 | `disconnect` | PASS — tested and checked | service permission/voice-state test and Batch 1 command-wiring test |
| 17 | `move` | PASS — tested and checked | destination-guild/service test and Batch 1 command-wiring test |
| 18 | `warn` | PASS — tested and checked | persistence, hierarchy, embed, and command-wiring tests |
| 19 | `unwarn` | PASS — tested and checked | scoped warning-ID deletion and command-wiring tests |
| 20 | `warnings` | PASS — tested and checked | persistence, guild isolation, history pagination, and command-wiring tests |
| 21 | `clearwarnings` | PASS — tested and checked | confirmed deletion and cancellation command tests |
| 22 | `warnlist` | PASS — tested and checked | guild-scoped database paging and command pagination test |
| 23 | `warnstats` | PASS — tested and checked | stored-data aggregation and command embed test |
| 24 | `purge` | PASS — tested and checked | confirmation, invocation exclusion, count, and old-message deletion tests |
| 25 | `purgeuser` | PASS — tested and checked | target-only message filtering test |
| 26 | `purgebots` | PASS — tested and checked | bot-author filtering test |
| 27 | `purgehumans` | PASS — tested and checked | human-author filtering test |
| 28 | `purgelinks` | PASS — tested and checked | URL filtering and normal-text/email negative tests |

## Not implemented or tested yet

These existing preview-catalog entries remain pending; they are not marked as
tested:

`warninfo`, `purgeinvites`, `purgeimages`, `purgefiles`, `purgeembeds`,
`purgementions`, `purgecontains`, `purgeafter`, `lock`, `unlock`, `lockall`,
`unlockall`, `slowmode`, `nick`, `resetnick`, `jail`, `unjail`.

The development plan names 16 Batch 3 commands while the existing preview catalog
contains 17 remaining entries including `warninfo`. Keep this discrepancy visible
and verify it against the original 45-command specification before final sign-off;
no extra command has been invented here.
