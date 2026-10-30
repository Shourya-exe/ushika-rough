# USHIKA: Implementation tasks

Status as of **2026-10-28**: all six phases are implemented and verified locally (51 automated tests and a 17-check live smoke test). The remaining work is verification against real Meta credentials, plus production hardening.

Legend: ✅ done · 🔲 open · ⛔ blocked (needs something outside the codebase)

## Phase 1: Project setup
**Deliverable:** configured development environment. **Depends on:** none.

- ✅ Python 3.12 virtualenv; `requirements.txt` (Django 5.2 LTS, DRF, drf-spectacular, django-filter, requests, python-dotenv, Celery, Redis), plus `requirements-dev.txt` and `requirements-prod.txt`.
- ✅ Django project `config/` and app `whatsapp/` with a module per responsibility.
- ✅ Settings fully env-driven (`.env` / `.env.example`); one `WHATSAPP` config dict; SQLite/PostgreSQL switch; logging.
- ✅ `.gitignore` (venv, `.env`, database, `storage/`).
- ✅ Fixed Phase 1 issues: `REST_FRAMEWORK` and `MEDIA_ROOT` were each defined twice (the second copy dropped token auth and moved media to a public-style path); `ALLOWED_HOSTS` read the wrong env var; the venv was missing packages; `SECRET_KEY` silently fell back to an insecure default.
- 🔲 Meta app setup: copy the phone number id, WABA id, access token and app secret into `.env`; invent a verify token.

**Done when:** `manage.py check` is clean, migrations apply, and the admin loads. ✅

## Phase 2: Webhook integration
**Deliverable:** secure incoming event receiver. **Depends on:** Phase 1.

- ✅ `GET /webhooks/whatsapp/` handshake with constant-time verify-token check (400 / 403 paths).
- ✅ `POST` signature validation of the raw body (`X-Hub-Signature-256`); rejects all requests when the app secret is missing.
- ✅ JSON validation; CSRF exemption scoped to this view only.
- ✅ `WebhookEvent` audit record (body SHA-256, payload, status, attempts, error).
- ✅ Always 200 after a valid signature; failures recorded for replay.
- ⛔ Register the callback URL in Meta. Needs a public HTTPS URL (tunnel or deployment) and real credentials.

**Done when:** Meta's "Verify and save" succeeds and the `messages` field is subscribed. (Locally: verified with tests and the smoke test.)

## Phase 3: Database and processing
**Deliverable:** persisted WhatsApp data. **Depends on:** Phase 2.

- ✅ Models: `Contact`, `Message`, `MediaAttachment`, `MessageStatusEvent`, `WebhookEvent`, with indexes and unique constraints.
- ✅ Normalisation of all inbound types into `Message` (readable `body`, reply context, raw payload, Meta errors on unsupported types).
- ✅ Contact upsert with profile-name refresh.
- ✅ Duplicate prevention at three levels (body hash, `wamid`, status triple) and race-safe through savepoints.
- ✅ Forward-only status tracking with a conditional `UPDATE`; orphan-status reconciliation.
- ✅ `reprocess_webhooks` command and admin action.

**Done when:** inbound messages and statuses persist exactly once. ✅ (tests)

## Phase 4: Media management
**Deliverable:** locally stored attachments. **Depends on:** Phase 3.

- ✅ `WhatsAppClient.get_media_info` / `open_media_stream` (Bearer auth, timeouts, GET retries).
- ✅ Streaming download into a temp file with a size limit; SHA-256 check (hex or base64); HTML-error detection; empty-file detection.
- ✅ Safe filenames and the `whatsapp/YYYY/MM/<media_id>/` layout through Django storage.
- ✅ Configurable media types (others `skipped`), attempt counting, `last_error`.
- ✅ Retry paths: API `POST /attachments/{id}/save/`, admin action, `retry_media_downloads`, and Celery backoff.
- ✅ Contact levels (2026-10-28): media saved on request; images and PDFs only when the contact's level allows; other media superuser-only. Download on arrival is now off by default (`WHATSAPP_DOWNLOAD_MEDIA=false`).
- ✅ Admin file access (2026-10-30): superusers preview and download any file from the admin or the API; unsaved files are fetched from Meta and not kept.
- ⛔ Verify against a real inbound image and document (needs credentials).

