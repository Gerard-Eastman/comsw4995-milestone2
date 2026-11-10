## E6. Web UI: messages, threads, reactions, logout

File: `/app/static/app.js`.

**Uses:** E5's `api`, `selectChannel`; message routes (post, list, replies, E1 edit/delete) and
the reaction routes (`POST /api/messages/{id}/reactions` `{emoji}` and
`DELETE /api/messages/{id}/reactions/{emoji}`, both `200 {reactions}`; they are Spec C's C1. If
Spec C is not in `/spec`, build just those two routes now, as the task description describes).

**Adds:**

| Function | What it does |
|---|---|
| `renderMessage(m)` | One message row (structure below) |
| `openThread(messageId)` | Shows `thread-panel` with the parent and its replies |

Each message row is `<div data-testid="message" data-message-id="<id>">` containing: an avatar
element with class `avatar` (e.g. the author's initial in a coloured circle), the author's
display name in an element with class `author`, a `<time datetime="<created_at>">` with
human-readable text (e.g. `3:04 PM`), `<div data-testid="message-body">`, an `(edited)`
indicator (element with class `edited`) when `edited_at` is set, a replies indicator
(class `reply-count`, text `1 reply` / `N replies`) when `reply_count > 0`, the reaction chips,
and a toolbar (shown on hover) with buttons `data-testid="open-thread-btn"`,
`data-testid="reaction-button"`, `data-action="edit"` and `data-action="delete"`.

**Rules**

E6.1 Typing in `message-input` and clicking `send-btn` (or pressing Enter) posts the message;
     it appears as the last `message` row with its text in `message-body`, and the input
     clears. An empty or whitespace-only message is not posted (no request, no new row).

E6.2 Edit via the toolbar: clicking `[data-action=edit]` replaces the body with an
     `<input name="edit-body">` holding the text; Enter saves (`PATCH`), Escape cancels. After
     saving, the row shows the new text and the `edited` indicator. Both survive a hard reload.

E6.3 Delete via the toolbar: clicking `[data-action=delete]` deletes the message (`DELETE`, no
     confirmation dialog) and removes the row; it stays gone after a reload.

E6.4 `open-thread-btn` opens `thread-panel` (the right-hand pane, `hidden` removed) showing the
     parent and its replies; `thread-input` + `thread-send` posts a reply (`parent_id`), which
     appears in the panel, and the parent row's `reply-count` shows `1 reply` (then `2 replies`).
     `close-thread` hides the panel.

E6.5 `reaction-button` opens an `emoji-picker` element (`data-testid="emoji-picker"`), a grid of
     at least 8 `<button data-testid="emoji-option">` emoji (never a `prompt()`). Clicking one
     adds that reaction and renders a `<button data-testid="reaction-chip">` on the message
     showing the emoji and its count (`👍 1`); clicking your own chip removes your reaction.

E6.6 `logout-btn` clears `localStorage["huddle.token"]` and shows `#auth-modal`. Logging in
     again with the same username and password shows the same workspace in `workspace-header`
     and its channels.

E6.7 Layout: the sidebar (coloured, not white), the message pane and the thread panel sit side
     by side (three panes when a thread is open); the channel header shows `channel-title` and
     `channel-topic`. New messages posted by others appear in the open channel within a few
     seconds (subscribe to it over the WebSocket, or poll).
