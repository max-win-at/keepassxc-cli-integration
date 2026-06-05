# Reaching KeePassXC across SSH

Use this when `kpxc-agent` runs on a **remote box** but KeePassXC runs on the
**client** the user sits at — e.g. VS Code Remote SSH, or an agent CLI driving the box
over `ssh` (kept alive with `tmux`/`screen`). The box has no local KeePassXC socket and
no local `keepassxc-proxy`, so the agent there can't reach the vault directly.

The fix is `ssh -R`: the client already opens an outbound SSH connection to the box, and
OpenSSH (≥ 6.7) can reverse-forward a socket back over it — no inbound connectivity to
the client, no new network service. The encrypted KeePassXC channel stays **end-to-end**
between the box's `kpxc-agent` and KeePassXC; the forward only shuttles bytes.

```
[client] KeePassXC ──▶ serve-bridge ──127.0.0.1:19455──▶ ssh -R ──▶ [box] /run/.../kpxc.sock
                                                                           ▲
                                       kpxc-agent --socket /run/.../kpxc.sock get-logins …
```

## Pairing happens once, on the client

Only the client can show KeePassXC's approve dialog. Run `associate` there, then forward
the two **non-secret** `KPXC_ASSOC_*` vars to the box — inline on the command, via
`SendEnv`/`AcceptEnv`, or by dropping the `export` lines in the box's profile.

## Linux / macOS client

KeePassXC already exposes a unix socket, so you can forward it with **no bridge** — just
`ssh -R` the raw socket onto the box:

```bash
ssh -R /run/user/1000/kpxc.sock:"$XDG_RUNTIME_DIR/org.keepassxc.KeePassXC.BrowserServer" box
# on the box:
KPXC_ASSOC_ID=… KPXC_ASSOC_KEY=… \
  kpxc-agent --socket /run/user/1000/kpxc.sock get-logins https://host --field password
```

Or, for the same uniform command as every other OS, run the bridge on the client:

```bash
kpxc-agent serve-bridge                 # listens on 127.0.0.1:19455
# then connect with:
ssh -R /run/user/1000/kpxc.sock:127.0.0.1:19455 box
```

## Windows / WSL client

KeePassXC speaks a **named pipe** here, not a unix socket, so `ssh -R` can't target it
directly. Run the bridge — it relays through `keepassxc-proxy.exe`:

```bash
# on the client, inside WSL (so 127.0.0.1 is shared with the ssh you run from WSL):
kpxc-agent serve-bridge                 # auto-selects keepassxc-proxy.exe
# from the same WSL shell:
ssh -R /run/user/1000/kpxc.sock:127.0.0.1:19455 box
```

If KeePassXC is installed in a non-default location, point the bridge at it with
`KPXC_WIN_KEEPASSXC=/mnt/c/path/to/KeePassXC` or `--exec`.

One-shot variant (set up the forward and run the command in a single invocation):

```bash
ssh -o ExitOnForwardFailure=yes \
    -R /tmp/kpxc.sock:127.0.0.1:19455 box \
    "KPXC_ASSOC_ID='$KPXC_ASSOC_ID' KPXC_ASSOC_KEY='$KPXC_ASSOC_KEY' \
     kpxc-agent --socket /tmp/kpxc.sock generate-password; rm -f /tmp/kpxc.sock"
```

## Wiring it into VS Code Remote SSH

Put the forward and identity passthrough in `~/.ssh/config` (VS Code Remote SSH uses
your system `ssh`), start the bridge on the client before connecting, and set
`KPXC_SOCKET` on the box:

```ssh-config
Host box
    RemoteForward /run/user/1000/kpxc.sock 127.0.0.1:19455
    SendEnv KPXC_ASSOC_ID KPXC_ASSOC_KEY
    # box's sshd needs: AcceptEnv KPXC_ASSOC_*  and  StreamLocalBindUnlink yes
```

Then on the box: `export KPXC_SOCKET=/run/user/1000/kpxc.sock`.

> `StreamLocalBindUnlink yes` in the box's `sshd_config` lets a reconnect reclaim a
> stale forwarded socket. On a Windows/WSL client, run both `serve-bridge` and `ssh`
> inside WSL so they share `127.0.0.1`.
