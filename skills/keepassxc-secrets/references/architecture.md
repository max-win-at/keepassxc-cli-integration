# kpxc-agent architecture and security model

Technical reference for developers and security auditors. It explains how the tool
is built, how the encrypted channel works, and — most importantly — the design
decisions that keep secrets from leaking into logs, transcripts, and agent context.
The user-facing surface is covered in `SKILL.md` and `references/commands.md`.

## Components

```
kpxc-agent              bash entry point: argument parsing, output shaping, exit codes
scripts/lib/kpxc_channel.py   crypto + transport: crypto_box channel, socket/proxy/exec I/O
scripts/lib/kpxc_bridge.py    serve-bridge: TCP/unix relay for SSH reverse-forwarding
```

`kpxc-agent` is a single bash script plus a small Python helper that uses only the
standard library and talks to `libsodium` through `ctypes` — no pip dependencies,
no virtualenv, nothing that needs a compiler at install time. The script resolves
`lib/` relative to its own real location (following symlinks via `readlink -f`),
so it behaves identically when invoked from a clone, from a symlink in `~/.local/bin`,
or from inside an installed skill bundle.

## The encrypted channel

`kpxc-agent` speaks KeePassXC's browser-integration protocol — the same protocol as
the `keepassxc-browser` extension, over the same transports. KeePassXC is unmodified.

- Messages are encrypted with libsodium `crypto_box` (Curve25519 + XSalsa20-Poly1305),
  the same construction the extension uses via TweetNaCl.js.
- Each invocation generates a fresh session key pair; secret keys are never transmitted.
- Nonces are 24 random bytes; the reply nonce must equal the request nonce incremented
  as a little-endian integer with carry (libsodium `sodium_increment`).
- Three key pairs are involved: KeePassXC's temporary host key, the agent's per-run
  session key, and the persistent identification key created at `associate` time.

Full wire format and message catalogue:
[keepassxc-cli-agent-protocol.md](https://github.com/max-win-at/keepassxc-cli-integration/blob/main/keepassxc-cli-agent-protocol.md).

## Transports

If no override is given, the agent picks a transport in this order:

1. A local unix socket, if one is reachable:
   `$KPXC_SOCKET` → `$XDG_RUNTIME_DIR/org.keepassxc.KeePassXC.BrowserServer` →
   `$TMPDIR/...` → `/tmp/...` (including Flatpak paths). The direct BrowserServer
   socket speaks bare JSON — no length framing.
2. Otherwise, a `keepassxc-proxy` relay, which wraps the same messages in
   native-messaging framing (4-byte little-endian length prefix) over stdio:
   - Windows: `keepassxc-proxy.exe` under `C:\Program Files\KeePassXC` (reachable from WSL)
   - Other platforms: `keepassxc-proxy` on `PATH`

Overrides: `--socket PATH` (a unix socket, e.g. an SSH-forwarded one), `--exec CMD`
(a proxy command spoken to over stdio), `--proxy CMD` (a relay to connect to).

`serve-bridge` listens on `127.0.0.1:19455` (or a unix socket with
`--listen unix:PATH`) and relays bytes to whatever backend it was pointed at,
converting framing in both directions when the backend is a framed proxy. It exists
for the SSH reverse-forward topology (`ssh -R`) described in
[`remote-ssh.md`](remote-ssh.md). The relay is byte-shuttling only — the crypto_box
channel remains end-to-end between the agent process and KeePassXC; a forwarded or
relayed hop never sees plaintext.

## Association identity

After a human approves the pairing dialog, KeePassXC assigns the agent an identity
pair `(id, idKey)`: a connection name and the public half of the identification key
pair.

**Neither value is secret.** The `idKey` is a public key; the protocol only ever uses
its public half after association (a known quirk it inherits from the browser
protocol). Leaking the pair lets another process *ask* KeePassXC for credentials
under the same connection name — but that process could equally pair itself with
its own key and a social-engineered approval click. The pair is therefore safe to
store on disk, keep in CI variables, or pass through `SendEnv` over SSH.

By default `associate` persists the pair keyed by database hash in
`${XDG_CONFIG_HOME:-$HOME/.config}/keepassxc-cli-agent/associations.json` with mode
`600` — the same on-disk model as the browser extension's keyRing. Every later
command reloads it and verifies it with `test-associate` before doing anything else,
so pairing happens once per database. `KPXC_ASSOC_ID` / `KPXC_ASSOC_KEY` in the
environment override the store, which serves ephemeral contexts (CI, one-shot SSH
commands) where a config file is unwanted.

## Secret-hygiene design

The tool is built for callers that log everything — terminal scrollback, CI logs,
and above all an AI agent's transcript. The design rule: **a secret can leave the
process only through `--field`, captured into a variable.** Everything else is
deliberately constructed so its output is safe to show.

| Output path | Guarantee |
|-------------|-----------|
| `get-logins --json` | Allowlisted metadata projection (`uuid`, `name`, `login`, `group`, `expired`). Structurally cannot contain a password or TOTP. |
| `probe` | Per-URL match counts and entry names only. |
| `db-info` | Database hash, name, paired status. No entry data. |
| `--debug` / `KPXC_AGENT_DEBUG=1` | Prints the plaintext request for troubleshooting — with the password value masked. |
| default `KEY=value` output | Shell-evalable by design (`eval "$(...)"`), so the value passes through memory, not through a printed line. |

Complementing that, **a lookup that matches nothing is loud**: exit code `6`, an
empty stdout, and a stderr message naming the URL and the database searched. An
automated caller cannot mistake "not found" for "no credential exists" and invent a
substitute. `--allow-empty` restores a quiet exit 0 for genuine existence checks.

The exit-code contract in full:

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

## Security considerations

- **Vault-side controls still apply.** KeePassXC's own settings — unlock prompts,
  per-entry browser-integration allowlists, "remember" decisions for access
  requests — are the actual access-control plane. The agent triggers them; it does
  not bypass them.
- **Pairing requires a human.** `associate` is useless without the approval click
  in KeePassXC; an agent cannot bootstrap access to a vault unattended.
- **Local socket = local trust.** Anyone with access to the user's account can talk
  to the BrowserServer socket; that is KeePassXC's browser-integration trust model,
  unchanged by this tool.
- **Memory, not disk.** Fetched secrets live in the calling process's environment
  for the lifetime of one command. The tool writes no secret to any file, ever.
- **The transcript is the main threat.** Every guarantee above exists because the
  primary consumer is an AI agent whose stdout is logged verbatim. The redactions
  are not conveniences; they are the security boundary.

## Testing

The suite in the repo's [`tests/`](https://github.com/max-win-at/keepassxc-cli-integration/tree/main/tests)
directory runs fully offline against a mock KeePassXC that implements the real
transport, handshake, per-connection `test-associate` requirement, and ack frames.
It explicitly asserts the hygiene guarantees above: `--json` carrying no password,
`--debug` masking one, a miss exiting 6, and `wait-db` unblocking on a database
switch. See [`tests/README.md`](https://github.com/max-win-at/keepassxc-cli-integration/blob/main/tests/README.md).
