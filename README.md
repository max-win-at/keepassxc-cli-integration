# KeepassXC CLI Integration _kpxc-agent_

A command-line client for the **KeePassXC browser-integration protocol**. It speaks
the same encrypted protocol as the `keepassxc-browser` extension, but with no
browser and no UI — built for headless / AI-agent use such as commissioning a
Linux box (server or SBC) from VS Code, locally or over `ssh`.

During commissioning an agent often needs secrets. The convention is that secrets
live in KeePassXC and are fetched through its *Browser Integration* feature; this
tool is that feature for the terminal.

## Features

- 🔐 **Secure encrypted channel**: Uses `crypto_box` for end-to-end encryption, matching the browser extension’s security model.
- 🤖 **Headless/AI-agent use**: Enables automated credential fetching, generation, and storage without manual intervention.
- 🔍 **Auto-detected transport**: Supports direct unix sockets, `keepassxc-proxy` relay, or SSH forwarding for cross-platform access.
- 📥 **Fetch credentials**: Retrieve usernames, passwords, and TOTP codes for any stored entry.
- 🔑 **Generate passwords**: Create secure passwords using KeePassXC’s built-in generator.
- 💾 **Store credentials**: Save new or updated credentials directly to the vault.
- 🔄 **TOTP support**: Fetch time-based one-time passwords for entries with TOTP enabled.
- 📁 **Group management**: List, create, and organize groups within the KeePassXC database.
- 🌐 **Cross-platform**: Works on Linux, macOS, and Windows (via WSL or native).
- 🔄 **Remote SSH integration**: Access KeePassXC from a remote machine using reverse SSH forwarding.
- 🛠️ **Agent skill**: Bundled skill for AI harnesses (e.g., Claude Code, Copilot CLI) to fetch secrets programmatically.

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
#    The association is saved to disk automatically (see below), so you do not need
#    to capture anything for normal local use:
./kpxc-agent associate

# 2. Fetch a secret (default output is shell-evalable). No env setup needed — the
#    saved association is reused, and a locked/closed KeePassXC is prompted to unlock:
eval "$(./kpxc-agent get-logins https://host.example)"
echo "$KPXC_USERNAME / $KPXC_PASSWORD"

