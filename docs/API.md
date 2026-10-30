# USHIKA: REST API reference

The machine-readable contract is the OpenAPI schema at `/api/schema/` (Swagger UI at `/api/docs/`). This document adds the behaviour, validation rules and examples that a schema doesn't capture. Every example below was captured from the running code.

## Conventions

| | |
|---|---|
| Base path | `/api/v1/` |
| Format | JSON (`Content-Type: application/json`), UTF-8 |
| Timestamps | ISO 8601, UTC (`2026-10-27T19:19:32Z`) |
| IDs | `id` is USHIKA's integer key; `wa_message_id` is WhatsApp's `wamid`; `wa_id` is the phone number in international format, digits only |
| Auth | Required on every `/api/v1/` endpoint except `auth/token/` |
| Storage | Saved media files go to local disk under `MEDIA_ROOT` (default `storage/`) |

### Authentication

USHIKA uses DRF token authentication. Send the token on every request:

```
Authorization: Token 9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b
```

Session cookies (Django admin login) also work, which is how the browsable API and Swagger UI authenticate.

**Get a token**: `POST /api/v1/auth/token/`, no auth needed:
```json
{"username": "operator", "password": "…"}
```
```json
200 OK
{"token": "9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b"}
```
A wrong username or password returns `400 {"non_field_errors": ["Unable to log in with provided credentials."]}`.

Alternatively, run `python manage.py drf_create_token <username>`. A user has one token; delete it in the admin (**Auth Token → Tokens**) to revoke it.

**Check a login**: `GET /api/v1/auth/me/` returns the user the token (or session) belongs to. A missing or invalid token returns `401`.
```json
200 OK
{"id": 2, "username": "admin", "is_staff": true, "is_superuser": true, "last_login": "2026-10-28T08:58:54.051234Z"}
```

### Pagination

List endpoints use page-number pagination: `?page=2&page_size=100`. The default page size is 50 and the maximum is 200.
```json
{"count": 132, "next": "http://…/api/v1/messages/?page=2", "previous": null, "results": [ … ]}
```

### Filtering, search and ordering

- **Filters** are exact-match query parameters (listed per endpoint).
- **Search:** `?search=<text>`, case-insensitive across the fields listed per endpoint.
- **Ordering:** `?ordering=<field>` or `?ordering=-<field>` for descending.

### Status codes and errors

| Code | When | Body |
|---|---|---|
| 200 | Success; idempotent replay of a send | resource |
| 201 | Message sent (accepted by Meta) | stored message |
| 400 | Validation error | `{"field": ["message", …]}` |
| 401 | Missing or invalid token | `{"detail": "Authentication credentials were not provided."}` |
| 403 | Authenticated but not allowed (for example, schema in production for non-staff) | `{"detail": "…"}` |
| 404 | Unknown id, a file you can't get, or a file type that can't be previewed | `{"detail": "…"}` |
| 405 | Wrong method | `{"detail": "Method \"GET\" not allowed."}` |
| 502 | Meta rejected or failed the operation; the record is still stored | the stored resource, with error fields (file preview and download: `{"detail": "…"}`) |

Field validation runs first, so cross-field errors (such as missing `text` for a text message) only appear once every field is individually valid.

---

## Contacts

### `GET /api/v1/contacts/`
Contacts with message counts, most recently active first.

| Query | |
|---|---|
| `wa_id` | exact phone number |
| `level` | contact level `id` |
| `search` | `wa_id`, `profile_name` |
| `ordering` | `last_message_at`, `created_at`, `profile_name` |

