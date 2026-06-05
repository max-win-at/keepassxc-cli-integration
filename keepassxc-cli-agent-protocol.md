# keepassxc-cli-agent protocol

This documents the wire protocol as spoken by `keepassxc-cli-agent`. It is the
same protocol as the `keepassxc-browser` extension (see `../keepassxc-protocol.md`),
with the term *browser* replaced by *keepassxc-cli-agent* and scoped to the actions
this CLI implements. KeePassXC is unmodified — only our side of the conversation
changes.

Messages are encrypted with the [libsodium] `crypto_box` construction
(Curve25519 + XSalsa20-Poly1305), the same primitive TweetNaCl.js exposes as
`nacl.box`. `crypto_box_easy` == `nacl.box`; `crypto_box_open_easy` == `nacl.box.open`.

1. keepassxc-cli-agent generates a key pair and transfers the public key to KeePassXC.
2. KeePassXC generates its own key pair and returns its public key in plain text.
   Secret keys are never transmitted.
3. All later messages are encrypted: keepassxc-cli-agent encrypts with KeePassXC's
   public key, a random 24-byte nonce, and its own secret key; KeePassXC replies
   encrypted with keepassxc-cli-agent's public key and the **incremented** nonce.
4. The nonce is incremented as a little-endian integer with carry (libsodium
   `sodium_increment`); the reply nonce must equal `increment(request nonce)`.

Three key pairs are involved:

- **host key** — temporary, created by KeePassXC for the current session.
- **agent session key** — temporary, created by keepassxc-cli-agent per invocation.
  (In the browser this is the *client key*.)
- **identification key** — a permanent key pair created by keepassxc-cli-agent during
  `associate`. Only its **public** half is ever used (to authenticate in later
  sessions); in this CLI it lives in `KPXC_ASSOC_KEY` and is not secret.

## Transport and framing

Reach KeePassXC either by connecting directly to its `AF_UNIX` stream socket
`org.keepassxc.KeePassXC.BrowserServer`, or by relaying through `keepassxc-proxy`
over stdio (used to cross the WSL→Windows boundary; the proxy owns the Windows named
pipe `\\.\pipe\org.keepassxc.KeePassXC.BrowserServer_<winuser>`).

A third reachability path is a **reverse-forwarded socket**: when the agent runs on a
remote box, the client runs `kpxc-agent serve-bridge` (which re-exposes one of the two
transports above on a listening endpoint) and `ssh -R` forwards it onto the box, where
the agent connects with `--socket`. The bridge is a transparent byte relay, so the
framing and crypto below are unchanged — they remain end-to-end between the box's agent
and KeePassXC. See the README's *Reaching KeePassXC across SSH* section.

**Every message is framed** with native messaging framing: a 4-byte little-endian
length prefix followed by the JSON. This applies to the direct socket and the proxy
alike (the proxy forwards the same framed stream). KeePassXC pretty-prints its reply
JSON, so read exactly `length` bytes rather than assuming one line per message.

## Envelope

Every encrypted request has this shape:

```json
{
    "action":  "<action name>",
    "message": "<base64(crypto_box(plaintext-json))>",
    "nonce":   "<base64(24 random bytes)>",
    "clientID":"<base64(24 random bytes, per session)>"
}
```

Optional envelope fields: `triggerUnlock: "true"` (ask KeePassXC to prompt for an
unlock), and `requestID` (echoed; used by `generate-password`). The decrypted reply
JSON carries the same `nonce` (incremented) plus `success` / `error` / `errorCode`.

## Handshake — `change-public-keys` (plaintext)

Request:
```json
{ "action":"change-public-keys", "publicKey":"<agent session public key>",
  "nonce":"<nonce>", "clientID":"<clientID>" }
```
Reply:
```json
{ "action":"change-public-keys", "version":"2.7.0",
  "publicKey":"<host public key>", "success":"true" }
```

## `associate`

Plaintext message (the `key` is the agent session public key; `idKey` is the new
identification public key):
```json
{ "action":"associate", "key":"<agent session public key>", "idKey":"<identification public key>" }
```
Reply: `{ "hash", "version", "success":"true", "id":"<assigned id>", "nonce" }`.
The CLI emits the resulting `id`/`idKey` as `KPXC_ASSOC_ID` / `KPXC_ASSOC_KEY`.

## `test-associate`

```json
{ "action":"test-associate", "id":"<KPXC_ASSOC_ID>", "key":"<KPXC_ASSOC_KEY>" }
```
Reply: `{ "version", "nonce", "hash", "id", "success" }`.

## Per-connection association

KeePassXC validates a client's association **per connection**. A credential or
database action (`get-logins`, `get-totp`, `set-login`, `get-database-groups`,
`create-new-group`, `generate-password`) must be preceded by a successful
`test-associate` *on the same connection*, or it is rejected with
`errorCode 8` (association failed). The CLI sends `test-associate` then the action
within one session. (The extension achieves the same by holding one long-lived
connection.)

## Asynchronous replies

`generate-password` emits an empty `{}` frame first, then the real (encrypted)
reply. Skip frames that carry neither an encrypted `message` nor an `error`/`errorCode`.

## `get-logins`

```json
{ "action":"get-logins", "id":"<KPXC_ASSOC_ID>", "url":"<url>",
  "submitUrl":"<optional>", "httpAuth":"<optional>",
  "keys":[ { "id":"<KPXC_ASSOC_ID>", "key":"<KPXC_ASSOC_KEY>" } ] }
```
Reply: `{ "count", "entries":[ {"login","name","password","uuid", ...} ], "success", "hash", "nonce" }`.
`errorCode: 15` means no logins matched (the CLI treats this as an empty result).

## `get-totp`

```json
{ "action":"get-totp", "uuid":"<entry uuid>" }
```
Reply: `{ "totp", "version", "success", "nonce" }`.

## `generate-password`

```json
{ "action":"generate-password", "requestID":"<8 hex chars>" }
```
Reply: `{ "version", "password", "success", "nonce" }` (older KeePassXC may return
the value under `entries`).

## `set-login`

```json
{ "action":"set-login", "id":"<KPXC_ASSOC_ID>", "url":"<url>", "submitUrl":"<url>",
  "login":"<username>", "password":"<password>",
  "group":"<optional>", "groupUuid":"<optional>", "uuid":"<optional, to update>" }
```
Reply: `{ "count":null, "entries":null, "error":"", "success":"true", "hash", "nonce" }`.

## `get-database-groups`

```json
{ "action":"get-database-groups" }
```
Reply (KeePassXC nests the array under `.groups.groups`):
`{ "groups": { "defaultGroup", "groups":[ {"name","uuid","children":[ ... ]} ] }, "success", "nonce" }`.

## `create-new-group`

```json
{ "action":"create-new-group", "groupName":"<name or path>" }
```
Reply: `{ "name", "uuid" }`.

## `lock-database`

```json
{ "action":"lock-database" }
```
Reply is, by design, an error envelope (e.g. `{ "errorCode":1, "error":"Database not opened" }`);
reaching it means the lock was processed.

## `get-databasehash`

```json
{ "action":"get-databasehash" }
```
Reply: `{ "action":"hash", "hash":"<sha256>", "version" }`.

[libsodium]: https://doc.libsodium.org/