# ...or grab a single field:
pw=$(./kpxc-agent get-logins https://host.example --field password)
```

## Identity & deployment topologies

The identity is a pair `(id, idKey)` — a connection name assigned by KeePassXC and a
public association key. Neither is secret (the idKey is a public key), so it is safe to
store on disk, in CI secrets, or pass over SSH.

By default `associate` **persists this pair automatically**, keyed by database hash, in
`${XDG_CONFIG_HOME:-~/.config}/keepassxc-cli-agent/associations.json` (mode `600`) —
the same model as the browser extension's keyRing. Every later command reloads it,
verifies it with `test-associate`, and proceeds without re-prompting. Pair once and
never again for that database. `associate` still prints `export KPXC_ASSOC_ID=… /
KPXC_ASSOC_KEY=…` lines for environments that prefer explicit variables.

For ephemeral or no-home contexts (CI, SSH-forwarded commands), set the two variables
in the environment instead; **`KPXC_ASSOC_ID` / `KPXC_ASSOC_KEY` override the on-disk
store** when present:

- `KPXC_ASSOC_ID`: The connection ID assigned by KeePassXC during association.
- `KPXC_ASSOC_KEY`: The association public key.

**Deployment scenarios:**
- **Agent runs on the target machine**: Just `associate` once — it's persisted to disk; nothing else to set up.
- **Agent drives the machine over SSH**: Associate on the machine where KeePassXC runs, then forward the variables to remote commands. For example:
  ```bash
  KPXXC_ASSOC_ID=$KPXC_ASSOC_ID KPXC_ASSOC_KEY=$KPXC_ASSOC_KEY \
    ssh box 'kpxc-agent get-logins https://host.example --field password'
  ```
  Alternatively, configure `SendEnv KPXC_ASSOC_*` in `~/.ssh/config` with `AcceptEnv` on the host.

Note: KeePassXC must be reachable from wherever `kpxc-agent` runs. Use `--socket PATH` if the socket is in a non-default location. When the agent runs on a remote machine while KeePassXC remains local, see *Reaching KeePassXC across SSH* below.

## Reaching KeePassXC across SSH

When the agent runs on a remote machine (e.g., VS Code Remote SSH or a classic SSH session) but KeePassXC runs locally, the remote machine lacks direct access to the local socket or proxy. The solution is `ssh -R`, which reverse-forwards a socket over an existing SSH connection.

### Transport resolution
If no transport override (`--socket`, `--exec`, or `--proxy`) is provided, the agent selects the transport as follows:
1. A local unix socket, if available:
   - `$KPXC_SOCKET` → `$XDG_RUNTIME_DIR/org.keepassxc.KeePassXC.BrowserServer` → `$TMPDIR/...` → `/tmp/...` (including Flatpak paths).
2. Otherwise, a `keepassxc-proxy` relay:
   - Windows: `keepassxc-proxy.exe` under `C:\Program Files\KeePassXC` (accessible from WSL).
   - Other platforms: `keepassxc-proxy` on `PATH`.

### SSH forwarding setup

The encrypted channel remains end-to-end between the remote machine and KeePassXC; the bridge only shuttles bytes.

**Pairing must occur on the client machine**, as KeePassXC’s approval dialog cannot be displayed remotely. After pairing, forward the `KPXC_ASSOC_*` variables to the remote machine.

#### Linux/macOS client
- Forward the local socket directly:
  ```bash
  ssh -R /run/user/1000/kpxc.sock:"$XDG_RUNTIME_DIR/org.keepassxc.KeePassXC.BrowserServer" box
  ```
  On the remote machine:
  ```bash
  KPXC_ASSOC_ID=… KPXC_ASSOC_KEY=… \
    kpxc-agent --socket /run/user/1000/kpxc.sock get-logins https://host --field password
  ```
- Or use the bridge for uniformity:
  ```bash
  kpxc-agent serve-bridge  # Listens on 127.0.0.1:19455
  ssh -R /run/user/1000/kpxc.sock:127.0.0.1:19455 box
  ```

#### Windows/WSL client
- The bridge relays through `keepassxc-proxy.exe`:
  ```bash
  kpxc-agent serve-bridge  # Auto-detects keepassxc-proxy.exe
  ssh -R /run/user/1000/kpxc.sock:127.0.0.1:19455 box
  ```
- If KeePassXC is installed in a non-default location, point the bridge at it:
  ```bash
  export KPXC_WIN_KEEPASSXC='/mnt/c/Program Files/KeePassXC'
  kpxc-agent serve-bridge
  ```

#### VS Code Remote SSH
- Add the forward and identity passthrough to `~/.ssh/config`:
  ```ssh-config
  Host box
      RemoteForward /run/user/1000/kpxc.sock 127.0.0.1:19455
      SendEnv KPXC_ASSOC_ID KPXC_ASSOC_KEY
      # Remote sshd needs: AcceptEnv KPXC_ASSOC_* and StreamLocalBindUnlink yes
  ```
- On the remote machine, set:
  ```bash
  export KPXC_SOCKET=/run/user/1000/kpxc.sock
  ```

**Note**: `StreamLocalBindUnlink yes` in the remote machine’s `sshd_config` allows reconnects to reclaim stale forwarded sockets. On Windows/WSL, run both `serve-bridge` and `ssh` inside WSL to share `127.0.0.1`.

## Tests

```bash
bash tests/selftest.sh
```

Runs fully offline: the libsodium binding, a `crypto_box` round-trip, nonce-increment
vectors, `doctor`, and a full **end-to-end flow against a mock KeePassXC**
(`tests/mock_kpxc.py`) that reproduces the real framing, the per-connection
`test-associate` requirement, and the `generate-password` ack frame. No running
KeePassXC is needed. For a live check, see *Quick start*.
