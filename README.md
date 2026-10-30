# USHIKA: WhatsApp Integration POC

USHIKA is a Django REST backend that connects the official **Meta WhatsApp Business Cloud API** to your own systems. It receives WhatsApp messages through Meta webhooks and stores contacts, messages and delivery statuses. It downloads incoming media to local storage, and exposes all of it, plus outbound sending, through a token-authenticated REST API.

> Email integration is a separate future workstream and is not part of this codebase yet.

## Features

- **Webhook receiver**: Meta's subscription handshake (`hub.challenge`) plus event delivery, with every POST checked against the `X-Hub-Signature-256` HMAC.
- **Persistence**: contacts, inbound and outbound messages, attachment metadata, delivery-status history, and a raw audit copy of every webhook delivery.
- **Duplicate-safe processing**: redelivered payloads, repeated messages (same `wamid`) and repeated statuses are each stored once, including under concurrent deliveries.
- **Media management**: inbound media is recorded on arrival and saved on request through the API. Images and PDFs are saved only when the sender's **contact level** allows them; other media (audio, video, stickers, other documents) only by a superuser. Each download is checked against a size limit and the SHA-256 Meta reports, then saved to local disk under `storage/`. Failed saves can be retried. Superusers can preview and download any file from the admin or the API without saving it.
- **REST API** under `/api/v1/`: log in and check the login; list, filter and search messages, contacts, attachments and statuses; save, preview and download files; send text, template and media messages, with optional idempotency keys.
- **Status tracking**: `sent → delivered → read` (or `failed`) updates move each message forward and never backwards. Meta's error details are kept on failure.
- **Failure handling**: invalid signatures are rejected; processing failures are kept and can be replayed; media downloads retry. Outbound failures are stored along with Meta's error code.
- **Tooling**: OpenAPI docs at `/api/docs/`, a Postman collection, Django admin, a 51-test suite, and optional Celery workers.

## Technology stack

| Concern | Choice |
|---|---|
| Language / framework | Python 3.12, Django 5.2 LTS, Django REST Framework 3.18 |
| WhatsApp | Meta WhatsApp Business Cloud API (Graph API, default `v25.0`) |
| Database | SQLite (POC), PostgreSQL via `DB_ENGINE=postgres` (production) |
| File storage | Local filesystem through Django's storage API (`MEDIA_ROOT`, default `storage/`) |
| HTTP client | `requests` (GET retries on 429/5xx) |
| API docs | OpenAPI 3 via drf-spectacular (`/api/schema/`, `/api/docs/`) |
| Filtering | django-filter |
| Background jobs | Celery + Redis, optional (`USE_CELERY=true`) |
| Testing | Django `TestCase`, DRF `APIClient`, `responses` (HTTP mocking), Postman |

## Project layout

```
config/                 Django project: settings, urls, celery app
whatsapp/
  models.py             ContactLevel, Contact, Message, MediaAttachment, MessageStatusEvent, WebhookEvent
  security.py           verify-token + X-Hub-Signature-256 checks
  webhooks.py           GET handshake / POST event receiver
  processing.py         payload → database, duplicate prevention, status tracking
  client.py             the only module that calls graph.facebook.com
  media.py              who may save which media, plus download, validation and storage
  messaging.py          outbound message payloads and sending
  tasks.py              background download task (Celery or inline)
  api/                  serializers, views, urls, pagination
  admin.py              admin screens, contact levels, "save file" / "reprocess" actions
  management/commands/  reprocess_webhooks, retry_media_downloads
  tests/                automated tests (no network access)
postman/                USHIKA.postman_collection.json
docs/                   PRD, architecture, API, tasks, testing, security, decisions
BRAIN.md                orientation file for AI-assisted development
```

## Setup

