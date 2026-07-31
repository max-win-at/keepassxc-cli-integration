# kpxc-agent command reference

Full surface of the CLI. The common path is covered in `SKILL.md`; this is the
exhaustive list for edge cases.

## Commands

| Command | Output |
|---------|--------|
| `associate` | `export KPXC_ASSOC_ID=…` / `KPXC_ASSOC_KEY=…` (pairing; needs human approval) |
| `test` | validity of the current association |
| `get-logins URL [opts]` | `KPXC_USERNAME=…` / `KPXC_PASSWORD=…` (see options) |
| `probe URL [URL…] [--json]` | `URL<TAB>count<TAB>names` — which URLs match; no secrets |
| `db-info [--json]` | which database is open: `database` / `hash` / `name` / `paired` |
| `wait-db --changed\|--hash H` | blocks until the right database is active; prints its hash |
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
- `--field username|password|name|uuid|totp` — print exactly one raw value. **The only
  way a secret leaves the tool**; capture it (`pw=$(…)`), never run it bare.
- `--json` — matches as **metadata only**: `uuid`, `name`, `login`, `group`, `expired`.
  Passwords and TOTPs are excluded by an allowlist and cannot appear here. For choosing
  among multiple matches, and safe to show the user.
- `--entry-uuid UUID` / `--index N` — pick one match (typically a `uuid` taken from a
  `--json` listing) before applying `--field` or the default output. `--index` is
  0-based; out of range is exit 64, an unknown uuid is exit 6.
- `--allow-empty` — exit 0 instead of 6 when nothing matches. For genuine existence
  checks only ("create the entry if absent") — never to quiet a failed lookup.

Default output is shell-evalable `KEY=value` lines: a single match is unprefixed
(`KPXC_USERNAME` / `KPXC_PASSWORD`); multiple matches emit `KPXC_COUNT=N` plus indexed
`KPXC_USERNAME_0`, `KPXC_PASSWORD_0`, …. Values are single-quote-escaped so
`eval "$(…)"` is safe even for passwords with quotes or spaces.

## Finding the right vault and the right URL

A lookup that matches nothing exits **6** with a message naming the URL and the open
database — it never returns an empty string with exit 0. The two commands that tell the
two causes apart:

- `db-info` — reports the active database as `hash` plus `name`, the root group name,
  which KeePassXC sets from the database name and is the only human-recognizable label
  the browser protocol exposes. Reports `database: closed-or-locked` and exits 2 when
  nothing is open. Does not force an unlock dialog (pass `--trigger-unlock` to allow it),
  and never triggers a pairing dialog.
- `probe URL [URL…]` — runs the same lookup against several candidate URLs and reports
  the match count and entry names for each. Exits 6 if none matched. Output is
  metadata-only, so it can be shown to the user to help them fix an entry's URL field.

`wait-db` blocks until the user has the right vault open, so a lookup can be retried
instead of aborting the task: `--changed` waits for the active database to differ from
the one at invocation (or for any database, if none is open), `--hash H` waits for a
specific one. `--timeout N` (default 300) exits 7 on expiry; `--interval N` (default 2)
sets the poll period. It polls rather than waiting on the `database-unlocked` broadcast
because switching between two already-unlocked databases emits no signal.

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
`$TMPDIR/...` → `/tmp/...` → `$XDG_RUNTIME_DIR/app/org.keepassxc.KeePassXC/...` for
Flatpak), otherwise a `keepassxc-proxy` relay (the Windows `keepassxc-proxy.exe` under
`C:\Program Files\KeePassXC`, else one on `PATH`).

## Other global options

- `--trigger-unlock` — ask KeePassXC to prompt the user to unlock a locked database.
- `--debug` (env `KPXC_AGENT_DEBUG=1`) — verbose protocol/crypto diagnostics on stderr.
  Password fields are masked in what it prints, so it is safe to use while debugging a
  `set-login`.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | success |
| 2 | KeePassXC unreachable / database not opened |
| 3 | request refused, cancelled, or locked |
| 4 | no / invalid association for the open database |
| 5 | protocol or crypto failure |
| 6 | no entry matched (reachable, unlocked and paired — but nothing found) |
| 7 | `wait-db` timed out |
| 64 | bad command-line usage |
