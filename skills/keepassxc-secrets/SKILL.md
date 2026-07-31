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
directory). The recipes below call it as `kpxc-agent`; if it isn't already on `PATH`
(`command -v kpxc-agent` to check), resolve it once — substitute this skill's actual
directory for `<skill-dir>`:

```bash
kpxc_bin="<skill-dir>/scripts/kpxc-agent"
[ -x "$kpxc_bin" ] || chmod +x "$kpxc_bin"
```

Shell state does not persist between tool calls. Use the full resolved path (`"$kpxc_bin"`)
in every subsequent Bash block — do not rely on `PATH`. If `kpxc-agent` is already on PATH,
use it directly and skip this block entirely.

Either way it needs `jq`, `python3`, and `libsodium` on the machine where it runs (these
are system packages, not bundled). Source and full docs:
<https://github.com/max-win-at/keepassxc-cli-integration>.

## The secret-handling rule (read this first)

Secrets must never land in a place that gets logged, echoed, or committed — and your
transcript is such a place. Anything a command prints to stdout that you do not capture
becomes part of your context. The whole point of this tool is that secrets stay in
process memory for one command and vanish. So:

- **A secret reaches you only through `--field`, captured into a shell variable.**
  Never run a secret-producing command bare — `kpxc-agent get-logins URL --field
  password` on its own line puts the password in the transcript, on disk, and in any
  log of this session. Always assign it instead:

  ```bash
  pw=$(kpxc-agent get-logins URL --field password)
  ```

- **`--json` is metadata only.** It returns `uuid`, `name`, `login`, `group` — it
  cannot return a password or TOTP by design. Use it to *choose* among matches, then
  fetch the chosen one:

  ```bash
  kpxc-agent get-logins https://host.example --json            # safe to read/show
  pw=$(kpxc-agent get-logins https://host.example --field password --entry-uuid <uuid>)
  ```

- The `KEY=value` default output is for `eval "$(…)"` only, and `eval` keeps the value
  in memory. Don't capture it into a variable you then print.
- Never `echo "$pw"`, never pass a secret on a visible command line where another
  recipe would do, never write it to a file the user didn't ask for.
- The association identifiers (`KPXC_ASSOC_ID` / `KPXC_ASSOC_KEY`) are **not** secret —
  they're safe to store in a profile or pass over SSH. Only the fetched
  usernames/passwords/TOTPs are sensitive.

## Step 1 — Check reachability

Run `kpxc-agent doctor` **once** when first setting up, or when troubleshooting a
connectivity problem. Skip it if reachability was already confirmed in this session.

```bash
kpxc-agent doctor
```

This reports `jq`/`python3`/`libsodium`, the chosen transport (local socket, proxy
relay, or a forwarded socket), and whether KeePassXC answers. If it can't find the
socket, KeePassXC isn't running or Browser Integration is disabled — tell the user.

`doctor` checks transport only; it does NOT verify that the database is unlocked. A
locked database still has an open socket, so `doctor` can succeed while the DB is
locked. That's fine: credential commands automatically send `triggerUnlock` to
KeePassXC (matching browser-extension behavior), so KeePassXC will show its unlock
dialog and wait for the user before returning credentials.

Nor does `doctor` tell you *which* vault is open — KeePassXC answers for whichever
database is currently active. If the user has more than one, or the task depends on a
specific vault, confirm it up front with `kpxc-agent db-info` (Step 5) instead of
discovering the mismatch as a failed lookup later.

## Step 2 — One-time pairing (association)

KeePassXC only talks to clients it has approved. Pairing happens **once** and requires
a human to click "Allow" in a KeePassXC dialog — you cannot complete it unattended:

```bash
eval "$(kpxc-agent --trigger-unlock associate)"
```

`kpxc-agent` saves the pairing itself, per database, in a local config file, and
reloads it automatically on later runs — so **you normally never need to think about
association at all**:

```
$HOME/.config/keepassxc-cli-agent/associations.json
```

The two non-secret `export` lines it prints are an override, useful for CI or for passing
identity over SSH (see `references/remote-ssh.md`); they are not a prerequisite. Verify
an existing pairing with `kpxc-agent test`.

