# USHIKA: Engineering decisions

Each entry records the context, the decision, what it costs, and when to reconsider it. Add new decisions at the end; don't rewrite old ones. Supersede them with a new entry instead.

---

## D1. Django 5.2 LTS, not Django 6.x
**Context.** The environment initially had Django 6.1. The project is a POC that may become production code.
**Decision.** Pin `Django>=5.2,<5.3` (5.2 LTS).
**Consequences.** Security support until April 2028, with full DRF, drf-spectacular, django-filter and Celery compatibility. It lacks 6.x features, none of which USHIKA needs.
**Revisit when.** The next LTS (6.2) is released and the ecosystem supports it.

## D2. SQLite locally, PostgreSQL in production
**Context.** The POC needs zero-setup persistence. Production needs concurrent writers (web workers and Celery), reliable locking and backups.
**Decision.** SQLite is the default. `DB_ENGINE=postgres` switches to PostgreSQL (`psycopg` in `requirements-prod.txt`). The code relies only on portable features: unique constraints, savepoints, conditional `UPDATE`s, `JSONField`.
**Consequences.** Easy local runs and fast tests. SQLite serialises writes, which is fine for one developer but not for concurrent webhook traffic.
**Revisit when (introduce PostgreSQL).** Any of these: deploying beyond one machine; running Celery workers; more than one web worker; needing point-in-time backups; data you can't afford to lose.

## D3. Local filesystem media through Django's storage API
**Context.** The brief asks for media to be stored locally. Production will need durability and possibly several app servers.
**Decision.** Save files with `FileField` on the default storage, rooted at `MEDIA_ROOT` (`./storage`). `media.py` only uses the storage API, never raw `open()` paths.
**Consequences.** Nothing extra to run. Moving to S3, GCS or Azure Blob needs no code change: install `django-storages` and set `STORAGES["default"]` (a private bucket). Local disk isn't shared between servers, isn't durable on ephemeral containers, and needs its own backups.
**Revisit when (introduce object storage).** Any of these: more than one app server or container; container platforms with ephemeral disks; media volume beyond what a single disk and backup comfortably hold; a need for lifecycle rules (automatic expiry) or encryption-at-rest managed by the provider.

## D4. No public media URL
**Context.** Customer files are personal data.
**Decision.** No `MEDIA_URL` route. Files are served only by the authenticated `GET /api/v1/attachments/{id}/download/`, always as an attachment download.
**Consequences.** Every download passes through Django (fine at POC scale). For object storage, the endpoint could later return short-lived signed URLs instead of streaming.
**Revisit when.** Download volume makes streaming through Django a bottleneck.

## D5. Acknowledge every validly signed webhook with 200
**Context.** Meta retries non-200 responses for up to 7 days. A permanently failing payload would be retried endlessly, and could get the webhook flagged.
**Decision.** After signature validation: store the raw event, process it in a transaction, and return 200 whatever happens. Failures are kept on `WebhookEvent` (`status=failed`, `error`) and replayed with `manage.py reprocess_webhooks` or the admin action. A redelivery of a failed event is processed again.
**Consequences.** Transient failures don't use Meta's retry. Recovery depends on our replay tooling, so failed events must be monitored.
**Revisit when.** There is alerting on failed events; or consider returning 5xx only for clearly transient errors (database unavailable).

## D6. Layered duplicate prevention
**Context.** Webhooks are delivered at least once, can be batched differently on redelivery, and can arrive concurrently.
**Decision.** Three keys: body SHA-256 (`WebhookEvent`), `wamid` (`Message.wa_message_id` unique), and `(wamid, status, timestamp)` (`MessageStatusEvent`). Existence checks give a fast path. Unique constraints plus `IntegrityError` caught inside savepoints handle races.
**Consequences.** Correct under concurrency on both SQLite and PostgreSQL. A status repeated with a *different* timestamp is stored as a separate event (it is genuinely a different notification).

## D7. Forward-only status ranking via a conditional UPDATE
**Context.** Status webhooks can arrive out of order (for example `read` before `delivered`).
**Decision.** `STATUS_RANK`: pending < accepted < sent < delivered < read < failed. Apply only `UPDATE … WHERE status IN (lower ranks)`. Unknown statuses are stored as events only. Statuses for unknown `wamid`s are stored with `message=NULL` and linked by `reconcile_orphan_statuses` after a send.
**Consequences.** A message's status can never regress, and the full history stays in `MessageStatusEvent`.

## D8. Celery is optional; inline after commit by default
**Context.** The brief says Celery and Redis are needed only when async processing is required. Media downloads are the only slow work.
**Decision.** `tasks.schedule_media_download` uses `transaction.on_commit(robust=True)`. With `USE_CELERY=false` it calls the task inline; with `true` it queues to Celery with backoff retries.
**Consequences.** The POC has no infrastructure dependency. Inline downloads delay the webhook response by the download time.
**Revisit when.** In production, or when media is large or frequent: turn on `USE_CELERY`.

