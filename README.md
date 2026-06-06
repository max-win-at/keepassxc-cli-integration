# KeepassXC CLI Integration _kpxc-agent_

A command-line client for the **KeePassXC browser-integration protocol**. It speaks
the same encrypted protocol as the `keepassxc-browser` extension, but with no
browser and no UI — built for headless / AI-agent use such as commissioning a
Linux box (server or SBC) from VS Code, locally or over `ssh`.

During commissioning an agent often needs secrets. The convention is that secrets
live in KeePassXC and are fetched through its *Browser Integration* feature; this
tool is that feature for the terminal.

## How it works

This tool speaks KeePassXC's browser-integration protocol directly. Messages use
native-messaging framing — a **4-byte little-endian length prefix + JSON** — and
every message after the handshake is encrypted with `crypto_box`
(Curve25519 + XSalsa20-Poly1305), exactly as the extension does.

Two components:

| File                 | Language | Role                                                                 |
|----------------------|----------|---------------------------------------------------------------------|
| `kpxc-agent`         | bash     | The CLI. Builds protocol messages (`jq`), formats output, exit codes |
| `lib/kpxc_channel.py`| python3  | A tiny, protocol-agnostic encrypted pipe (framing + handshake + `crypto_box`) |

The python helper knows *nothing* about individual actions — it just provides the
secure channel. All protocol logic lives in the bash script.

**Transport** is auto-detected:

- **Local KeePassXC** (same machine, e.g. a Linux box): connect directly to its unix
  socket `org.keepassxc.KeePassXC.BrowserServer`.
- **Otherwise** (no local socket): relay through **`keepassxc-proxy`**, KeePassXC's own
  native-messaging proxy, over its stdio. This is what lets a tool running in **WSL
  reach a KeePassXC running on Windows** — WSL execs the Windows `keepassxc-proxy.exe`,
  which handles the named pipe.

Override with `--socket PATH`, `--proxy`, or `--exec CMD` (see below).

## Install

`kpxc-agent` is a single script plus a small python helper in `lib/`. It resolves `lib/`
relative to its own real location (following symlinks), so symlink it onto your `PATH` —
or add the repo dir directly:

```bash
git clone https://github.com/max-win-at/keepassxc-cli-integration.git
ln -s "$PWD/keepassxc-cli-integration/kpxc-agent" ~/.local/bin/kpxc-agent  # or: export PATH="$PWD/keepassxc-cli-integration:$PATH"
kpxc-agent doctor
```

For agent/AI use, an Agent Skill that teaches this CLI lives in
[`skills/keepassxc-secrets/`](skills/keepassxc-secrets/SKILL.md).

### Installing the skill

