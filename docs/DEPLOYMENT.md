# Deployment

The application ships as three containers: PostgreSQL, the FastAPI backend, and nginx serving the built React app and proxying `/api`.

## Requirements
- Docker with Compose v2.
- A host or reverse proxy that terminates HTTPS in front of the `web` container. Tokens travel in the `Authorization` header, so use HTTPS in production.

## First start
```bash
cp .env.example .env
```
Edit `.env`:
- `POSTGRES_PASSWORD`: a long random password.
- `STW_SECRET_KEY`: 32 or more random characters. Generate one with
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`. The backend refuses to start without it.
- `STW_CORS_ORIGINS`: the public address of the site, for example `https://stewarding.example.com`.
- Optional, for push alerts to phones and browsers: run `python -m scripts.vapid_keys` in `backend` once and set `STW_VAPID_PUBLIC_KEY` and
  `STW_VAPID_PRIVATE_KEY` from its output, and `STW_VAPID_SUBJECT` to a `mailto:` address you own. The site must be on HTTPS. Keep the same
  pair for good: a new pair drops every device's subscription and people must turn alerts on again. On Render, enter them when applying the blueprint
  or under the API service's Environment. Without them alerts stay in the app only. People turn alerts on from Notifications; an iPhone needs the
  site added to the Home Screen first.

```bash
docker compose up -d --build
```
The backend applies database migrations on every start.

## Create the first manager
Do not run the demo seed in production. It creates sample users and sample data.

```bash
docker compose run --rm -e STW_BOOTSTRAP_PASSWORD='choose-a-long-password' backend \
  python -m app.bootstrap --email you@company.com --name "Your Name" --code E001
```
Or leave out `STW_BOOTSTRAP_PASSWORD` and use `docker compose run --rm backend ...` interactively to be prompted. This also creates the default dropdown lists (job titles, checklist categories, breakage reasons, standard corrective actions).

## First-time setup (Settings, in this order)
Sign in as the manager and open **Settings**. Each tab manages one kind of data:

1. **Organization** - your organization's name, address, contact details, registration number, report footer note and logo. They head the app and every PDF, Excel and CSV report.
2. **Locations** - kitchens, bars, banquet areas; time zone and an optional area (geofence) that check-in and check-out are limited to.
3. **Shifts** - hours, late-after minutes, break and overtime rules.
4. **Categories & units** - item categories, units of measure.
5. **Suppliers** - the companies you receive stock from.
6. **Item master** - every item once (names are checked for duplicates and the item ID is generated automatically), linked to a category, unit and supplier.
7. **Monitoring setup** - for each chiller, freezer, machine or log you keep: its checks, what each measures, how often it is due, and the limits. Start from a template where one fits. Limits are not pre-filled in production; set them from the manufacturer's instructions and your food-safety procedure.
8. **Rules & alerts** - reminder, escalation, retest and approval thresholds.
9. **Dropdown lists** - job titles, checklist categories, breakage reasons and standard corrective actions.

Employees get their login when you add them (Employees, Add): give each person the temporary password in person; they choose their own at first sign-in. Use **Reset password** on the Employees page if someone forgets theirs.

Then add employees and checklist templates (Checklists, Configure) and receive opening stock under **Stock Movements, Receiving**.

## Deploy on Render
`render.yaml` at the repository root describes the whole stack: a PostgreSQL database, a private API service with a 1 GB disk for uploads, and a public web service that serves the app and forwards `/api` to the API. It uses `backend/Dockerfile.render` and `frontend/Dockerfile.render`; the regular Dockerfiles are for Docker Compose.

1. Push the repository to GitHub or GitLab.
2. In Render choose **New > Blueprint**, pick the repository and apply. Render generates `STW_SECRET_KEY` and wires the database address and the API address itself; no secret goes in the file.
3. When the three resources are live, open the `plato-api` service, its **Shell** tab, and create the first manager:
   ```bash
   STW_BOOTSTRAP_PASSWORD='choose-a-long-password' python -m app.bootstrap --email you@company.com --name "Your Name" --code E001
   ```
4. Open the `plato` service address and sign in. Continue with first-time setup below.