You need Python 3.12 and a Meta developer app with the WhatsApp product added. See [Meta setup](#meta-setup).

**Windows (PowerShell)**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env        # then fill it in (see below)
python manage.py migrate
python manage.py createsuperuser
python manage.py drf_create_token <your-username>   # API token for Postman / clients
```

**macOS / Linux**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py drf_create_token <your-username>
```

### Meta setup

1. At [developers.facebook.com](https://developers.facebook.com/), create an app and add the **WhatsApp** product.
2. Go to **WhatsApp → API Setup**. Copy the test number's **Phone number ID**, the **WhatsApp Business Account ID** and the **temporary access token** into `.env`.
3. On the same page, add your own phone as an allowed recipient and verify it.
4. Go to **App settings → Basic** and copy the **App secret** into `WHATSAPP_APP_SECRET`.
5. Invent a random `WHATSAPP_VERIFY_TOKEN`. You'll paste the same value into Meta's webhook settings.
6. For anything longer than a day, replace the temporary token with a System User token. See [docs/SECURITY.md](docs/SECURITY.md).

## Environment variables

All configuration comes from the environment. In development it is loaded from `.env`; `.env.example` lists every variable.

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | — | **Required when DEBUG is off.** Django signing key. |
| `DJANGO_DEBUG` | `false` | Development mode. Keep it off in production. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated host names. Add your tunnel or production host. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | — | Needed for admin login through an HTTPS tunnel or proxy. |
| `DB_ENGINE` | `sqlite` | `postgres` switches to PostgreSQL (`POSTGRES_DB/USER/PASSWORD/HOST/PORT`). |
| `MEDIA_ROOT` | `./storage` | Where downloaded media is written. |
| `WHATSAPP_ACCESS_TOKEN` | — | Bearer token for the Cloud API. |
| `WHATSAPP_PHONE_NUMBER_ID` | — | Business phone number that sends messages. |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | — | WABA id (informational). |
| `WHATSAPP_APP_SECRET` | — | Verifies webhook signatures. All webhooks are rejected without it. |
| `WHATSAPP_VERIFY_TOKEN` | — | Shared secret for Meta's subscription handshake. |
| `WHATSAPP_API_VERSION` | `v25.0` | Graph API version. Match your app's API Setup page. |
| `WHATSAPP_REQUEST_TIMEOUT` | `20` | Seconds per call to Meta. |
| `WHATSAPP_DOWNLOAD_MEDIA` | `false` | `false`: files are saved on request (`POST /api/v1/attachments/{id}/save/`). `true`: also saved on arrival when the contact's level allows it. |
| `WHATSAPP_MEDIA_TYPES` | `image,document,audio,video,sticker` | Media types downloaded on arrival when `WHATSAPP_DOWNLOAD_MEDIA` is on. |
| `WHATSAPP_MEDIA_MAX_BYTES` | `104857600` | Per-file size limit (100 MB). |
| `WHATSAPP_MEDIA_MAX_ATTEMPTS` | `5` | Attempt cap used by `retry_media_downloads`. |
| `USE_CELERY` | `false` | Run media downloads on Celery workers instead of inline. |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery broker. |
| `WHATSAPP_LOG_LEVEL` | `INFO` | Log level for the `whatsapp` app. |

## Running the server

```powershell
python manage.py runserver
```

| URL | What |
|---|---|
| `http://127.0.0.1:8000/webhooks/whatsapp/` | Webhook endpoint (give Meta the public HTTPS version of this) |
| `http://127.0.0.1:8000/api/v1/` | REST API (token required) |
| `http://127.0.0.1:8000/api/docs/` | Swagger UI. Public in DEBUG; staff-only otherwise. |
| `http://127.0.0.1:8000/admin/` | Django admin |
| `http://127.0.0.1:8000/health/` | Liveness check |

### Receiving real webhooks locally

Meta can only call a public HTTPS URL, so tunnel your local server:

```bash
cloudflared tunnel --url http://127.0.0.1:8000      # or: ngrok http 8000
```

1. Add the tunnel host to `DJANGO_ALLOWED_HOSTS` (for example `.trycloudflare.com`) and restart.
2. In Meta, open **WhatsApp → Configuration → Webhook**:
   - Callback URL: `https://<tunnel-host>/webhooks/whatsapp/`
   - Verify token: your `ushika123`
   - Click **Verify and save**, then subscribe to the **messages** field.
3. Send a WhatsApp message to the test number from your phone. It should appear at `/api/v1/messages/`.

### Optional: Celery workers

```bash
# USE_CELERY=true in .env, Redis running
celery -A config worker -l info
```

Celery only matters when `WHATSAPP_DOWNLOAD_MEDIA` is on. With Celery off (the default), downloads on arrival run inside the webhook request right after the database commit. Saves through the API always run inside that API request.

## Contact levels: which media gets saved

A contact's **level** decides whether their images and PDFs can be saved. Nothing is saved for a contact with no level.

1. In the admin, open **Whatsapp → Contact levels** and add levels, for example *Images* (can save images) and *Full* (can save images and PDFs).
2. Open **Whatsapp → Contacts** and pick a level for each contact in the **Level** column, then click **Save**. A contact appears after their first message.
3. Save a file with `POST /api/v1/attachments/{id}/save/`. If it isn't allowed, the API returns `403` with the reason. Audio, video, stickers and non-PDF documents can only be saved by a superuser.

The rules are in [docs/API.md](docs/API.md#saving-media-contact-levels).

## Previewing and downloading files

Log in to the admin as a superuser and open **Whatsapp → Media attachments**. Every row has a **Download** link, and a **Preview** link if a browser can show the file: PDFs, images, plain text, audio and video. Opening a row shows the preview on its page. A message's page has the same links for its attachments.

This works for any file, whatever the contact's level. A file that isn't saved is fetched from WhatsApp when you open it and isn't kept, so it needs a valid access token and only works while Meta holds the file (about 30 days). Save a file if it must stay available for longer. Word, Excel and PowerPoint files can be downloaded but not previewed, and so can HTML and SVG files, for security.

Other users can only preview and download saved files. See [docs/API.md](docs/API.md#previewing-and-downloading).

## Running tests

```powershell
python manage.py test whatsapp
```

The suite fakes every Meta call with `responses`, so it needs no credentials or network access. Postman tests and the real-number checklist are in [docs/TESTING.md](docs/TESTING.md).

## Maintenance commands

```powershell
python manage.py reprocess_webhooks            # replay webhook events that failed processing
python manage.py reprocess_webhooks 12 13      # replay specific events
python manage.py retry_media_downloads         # retry pending/failed downloads under the attempt cap
python manage.py retry_media_downloads 42      # save or force-retry one attachment (contact levels still apply)
```

## command to save

```curl.exe -X POST -H $h http://127.0.0.1:8000/api/v1/attachments/3/save/ ```

## Documentation

| Document | Contents |
|---|---|
| [BRAIN.md](BRAIN.md) | Orientation for AI coding agents: status, rules, decisions, where things are |
| [docs/PRD.md](docs/PRD.md) | Goals, user stories, scope, acceptance criteria |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, data flow, webhook lifecycle, storage, error handling |
| [docs/API.md](docs/API.md) | REST API contracts with request and response examples |
| [docs/TASKS.md](docs/TASKS.md) | The six phases, task status, blockers, next steps |
| [docs/TESTING.md](docs/TESTING.md) | Automated tests, Postman, webhook simulation, real Meta checks |
| [docs/SECURITY.md](docs/SECURITY.md) | Secrets, signatures, authorization, privacy, retention, deployment |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Engineering decisions and when to revisit them |

## Project boundaries

USHIKA uses only Meta's supported Cloud API operations and webhook events. It cannot read historical chats, and it does not automate a personal WhatsApp account. Local file storage is for the POC; production needs persistent storage, access controls, backups and proper secret management (see [docs/DECISIONS.md](docs/DECISIONS.md)).
