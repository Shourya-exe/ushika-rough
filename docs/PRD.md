# USHIKA: Product Requirements Document

| | |
|---|---|
| Product | USHIKA: WhatsApp Integration POC |
| Status | Implemented; awaiting real Meta test-number verification |
| Last updated | 2026-10-28 |

## 1. Problem and goals

Teams that talk to customers on WhatsApp need those conversations inside their own systems: stored, searchable, auditable, and usable for automated replies. USHIKA does this through Meta's **official** WhatsApp Business Cloud API, with no unofficial clients and no personal-account automation.

**Goals**
1. **G1:** Receive incoming WhatsApp messages and delivery-status notifications through Meta webhooks.
2. **G2:** Persist contacts, message content, timestamps and delivery statuses.
3. **G3:** Download supported incoming media (images, documents, etc.) to local storage.
4. **G4:** Expose messages, contacts, attachments and statuses through secure REST APIs.
5. **G5:** Send WhatsApp messages from the backend and record the results.
6. **G6:** Be safe by default: signature validation, authentication, duplicate prevention and error handling.
7. **G7:** Be verifiable with Postman, automated tests and one real exchange with a Meta test number.

## 2. Users

| User | Needs |
|---|---|
| **Integrating developer / client system** | Pulls messages and files through the API; sends messages; needs stable contracts and clear errors. |
| **Operator / support staff** | Inspects conversations, failed downloads and failed webhook events in the admin; triggers retries. |
| **Customer on WhatsApp** | Messages the business number and gets replies. Never interacts with USHIKA directly. |
| **Meta** (system actor) | Calls the webhook; expects the verify-token handshake and a quick 200. |

## 3. User stories and acceptance criteria

| ID | Story | Acceptance criteria |
|---|---|---|
| US-1 | As Meta, I can verify the webhook subscription. | `GET /webhooks/whatsapp/` with `hub.mode=subscribe` and the right `hub.verify_token` returns `hub.challenge` as text/plain with 200. A wrong or missing token returns 403. A bad mode or missing challenge returns 400. |
| US-2 | As the business, only genuine Meta events are processed. | A POST without a valid `X-Hub-Signature-256` (HMAC-SHA256 of the raw body with the app secret) returns 403 and stores nothing. With no app secret configured, every POST is rejected. |
| US-3 | As an operator, I see each customer message once, with sender and time. | An inbound message creates or updates a `Contact` (with profile name) and stores one `Message` with type, text or caption, WhatsApp timestamp and raw payload. Redelivering it (same body or a new envelope) creates no new rows. |
| US-4 | As an operator, attachments are saved locally. | Inbound media creates a `MediaAttachment`. On request (`POST /api/v1/attachments/{id}/save/`) the file is fetched from Meta, checked against the size limit and Meta's SHA-256, and saved under `MEDIA_ROOT/whatsapp/YYYY/MM/<media_id>/`. Failures record `download_status=failed` with `last_error`. |
| US-4a | As the business, only permitted media is stored. | Images are saved only when the contact's level has *can save images*, and PDFs only with *can save PDFs*. A contact without a level has nothing saved. Audio, video, stickers and other documents are saved only by a superuser. A refused save returns 403 and fetches nothing. Levels are managed in the Django admin. |
| US-5 | As an operator, I can retry failed downloads. | `POST /api/v1/attachments/{id}/save/`, the admin action and `manage.py retry_media_downloads` each re-attempt (subject to US-4a) and update the attachment. |
| US-6 | As a client system, I can list and fetch data securely. | Every `/api/v1/` endpoint requires a token or session. Messages can be filtered by direction, type, status, contact, `wa_id` and time window, and searched by text. Responses are paginated. |
| US-7 | As a client system, I can download stored files. | `GET /api/v1/attachments/{id}/download/` streams the file as an attachment with its MIME type; it returns 404 if the file isn't downloaded. No public media URL exists. |
| US-7a | As an admin, I can preview any file and download whichever I want. | A superuser can open any attachment from the admin or `GET /api/v1/attachments/{id}/preview/` and `/download/`, whatever the contact's level. Unsaved files are fetched from Meta and not kept. PDFs, images, plain text, audio and video can be previewed; other types can only be downloaded. |
| US-8 | As a client system, I can send messages. | `POST /api/v1/messages/send/` supports text, template, image, document, audio, video and sticker, plus reply context. A success returns 201 with the stored message and its `wamid`. A Meta rejection returns 502 with the stored failed message and Meta's error code and details. |
| US-9 | As a client system, retries never double-send. | Repeating a send with the same `idempotency_key` returns 200 with the original record and makes no second call to Meta. |
| US-10 | As an operator, I see delivery progress. | Status webhooks are stored as `MessageStatusEvent`s. The message status moves forward only (`accepted → sent → delivered → read`, or `failed` with error details). Duplicates and out-of-order statuses are handled. |
| US-11 | As an operator, processing failures aren't lost. | If processing a signed webhook fails, the response is still 200, the `WebhookEvent` is marked `failed` with the error, and `manage.py reprocess_webhooks` replays it. |
| US-12 | As a developer, I can verify the system. | Automated tests run without network access. The Postman collection signs simulated webhooks. TESTING.md has a real-number checklist. |

