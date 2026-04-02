# Vacation Scheduler

Vacation Scheduler is a lightweight Flask + SQLite web app for managing physician vacation requests with:

- Month-first calendar UI with today's date highlighted
- Six vacation slots per day
- Physician login and personal request history
- Admin area for confirming or marking requests unavailable
- Automatic waitlist promotion when a request moves into the top six
- Imported physician roster from the provided Excel workbooks

## Local run

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

Open `http://127.0.0.1:5000`.

The app reads configuration from environment variables. For local development, copy `.env.example` to `.env` and adjust values as needed.

## Seeded accounts

- Admin username: `admin`
- Admin password: `Admin123!`
- Seeded physician password: `ChangeMe123!`

Each imported physician also gets a generated username and placeholder email like `username@example.com`. Use the admin area to update emails, add users, disable users, or create new admin accounts.

## Imported data

The app seeded 58 physician names from:

- `Holiday Rotation Schedule.xlsx`
- `VL Calendar 2024.xlsx`
- `VL Calendar 2025.xlsx`
- `VL Calendar 2026.xlsx`

Those source files are also copied into `app/uploads/` and exposed in the Holiday Rotation page for download.

## Security recommendations

- Change the default admin and physician passwords immediately.
- Set a unique `SECRET_KEY` in your host's environment-variable settings before production.
- Keep password hashing enabled with PBKDF2 and use HTTPS in production.
- Add SMTP credentials so automatic approval emails are actually sent rather than logged.
- For a production launch, consider adding password reset flows, audit logging, CSRF protection, and stricter session cookie settings.

## GitHub + deployment checklist

1. Create a new GitHub repository.
2. Push this project folder to that repository.
3. Connect the GitHub repo to Render.
4. Let Render detect `render.yaml` and deploy the app.
5. Set any needed environment variables in Render, especially SMTP settings if you want email.

Example git commands:

```bash
git init
git add .
git commit -m "Initial prototype"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPO.git
git push -u origin main
```

## Sharing with a friend

- Easiest browser-only option: deploy the project and send them the URL.
- Easiest code-sharing option: push to GitHub and invite them to the repository.
- If you send the folder directly, zip the project and include the setup steps above.

## Low-cost hosting suggestions

- Cheapest/easiest: [Render](https://render.com/) web service + persistent disk for the Flask app, still inexpensive and simple to manage.
- Mostly free data layer: [Supabase](https://supabase.com/) for Postgres/auth if you later want to move beyond SQLite and add more durable hosted storage.
- Lowest operational cost for a small private group: a small [Fly.io](https://fly.io/) or [Railway](https://railway.com/) deployment running this app with a mounted volume.

If you want the most production-ready path, the next upgrade I’d recommend is moving from SQLite to Postgres and storing secrets in the hosting platform’s environment-variable manager.