Pairing is per database: a vault that has never been paired will pop an approval dialog
the first time you read from it. If a command exits with code 4 ("no/invalid
association"), the stored pairing doesn't match the open database — re-run `associate`.

## Step 3 — Common recipes

**Constructing the lookup URL**: KeePassXC matches credentials by URL — not by service name
or keyword. Always build an explicit `https://` URL before calling `get-logins` or
`set-login`:

- If the user says "the GitHub password" → use `https://github.com`
- If the user says "myserver.local postgres" → use `https://myserver.local`
- If you don't know the exact URL stored in KeePassXC → **ask the user** before
  proceeding: *"What URL is this credential stored under in KeePassXC?"*

A service name without a proper domain (e.g. `github` instead of `github.com`) will not
match even with `https://` prepended. `kpxc-agent` auto-prepends `https://` to bare
hostnames as a safety net, but you must still supply the correct domain.

You cannot know how the user organized their vault, so treat your URL as a guess: if it
doesn't match, `kpxc-agent probe` (Step 5) tells you which variants do — don't give up
on the first miss.

**Fetch a single password (most common):**
```bash
pw=$(kpxc-agent get-logins https://host.example --field password)
```

A lookup that matches nothing exits **6** — it does not return an empty string. See
Step 5; do not treat it as "no credential exists".

**Fetch the whole entry into shell vars:**
```bash
eval "$(kpxc-agent get-logins https://host.example)"
# now $KPXC_USERNAME and $KPXC_PASSWORD are set (in memory only)
```

**Choose among several matches** — list them as metadata, then fetch the one you want:
```bash
kpxc-agent get-logins https://host.example --json
# [{"uuid":"a1…","name":"Box prod","login":"admin"},{"uuid":"b2…","name":"Box staging",…}]
pw=$(kpxc-agent get-logins https://host.example --field password --entry-uuid a1…)
```
`--index N` (0-based) works too. Without a selector, `--field` reads the first match and
the default output switches to `KPXC_COUNT=N` plus indexed `KPXC_USERNAME_0` /
`KPXC_PASSWORD_0` …. If the entry names alone don't make the right choice obvious, show
the user the `--json` list and ask — it contains no secrets.

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
| 2 | KeePassXC unreachable (no socket / Browser Integration disabled) | ask the user to start KeePassXC and enable Browser Integration; re-run `doctor` |
| 3 | request refused, cancelled, or locked | the user declined the dialog or the DB locked — ask them |
| 4 | no/invalid association for the open database | re-run `associate` (needs a click) |
| 5 | protocol or crypto failure | likely a version/transport issue; check `doctor`, retry with `--debug` |
| 6 | **no entry matched** — reachable, unlocked, paired, but nothing found | **Step 5.** Never treat as "no such credential" |
| 7 | `wait-db` timed out | the user didn't switch/unlock in time — ask again |
| 64 | bad command-line usage | fix the command |

## Step 5 — When a lookup comes back empty (do NOT fall back)

Exit 6 means KeePassXC was reachable, unlocked and paired — and still found nothing.
There are exactly two causes, and you cannot tell them apart without asking:

1. **The wrong vault is open.** The user has several `.kdbx` files; the one holding this
   credential isn't the active one.
2. **The URL doesn't match what's stored.** A typo, a different format, or the entry's
   URL field is empty.

Neither is a reason to give up, and **neither is a reason to substitute something else**.
Do not invent a password, do not fall back to preconfigured environment variables, do not
ask the user to paste the secret into the chat, and do not silently skip the step. A
missing credential is a pause, not a failure — especially inside a longer provisioning
run, where continuing with the wrong secret is worse than stopping.

Work the loop:

**1. Find out which vault is actually open.**
```bash
kpxc-agent db-info
# database: open
# hash:     3f9a1c…
# name:     Personal Vault      <- root group name; KeePassXC names it after the database
# paired:   yes (association store)
```

**2. Find out whether any URL variant matches.** `probe` takes several URLs, reports how
many entries each matched and what they're called, and never prints a secret:
```bash
kpxc-agent probe https://box.example https://example.com https://www.box.example http://box.example
```
Build the variant list from the URL you tried: the registrable domain with subdomains
stripped, with and without `www.`, `http://` instead of `https://`, and the bare host
with any path or port removed.

**3. Tell the user both facts and ask one question.** Give them what only they can
resolve — don't make them guess what you tried:

> The vault currently open in KeePassXC is **Personal Vault** (`3f9a1c…`). I couldn't
> find an entry for `https://box.example` there — I also tried `https://example.com`,
> `https://www.box.example` and `http://box.example`, all no match.
>
> Either open the vault that holds this credential, or check the entry's URL field in
> KeePassXC. Tell me when to retry.

**4. If they're switching vaults, wait for it** rather than failing and making them
restart the task. This blocks until the active database actually changes:
```bash
kpxc-agent wait-db --changed --timeout 300     # prints the new hash, exit 7 on timeout
```
Then go back to step 1 to confirm the new vault, and retry the original lookup. If
they're editing an entry in the *current* vault instead, just retry when they say so.

**5. Retry up to three times.** After the third failure, stop and report the blocker
plainly — what you searched for, which vault, which variants. Never continue the larger
task with a substitute secret.

> Note: `get-logins --allow-empty` turns exit 6 back into exit 0 with no output. Use it
> only for a genuine existence check — "create this entry if it doesn't exist yet" —
> never to make a failed lookup quiet.

## Remote / SSH (agent on a different box than KeePassXC)

When `kpxc-agent` runs on a remote box but KeePassXC runs on the machine the user sits
at (VS Code Remote SSH, or an ssh-driven agent), the box has no local KeePassXC. The
fix is a reverse-forwarded socket: run `kpxc-agent serve-bridge` on the client and
`ssh -R` it to the box. This is a common setup — read **`references/remote-ssh.md`**
for the exact commands for Linux/macOS and Windows/WSL clients.

## Going deeper

- **`references/commands.md`** — every command, all options, transport overrides.
- Wire protocol (rarely needed): the repo's `keepassxc-cli-agent-protocol.md`.
