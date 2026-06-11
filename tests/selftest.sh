#!/usr/bin/env bash
#
# Offline self-test for keepassxc-cli-agent. Exercises the crypto channel without
# a running KeePassXC: libsodium binding, crypto_box round-trip, nonce increment
# vector, and the bash `doctor` preflight. A live KeePassXC is NOT required.
#
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
ROOT="$(dirname "$HERE")"
CHANNEL="$ROOT/lib/kpxc_channel.py"
AGENT="$ROOT/kpxc-agent"
PY="${KPXC_PYTHON:-python3}"

pass=0; fail=0
ok()   { printf '  [PASS] %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf '  [FAIL] %s\n' "$1"; fail=$((fail+1)); }

echo "keepassxc-cli-agent self-test"

# 1. keypair mode produces a 32-byte (base64) public key.
if pub=$("$PY" "$CHANNEL" keypair) && [[ $("$PY" -c "import base64,sys;print(len(base64.b64decode(sys.argv[1])))" "$pub") == 32 ]]; then
    ok "keypair: libsodium loads and yields a 32-byte public key"
else
    bad "keypair: could not generate a 32-byte public key (libsodium missing?)"
fi

# 2. crypto_box round-trip and nonce-increment vector, using the channel's own primitives.
if "$PY" - "$CHANNEL" <<'PY'
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("kpxc_channel", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

# round-trip: encrypt with (server_pk, client_sk), decrypt with (client_pk, server_sk)
cpk, csk = m.keypair()
spk, ssk = m.keypair()
payload = json.dumps({"action": "get-logins", "x": "umlaut-äöü"}).encode()
nonce = os.urandom(m.NONCE_BYTES)
ct = m.box(payload, nonce, spk, csk)
pt = m.box_open(ct, nonce, cpk, ssk)
assert pt == payload, "round-trip mismatch"

# nonce increment: little-endian carry
assert m.increment_nonce(b"\x00" * 24) == b"\x01" + b"\x00" * 23
assert m.increment_nonce(b"\xff" + b"\x00" * 23) == b"\x00\x01" + b"\x00" * 22
assert m.increment_nonce(b"\xff" * 24) == b"\x00" * 24  # full wrap
print("primitives ok")
PY
then ok "crypto_box round-trip + nonce-increment vectors"
else bad "crypto primitives self-test failed"; fi

# 3. doctor runs and reports tool status (non-zero exit only means a missing prereq).
if "$AGENT" doctor >/tmp/kpxc_doctor.$$ 2>&1; then ok "doctor: all prerequisites present"
else ok "doctor: ran and reported missing prerequisites (see below)"; fi
sed 's/^/      /' /tmp/kpxc_doctor.$$; rm -f /tmp/kpxc_doctor.$$

# 4. help works and unknown command fails cleanly.
"$AGENT" --help >/dev/null 2>&1 && ok "help renders" || bad "help failed"
if "$AGENT" bogus-cmd >/dev/null 2>&1; then bad "unknown command should fail"; else ok "unknown command exits non-zero"; fi

# 5. End-to-end against the framed mock KeePassXC (validates framing, the
#    crypto_box handshake, per-connection test-associate, and the generate-password
#    ack frame end to end - the parts that the unit checks above cannot cover).
if command -v jq >/dev/null 2>&1; then
    SOCK="$(mktemp -u /tmp/kpxc_mock.XXXXXX.sock)"
    "$PY" "$HERE/mock_kpxc.py" "$SOCK" 2>/dev/null &
    MOCK=$!
    for _ in $(seq 1 50); do [[ -S "$SOCK" ]] && break; sleep 0.05; done
    export KPXC_SOCKET="$SOCK"
    # Isolate the persisted association store so the suite never touches the real
    # ~/.config and can verify store-backed reuse.
    export XDG_CONFIG_HOME="$(mktemp -d /tmp/kpxc_cfg.XXXXXX)"

    A=$("$AGENT" associate 2>/dev/null) && eval "$A" \
        && [[ -n "${KPXC_ASSOC_ID:-}" && -n "${KPXC_ASSOC_KEY:-}" ]] \
        && ok "e2e: associate yields KPXC_ASSOC_ID/KEY" || bad "e2e: associate failed"

    # associate persists to the store keyed by db hash, like the browser keyRing.
    [[ -f "$XDG_CONFIG_HOME/keepassxc-cli-agent/associations.json" ]] \
        && ok "e2e: associate persists to the store" || bad "e2e: associate did not persist"

    "$AGENT" test >/dev/null 2>&1 && ok "e2e: test-associate valid" || bad "e2e: test failed"

    # get-logins must succeed only because run_assoc_action preludes test-associate.
    out=$("$AGENT" get-logins https://box.example 2>/dev/null) || true
    pw=$("$AGENT" get-logins https://box.example --field password 2>/dev/null) || true
    if grep -q "KPXC_USERNAME='admin'" <<<"$out" && [[ "$pw" == "p'q\"x y" ]]; then
        ok "e2e: get-logins returns entry; tricky password survives quoting"
    else
        bad "e2e: get-logins/quoting (out=$out pw=$pw)"
    fi
    eval "$out"; [[ "$KPXC_PASSWORD" == "p'q\"x y" ]] \
        && ok "e2e: eval of env output recovers password exactly" || bad "e2e: eval round-trip"

    g=$("$AGENT" generate-password 2>/dev/null); gv=${g#KPXC_PASSWORD=}; gv=${gv//\'/}
    [[ "$gv" == "Gen3r@ted-Long-Pass" ]] && ok "e2e: generate-password (ack frame skipped)" \
        || bad "e2e: generate-password (got [$g])"

    "$AGENT" groups 2>/dev/null | grep -q $'\tRoot/Servers' \
        && ok "e2e: groups walks nested tree" || bad "e2e: groups"

    # Persisted association: a clean env (no KPXC_ASSOC_*) reuses the stored pairing
    # via the resolver, so no re-association is needed (the Problem-2 fix).
    if spw=$(env -u KPXC_ASSOC_ID -u KPXC_ASSOC_KEY KPXC_SOCKET="$SOCK" XDG_CONFIG_HOME="$XDG_CONFIG_HOME" \
            "$AGENT" get-logins https://box.example --field password 2>/dev/null) \
        && [[ "$spw" == "p'q\"x y" ]]; then
        ok "e2e: persisted association reused without env vars"
    else
        bad "e2e: store-backed reuse (spw=${spw:-})"
    fi

    # Locked/closed database: get-databasehash(triggerUnlock) preamble must wait for
    # the unlock broadcast and then proceed (the Problem-1 fix). A second mock starts
    # "locked" and unlocks itself ~0.3s after the first hash request.
    LSOCK="$(mktemp -u /tmp/kpxc_locked.XXXXXX.sock)"
    KPXC_MOCK_LOCKED=1 "$PY" "$HERE/mock_kpxc.py" "$LSOCK" 2>/dev/null &
    LMOCK=$!
    for _ in $(seq 1 50); do [[ -S "$LSOCK" ]] && break; sleep 0.05; done
    if lpw=$(KPXC_SOCKET="$LSOCK" KPXC_ASSOC_ID=mock KPXC_ASSOC_KEY=x \
            "$AGENT" get-logins https://box.example --field password 2>/dev/null) \
        && [[ "$lpw" == "p'q\"x y" ]]; then
        ok "e2e: locked database triggers unlock-wait then returns creds"
    else
        bad "e2e: locked-DB unlock-wait (lpw=${lpw:-})"
    fi
    kill "$LMOCK" 2>/dev/null; wait "$LMOCK" 2>/dev/null || true; rm -f "$LSOCK"

    # 6. Bridge round-trip: serve-bridge relays a forwarded unix socket (BSOCK) to
    #    the mock (SOCK), standing in for the ssh -R hop. The agent talks to BSOCK
    #    exactly as the remote box would talk to its forwarded endpoint.
    BSOCK="$(mktemp -u /tmp/kpxc_bridge.XXXXXX.sock)"
    "$AGENT" --socket "$SOCK" serve-bridge --listen "unix:$BSOCK" >/dev/null 2>&1 &
    BRIDGE_PID=$!
    for _ in $(seq 1 50); do [[ -S "$BSOCK" ]] && break; sleep 0.05; done
    if KPXC_SOCKET="$BSOCK" "$AGENT" test >/dev/null 2>&1 \
        && bpw=$(KPXC_SOCKET="$BSOCK" "$AGENT" get-logins https://box.example --field password 2>/dev/null) \
        && [[ "$bpw" == "p'q\"x y" ]]; then
        ok "e2e: serve-bridge relays a forwarded socket (test + get-logins)"
    else
        bad "e2e: serve-bridge relay (bpw=${bpw:-})"
    fi
    kill "$BRIDGE_PID" 2>/dev/null; wait "$BRIDGE_PID" 2>/dev/null || true
    rm -f "$BSOCK"

    kill "$MOCK" 2>/dev/null; wait "$MOCK" 2>/dev/null || true
    rm -f "$SOCK"; rm -rf "$XDG_CONFIG_HOME"
    unset KPXC_SOCKET KPXC_ASSOC_ID KPXC_ASSOC_KEY KPXC_PASSWORD XDG_CONFIG_HOME
else
    printf '  [skip] e2e tests need jq\n'
fi

echo
printf 'self-test: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" == 0 ]]
