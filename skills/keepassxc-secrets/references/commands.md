# kpxc-agent command reference

Full surface of the CLI. The common path is covered in `SKILL.md`; this is the
exhaustive list for edge cases.

## Commands

| Command | Output |
|---------|--------|
| `associate` | `export KPXC_ASSOC_ID=…` / `KPXC_ASSOC_KEY=…` (pairing; needs human approval) |
| `test` | validity of the current association |
| `get-logins URL [opts]` | `KPXC_USERNAME=…` / `KPXC_PASSWORD=…` (see options) |
| `get-totp UUID` | `KPXC_TOTP=…` |
| `generate-password` | `KPXC_PASSWORD=…` |
| `set-login URL --username U --password P [...]` | `Saved.` |
| `groups [--json]` | `uuid<TAB>group/path` per line |
| `create-group NAME` | `uuid<TAB>name` |
| `lock` | locks the database |
| `hash` | active database hash |
| `serve-bridge [--listen ADDR]` | expose local KeePassXC for `ssh -R` (run on the client) |
| `doctor` | prerequisite / transport / reachability check |

## `get-logins` options

- `--submit-url URL` — narrow the match by form submit URL.
- `--http-auth` — match HTTP Basic/Digest auth entries.
- `--field username|password|name|uuid|totp` — print exactly one raw value (best for
  scripts; nothing else to leak).
- `--json` — raw entries array, for choosing among multiple matches programmatically.

Default output is shell-evalable `KEY=value` lines: a single match is unprefixed
(`KPXC_USERNAME` / `KPXC_PASSWORD`); multiple matches emit `KPXC_COUNT=N` plus indexed
`KPXC_USERNAME_0`, `KPXC_PASSWORD_0`, …. Values are single-quote-escaped so
`eval "$(…)"` is safe even for passwords with quotes or spaces.

## `set-login` options

Beyond `--username` / `--password`: `--submit-url URL`, `--group NAME`,
`--group-uuid UUID` (file the entry in a specific group), `--uuid UUID` (update an
existing entry instead of creating one).

## Transport (auto-detected; override only when needed)

- `--socket PATH` (env `KPXC_SOCKET`) — connect to a unix socket directly. This is how
  the box reaches a `ssh -R`-forwarded socket.
- `--proxy` — relay through an auto-detected `keepassxc-proxy`.
- `--exec CMD` (env `KPXC_EXEC`) — use a specific relay command's stdio (e.g. a
  non-default `keepassxc-proxy.exe`).

Resolution order when none is given: an existing local unix socket
(`$KPXC_SOCKET` → `$XDG_RUNTIME_DIR/org.keepassxc.KeePassXC.BrowserServer` →
`$TMPDIR/...` → `/tmp/...`, plus the Flatpak path), otherwise a `keepassxc-proxy` relay
(the Windows `keepassxc-proxy.exe` under `C:\Program Files\KeePassXC`, else one on `PATH`).

## Other global options

- `--trigger-unlock` — ask KeePassXC to prompt the user to unlock a locked database.
- `--debug` (env `KPXC_AGENT_DEBUG=1`) — verbose protocol/crypto diagnostics on stderr.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | success |
| 2 | KeePassXC unreachable / database not opened |
| 3 | request refused, cancelled, or locked |
| 4 | no / invalid association (set `KPXC_ASSOC_*`) |
| 5 | protocol or crypto failure |
| 64 | bad command-line usage |
