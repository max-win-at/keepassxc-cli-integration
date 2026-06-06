---
name: keepassxc-secrets
description: >
  Fetches, generates, or stores credentials (passwords, usernames, TOTP) from a
  KeePassXC vault via the `kpxc-agent` CLI. Activate when a task needs a secret from
  KeePassXC — provisioning or commissioning a Linux box or SBC, wiring up a service
  that needs a DB/API/SSH password, saving a freshly generated credential, or reading
  a TOTP — locally or over SSH. Also activates when the user mentions "my vault" or
  "password manager", or asks to generate and save a password rather than inventing one.
---

# KeePassXC secrets via kpxc-agent

`kpxc-agent` is a CLI that speaks KeePassXC's browser-integration protocol with no
browser — built for headless and agent use. It lets you read, generate, and store
secrets in the user's running KeePassXC, with the same end-to-end encryption the
browser extension uses. Reach for it instead of inventing passwords, hardcoding
placeholders, or asking the user to paste secrets into the chat.

This skill **bundles the tool** at `scripts/kpxc-agent` (relative to this skill's
directory). The recipes below call it as `kpxc-agent`; if it isn't already on `PATH`, put
the bundle there first — substitute this skill's actual directory for `<skill-dir>`:

```bash
export PATH="<skill-dir>/scripts:$PATH"
chmod +x "<skill-dir>/scripts/kpxc-agent"
```

Either way it needs `jq`, `python3`, and `libsodium` on the machine where it runs (these
are system packages, not bundled). Source and full docs:
<https://github.com/max-win-at/keepassxc-cli-integration>.

## The secret-handling rule (read this first)

Secrets must never land in a place that gets logged, echoed, or committed. The whole
point of this tool is that secrets stay in process memory for one command and vanish.
So:

- **Capture into a shell variable, never print it.** Use `--field` or `--json` and
  assign: `pw=$(kpxc-agent get-logins URL --field password)`. Don't `echo "$pw"`,
  don't pass it on a visible command line, don't write it to a file the user didn't ask for.
- **Prefer `--field`/`--json` over the default `KEY=value` output in scripts** that
  might end up in a log. The default is fine for an interactive `eval`, but `--field`
  gives you exactly one value with nothing extra to leak.
- The association identifiers (`KPXC_ASSOC_ID` / `KPXC_ASSOC_KEY`) are **not** secret —
  they're safe to store in a profile or pass over SSH. Only the fetched
  usernames/passwords/TOTPs are sensitive.

## Step 1 — Check reachability

Before anything else, confirm KeePassXC is reachable and the prerequisites are present:

```bash
kpxc-agent doctor
```

This reports `jq`/`python3`/`libsodium`, the chosen transport (local socket, proxy
relay, or a forwarded socket), and whether KeePassXC answers. If it can't reach
KeePassXC, the database is probably locked or Browser Integration is disabled — tell
the user; you can't unlock it for them.

## Step 2 — One-time pairing (association)

KeePassXC only talks to clients it has approved. Pairing happens **once** and requires
a human to click "Allow" in a KeePassXC dialog — you cannot complete it unattended:

```bash
eval "$(kpxc-agent --trigger-unlock associate)"
```

This prints two non-secret `export` lines (`KPXC_ASSOC_ID`, `KPXC_ASSOC_KEY`).
Persist them so future calls skip pairing — drop them in the user's shell profile, a
CI secret store, or pass them over SSH (see `references/remote-ssh.md`). Verify an
existing pairing with `kpxc-agent test`.

If a command exits with code 4 ("no/invalid association"), the env vars are missing or
stale — re-run `associate`.

## Step 3 — Common recipes

All of these assume `KPXC_ASSOC_ID` / `KPXC_ASSOC_KEY` are set.

**Fetch a single password (most common):**
```bash
pw=$(kpxc-agent get-logins https://host.example --field password)
```

**Fetch the whole entry into shell vars:**
```bash
eval "$(kpxc-agent get-logins https://host.example)"
# now $KPXC_USERNAME and $KPXC_PASSWORD are set (in memory only)
```
If several entries match, the default output switches to `KPXC_COUNT=N` plus indexed
`KPXC_USERNAME_0` / `KPXC_PASSWORD_0` …. Use `--json` when you need to choose among
matches programmatically.

**Generate a password** (uses KeePassXC's own generator settings). Unlike `get-logins`,
`generate-password` has no `--field`; it prints a quote-escaped `KPXC_PASSWORD=…` line,
so `eval` it into a variable rather than capturing stdout directly:
```bash
eval "$(kpxc-agent generate-password)"   # sets $KPXC_PASSWORD, in memory only
```
> If a command seems to hang, KeePassXC is probably showing a confirmation dialog the
> user must approve (depending on their access settings). That's expected for an
> unattended agent — surface it to the user rather than killing the command.

**Store a new login** (e.g. after generating one for a service you just configured):
```bash
kpxc-agent set-login https://host.example --username svc --password "$KPXC_PASSWORD"
```

**Read a TOTP** for an entry you already located (uuid comes from `get-logins --field
uuid`). Like generate-password it prints `KPXC_TOTP=…`, so `eval` it too:
```bash
eval "$(kpxc-agent get-totp "$uuid")"    # sets $KPXC_TOTP
```

**List groups** (to choose where `set-login` should file an entry):
```bash
kpxc-agent groups            # uuid<TAB>group/path per line; add --json for structure
```

## Step 4 — Handle exit codes deliberately

Don't just check for zero — the codes tell you what to do next:

| Code | Meaning | What to do |
|------|---------|------------|
| 0 | success | proceed |
| 2 | KeePassXC unreachable / DB not opened | ask the user to open/unlock KeePassXC; re-run `doctor` |
| 3 | request refused, cancelled, or locked | the user declined the dialog or the DB locked — ask them |
| 4 | no/invalid association | set/refresh `KPXC_ASSOC_*` via `associate` |
| 5 | protocol or crypto failure | likely a version/transport issue; check `doctor`, retry with `--debug` |
| 64 | bad command-line usage | fix the command |

## Remote / SSH (agent on a different box than KeePassXC)

When `kpxc-agent` runs on a remote box but KeePassXC runs on the machine the user sits
at (VS Code Remote SSH, or an ssh-driven agent), the box has no local KeePassXC. The
fix is a reverse-forwarded socket: run `kpxc-agent serve-bridge` on the client and
`ssh -R` it to the box. This is a common setup — read **`references/remote-ssh.md`**
for the exact commands for Linux/macOS and Windows/WSL clients.

## Going deeper

- **`references/commands.md`** — every command, all options, transport overrides.
- Wire protocol (rarely needed): the repo's `keepassxc-cli-agent-protocol.md`.
