# kpxc-agent — KeePassXC secrets for AI agents

[![skills.sh](https://skills.sh/b/max-win-at/keepassxc-cli-integration)](https://skills.sh/max-win-at/keepassxc-cli-integration)
[![agentskill.sh](https://img.shields.io/badge/agentskill.sh-%40maxwin%2Fkeepassxc--secrets-181717)](https://agentskill.sh/@maxwin/keepassxc-secrets)

AI agents need credentials — for the box they are commissioning, the database they
are wiring up, the service they are deploying. The usual answers all put the secret
somewhere it should not be: pasted into a chat transcript, dropped into a `.env`
file, exported into a CI variable that outlives the job.

`kpxc-agent` takes a different route. It speaks the same end-to-end encrypted
protocol as the KeePassXC browser extension — but for the terminal, with no
browser and no UI. Your agent asks your vault, the vault answers, and the secret
lives in process memory for exactly one command. It never reaches a log, a
transcript, or a dotfile.

```bash
pw=$(kpxc-agent get-logins https://host.example --field password)
```

Pair once; every later fetch, generation, or store runs unattended.

## Why it is safe

- 🔐 **Encrypted like the browser extension.** The same `crypto_box`
  end-to-end channel the `keepassxc-browser` extension uses; KeePassXC stays
  unmodified, and its own prompts and access settings still apply.
- 🚫 **Secrets stay out of logs.** Listing output (`--json`, `probe`) is metadata
  only — a password can leave the tool solely through `--field`, captured into a
  variable. `--debug` masks secret values.
- 🎯 **No silent misses.** A lookup that matches nothing exits `6` naming the
  vault it searched — an automated caller cannot mistake "not found" for "no
  credential" and invent a substitute.
- 🧭 **Wrong-vault recovery.** `db-info` identifies the active database and
  `wait-db` blocks until the user opens the right one, so a task can retry
  instead of aborting.
- 🔑 **Pairing needs a human.** Access is granted once, through KeePassXC's own
  approval dialog — an agent cannot bootstrap itself into your vault.

For the full security model — transports, association identity, threat
reasoning — see the [architecture and security reference](skills/keepassxc-secrets/references/architecture.md),
written for reviewers and auditors.

## Features

- 📥 **Fetch credentials**: usernames, passwords, and TOTP codes for any stored entry.
- 🔑 **Generate passwords**: create secure passwords using KeePassXC's built-in generator.
- 💾 **Store credentials**: save new or updated credentials directly to the vault.
- 📁 **Group management**: list, create, and organize groups within the database.
- 🌐 **Cross-platform**: Linux, macOS, and Windows (WSL or native).
- 🔄 **Remote SSH**: drive a remote box while KeePassXC stays on your machine —
  see [remote SSH setup](skills/keepassxc-secrets/references/remote-ssh.md).
- 🛠️ **Agent skill**: a bundled [SKILL.md](skills/keepassxc-secrets/SKILL.md)
  teaches any AI harness (Claude Code, Copilot CLI, Cursor, …) to use it safely.

## Install

The tool ships inside the agent skill — installing the skill installs the CLI.

**via [skills.sh](https://skills.sh)** (Vercel) — any agent supported by the
`skills` CLI (Claude Code, Cursor, Codex, Copilot, Windsurf, …):

```bash
npx skills add max-win-at/keepassxc-cli-integration --skill keepassxc-secrets
```

**via [agentskill.sh](https://agentskill.sh)** — harnesses with the `/learn`
command (Claude Code, Copilot CLI, Gemini CLI, Cursor, Codex CLI, …):

```
/learn @maxwin/keepassxc-secrets
```

If your harness does not have `/learn` yet, add it first with
`npx @agentskill.sh/cli@latest setup`.

**Standalone CLI:**

```bash
git clone https://github.com/max-win-at/keepassxc-cli-integration.git
ln -s "$PWD/keepassxc-cli-integration/skills/keepassxc-secrets/scripts/kpxc-agent" ~/.local/bin/kpxc-agent
kpxc-agent doctor
```

**Prerequisites** — `jq`, `python3` (stdlib only), and `libsodium`
(`apt install jq libsodium23` · `dnf install jq libsodium` · `pacman -S jq libsodium`
· `apk add jq libsodium`), plus KeePassXC running with *Browser Integration*
enabled. `keepassxc-proxy` ships with KeePassXC and is already present wherever it
is installed. Run `kpxc-agent doctor` to check everything at once.

## Quick start

```bash
# 1. One-time pairing — KeePassXC pops a dialog asking you to name the
#    connection. The pairing is saved per database, so this is the only
#    interactive step you will ever see:
kpxc-agent associate

# 2. Fetch a secret. Default output is shell-evalable:
eval "$(kpxc-agent get-logins https://host.example)"
echo "$KPXC_USERNAME / $KPXC_PASSWORD"

#    ...or capture a single field. Never run this bare — an uncaptured
#    password ends up in your scrollback and in any agent's transcript:
pw=$(kpxc-agent get-logins https://host.example --field password)
```

**Several matches for one URL?** List them as metadata, then fetch the one you
picked — the list cannot carry a secret:

```bash
kpxc-agent get-logins https://host.example --json
# [{"uuid":"a1b2…","name":"Box prod","login":"admin"},{"uuid":"c3d4…","name":"Box staging",…}]
pw=$(kpxc-agent get-logins https://host.example --field password --entry-uuid a1b2…)
```

**A lookup found nothing?** It exits `6`, naming the vault it searched. Two causes,
two diagnostics:

```bash
kpxc-agent db-info                                    # which vault is actually open?
kpxc-agent probe https://host.example https://example.com  # which URL variants match?
kpxc-agent wait-db --changed                          # block while the user switches vaults
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | success |
| 2 | KeePassXC unreachable / database not opened |
| 3 | request refused, cancelled, or locked |
| 4 | no / invalid association for the open database |
| 5 | protocol or crypto failure |
| 6 | no entry matched — reachable, unlocked and paired, but nothing found |
| 7 | `wait-db` timed out |
| 64 | bad command-line usage |

## Documentation

- [Agent skill usage guide](skills/keepassxc-secrets/SKILL.md) — how an AI harness
  should drive the CLI, including the secret-handling rules.
- [Command reference](skills/keepassxc-secrets/references/commands.md) — every
  command and option.
- [Remote SSH setup](skills/keepassxc-secrets/references/remote-ssh.md) —
  reverse-forwarded sockets for VS Code Remote SSH and friends.
- [Architecture and security model](skills/keepassxc-secrets/references/architecture.md) —
  for developers and security auditors.
- [Wire protocol](keepassxc-cli-agent-protocol.md) — the encrypted message format.
- [Test suite](tests/README.md) — the offline self-test and its mock KeePassXC.
- [Changelog](CHANGELOG.md) — release history.

## License

[MIT](LICENSE)
