# WASKO VIRTUAL ACADEMY — upgraded

Production-oriented Flask academy application with student registration, secure
status verification, protected course-material downloads, admin approval, and
course-material management.

## What was upgraded

- PostgreSQL support through SQLAlchemy; SQLite remains available for local development.
- Secure CSRF protection on all POST forms.
- Secure, HTTP-only, SameSite session cookies.
- Production secret enforcement.
- Password-hash based admin authentication.
- Protected student material downloads — a filename alone is no longer enough.
- Protected admin passport viewing.
- Safe generated filenames for uploaded files.
- Upload size/type validation.
- Duplicate-safe enrolment code generation.
- `/health` endpoint for production health checks.
- Security response headers.
- Better database indexing and transaction handling.
- Production Gunicorn configuration.
- Render Blueprint with Postgres + persistent storage.

## Local setup

Windows Git Bash:

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="change-this-password"
python app.py
```

Open `http://127.0.0.1:5000`.

If you prefer PowerShell, use:

```powershell
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_urlsafe(48))"
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "change-this-password"
python app.py
```

## Production deployment

The included `render.yaml` provisions:

- WASKO Virtual Academy web service
- PostgreSQL database
- 1 GB persistent disk for uploaded passports/materials
- HTTPS through Render
- `/health` health check

Render's filesystem is ephemeral by default, so the persistent disk is used for
the uploaded files. The PostgreSQL database stores application records.

Do **not** commit passwords or secret keys. Set `ADMIN_USERNAME` and a strong
`ADMIN_PASSWORD_HASH` in Render. You can create a hash locally with:

```bash
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('YOUR-STRONG-PASSWORD'))"
```

Paste the resulting value into Render as `ADMIN_PASSWORD_HASH`.

### Important

The Blueprint uses paid Render resources for a production-oriented setup.
Render's free web services cannot use persistent disks, and free Postgres
databases expire after 30 days. If you only want a temporary demo, the service
and database can be changed to free plans, but that is not appropriate for
long-term academy data.

## Existing SQLite data

The upgraded app uses new SQLAlchemy tables. If your old local `instance/wasko.db`
contains registrations you need to preserve, back it up before first running the
upgrade. The original SQLite schema is not automatically migrated because a
production PostgreSQL migration should be performed deliberately.

## Routes

- `/` — public academy
- `/register` — student registration
- `/status` — registration verification
- `/admin/login` — staff login
- `/admin` — registration dashboard
- `/admin/materials` — course materials
- `/health` — deployment health check
