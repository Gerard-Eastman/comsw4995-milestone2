# E7. Web UI: workspace settings, invitations, joining, channel settings (Spec E, step 7 of 7)

Check: `bash /spec/e/checks/check_e_7.sh` (rules E7.1-E7.6). Architecture, conventions and the basics: `/spec/base/base.md`.

Start this step only after `bash /spec/e/checks/check_e_6.sh` reports `0 failed`. Call the functions listed under **Uses**; do not write second versions of them.

File: `/app/static/app.js`.

**Uses:** E5's `api`, `selectChannel`, `renderChannels`; the routes of Spec A (members, roles,
invitations, `PATCH /api/workspaces/{slug}`) and Spec B (channel members, topic, archive), and
C4's `/invite @user` to add someone to a channel.

**Adds:**

| Function | What it does |
|---|---|
| `openWorkspaceSettings()` | Shows `#workspace-settings-modal` on the Members tab |
| `showSettingsTab(name)` | `members` / `invitations` / `general`: shows that `settings-pane-*`, hides the other two, loads its data |
| `openChannelSettings()` | Shows `#channel-settings-modal` for the current channel |

These elements are created by your JavaScript (they are not in the skeleton), with exactly these
`data-testid` values:

- `member-row`: one per workspace member inside `settings-pane-members`, with
  `data-user-id="<id>"`, showing the username, and containing a `role-badge` element whose text
  is the role (`owner`, `admin`, `member` or `guest`). When the viewer is the owner or an admin,
  every row except the owner's also contains a `<select data-testid="role-select">` with the
  options `admin`, `member`, `guest` (current role selected).
- `invitation-code`: one per active invitation inside `invitations-list`; its text is exactly
  the invitation code.
- `join-workspace-error`: an element inside `join-workspace-form` that shows the error text when
  a code is rejected (hidden or empty otherwise).
- `channel-member-row`: one per channel member inside `channel-members-list`, with
  `data-user-id="<id>"`, showing the username.

**Rules**

E7.1 `workspace-settings-btn` shows `#workspace-settings-modal` with `settings-pane-members`
     visible and one `member-row` (with `role-badge`) per workspace member;
     `settings-tab-invitations` / `settings-tab-general` / `settings-tab-members` switch which
     pane is visible (exactly one at a time); `workspace-settings-close` hides the modal.

E7.2 As the owner, changing a member's `role-select` to `admin` sends
     `PATCH /api/workspaces/{slug}/members/{user_id}` `{role}`; the row's `role-badge` then shows
     `admin`, and the server has the new role.

E7.3 On the Invitations tab, `create-invitation-btn` shows `#create-invitation-form`; submitting
     it (input `max_uses`) creates an invitation, and a new `invitation-code` with its code
     appears in `invitations-list`. That code can be accepted by another user.

E7.4 On the General tab, `workspace-name-input` and `workspace-join-mode` hold the current values;
     `workspace-general-submit` saves them (`PATCH /api/workspaces/{slug}`), and
     `workspace-header` shows the new name (also after a reload).

E7.5 `join-workspace-form` (input `code`, button `join-workspace-submit`): a valid code accepts the
     invitation and switches to that workspace (its name in `workspace-header`, its channels in
     `channel-list`); an unknown code shows visible, non-empty text in `join-workspace-error`.

E7.6 `channel-settings-btn` shows `#channel-settings-modal`: `channel-settings-title` shows
     `#<name>`, `channel-members-list` holds one `channel-member-row` per member. Submitting
     `channel-add-member-form` with a workspace member's username adds them (a new row appears;
     the server lists them as a channel member). `channel-topic-input` + `channel-topic-submit`
     sets the topic (`channel-topic` in the header updates). `archive-channel-btn` archives the
     channel; the modal then stays open, hides `archive-channel-btn` and shows
     `unarchive-channel-btn`, which unarchives it (the server agrees each time).
     `channel-settings-close` hides the modal.
