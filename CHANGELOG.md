# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `CHANGELOG.md` — this changes journal.
- `tests/README.md` — a guide to the offline self-test suite, scoped to the tests.
- `references/architecture.md` (in the skill) — technical reference for developers
  and security auditors: components, crypto channel, transports, association
  identity model, secret-hygiene design, and security considerations.

### Changed

- README rewritten as a product overview: marketplace-first install instructions,
  badges for skills.sh and agentskill.sh, and pointers to the new technical
  reference instead of inline deep-dives.

## [1.0.0] - 2026-10-10

First stable release: the public surface (commands, output formats, exit-code
contract) is now frozen.

### Changed

- **Breaking:** the skill bundle at `skills/keepassxc-secrets/scripts/` is now the
  canonical location of `kpxc-agent`; the tool ships inside the agent skill so a
  marketplace install is self-contained. Update any references to the previous
  top-level `scripts/` path.
- Consolidated the CLI and skill install instructions into a single Install
  section.

## [0.4.1] - 2026-10-05

### Fixed

- The direct BrowserServer unix socket speaks bare JSON, not native-messaging
  framing. Connecting to the local socket previously failed; the framing is now
  applied only where the real endpoint requires it (proxy relays).

## [0.4.0] - 2026-07-31

### Changed

- **Breaking:** `get-logins --json` no longer contains passwords or TOTPs. It
  returns an allowlisted metadata projection (`uuid`, `name`, `login`, `group`,
  `expired`) so listing matches cannot leak a secret into a log or an agent's
  context. Fetch the chosen entry with `--field password --entry-uuid <uuid>`.
- **Breaking:** a lookup that matches nothing now exits `6` instead of exiting `0`
  with empty output, and the message names the database it searched — an
  automated caller can no longer mistake "not found" for "no credential". Pass
  `--allow-empty` to restore the old behavior for genuine existence checks.

## [0.3.0] - 2026-06-11

### Added

- Persistent association store: `associate` saves the pairing per database
  (keyed by database hash) in `~/.config/keepassxc-cli-agent/associations.json`
  (mode `600`), the same model as the browser extension's keyRing. Later commands
  reload and verify it — pair once per database.
- `KPXC_ASSOC_ID` / `KPXC_ASSOC_KEY` environment variables now override the
  on-disk store, for ephemeral contexts such as CI or SSH-forwarded commands.
- Database-open handling: `db-info` names the active database, `wait-db` blocks
  until the right one is active, and credential commands auto-trigger KeePassXC's
  unlock dialog when the vault is locked.

## [0.2.0] - 2026-06-06

### Added

- Credential commands automatically trigger KeePassXC's unlock dialog and wait
  for the `database-unlocked` broadcast before proceeding.

### Fixed

- Two channel bugs that prevented the unlock-wait flow from activating.
- Skill setup: conditional `chmod`, one-time `doctor` check, PATH-safe script
  resolution, and auto-prepend of `https://` to bare hostnames.
- URL-construction guidance for `get-logins` and `set-login` in the skill.

## [0.1.0] - 2026-06-05

### Added

- Initial release of `kpxc-agent`: a CLI that speaks KeePassXC's browser-integration
  protocol headlessly — fetch, generate, and store credentials (including TOTP),
  list and create groups, with end-to-end `crypto_box` encryption and auto-detected
  transports (direct unix socket, `keepassxc-proxy` relay, SSH-forwarded socket).
- The `keepassxc-secrets` agent skill bundling the tool for AI harnesses.
- Symlink- and PATH-safe script resolution via `readlink -f`.

[Unreleased]: https://github.com/max-win-at/keepassxc-cli-integration/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/max-win-at/keepassxc-cli-integration/compare/v0.4.1...v1.0.0
[0.4.1]: https://github.com/max-win-at/keepassxc-cli-integration/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/max-win-at/keepassxc-cli-integration/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/max-win-at/keepassxc-cli-integration/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/max-win-at/keepassxc-cli-integration/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/max-win-at/keepassxc-cli-integration/releases/tag/v0.1.0