Notes:
- The region (Frankfurt) and the database name cannot be changed after creation; edit `render.yaml` before the first apply if you want another region. Plans are set to the smallest paid sizes; raise them in the dashboard when load grows.
- A disk limits the API to one instance and makes each deploy restart it, so the site is unavailable for a few seconds. One instance is also what the in-process scheduler needs.
- The API is not reachable from the internet; only the web service can call it, so the browser always talks to one address.
- The database address Render provides starts with `postgresql://`; the app rewrites it to the psycopg driver itself.
- Back up the database and the `/data` disk; they hold everything.

## Demo data (non-production only)
```bash
docker compose exec -e STW_SEED_PASSWORD='demo-password-1' backend python -m app.seed
```
Seeded users are `manager`, `sup.mk`, `sup.rb`, `steward.mk`, `steward.bq` and `steward.rb` at `@example.test`. The seeded temperature limits are placeholders.

## Operations
- **Backups:** back up the `dbdata` volume (for example `pg_dump`) and the `uploads` volume (evidence photos).
- **Upgrades:** `git pull && docker compose up -d --build`. Migrations run automatically.
- **Scheduler:** it runs inside the backend process. Keep one backend replica and one worker. If you scale out, database constraints still prevent duplicate tasks and notifications, but alert jobs would run more than once.
- **Login lockout:** the failed-attempt counter is held in memory, so it is per process and resets on restart.
- **Time zones:** each location has an IANA time zone (Settings). All timestamps are stored in UTC and shown in the location's zone.
- **Logs:** `docker compose logs -f backend`.

## Development without Docker
See the README. Tests run on SQLite by default. To run them against PostgreSQL set
`STW_TEST_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/dbname` before `pytest`; the tests drop and recreate every table in that database, so point it at a disposable one.

## Verification performed
The compose stack was built and run end to end: migration, API through nginx, SPA fallback, security headers on every route type, seeding and sign-in. The full test suite passes on both SQLite and PostgreSQL 16, and `alembic check` reports no drift on PostgreSQL.

## Training files

Training videos, audio and documents are stored on the same disk as other uploads (`STW_UPLOAD_DIR`, in a `training` folder), not in the database, so back that disk up as well as the database. They stream to the browser with range requests, so a video starts quickly and can be skipped through.

- **Size.** The largest file is `STW_TRAINING_MAX_MB` (500 by default). The web server's upload limit for the training upload address is 520 MB in `frontend/nginx.conf` and `frontend/nginx.render.conf`; keep it above `STW_TRAINING_MAX_MB` if you raise it.
- **Disk.** `render.yaml` asks for a 10 GB disk for the API. A Render disk can be made bigger but never smaller, and a full disk makes uploads fail with a clear message. Check the usage from time to time.
- **Time.** An upload of a large video over a slow connection can take many minutes; the web server allows 15 minutes per file.
- **Video format.** Browsers play MP4 (H.264 with AAC audio), WebM and MOV from most phones. Convert unusual formats before uploading.

## Videos made from slides

A video lesson can be made from slides as well as uploaded: a manager writes slides (title, points, optional picture) and chooses a voice-over for each, and the server makes an ordinary MP4. It needs no software beyond the Python packages in `requirements.txt` (the video encoder comes with the `av` package) and nothing is sent to an outside service.

- **Recorded voice-over** works straight away: upload an MP3, M4A, WAV or OGG per slide, and the slide stays up as long as the recording lasts.
- **Typed voice-over** (a computer voice reads the text) needs one voice installed, once, because the voice files are not bundled:
  1. Choose a voice from the Piper voices collection and read its model card: voices have different licences, so pick one that allows your use.
  2. Put the `.onnx` file and its `.onnx.json` file side by side on the persistent disk, for example in `/data/voices/`.
  3. Set `STW_TTS_VOICE` to the full path of the `.onnx` file, for example `/data/voices/en_US-amy-medium.onnx`, and restart. The slide editor then enables "Type what is said".
  Loading a voice uses about 100 MB of memory. On a very small server, a bigger plan may be needed.
- **One at a time.** Videos are made in the background, one at a time, at about 1280 by 720. A ten-minute video takes a few minutes on a small server. A restart during a render marks the video as failed so it can simply be made again.
- **Text.** Slide text uses a built-in Latin font, so letters outside the Latin alphabet (for example Arabic) do not display correctly yet.
- **Licence.** The Piper package (`piper-tts`) is GPL-3.0. Running it inside your own organisation is fine; if you ever give the software to another company, take advice first.