## D9. Never auto-retry outbound sends; use idempotency keys
**Context.** Retrying a POST after a timeout can deliver the same WhatsApp message twice, which customers see.
**Decision.** The HTTP session retries only GETs. Sends are stored first, then attempted once; failures are recorded. Clients get safe retries with `idempotency_key` (unique), which returns the original record without calling Meta.
**Consequences.** A timed-out but actually delivered send is recorded as `failed` (and may later receive a `sent` webhook, but only if a `wamid` was returned). Operators decide whether to resend.

## D10. DRF token authentication
**Context.** Internal clients and Postman need simple, revocable credentials.
**Decision.** `rest_framework.authtoken`, one token per user, plus session auth for the admin and browsable API.
**Consequences.** Simple, with no expiry or scopes.
**Revisit when.** External or third-party clients, or several services with different rights. Then consider scoped API keys, OAuth2 client credentials, or JWT with expiry.

## D11. One `WHATSAPP` settings dict, read at call time
**Decision.** All Meta configuration lives in `settings.WHATSAPP` and is read inside functions.
**Consequences.** Tests override everything with one `override_settings`. There's a single place to audit configuration.

## D12. Plain Django view for the webhook
**Context.** Signature verification needs the exact raw body, and the endpoint must not require API authentication.
**Decision.** `WhatsAppWebhookView` is a CSRF-exempt Django `View`, not a DRF view.
**Consequences.** No DRF parser can consume or alter the body before verification, and no API auth applies to Meta's calls.

## D13. Graph API version `v25.0` by default, configurable
**Context.** Meta released v25.0 in February 2026. Versions are supported for about 2 years, and the scaffold's earlier default (v21.0, October 2024) is at end of life.
**Decision.** Default `v25.0`, overridable with `WHATSAPP_API_VERSION`.
**Revisit when.** Meta announces deprecation of v25.0 (check the Graph API changelog). Bump the setting and re-run the real-number checklist.

## D14. SHA-256 check accepts hex or base64
**Context.** Meta's documentation shows media hashes without a clear encoding, and observed values differ by surface.
**Decision.** Compare against hex if the value is 64 hex characters, or against base64 or base64url if it decodes to 32 bytes. An unrecognised format logs a warning and skips the check rather than rejecting every file.
**Revisit when.** Real traffic confirms a single format; then tighten the check.

## D15. Store raw payloads
**Decision.** Keep the raw inbound message (`Message.payload`), the outbound request, and full webhook bodies (`WebhookEvent.payload`).
**Consequences.** Full auditability, replay, and new fields can be extracted later without data loss. It duplicates personal data, so it's covered by the retention policy in [SECURITY.md](SECURITY.md#data-retention).

## D16. HTTP mocking with `responses`; no network in tests
**Decision.** Tests fake Meta at the `requests` adapter layer, with payload builders in `tests/helpers.py`. Real Meta verification is a separate, manual checklist.
**Consequences.** A fast, deterministic suite (about 1 s). It can't catch changes in Meta's real behaviour, which is what the real-number checklist and Postman are for.

## D17. Documentation layout
**Decision.** `README.md` and `BRAIN.md` at the root (front page and agent orientation); detailed docs in `docs/`.

## D18. Media saved on request, gated by contact level
**Context.** Not every customer's files should be kept, and only images and PDFs are needed routinely.
**Decision.** Inbound media is recorded on arrival but not downloaded (`WHATSAPP_DOWNLOAD_MEDIA=false` by default). `POST /api/v1/attachments/{id}/save/` fetches it. `media.save_refusal` is the single rule: images need the contact's `ContactLevel.can_save_images`, PDFs (`application/pdf` documents) need `can_save_pdfs`, and all other media needs a superuser. Levels are rows edited in the admin, so the rules change without code. The API save, the admin action, `retry_media_downloads` and the optional on-arrival download all check it.
**Consequences.** Nothing is stored for a contact without a level. Files must be saved while Meta still holds them (about 30 days). The PDF check trusts the MIME type WhatsApp reports. Superusers follow the level rules for images and PDFs too.
**Revisit when.** API users need their own levels (then add Django permissions or groups on top), or files must be checked by content rather than MIME type.

## D19. Superusers preview and download any file without saving it
**Context.** Admins must be able to view any customer file and download the ones they choose, but contact levels (D18) forbid storing some files, even for superusers.
**Decision.** Levels keep deciding what is stored. For a superuser, `preview` and `download` on an unsaved attachment fetch the file from Meta into a temp file with the usual checks, serve it, and discard it. `preview` serves only `media.PREVIEW_MIME_TYPES` inline: never HTML, SVG or XML, which could run scripts on the app's origin in an admin's session. The admin links to these endpoints, so files are served from one place only.
**Consequences.** An unsaved file can only be viewed while Meta holds it (about 30 days) and while the access token is valid, and each view downloads it again. Word, Excel and PowerPoint files have no preview.
**Revisit when.** Office files need previews (convert on the server, for example with LibreOffice; don't send customer files to an online viewer), or files must stay viewable after Meta's retention without being saved under the level rules.

