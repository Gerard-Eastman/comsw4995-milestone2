## C3. Files

Routes: `POST /api/files`, `GET /api/files/{id}`, `GET /api/files/{id}/download`, and
`file_ids` on `POST /api/channels/{id}/messages`. File: `/app/routes_extras.py` (and
`routes_messages.py` for `file_ids`).

**Uses:** `require_user`, `HTTPError`, `now_iso`; the message post route from the basics.

**Adds:**

| Function | What it does |
|---|---|
| `file_to_json(row)` | `FileObj = {id, uploader_id, filename, content_type, size, created_at}` |
| `files_for(message_id)` | `[FileObj]` attached to a message, in attach order |

Table: `files(id INTEGER PRIMARY KEY, uploader_id, filename, content_type, size, created_at, message_id NULL)`.
Store the bytes at `/app/data/files/<id>` (the folder is shared by all nodes).

**Rules**

C3.1 `POST /api/files` with `multipart/form-data` and a part named `file` -> `201 {file: FileObj}`.
     `filename` is the part's filename, `content_type` the part's `Content-Type` (default
     `application/octet-stream`), `size` the byte count. Read the upload with
     `reader = await request.multipart()` and count bytes while writing them to disk.

C3.2 A file over 10 MiB (`size > 10 * 1024 * 1024`) -> `413` (delete what you wrote). Exactly
     10 MiB is allowed. No `file` part, or not multipart -> `400`. No token -> `401`.

C3.3 `GET /api/files/{id}` -> `200 {file}`; unknown id -> `404`; works on every node.

C3.4 `GET /api/files/{id}/download` -> `200` with the exact bytes, `Content-Type` equal to the
     stored `content_type`, and `Content-Disposition: attachment; filename="<filename>"`.
     Unknown -> `404`.

C3.5 `POST /api/channels/{id}/messages` `{body, file_ids: [..]}` attaches the files: the
     message's `files` lists their FileObjs (also in `GET .../messages`). Each file must exist,
     belong to the caller (`uploader_id`), and not be attached to any message yet; otherwise
     `400` and no message is created. `file_ids` must be a list of integers (else `400`).
     `body` must still be non-empty, as for every message.