**Harnesses with [agentskill.sh](https://agentskill.sh)** (Claude Code, Copilot CLI, Gemini CLI):

Once published, one command installs it:
```
/learn @maxwin/keepassxc-secrets
```
Until published: copy the `skills/keepassxc-secrets/` directory into your harness's skills
directory (e.g. `~/.claude/skills/` for Claude Code) and the harness will pick it up.

**Harnesses without agentskill.sh** (Cursor, Codex CLI, bare Copilot, etc.):
Paste the contents of `skills/keepassxc-secrets/SKILL.md` into the harness's
custom-instructions or rules file.

## Prerequisites

- **`jq`** — `dnf install jq` · `apt install jq` · `pacman -S jq` · `apk add jq`
- **`python3`** — standard on every distro (uses only the standard library)
- **`libsodium`** — `dnf install libsodium` · `apt install libsodium23` · `pacman -S libsodium` · `apk add libsodium`
- **KeePassXC** running, with **Browser Integration enabled**
  (Settings → Browser Integration → *Enable browser integration*).
- For the relay transport (e.g. WSL → Windows), **`keepassxc-proxy`** — it ships with
  KeePassXC, so it is already present wherever KeePassXC is installed.

Run `./kpxc-agent doctor` to check all of these and the transport to KeePassXC.

## Quick start

```bash
# 1. One-time pairing. KeePassXC pops a dialog asking you to name the connection.
#    This prints two non-secret values (an id + a public key) to capture:
eval "$(./kpxc-agent --trigger-unlock associate)"
# or copy/paste the printed `export KPXC_ASSOC_ID=...` / `export KPXC_ASSOC_KEY=...`

# 2. Fetch a secret (default output is shell-evalable):
eval "$(./kpxc-agent get-logins https://host.example)"
echo "$KPXC_USERNAME / $KPXC_PASSWORD"

# ...or grab a single field:
pw=$(./kpxc-agent get-logins https://host.example --field password)
```

## Identity & the two deployment topologies

The persistent identity is just two environment variables:

- `KPXC_ASSOC_ID`  — the connection id KeePassXC assigned during `associate`
- `KPXC_ASSOC_KEY` — the association **public** key

Neither is secret (KeePassXC only ever stores/uses the public key), so they are
safe to keep in a shell profile, a CI secret, or pass over `ssh`.

**Agent runs on the box** (VS Code remote): `associate` once on the box, drop the
two `export` lines into the user's profile, done.

**Agent drives the box over `ssh`** (fallback when no remote server can be
installed): associate on the machine where KeePassXC runs, then forward the two
vars to the remote command, e.g.

```bash
KPXC_ASSOC_ID=$KPXC_ASSOC_ID KPXC_ASSOC_KEY=$KPXC_ASSOC_KEY \
  ssh box 'kpxc-agent get-logins https://host.example --field password'
# or configure SendEnv KPXC_ASSOC_* in ~/.ssh/config with AcceptEnv on the host
```

(Note: KeePassXC itself must be reachable from wherever `kpxc-agent` runs — i.e.
its socket must be on that machine. Use `--socket PATH` if it is in a non-default
location. When the agent runs on a **remote box** while KeePassXC stays on your
local machine, see *Reaching KeePassXC across SSH* below.)

## Reaching KeePassXC across SSH (remote agent)

In two common setups the agent runs on a **remote box** but KeePassXC runs on the
**client** you sit at:

- **VS Code Remote SSH** — the agent's terminal runs on the box; KeePassXC is local.
- **Classic SSH** (an agent CLI driving the box over `ssh`, kept alive with
  `tmux`/`screen`) — same split.

Neither the local socket nor a local `keepassxc-proxy` exists on the box, so the
agent there cannot reach your KeePassXC. The fix is **`ssh -R`**: the client already
opens an outbound SSH connection to the box, and OpenSSH (≥ 6.7) can reverse-forward
a socket back over it — no inbound connectivity to the client, no new network
service. `serve-bridge` exposes your local KeePassXC on an endpoint that `ssh -R`
forwards, and the box's plain `kpxc-agent --socket <forwarded>` talks straight to it.
The encrypted channel stays end-to-end between the box and KeePassXC; the bridge only
shuttles bytes.

```
[client] KeePassXC ──▶ kpxc-agent serve-bridge ──127.0.0.1:19455──▶ ssh -R ──▶ [box] /run/.../kpxc.sock
                                                                                      ▲
                                                  kpxc-agent --socket /run/.../kpxc.sock get-logins …
```

**Pairing happens once, on the client** (only there can KeePassXC show its approve
dialog). Run `associate` on the client, then forward the two **non-secret**
`KPXC_ASSOC_*` vars to the box — inline, via `SendEnv`/`AcceptEnv`, or by dropping
the `export` lines into the box's profile (see *Identity* above).

### Linux / macOS client

KeePassXC already exposes a unix socket, so you can forward it **with no bridge and
no extra code** — just `ssh -R` the raw socket:

```bash
# client → box; map the box-side socket onto your local KeePassXC socket:
ssh -R /run/user/1000/kpxc.sock:"$XDG_RUNTIME_DIR/org.keepassxc.KeePassXC.BrowserServer" box
# on the box:
KPXC_ASSOC_ID=… KPXC_ASSOC_KEY=… \
  kpxc-agent --socket /run/user/1000/kpxc.sock get-logins https://host --field password
```

Or, for the same uniform command as every other OS, run the bridge instead:

```bash
# on the client:
kpxc-agent serve-bridge                       # listens on 127.0.0.1:19455
# connect with:  ssh -R /run/user/1000/kpxc.sock:127.0.0.1:19455 box
```

### Windows / WSL client

KeePassXC speaks a **named pipe** here, not a unix socket, so `ssh -R` can't target
it directly — run the bridge, which relays through `keepassxc-proxy.exe`:

```bash
# on the client (inside WSL, so 127.0.0.1 is shared with the ssh you run from WSL):
kpxc-agent serve-bridge                       # auto-selects keepassxc-proxy.exe
# from the same WSL shell:
ssh -R /run/user/1000/kpxc.sock:127.0.0.1:19455 box
```

(If your KeePassXC is installed in a non-default location, point the bridge at it with
`KPXC_WIN_KEEPASSXC` / `--exec`, exactly as in *Reaching a KeePassXC running on
Windows, from WSL* below.)

### Wiring it into VS Code Remote SSH

Put the forward and the identity passthrough in `~/.ssh/config` (VS Code Remote SSH
uses your system `ssh`), start the bridge on the client before connecting, and set
`KPXC_SOCKET` on the box:

```ssh-config
Host box
    RemoteForward /run/user/1000/kpxc.sock 127.0.0.1:19455
    SendEnv KPXC_ASSOC_ID KPXC_ASSOC_KEY
    # box's sshd needs: AcceptEnv KPXC_ASSOC_*  and  StreamLocalBindUnlink yes
```

Then on the box (e.g. in the profile or VS Code's terminal env):
`export KPXC_SOCKET=/run/user/1000/kpxc.sock`. The classic-SSH case is identical —
the same `RemoteForward`, just on your interactive `ssh box` session.

> `StreamLocalBindUnlink yes` in the box's `sshd_config` lets a reconnect reclaim a
> stale forwarded socket. On a Windows/WSL client, run both `serve-bridge` and `ssh`
> inside WSL so they share `127.0.0.1`.

## Commands

| Command                              | Output                                              |
|--------------------------------------|-----------------------------------------------------|
| `associate`                          | `export KPXC_ASSOC_ID=…` / `KPXC_ASSOC_KEY=…`        |
| `test`                               | Validity of the current association                 |
| `get-logins URL [opts]`              | `KPXC_USERNAME=…` / `KPXC_PASSWORD=…` (see below)    |
| `get-totp UUID`                      | `KPXC_TOTP=…`                                        |
| `generate-password`                  | `KPXC_PASSWORD=…`                                    |
| `set-login URL --username U --password P [...]` | `Saved.`                                 |
| `groups [--json]`                    | `uuid<TAB>group/path` per line                       |
| `create-group NAME`                  | `uuid<TAB>name`                                      |
| `lock`                               | locks the database                                  |
| `hash`                               | active database hash                                |
| `serve-bridge [--listen ADDR]`       | expose local KeePassXC for `ssh -R` (run on the client) |
| `doctor`                             | prerequisite / socket check                          |

`get-logins` options: `--submit-url URL`, `--http-auth`,
`--field username|password|name|uuid|totp` (print one raw value),
`--json` (raw entries array). Default emits shell-evalable `KEY=value` lines —
single match unprefixed, multiple matches as `KPXC_COUNT=N` plus indexed
`KPXC_USERNAME_0`, `KPXC_PASSWORD_0`, … Values are single-quote-escaped so
`eval "$(...)"` is safe even for passwords containing quotes or spaces.

Transport options (auto-detected; override only when needed):
`--socket PATH` (env `KPXC_SOCKET`) connect to a unix socket directly;
`--proxy` relay through an auto-detected `keepassxc-proxy`;
`--exec CMD` (env `KPXC_EXEC`) use a specific relay command's stdio.
Other global options: `--trigger-unlock` (prompt KeePassXC to unlock a locked
database), `--debug` (env `KPXC_AGENT_DEBUG=1`).

### Reaching a KeePassXC running on Windows, from WSL

WSL can't open a Windows named pipe directly, so it relays through the Windows
`keepassxc-proxy.exe`. Auto-detection finds it under `C:\Program Files\KeePassXC`
when no local socket exists, so usually it just works:

```bash
./kpxc-agent doctor                 # should report "reachable through relay"
./kpxc-agent --trigger-unlock associate
```

If KeePassXC is installed elsewhere, point at it with either:

```bash
export KPXC_WIN_KEEPASSXC='/mnt/c/Program Files/KeePassXC'   # dir containing keepassxc-proxy.exe
# or, explicitly:
./kpxc-agent --exec "'/mnt/d/Apps/KeePassXC/keepassxc-proxy.exe'" get-logins https://host
```

## Exit codes

| Code | Meaning                                            |
|------|----------------------------------------------------|
| 0    | success                                            |
| 2    | KeePassXC unreachable / database not opened        |
| 3    | request refused, cancelled, or locked              |
| 4    | no / invalid association (set `KPXC_ASSOC_*`)       |
| 5    | protocol or crypto failure                         |
| 64   | bad command-line usage                             |

## Security notes

- `get-logins` prints secrets to stdout. Capture into a variable (`pw=$(... --field
  password)`) or `eval` directly; avoid logging the output. Prefer `--field` /
  `--json` over the default in scripts that might end up in logs.
- The association vars are *not* secret; the actual secrets never touch disk and
  are only held in memory for the duration of a command.
- Each invocation generates fresh ephemeral session keys (matching the extension);
  nothing about the encrypted channel persists between calls.

## Transport resolution

When neither `--socket`/`--exec`/`--proxy` is given, the transport is chosen as:

1. A local unix socket if one exists: `$KPXC_SOCKET` →
   `$XDG_RUNTIME_DIR/org.keepassxc.KeePassXC.BrowserServer` → `$TMPDIR/...` → `/tmp/...`
   (plus the Flatpak path `$XDG_RUNTIME_DIR/app/org.keepassxc.KeePassXC/...`).
2. Otherwise a `keepassxc-proxy` relay — the Windows `keepassxc-proxy.exe` under
   `C:\Program Files\KeePassXC` (reachable from WSL), else a `keepassxc-proxy` on `PATH`.

## Tests

```bash
bash tests/selftest.sh
```

Runs fully offline: the libsodium binding, a `crypto_box` round-trip, nonce-increment
vectors, `doctor`, and a full **end-to-end flow against a mock KeePassXC**
(`tests/mock_kpxc.py`) that reproduces the real framing, the per-connection
`test-associate` requirement, and the `generate-password` ack frame. No running
KeePassXC needed. For a live check, see *Quick start*.

## Protocol

See `keepassxc-cli-agent-protocol.md` for the wire protocol (adapted from the
extension's `keepassxc-protocol.md`).
