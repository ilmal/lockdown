# Remote kill switch

## Bind address

The server binds **only** to your Tailscale address (`100.x.y.z` on this
machine), never `0.0.0.0`. Nothing on the LAN or the internet can reach it, and
no port is opened on a public interface.

Check the address with:

```bash
tailscale ip -4
```

## Token

```bash
mkdir -p ~/.claude/secrets
head -c 32 /dev/urandom | base64 > ~/.claude/secrets/presence-guard-token
chmod 600 ~/.claude/secrets/presence-guard-token
```

The server refuses to start without it. Tokens are compared in constant time
and never logged.

## Granting poweroff without blanket root

`panic` calls `loginctl poweroff`. On a stock Ubuntu desktop an active local
session is normally allowed to do this. If it is refused, choose **one** of the
following.

### Option A — polkit rule (preferred)

`/etc/polkit-1/rules.d/50-presence-guard-poweroff.rules`:

```javascript
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.login1.power-off" &&
        subject.user == "nils") {
        return polkit.Result.YES;
    }
});
```

This grants power-off to your user and nothing else. It does not grant sudo.

### Option B — narrow sudoers entry

`/etc/sudoers.d/presence-guard`:

```
nils ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff
```

Then the fallback path works. This is broader than Option A; prefer A.

Verify without triggering anything:

```bash
loginctl show-session $XDG_SESSION_ID -p LockedHint
sudo -n systemctl poweroff --dry-run 2>/dev/null || echo "cannot test dry-run; fine"
```

## From the phone

With Tailscale connected:

```bash
TOKEN=$(cat ~/.claude/secrets/presence-guard-token)

# check it is alive
curl -s -H "Authorization: Bearer $TOKEN" http://100.x.y.z:8791/status

# lock only
curl -s -X POST -H "Authorization: Bearer $TOKEN" http://100.x.y.z:8791/lock

# lock + power off (recommended emergency action)
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"confirm":"panic"}' http://100.x.y.z:8791/panic
```

An iOS Shortcut is just a "Get Contents of URL" action with method `POST`, the
`Authorization` header, and that JSON body. `docs/phone-setup.md` has the
step-by-step.

## What is deliberately absent

No endpoint deletes keys, edits `crypttab`, or reformats anything. The worst
outcome of calling this server is a powered-off laptop that needs your
passphrase — which is exactly the property you want when you are calling it in a
panic, possibly on a bad connection, possibly with a mistyped URL.
