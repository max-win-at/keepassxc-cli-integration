#!/usr/bin/env bash
#
# Offline self-test for keepassxc-cli-agent. Exercises the crypto channel without
# a running KeePassXC: libsodium binding, crypto_box round-trip, nonce increment
# vector, and the bash `doctor` preflight. A live KeePassXC is NOT required.
#
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
ROOT="$(dirname "$HERE")"
SCRIPTS="$ROOT/skills/keepassxc-secrets/scripts"
CHANNEL="$SCRIPTS/lib/kpxc_channel.py"
AGENT="$SCRIPTS/kpxc-agent"
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

# 5. End-to-end against the bare-JSON mock KeePassXC (validates the raw-JSON
#    transport, the crypto_box handshake, per-connection test-associate, and the
#    generate-password ack frame end to end - the parts that the unit checks
#    above cannot cover).
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

    # --json is metadata ONLY. It exists to choose among matches; a password must never
    # reach stdout that way, because an agent that runs it uncaptured logs the secret.
    j=$("$AGENT" get-logins https://multi.example --json 2>/dev/null) || true
    if [[ "$(jq 'length' <<<"$j" 2>/dev/null)" == 2 ]] \
        && ! grep -qE 'password|first-secret|second-secret' <<<"$j" \
        && jq -e '.[0] | has("uuid") and has("name") and has("login")' >/dev/null 2>&1 <<<"$j"; then
        ok "e2e: --json lists matches as metadata, with no password/totp"
    else
        bad "e2e: --json redaction (j=$j)"
    fi

    # ...which is only usable if the chosen match can then be fetched by uuid/index.
    p2=$("$AGENT" get-logins https://multi.example --field password --entry-uuid u2 2>/dev/null) || true
    p0=$("$AGENT" get-logins https://multi.example --field password --index 0 2>/dev/null) || true
    if [[ "$p2" == "second-secret" && "$p0" == "first-secret" ]]; then
        ok "e2e: --entry-uuid / --index select among multiple matches"
    else
        bad "e2e: entry selector (uuid=$p2 index=$p0)"
    fi

    # A miss must be LOUD: exit 6, not exit 0 with an empty string. The silent-empty
    # result is what made a consuming agent fall back to an invented secret.
    rc=0; miss=$("$AGENT" get-logins https://nope.example --field password 2>/tmp/kpxc_miss.$$) || rc=$?
    if [[ "$rc" == 6 && -z "$miss" ]] && grep -q 'nope.example' /tmp/kpxc_miss.$$; then
        ok "e2e: no match exits 6 and names the URL on stderr"
    else
        bad "e2e: no-match exit code (rc=$rc out=[$miss])"
    fi
    rm -f /tmp/kpxc_miss.$$

    rc=0; "$AGENT" get-logins https://nope.example --field password --allow-empty >/dev/null 2>&1 || rc=$?
    [[ "$rc" == 0 ]] && ok "e2e: --allow-empty restores exit 0 for existence checks" \
        || bad "e2e: --allow-empty (rc=$rc)"

    rc=0; mj=$("$AGENT" get-logins https://nope.example --json 2>/dev/null) || rc=$?
    [[ "$rc" == 6 && "$mj" == "[]" ]] && ok "e2e: --json miss prints [] and still exits 6" \
        || bad "e2e: --json miss (rc=$rc mj=$mj)"

    # probe: the diagnostic for a mistyped/ill-formatted URL field. Safe to show a user.
    if pr=$("$AGENT" probe https://box.example https://nope.example 2>/dev/null) \
        && grep -q "$(printf 'https://box.example\t1\t')" <<<"$pr" \
        && grep -q "$(printf 'https://nope.example\t0\t')" <<<"$pr" \
        && ! grep -q "p'q" <<<"$pr"; then
        ok "e2e: probe reports per-URL match counts without secrets"
    else
        bad "e2e: probe (pr=$pr)"
    fi
    rc=0; "$AGENT" probe https://nope.example https://also-nope.example >/dev/null 2>&1 || rc=$?
    [[ "$rc" == 6 ]] && ok "e2e: probe exits 6 when no URL matches" || bad "e2e: probe all-miss (rc=$rc)"

    # db-info answers "which vault am I talking to?" in terms a user can recognize.
    if di=$("$AGENT" db-info 2>/dev/null) \
        && grep -qE '^database: +open' <<<"$di" \
        && grep -qE '^hash: +abc123deadbeef' <<<"$di" \
        && grep -qE '^name: +Root' <<<"$di" \
        && ! grep -q "p'q" <<<"$di"; then
        ok "e2e: db-info names the open database (hash + root group)"
    else
        bad "e2e: db-info (di=$di)"
    fi

    h=$("$AGENT" hash 2>/dev/null)
    w=$("$AGENT" wait-db --hash "$h" --timeout 5 --interval 1 2>/dev/null) || true
    [[ "$w" == "$h" ]] && ok "e2e: wait-db --hash returns at once when already active" \
        || bad "e2e: wait-db --hash (w=$w h=$h)"
    rc=0; "$AGENT" wait-db --hash nosuchhash --timeout 2 --interval 1 >/dev/null 2>&1 || rc=$?
    [[ "$rc" == 7 ]] && ok "e2e: wait-db times out with exit 7" || bad "e2e: wait-db timeout (rc=$rc)"

    # Switching between two already-unlocked databases emits no broadcast, so wait-db
    # polls. This mock flips its hash 2s in, standing in for the user switching vaults.
    WSOCK="$(mktemp -u /tmp/kpxc_switch.XXXXXX.sock)"
    KPXC_MOCK_HASH_SWITCH_AFTER=2 "$PY" "$HERE/mock_kpxc.py" "$WSOCK" 2>/dev/null &
    WMOCK=$!
    for _ in $(seq 1 50); do [[ -S "$WSOCK" ]] && break; sleep 0.05; done
    if nh=$(KPXC_SOCKET="$WSOCK" "$AGENT" wait-db --changed --timeout 15 --interval 1 2>/dev/null) \
        && [[ "$nh" == "fee1deadbeef99" ]]; then
        ok "e2e: wait-db --changed unblocks when the active database changes"
    else
        bad "e2e: wait-db --changed (nh=${nh:-})"
    fi
    kill "$WMOCK" 2>/dev/null; wait "$WMOCK" 2>/dev/null || true; rm -f "$WSOCK"

    # SKILL.md tells agents to retry with --debug, so --debug must not echo secrets.
    derr=$(KPXC_AGENT_DEBUG=1 "$AGENT" set-login https://box.example --username u \
        --password 'SENTINEL-do-not-log' 2>&1 >/dev/null) || true
    if ! grep -q 'SENTINEL-do-not-log' <<<"$derr"; then
        ok "e2e: --debug masks the password in the plaintext it prints"
    else
        bad "e2e: --debug leaked the password to stderr"
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

    # 7. ExecTransport relay path: the mock's --proxy-stdio stand-in wraps the
    #    mock's bare JSON in native-messaging framing over stdio, exactly as the
    #    real keepassxc-proxy does (e.g. keepassxc-proxy.exe across the WSL
    #    boundary). The channel must frame requests and unframe replies.
    if epw=$(KPXC_SOCKET= KPXC_EXEC="$PY $HERE/mock_kpxc.py --proxy-stdio $SOCK" \
            "$AGENT" get-logins https://box.example --field password 2>/dev/null) \
        && [[ "$epw" == "p'q\"x y" ]]; then
        ok "e2e: --exec relay speaks native-messaging framing over stdio"
    else
        bad "e2e: --exec relay (epw=${epw:-})"
    fi

    # 8. serve-bridge with a framed backend: the agent side of the bridge speaks
    #    bare JSON, the proxy backend speaks native messaging - the bridge must
    #    convert the framing in both directions.
    B2SOCK="$(mktemp -u /tmp/kpxc_bridge2.XXXXXX.sock)"
    "$AGENT" --exec "$PY $HERE/mock_kpxc.py --proxy-stdio $SOCK" \
        serve-bridge --listen "unix:$B2SOCK" >/dev/null 2>&1 &
    B2_PID=$!
    for _ in $(seq 1 50); do [[ -S "$B2SOCK" ]] && break; sleep 0.05; done
    if b2pw=$(KPXC_SOCKET="$B2SOCK" KPXC_EXEC= \
            "$AGENT" get-logins https://box.example --field password 2>/dev/null) \
        && [[ "$b2pw" == "p'q\"x y" ]]; then
        ok "e2e: serve-bridge converts framing toward a framed proxy backend"
    else
        bad "e2e: serve-bridge framing conversion (b2pw=${b2pw:-})"
    fi
    kill "$B2_PID" 2>/dev/null; wait "$B2_PID" 2>/dev/null || true
    rm -f "$B2SOCK"

    kill "$MOCK" 2>/dev/null; wait "$MOCK" 2>/dev/null || true
    rm -f "$SOCK"; rm -rf "$XDG_CONFIG_HOME"
    unset KPXC_SOCKET KPXC_ASSOC_ID KPXC_ASSOC_KEY KPXC_PASSWORD XDG_CONFIG_HOME
else
    printf '  [skip] e2e tests need jq\n'
fi

echo
printf 'self-test: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" == 0 ]]