`level` is the name of the contact's level, or `null`. It decides whether the contact's images and PDFs can be saved (see [Saving media](#saving-media-contact-levels)). Levels are created and assigned in the Django admin, not through the API.

```json
{
  "count": 1, "next": null, "previous": null,
  "results": [{
    "id": 1,
    "wa_id": "16315551234",
    "profile_name": "Kerry Fisher",
    "level": "Full",
    "message_count": 2,
    "last_message_at": "2025-10-27T21:21:40Z",
    "created_at": "2026-10-27T19:19:31.979545Z",
    "updated_at": "2026-10-27T19:19:31.979545Z"
  }]
}
```

### `GET /api/v1/contacts/{id}/`
A single contact, in the same shape.

---

## Messages

### `GET /api/v1/messages/`
Inbound and outbound messages, newest first, with attachments inlined.

| Query | Values |
|---|---|
| `direction` | `inbound`, `outbound` |
| `message_type` | `text`, `image`, `document`, `audio`, `video`, `sticker`, `template`, `interactive`, `button`, `location`, `reaction`, `contacts`, `unsupported`, … |
| `status` | `received`, `pending`, `accepted`, `sent`, `delivered`, `read`, `failed` |
| `contact` | contact `id` |
| `wa_id` | contact phone number |
| `since`, `until` | ISO 8601 datetime bounds on `timestamp` (inclusive) |
| `search` | `body`, contact `wa_id`, contact `profile_name` |
| `ordering` | `timestamp`, `created_at` (default `-timestamp`) |

```json
{
  "count": 2, "next": null, "previous": null,
  "results": [
    {
      "id": 2,
      "wa_message_id": "wamid.HBgLMTYzMTU1NTEyMzQVAgASGBQzQUI3RDRERjM5MkM1MzU2NDhDRAA=",
      "contact": {"id": 1, "wa_id": "16315551234", "profile_name": "Kerry Fisher"},
      "direction": "inbound",
      "message_type": "image",
      "status": "received",
      "body": "Receipt",
      "context_wa_message_id": "",
      "timestamp": "2025-10-27T21:21:40Z",
      "status_updated_at": null,
      "error_code": "", "error_title": "", "error_details": "",
      "attachments": [{
        "id": 1, "message": 2,
        "media_id": "1013859600285441",
        "media_type": "image",
        "mime_type": "image/jpeg",
        "sha256": "",
        "filename": "",
        "caption": "Receipt",
        "file_size": 11,
        "download_status": "downloaded",
        "download_attempts": 1,
        "last_error": "",
        "downloaded_at": "2026-10-27T19:19:32.007665Z",
        "download_url": "http://127.0.0.1:8000/api/v1/attachments/1/download/",
        "preview_url": "http://127.0.0.1:8000/api/v1/attachments/1/preview/",
        "created_at": "2026-10-27T19:19:31.981539Z"
      }],
      "created_at": "2026-10-27T19:19:31.981539Z"
    }
  ]
}
```

What the fields mean:
- `timestamp` is when WhatsApp received an inbound message, or when USHIKA sent an outbound one.
- `body` holds text, a caption, or a readable summary (button title, emoji, location label).
- `context_wa_message_id` is set when the message is a reply.

### `GET /api/v1/messages/{id}/`
The list shape plus `phone_number_id`, `idempotency_key`, `sent_by` (username), `payload` (the raw WhatsApp message or the request sent to Meta) and `status_events` (full history, oldest first).

### `GET /api/v1/messages/{id}/statuses/`
That message's status events, paginated (same shape as `/statuses/`).

### `POST /api/v1/messages/send/`
Sends a WhatsApp message through the configured business number and stores it.

| Field | Type | Required | Notes |
|---|---|---|---|
| `to` | string | yes | International format. `+`, spaces, dashes and brackets are stripped; must be 7–15 digits. |
| `type` | string | yes | `text`, `template`, `image`, `document`, `audio`, `video`, `sticker` |
| `text` | string ≤ 4096 | text | Text messages only |
| `preview_url` | bool | no | Text only; renders link previews |
| `template_name` | string | template | An approved template name, e.g. `hello_world` |
| `language_code` | string | no | Default `en_US` |
| `components` | array | no | Template components (header/body/button parameters), passed through as Meta expects |
| `media_link` | HTTPS URL | media* | Publicly reachable file |
| `media_id` | string | media* | Id of media already uploaded to Meta |
| `caption` | string ≤ 1024 | no | `image`, `video`, `document` only |
| `filename` | string | no | `document` only |
| `reply_to` | string | no | `wamid` to quote (adds `context.message_id`) |
| `idempotency_key` | string ≤ 64 | no | Same key → same record, no second send |

\* Media types need exactly one of `media_link` or `media_id`.

**Rules from WhatsApp, not USHIKA:**
- Free-form messages (text or media) are accepted only within 24 hours of the customer's last message. Outside that window, send a template.
- On a test number, recipients must be on the verified list.

**Request: text reply**
```json
{
  "to": "+1 631 555 1234",
  "type": "text",
  "text": "Yes, it is ready for pickup.",
  "reply_to": "wamid.HBgLMTYzMTU1NTEyMzQVAgASGBQzQTdGNDc5MjBBQkI1RjQ3RkQ5RQA=",
  "idempotency_key": "order-1042-ready"
}
```
**Response: `201 Created`** (accepted by Meta; delivery statuses follow by webhook)
```json
{
  "id": 3,
  "wa_message_id": "wamid.HBgLMTYzMTU1NTEyMzQVAgARGBI5QTNDQTVCM0Q0Q0Q2RTY3RTcA",
  "contact": {"id": 1, "wa_id": "16315551234", "profile_name": "Kerry Fisher"},
  "direction": "outbound",
  "message_type": "text",
  "status": "accepted",
  "body": "Yes, it is ready for pickup.",
  "context_wa_message_id": "wamid.HBgLMTYzMTU1NTEyMzQVAgASGBQzQTdGNDc5MjBBQkI1RjQ3RkQ5RQA=",
  "timestamp": "2026-10-27T19:19:32.060227Z",
  "status_updated_at": "2026-10-27T19:19:32.061803Z",
  "error_code": "", "error_title": "", "error_details": "",
  "attachments": [],
  "created_at": "2026-10-27T19:19:32.060766Z",
  "phone_number_id": "109876543210",
  "idempotency_key": "order-1042-ready",
  "sent_by": "operator",
  "payload": {
    "messaging_product": "whatsapp",
    "recipient_type": "individual",
    "to": "16315551234",
    "type": "text",
    "text": {"body": "Yes, it is ready for pickup.", "preview_url": false},
    "context": {"message_id": "wamid.HBgLMTYzMTU1NTEyMzQVAgASGBQzQTdGNDc5MjBBQkI1RjQ3RkQ5RQA="}
  },
  "status_events": []
}
```

**Request: template**
```json
{
  "to": "16315551234",
  "type": "template",
  "template_name": "order_update",
  "language_code": "en_GB",
  "components": [{"type": "body", "parameters": [{"type": "text", "text": "Kerry"}]}]
}
```

**Request: document by link**
```json
{"to": "16315551234", "type": "document", "media_link": "https://example.com/invoice.pdf",
 "caption": "Invoice", "filename": "invoice.pdf"}
```

**Response: `502 Bad Gateway`** (Meta rejected the send; the record is kept as `failed`)
```json
{
  "id": 4,
  "wa_message_id": null,
  "contact": {"id": 2, "wa_id": "447700900123", "profile_name": ""},
  "direction": "outbound",
  "message_type": "template",
  "status": "failed",
  "body": "hello_world",
  "error_code": "131030",
  "error_title": "(#131030) Recipient phone number not in allowed list",
  "error_details": "Recipient phone number not in allowed list",
  "…": "remaining fields as in the 201 example"
}
```

**Response: `200 OK`**: replay of an `idempotency_key` already used; returns the original record unchanged.

**Response: `400 Bad Request`**
```json
{"text": ["Required for text messages."]}
```
```json
{"to": ["Enter a phone number in international format (7-15 digits)."]}
```
Other 400 cases:
- `template_name` missing for a template.
- Neither or both of `media_link`/`media_id`.
- `media_link` not HTTPS.
- `caption` on audio or sticker.
- `filename` on a non-document.
- Text-only fields on other types, or template-only fields on other types.
- Unknown `type`.

**Status lifecycle of an outbound message:** `pending` (stored, before Meta answers), then `accepted` (Meta returned a `wamid`), `sent`, `delivered`, `read`. It can become `failed` at any point, with `error_*` filled from Meta.

---

## Attachments

### Saving media (contact levels)

Inbound media is recorded on arrival (type, MIME type, filename, caption) but the file is not downloaded: the attachment starts as `skipped`. A client saves it to local storage with [`POST /attachments/{id}/save/`](#post-apiv1attachmentsidsave). Whether that is allowed depends on what kind of file it is:

| Kind | Who can save it |
|---|---|
| Image (`media_type` `image`) | Anyone, if the contact's level has **can save images** |
| PDF (`document` with MIME type `application/pdf`) | Anyone, if the contact's level has **can save PDFs** |
| Anything else: audio, video, stickers, Word/Excel and other documents | Superusers only |

A contact with no level has no images or PDFs saved, by anyone. Superusers follow the level rules for images and PDFs too. These rules are about keeping a file in storage; a superuser can still look at any file without saving it (see [Previewing and downloading](#previewing-and-downloading)).

Setting `WHATSAPP_DOWNLOAD_MEDIA=true` brings back download on arrival, for images and PDFs the contact's level allows (other media still waits for a superuser).

### Previewing and downloading

| | Saved file | Not saved |
|---|---|---|
| Superuser | From storage | Fetched from WhatsApp for that request, then discarded |
| Other users | From storage | `404` |

A superuser can get any file, whatever the contact's level. Fetching an unsaved file runs the same size, hash and HTML checks as a save, doesn't change the attachment and stores nothing, so each request fetches it again. It needs a valid `WHATSAPP_ACCESS_TOKEN` and only works while Meta still holds the file (about 30 days). After that, only saved files can be opened.

In the Django admin, **Media attachments** has Preview and Download links on every row, and opening an attachment shows the preview on its page. A message's page has the same links for its attachments.

### `GET /api/v1/attachments/`
| Query | |
|---|---|
| `download_status` | `pending`, `downloaded`, `failed`, `skipped` |
| `media_type` | `image`, `document`, `audio`, `video`, `sticker` |
| `message` | message `id` |
| `ordering` | `created_at`, `downloaded_at` |

Each item has the same shape as in the message example. `download_url` is `null` when you can't get the file (it isn't saved and you aren't a superuser). `preview_url` is also `null` when the file type can't be previewed.

### `GET /api/v1/attachments/{id}/`
A single attachment.

### `GET /api/v1/attachments/{id}/download/`
Streams the file as a download (see [who can get what](#previewing-and-downloading)):
- `200` with `Content-Type` set to the file's MIME type and `Content-Disposition: attachment; filename="…"`.
- `404 {"detail": "This attachment has not been downloaded."}` if it isn't saved and you aren't a superuser, or `{"detail": "The stored file is missing from storage."}` if the file was removed from disk.
- `502 {"detail": "…"}` if an unsaved file couldn't be fetched from WhatsApp. The attachment doesn't change.

This works with any `Accept` header.

### `GET /api/v1/attachments/{id}/preview/`
The same file with the same access rules, for showing in a browser:
- `200` with `Content-Disposition: inline; filename="…"`. Pages on the same origin can embed it in a frame.
- `404 {"detail": "This file type can't be previewed. Download it instead."}` for anything but PDFs, plain text, JPEG, PNG, WebP and GIF images, MP4 and WebM video, and MP3, M4A, AAC, Ogg, Opus and WAV audio. Browsers can't show Word, Excel or PowerPoint files, and HTML, SVG and XML can carry scripts, so those can only be downloaded.
- The other `404` and `502` responses are the same as for download.

### `POST /api/v1/attachments/{id}/save/`
Fetches the file from WhatsApp and saves it to local storage, synchronously. It is also how a failed save is retried; earlier failures and the attempt cap don't block it. No body.
- `200`: the attachment, now `downloaded` (also returned if it already was).
- `403`: not allowed, with the reason. Nothing is fetched and the attachment is unchanged:
  - `{"detail": "This contact's level does not allow saving images."}` (or `… PDFs.`)
  - `{"detail": "Only admins can save audio files."}` (or `… non-PDF documents.`, `… video files.`, `… sticker files.`)
- `502`: the attachment, `failed`, with `last_error` explaining why.

Meta keeps inbound media for about 30 days, so save files within that window.

---

## Delivery statuses

### `GET /api/v1/statuses/`
Every status notification received, oldest first.

| Query | |
|---|---|
| `wa_message_id` | the `wamid` |
| `status` | `sent`, `delivered`, `read`, `failed`, or any other value Meta sends |
| `message` | message `id` (statuses for unknown messages have `message: null`) |
| `ordering` | `timestamp`, `created_at` |

```json
{
  "count": 1, "next": null, "previous": null,
  "results": [{
    "id": 1,
    "message": 3,
    "wa_message_id": "wamid.HBgLMTYzMTU1NTEyMzQVAgARGBI5QTNDQTVCM0Q0Q0Q2RTY3RTcA",
    "status": "delivered",
    "timestamp": "2025-10-27T21:26:40Z",
    "recipient_id": "16315551234",
    "conversation_id": "",
    "pricing_category": "",
    "error_code": "", "error_title": "", "error_details": "",
    "created_at": "2026-10-27T19:19:32.068281Z"
  }]
}
```

### `GET /api/v1/statuses/{id}/`
A single event.

---

## Non-API endpoints

### Webhook: `/webhooks/whatsapp/` (called by Meta, not by clients)

| Request | Response |
|---|---|
| `GET ?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=<n>` | `200 text/plain <n>`; `403` wrong or unconfigured token; `400` bad mode or missing challenge |
| `POST` JSON + `X-Hub-Signature-256: sha256=<hex HMAC of raw body>` | `200 {"status": "ok"}`; `200 {"status": "duplicate"}`; `403` bad or missing signature; `400` invalid JSON |

Payload format: Meta's Cloud API webhook reference (developers.facebook.com → WhatsApp → Webhooks). The handler processes `object=whatsapp_business_account` with `field=messages` (both `messages` and `statuses`) and acknowledges everything else.

### Other

| Path | |
|---|---|
| `GET /health/` | `{"status": "ok"}`, no auth |
| `GET /api/schema/` | OpenAPI 3 YAML. Open in DEBUG; staff-only otherwise. |
| `GET /api/docs/` | Swagger UI. Same access as the schema. |
| `/admin/` | Django admin (staff) |
