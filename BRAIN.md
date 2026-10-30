# BRAIN.md: USHIKA project context

Read this first. It tells an AI coding agent (or a new developer) what USHIKA is, where it stands, and which rules the code depends on. Details live in the linked docs.

## Purpose

USHIKA is a Django/DRF backend that integrates the **Meta WhatsApp Business Cloud API**:
- receives messages and status webhooks
- stores contacts, messages, statuses and attachment metadata
- saves incoming images and PDFs to local storage on request, when the sender's contact level allows it (other media: superusers only)
- lets superusers preview and download any file, saved or not, from the Django admin or the API
- exposes everything through an authenticated REST API, including outbound sends.

It is a POC. The definition of success (from the brief) is: a real WhatsApp message reaches USHIKA, is securely processed and stored, its attachment is saved locally, and the records can be fetched through authenticated REST endpoints. Outbound messaging, status tracking, error handling and Postman testing must also work.

## Current status (2026-10-28)

| Area | State |
|---|---|
| Phases 1–6 (setup → testing/deployment prep) | Implemented |
| Automated tests | 70 passing (`python manage.py test whatsapp`), no network access |
| Live local smoke test | 17/17 checks against `runserver` with signed simulated webhooks |
| OpenAPI schema | `manage.py spectacular --validate --fail-on-warn` passes |
| `check --deploy` (DEBUG off) | Clean except the opt-in HSTS subdomains/preload warnings |
| **Real Meta exchange** | **In progress.** Credentials are in `.env` and the webhook is verified through ngrok (2026-10-28); no inbound message received yet. This is the last success criterion. See [docs/TESTING.md](docs/TESTING.md#4-real-meta-test-number-checks) |
| Postman collection | Built (`postman/`). Not yet run inside Postman/Newman. |
| Email integration | Out of scope (separate future module) |

Open work and blockers: [docs/TASKS.md](docs/TASKS.md).

## Code map

| Path | Responsibility |
|---|---|
| `config/settings.py` | All configuration from env vars; the `WHATSAPP` dict; `USE_CELERY`; logging; production security |
| `whatsapp/models.py` | `ContactLevel`, `Contact`, `Message`, `MediaAttachment`, `MessageStatusEvent`, `WebhookEvent` |
| `whatsapp/security.py` | Verify-token and `X-Hub-Signature-256` checks (constant-time) |
| `whatsapp/webhooks.py` | `GET` handshake and `POST` receiver; the plain Django view that reads the raw body |
| `whatsapp/processing.py` | Payload → rows, duplicate prevention, forward-only status updates, orphan-status reconciliation |
| `whatsapp/client.py` | **Only** module that calls `graph.facebook.com`; `WhatsAppAPIError` |
| `whatsapp/media.py` | `save_refusal` (who may save which media), media lookup → stream → size/hash/HTML checks → save via Django storage, `fetch_unsaved` (same checks, nothing stored), `preview_mime_type` (what may be shown inline) |
| `whatsapp/messaging.py` | Outbound payload building, sending, idempotency, recording results |
| `whatsapp/tasks.py` | `download_media_task` and `schedule_media_download` (Celery or inline, after commit) |
| `whatsapp/api/` | DRF serializers, viewsets, router (`/api/v1/`), pagination |
| `whatsapp/admin.py` | Admin (including contact levels), file previews and download links, plus the "Save file" and "Reprocess" actions |
| `whatsapp/management/commands/` | `reprocess_webhooks`, `retry_media_downloads` |
| `whatsapp/tests/` | `helpers.py` (payload builders, signed-webhook test case) and per-area tests |

## Architectural rules (keep these true)

1. **Only `client.py` talks to Meta.** Everything else goes through `WhatsAppClient`. Tests fake HTTP with `responses`, and nothing in the test suite may reach the network.
2. **Read `settings.WHATSAPP[...]` at call time, never at import time**, so `override_settings` works in tests.
3. **Once the webhook signature is valid, always return 200** (or `{"status": "duplicate"}`). Processing errors go into `WebhookEvent.status/error` and are replayed with `reprocess_webhooks`. A non-200 makes Meta retry the payload for days.
4. **Reject any webhook that isn't signed.** With no `WHATSAPP_APP_SECRET`, every POST is rejected. Don't add a "skip verification" flag.
5. **Every write path is idempotent.** Messages are unique on `wa_message_id`, status events on `(wa_message_id, status, timestamp)`, webhook deliveries on the body SHA-256. Catch `IntegrityError` inside a savepoint for concurrent duplicates.
6. **Outbound status only moves forward**, by `Message.STATUS_RANK`, using a conditional `UPDATE`. Unknown status values are stored as events only.
7. **Never auto-retry an outbound send (POST).** It can double-deliver. Clients use `idempotency_key` instead. Only GETs (media) retry.
8. **Media is never publicly served.** There is no `MEDIA_URL` route. Files leave only through `GET /api/v1/attachments/{id}/download/` and `/preview/`, which require auth; the admin links to them instead of serving files itself. Only types in `media.PREVIEW_MIME_TYPES` are shown inline. Never add one that can carry scripts (HTML, SVG, XML): it would run on our origin in an admin's session.
9. **Background work is scheduled with `transaction.on_commit(..., robust=True)`** via `tasks.schedule_media_download`. It runs on Celery when `USE_CELERY`, otherwise inline.
10. **No secrets, tokens, phone numbers or message text in logs.** Log ids (`wamid`, pk, media id) and error codes.
11. Store every send *before* calling Meta, so failures are kept with Meta's error.
12. **Every path that saves a media file checks `media.save_refusal` first**: the API `save` action, the admin action, `retry_media_downloads` and on-arrival download. Images and PDFs follow the contact's `ContactLevel`; other media needs a superuser. A superuser previewing or downloading an unsaved file stores nothing (`media.fetch_unsaved`), so the level doesn't apply.

## Key decisions (full list in [docs/DECISIONS.md](docs/DECISIONS.md))

- **Django 5.2 LTS** rather than 6.x: support runs to April 2028.
- **SQLite for the POC**, PostgreSQL in production (`DB_ENGINE=postgres`).
- **Local filesystem through Django storage**: moving to object storage is a settings change.
- **DRF token auth** for internal clients.
- **Celery optional**: inline after commit by default.
- **Graph API `v25.0`** by default (configurable).
- **Store raw payloads** (`Message.payload`, `WebhookEvent.payload`) for audit and replay.

## External constraints (Meta)

- Free-form messages only within **24 hours** of the customer's last message. Otherwise send an approved **template** (error 131047).
- A test number can only message **verified recipients**, up to 5 (error 131030 otherwise).
- Media download URLs expire after **about 5 minutes**. Always call `GET /{media_id}` right before downloading.
- Temporary access tokens expire after **about 24 hours** (error 190). Use a System User token for anything longer-lived.
- Webhooks are delivered **at least once** and possibly out of order.

## Commands

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py runserver
python manage.py test whatsapp
python manage.py makemigrations whatsapp
python manage.py spectacular --validate --fail-on-warn --file schema.yml
python manage.py reprocess_webhooks [ids...]
python manage.py retry_media_downloads [ids...]
python manage.py drf_create_token <username>
```

## How to extend

- **New inbound message type**: extend `processing.extract_body`. If it carries media, add the type to `MEDIA_MESSAGE_TYPES` and the default `WHATSAPP_MEDIA_TYPES`. Add a payload builder and a test.
- **New outbound type** (for example `location` or `interactive`): add it to `messaging.SEND_TYPES` and `build_payload`, add fields and validation in `SendMessageSerializer`, add a test in `test_api.py`, and update `docs/API.md`.
- **New Meta call**: add a method on `WhatsAppClient`. Decide whether it's safe to retry (GET-only retries are configured in `build_session`).
- **Schema change**: edit `models.py`, run `makemigrations`, update serializers and `docs/ARCHITECTURE.md` (data model).

## Documentation

[README](README.md) · [PRD](docs/PRD.md) · [Architecture](docs/ARCHITECTURE.md) · [API](docs/API.md) · [Tasks](docs/TASKS.md) · [Testing](docs/TESTING.md) · [Security](docs/SECURITY.md) · [Decisions](docs/DECISIONS.md)