**Done when:** a real attachment is saved under `storage/` and downloadable through the API.

## Phase 5: REST APIs and messaging
**Deliverable:** functional backend integration. **Depends on:** Phases 3–4.

- ✅ Token auth (`/api/v1/auth/token/`, `drf_create_token`) and session auth; everything authenticated by default. `GET /api/v1/auth/me/` checks a login.
- ✅ Read APIs for contacts, messages (detail includes status history), attachments and statuses, with filters, search, ordering and pagination.
- ✅ Authenticated file download; no public media route.
- ✅ `POST /messages/send/`: text, template, image, document, audio, video, sticker; replies; validation; idempotency keys; failures stored with Meta's error (502).
- ✅ OpenAPI schema and Swagger UI (`/api/docs/`); schema validates with no warnings.
- ⛔ Real send to the verified test recipient, and real `sent/delivered/read` webhooks.

**Done when:** a message sent through the API arrives on the phone and its statuses update.

## Phase 6: Testing and deployment
**Deliverable:** tested and documented POC. **Depends on:** Phases 1–5.

- ✅ 51 automated tests (webhook, processing, media, API) with Meta mocked through `responses`.
- ✅ Live smoke test against `runserver`, 17/17 checks (handshake, signatures, dedup, storage, API auth, failed-send recording, idempotency, statuses, schema).
- ✅ Postman collection (`postman/USHIKA.postman_collection.json`): 34 requests, webhook bodies signed automatically.
- ✅ Logging (no secrets, phone numbers or message text), media retries, webhook replay.
- ✅ Deployment prep: `requirements-prod.txt` (gunicorn, psycopg), production security settings, `check --deploy` clean apart from opt-in HSTS flags.
- ✅ Documentation set (README, BRAIN, PRD, ARCHITECTURE, API, TASKS, TESTING, SECURITY, DECISIONS).
- 🔲 Run the Postman collection end to end in Postman or Newman.
- ⛔ Real Meta test-number exchange (the [TESTING.md](TESTING.md#4-real-meta-test-number-checks) checklist).
- 🔲 Choose hosting; provision PostgreSQL, Redis and persistent or object storage; set production env vars; `collectstatic`; run gunicorn behind HTTPS.

**Done when:** the PRD success criteria are all checked.

## Known blockers

| Blocker | Unblocks | Owner / action |
|---|---|---|
| No Meta credentials in `.env` | Real webhooks, downloads, sends | Fill `WHATSAPP_*` from the Meta app ([README](../README.md#meta-setup)) |
| No public HTTPS URL | Webhook registration | `cloudflared tunnel --url http://127.0.0.1:8000` (or ngrok), or deploy |
| Temporary token lasts about 24 h | Anything beyond a day of testing | Create a System User token with `whatsapp_business_messaging` and `whatsapp_business_management` |
| Test number only reaches verified recipients | Messaging other people | Add recipients in API Setup, or register a real business number |
| Free-form sends need an open 24-hour window | Text replies | Message the test number from your phone first, or send `hello_world` |

## Next steps (in order)

1. Fill `.env` with Meta credentials and restart.
2. Start a tunnel, register the webhook in Meta, subscribe to `messages`.
3. Run the real-number checklist in [TESTING.md](TESTING.md#4-real-meta-test-number-checks): inbound text, image and document, outbound text and template, statuses.
4. Run the Postman collection against the same server.
5. Decide production hosting and object storage (see [DECISIONS.md](DECISIONS.md)), then turn on `USE_CELERY`.
6. Agree on a data-retention policy and implement a purge command ([SECURITY.md](SECURITY.md#data-retention)).

## Possible follow-ups (not in POC scope)

- Upload local files to Meta (`POST /{phone_number_id}/media`) so outbound media doesn't need a public URL.
- Mark inbound messages as read (`{"status": "read", "message_id": …}`) from the API.
- Multiple phone numbers or tenants; per-client API scopes.
- Containerisation (Dockerfile / compose) for the target host.
- Email integration module.
