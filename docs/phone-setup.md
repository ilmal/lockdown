# Phone setup

Two ways, both need Tailscale connected on the phone.

## Option 1 — browser bookmark

Most phones cannot run `curl`. Put the token in a bookmark instead. Create a
file on the laptop:

```bash
TOKEN=$(cat ~/.claude/secrets/presence-guard-token)
echo "http://100.x.y.z:8791/status" 
```

Browser requests cannot send an `Authorization` header from the address bar, so
browser bookmarks only work for the endpoints if you add a small query-token
variant. **This repo does not add one on purpose** — tokens in URLs end up in
history and screenshots. Use a Shortcut.

## Option 2 — iOS Shortcut (recommended)

1. Shortcuts app → **+** → name it `Panic`.
2. Add action **Get Contents of URL**.
3. URL: `http://100.x.y.z:8791/panic`
4. Tap **Show More**:
   - Method: `POST`
   - Headers: `Authorization` = `Bearer <paste token>`
   - Request Body: `JSON`
   - Add field `confirm` (text) = `panic`
5. Add it to the Home Screen or as a Back Tap action
   (Settings → Accessibility → Touch → Back Tap → Double Tap).

Make a second, gentler shortcut for `/lock` with no body.

## Option 3 — Android

Use **HTTP Request Shortcuts** (free, F-Droid / Play) with the same method,
header and JSON body. Add a home-screen widget.

## Test without powering off

Before you trust it, call `/lock` from the phone and watch the screen lock. That
exercises the token, the network path, and the session call in one shot, and it
is fully reversible.
