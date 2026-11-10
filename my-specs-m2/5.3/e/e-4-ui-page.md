# E4. Web UI: served page and pinned hooks (Spec E, step 4 of 7)

Check: `bash /spec/e/checks/check_e_4.sh` (rules E4.1-E4.5). Architecture, conventions and the basics: `/spec/base/base.md`.

Start this step only after `bash /spec/e/checks/check_e_3.sh` reports `0 failed`. Call the functions listed under **Uses**; do not write second versions of them.

Files: `/app/static/index.html`, `/app/static/style.css`, `/app/static/app.js`; two routes in
`server.py`: `GET /` returns `index.html` (`content_type="text/html"`), and
`app.router.add_static("/static/", "/app/static")`. Neither needs a token.

A Playwright test and a browser grader drive this page through **pinned selectors**, so the
markup is part of the contract. Two starter files hold it; copy them first:

```bash
mkdir -p /app/static && cp /spec/e/ui/index.html /spec/e/ui/style.css /app/static/
```

`index.html` is the skeleton: every `data-testid`, `id`, `name` and `data-button-role` in it must
stay exactly as written. You may add elements, classes and text (for example inside the lists),
but do not rename, move out of their forms, or drop pinned ones. Read it once
(`cat /app/static/index.html`) so you know the hooks your `app.js` must use.

`style.css` starts with rules that pin the button colours (`data-button-role` = `primary`
`#007a5a`, `danger` `#e01e5a`, `secondary` `#1264a3`, white text, all `!important`), make the
`hidden` attribute win over any `display` rule (`[hidden] { display: none !important; }`), give the
sidebar a coloured background and lay out the three panes as a grid. Keep those rules; add your
own after them. Never give these buttons a gradient, image or transparent background, and never
change their colour with `:disabled`/opacity in the resting state. Show and hide things only by
setting the `hidden` property (`el.hidden = true/false`).

**Adds:** `GET /` and `/static/*` routes.

**Rules**

E4.1 `GET /` on each of the three nodes -> `200`, `Content-Type: text/html`, no token needed.

E4.2 The served HTML (before any JavaScript runs) contains every `data-testid` of the skeleton
     and the DOM ids `auth-modal`, `create-channel-modal`, `channel-settings-modal`,
     `workspace-settings-modal` and `create-invitation-form`.

E4.3 In the served HTML, each pinned button carries its `data-button-role`: `primary` on
     `auth-submit`, `send-btn`, `thread-send`, `create-channel-submit`, `join-workspace-submit`,
     `workspace-general-submit`, `create-invitation-submit`, `channel-topic-submit`,
     `channel-add-member-submit`; `danger` on `archive-channel-btn`, `logout-btn`; `secondary`
     on `new-channel-btn`, `create-invitation-btn`, `unarchive-channel-btn`,
     `create-channel-cancel`, `close-thread`, `channel-settings-close`,
     `workspace-settings-close`, `channel-settings-btn`, `workspace-settings-btn`.

E4.4 In Chromium at 1280x900, each of those buttons' computed resting style is exactly
     `background-color: rgb(0, 122, 90)` (primary), `rgb(224, 30, 90)` (danger) or
     `rgb(18, 100, 163)` (secondary), with `color: rgb(255, 255, 255)`.

E4.5 `/static/app.js` and `/static/style.css` are served with `200`. Loading `/` with no token
     shows `#auth-modal` and no JavaScript error is thrown.
