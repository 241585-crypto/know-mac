# Ambulance Locator (MVP)

## What this does
- `POST /create` → generates a unique, time-limited link for a specific patient/case.
- Send that link to the patient over WhatsApp.
- Patient opens link (`/loc/<token>`) → taps "Allow Location Access" → browser's native
  geolocation prompt appears → coordinates are sent to `/api/location-update`.
- `/dashboard` → live table of all cases, auto-refreshing every 4 seconds, with a
  clickable Google Maps link for each located patient.

## Local test
```bash
pip install -r requirements.txt
python app.py
```
Visit http://localhost:5000/dashboard

Create a test case:
```bash
curl -X POST http://localhost:5000/create \
  -H "Content-Type: application/json" \
  -d '{"patient_name": "Test Patient", "phone": "0300xxxxxxx"}'
```
This returns a `link` — open it on your phone (same network, or after deploying) to test
the permission prompt.

## Deploying on Railway
1. Push this folder to a GitHub repo.
2. In Railway: New Project → Deploy from GitHub repo → select this repo.
3. Railway auto-detects the `Procfile` and Python via `requirements.txt`. No extra config needed.
4. Once deployed, attach your custom domain in Railway's project settings (Settings → Domains).
5. Because your domain already has HTTPS, the Geolocation API will work — it requires a
   secure context.

## Important next steps (not included yet, by design)
- **Persistent storage**: this MVP stores cases in memory, so a Railway restart wipes data.
  Add Railway's Postgres plugin and swap the `CASES` dict for real DB reads/writes before
  going to production.
- **WhatsApp sending**: this only builds the link. To actually send it via WhatsApp
  automatically, you'll need the WhatsApp Business API (Meta directly, or a BSP like
  Twilio/Gupshup) — happy to help wire that in next.
- **Auth on `/create` and `/dashboard`**: right now anyone who finds the URL could create
  cases or view the dashboard. Add a simple API key or login before real deployment.
