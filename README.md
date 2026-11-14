# Vitodens Smart — companion app for ViCare

A mobile-friendly local web app for the Viessmann Vitodens 100-W, using the official Viessmann Cloud API. ViCare continues to work independently.

## Run

1. Install Python 3.10+ and run `pip install -r requirements.txt`.
2. Sign in at https://developer.viessmann-climatesolutions.com/ with your existing ViCare account.
3. Create an OAuth API client with redirect URI **`http://localhost:5000/callback`**. Copy the **Client ID** (not the password or secret). Some portal setups may require an HTTPS callback; if so, use an HTTPS reverse proxy and set REDIRECT_URI to its public callback URL.
4. Set environment variables:
   - macOS/Linux: `export VIESSMANN_CLIENT_ID='YOUR_CLIENT_ID'` and `export FLASK_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"`
   - Windows PowerShell: `$env:VIESSMANN_CLIENT_ID='YOUR_CLIENT_ID'`; `$env:FLASK_SECRET_KEY='your-long-random-secret'`
5. Run `python app.py`, open http://localhost:5000 and tap **Connect**.

To open it on your iPhone, deploy behind HTTPS with secure session cookies and a persistent server-side token store; `localhost` on the iPhone refers to the phone itself. This starter version is intended for local development on your computer, not internet-exposed production use.

## Notes

- OAuth authorization code + PKCE. Tokens are kept in the Python process memory, not in browser localStorage.
- Uses the current `/iot/v2/features` endpoint, not retired v1 feature endpoints.
- Discovers installation, gateway, and device IDs after login.
- Commands are shown only when the device reports `isExecutable: true`, and server checks again before executing.
- Only supports command parameters reported by the device; actual device availability depends on API subscription and firmware.
- Refreshes every 90 seconds to reduce API-limit risk; commands and device discovery add requests.
- For a production app, add HTTPS, persistent encrypted token storage, CSRF protection for POST endpoints, access controls, a durable session store, proper multi-device selection, and audited command whitelists.
- A Wi-Fi module label can include network credentials. Never publish that label or its QR code publicly.

References: https://developer.viessmann-climatesolutions.com/start.html and https://developer.viessmann-climatesolutions.com/start/news/important-updates-to-viessmann-api-effective-30-04-2025.html

## Smart programs (experimental)

The Smart programs section supports day/night DHW target changes, a timed DHW setpoint boost, and heating circuit 1 normal-program target changes at selected times. These controls are enabled only when the Viessmann API reports the matching command executable. All schedules default to every day and use `Europe/Bucharest`; set `APP_TIMEZONE` to another IANA timezone if necessary.

**Limitations:** This is an experimental local scheduler, not a boiler-native time program. The Flask process must remain running, with one scheduler worker, network access and a valid OAuth session. OAuth tokens are held in memory and are lost after a restart, so automatic actions cannot work until re-login. A failed restore is retained for retry, but a power outage or lost credentials can leave the boosted setpoint active. Verify changes in ViCare. Never expose the development server directly to the internet. The app does not yet reconcile edits made concurrently in ViCare. The heating schedule sets the *normal room-target program temperature*, not flow temperature, and may not affect an inactive operating mode. A proper production version needs persistent encrypted token storage, CSRF protection, retry/backoff, startup recovery, scheduler leadership, capability-aware UI and dedicated device testing.

Boost is not Viessmann's one-time DHW cylinder charge: it temporarily changes the target temperature and restores it later. Use a safe DHW temperature appropriate for your plumbing and follow the boiler manufacturer's hygiene recommendations.
