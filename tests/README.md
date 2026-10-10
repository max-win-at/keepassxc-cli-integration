# Tests

Offline self-test suite for `kpxc-agent`. It validates the crypto channel and the
full command flow **end to end against a mock KeePassXC** — no running KeePassXC,
no network, no real vault is touched.

## Run

```bash
bash tests/selftest.sh
```

The script exits `0` when every check passes and prints a per-check `[PASS]` /
`[FAIL]` list plus a final tally. The end-to-end section additionally needs `jq`
(the same prerequisite as the tool itself); without it the unit checks still run
and the e2e section is skipped with a `[skip]` note.

## What it covers

**Unit checks** (no KeePassXC involved):

- The libsodium binding loads and produces a 32-byte `crypto_box` public key.
- A `crypto_box` encrypt/decrypt round-trip through the channel's own primitives.
- Nonce-increment vectors: little-endian carry, boundary carry, and full wrap.
- `doctor` runs and reports tool status.
- `--help` renders; an unknown command exits non-zero.

**End-to-end checks against the mock server** — these exercise the real code
paths: the bare-JSON transport the BrowserServer socket speaks, the
`crypto_box` handshake, the per-connection `test-associate` requirement, and the
`generate-password` ack frame:

- `associate` yields identity variables and persists them to the association store.
- `get-logins` returns an entry; a tricky password (`p'q"x y`) survives shell
  quoting and the `eval` round-trip exactly.
- `generate-password` returns the generated value across the ack frame.
- `groups` walks a nested group tree.
- A clean environment reuses the persisted association without env vars or
  re-pairing.
- `--json` lists matches as metadata with **no password or TOTP present**, and
  `--entry-uuid` / `--index` then select among the matches.
- A miss exits **6** with the URL named on stderr; `--allow-empty` restores exit 0;
  a `--json` miss prints `[]` and still exits 6.
- `probe` reports per-URL match counts without secrets and exits 6 when nothing
  matches.
- `db-info` names the open database (hash + root group).
- `wait-db` returns immediately for an already-active hash, times out with exit 7,
  and unblocks on a database switch.
- `--debug` masks the password in the plaintext it prints.
- A locked database triggers the unlock-wait flow and then returns credentials.
- `serve-bridge` relays a forwarded socket and converts framing toward a
  native-messaging proxy backend; the `--exec` relay speaks native-messaging
  framing over stdio.

## Isolation

The suite never touches real user state: all sockets are `mktemp` paths, and the
association store is redirected into a throwaway `XDG_CONFIG_HOME` (which also
lets the suite verify store-backed reuse). Mock processes and temp files are
cleaned up on every path.

## The mock server

`mock_kpxc.py` implements the server half of the browser-integration protocol
faithfully enough to exercise the real client code: bare-JSON transport, the
`crypto_box` handshake, per-connection association, ack frames, and a small
fixture vault. It is standalone (stdlib + libsodium) and doubles as a readable
reference implementation of the wire protocol.

Behavior knobs:

- `KPXC_MOCK_LOCKED=1` — starts "locked" and self-unlocks shortly after the first
  hash request (tests the unlock-wait flow).
- `KPXC_MOCK_HASH_SWITCH_AFTER=SECONDS` — flips the active database hash after a
  delay (tests `wait-db --changed`, standing in for the user switching vaults).
- `--proxy-stdio SOCKET` — instead of listening, acts as a `keepassxc-proxy`
  stand-in: reads native-messaging framing on stdin, relays to the bare-JSON
  socket, frames replies on stdout (tests the ExecTransport / WSL relay path).

For a live check against real KeePassXC, see the repo's *Quick start*.
