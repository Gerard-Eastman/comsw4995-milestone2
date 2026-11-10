# E5. Web UI: sign-up, login, workspace and channels (Spec E, step 5 of 7)

Check: `bash /spec/e/checks/check_e_5.sh` (rules E5.1-E5.7). Architecture, conventions and the basics: `/spec/base/base.md`.

Start this step only after `bash /spec/e/checks/check_e_4.sh` reports `0 failed`. Call the functions listed under **Uses**; do not write second versions of them.

File: `/app/static/app.js` (plain JavaScript, no build step, no framework from the network).

**Uses:** the E4 skeleton; the REST routes from the basics (and Specs A/B if present).

**Adds:**

| Function | What it does |
|---|---|
| `api(method, path, body)` | `fetch` with `Authorization: Bearer <token>` and JSON; returns `{status, data}` |
| `boot()` | On load: take `?token=` from the URL if present and store it; then if a token is stored, call `GET /api/auth/me` and show the app, else show `#auth-modal` |
| `renderChannels()`, `selectChannel(id)` | Fill `channel-list`, switch the current channel |

Token storage is pinned: keep the bearer token in `localStorage["huddle.token"]` (also set
`window.__huddle_token`). Never use `alert()`, `confirm()` or `prompt()` anywhere: they block
the test browser.

**Rules**

E5.1 Auth form: `[data-testid=auth-form]` has `data-mode="login"` or `"signup"`;
     `auth-toggle` switches the mode (and shows the `display_name` input only in signup mode).
     Submitting in signup mode calls register, in login mode calls login.

E5.2 An invalid sign-up (e.g. password shorter than 8 characters, or a username with a space)
     shows the server's error as visible, non-empty text in the form's `[role=alert]` element,
     and the user stays logged out.

E5.3 A valid sign-up logs in automatically: the token is stored in
     `localStorage["huddle.token"]`, `#auth-modal` becomes hidden, and `current-user` shows the
     username. Login with the same credentials works the same way. `?token=<bearer>` in the URL
     logs in without the form.

E5.4 A user in no workspace sees `empty-state-create-workspace` (visible, non-blank copy).
     Submitting `workspace-create-form` (inputs `slug`, `name`) creates the workspace, hides the
     empty state, shows the workspace name in `workspace-header`, and lists `#general`.

E5.5 `channel-list` holds one clickable `<li data-testid="channel-entry" data-channel-id="<id>"
     data-channel-name="<name>">` per channel (the clickable element carries the data
     attributes), showing the name with a `#` prefix (e.g. `# general`). The first channel is
     selected after login.

E5.6 `new-channel-btn` shows `#create-channel-modal`; submitting `create-channel-form` (input
     `name`, checkbox `create-channel-private`) creates the channel, hides the modal, adds the
     entry and switches to it. A duplicate name shows the server error as visible text in the
     form's `[role=alert]` and keeps the modal open. `create-channel-cancel` hides it.

E5.7 Clicking a `channel-entry` switches channel: `channel-title` shows `#<name>`,
     `channel-topic` shows the topic, and `message-list` shows that channel's messages (oldest
     at the top). A channel with no messages shows visible, non-blank copy inside
     `message-list` (e.g. "No messages yet. Say hi!") and no `message` rows.