## 4. Functional requirements

- **FR-1 Webhook:** handshake (US-1); signature validation (US-2); JSON validation (400 on invalid JSON); audit copy of each delivery (`WebhookEvent`).
- **FR-2 Message types:** store all inbound types. Readable `body` text is extracted for text, image/video/document captions, button and interactive replies, reactions, locations and shared contacts. Unsupported types keep Meta's error.
- **FR-3 Contacts:** keyed by `wa_id`; profile name is updated from the latest webhook.
- **FR-4 Media:** saved on request, gated by contact level (images, PDFs) or superuser (other media); optional download on arrival; configurable types (`WHATSAPP_MEDIA_TYPES`), size limit (`WHATSAPP_MEDIA_MAX_BYTES`, default 100 MB), SHA-256 verification (hex or base64), HTML-error-page detection, filename sanitisation, attempt counting.
- **FR-5 REST API:** contacts, messages, attachments, statuses, send, preview, download, save, token issue, login check (`auth/me/`), OpenAPI schema and Swagger UI.
- **FR-6 Outbound:** text (with link preview flag), templates (name, language, components), media by HTTPS link or Meta media id, reply context, idempotency keys.
- **FR-7 Status tracking:** forward-only ranking; orphan statuses (arriving before the send response saves the `wamid`) are linked afterwards.
- **FR-8 Operations:** admin screens; replay and retry commands; structured logging without secrets or personal data.

## 5. Non-functional requirements

| Area | Requirement |
|---|---|
| Security | HMAC signature check with constant-time comparison; token auth on every API endpoint; no public file URLs; production refuses to start without `DJANGO_SECRET_KEY`. See [SECURITY.md](SECURITY.md). |
| Reliability | At-least-once webhooks handled idempotently; failed processing is replayable; media downloads retry; outbound sends are never auto-retried. |
| Performance | Webhook DB work is a few inserts. Media downloads can move off the request path with Celery. List endpoints paginate (50 per page by default, max 200). |
| Portability | SQLite to PostgreSQL by env var; local disk to object storage through Django's storage API. |
| Observability | `whatsapp.*` loggers; `WebhookEvent` audit trail; admin visibility of failures. |

## 6. Scope

**In scope:** everything in sections 3–5, for one WhatsApp Business phone number configured through environment variables.

**Out of scope / exclusions**
- Reading historical chats, or anything outside Meta's supported webhook events and Cloud API operations.
- Automating a personal WhatsApp account or WhatsApp Web.
- Email integration (a separate future workstream; provider and auth undecided).
- Uploading local files to Meta for outbound media (send by HTTPS link or an existing media id).
- Template management (creating or approving templates), WhatsApp Flows, catalog and commerce, calling.
- Multi-tenant or multi-number routing, role-based permissions inside the API (beyond contact levels for saving media), a UI beyond the Django admin.
- Automatic data-retention purging (see [SECURITY.md](SECURITY.md#data-retention)).

## 7. Success criteria (definition of done)

The POC succeeds when:
1. A **real** WhatsApp message from a phone reaches USHIKA through Meta's webhook and passes signature validation.
2. It is stored (contact plus message) and is retrievable through authenticated REST endpoints.
3. A real attachment is downloaded and saved locally, and can be fetched through the download endpoint.
4. An outbound message sent through `POST /api/v1/messages/send/` arrives on the phone, and its `sent/delivered/read` statuses update the record.
5. Error handling holds: invalid signatures rejected, duplicates ignored, failed downloads retryable.
6. The Postman collection and the automated test suite pass.

Items 1–4 need real Meta credentials. Items 5–6 are verified locally. Current state is tracked in [TASKS.md](TASKS.md).

## 8. Expected outcomes

| Outcome | Delivered by |
|---|---|
| Receiving messages | `webhooks.py` + `processing.py` |
| Persisting information | `models.py`: five models, unique constraints |
| Managing media | `media.py` + `tasks.py` |
| Exposing REST APIs | `whatsapp/api/`, `/api/docs/` |
| Sending messages | `messaging.py`, `POST /api/v1/messages/send/` |
| Tracking statuses | `processing.record_status/apply_status`, `/api/v1/statuses/` |
| Handling failures | signature rejection, idempotency, `reprocess_webhooks`, `retry_media_downloads` |
| Supporting verification | `whatsapp/tests/`, `postman/`, [TESTING.md](TESTING.md) |

## 9. Open questions

- Production hosting target and object-storage provider. These decide when to swap `STORAGES` (see [DECISIONS.md](DECISIONS.md)).
- Data-retention period for messages and media (legal and business input needed).
- Whether API consumers need per-client scoping (multiple tokens with different permissions).
- Email workstream: provider (Gmail API, Microsoft Graph, IMAP) and auth model.
