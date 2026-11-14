# Build Windows EXE with GitHub Actions

1. Create a **private** GitHub repository and upload the contents of this `vitodens-smart` folder to the repository root (including `.github/workflows/windows-exe.yml`). Do not upload your TCU label or credentials.
2. Go to **Actions** > **Build Windows EXE** > **Run workflow**. Push to `main` also triggers the build.
3. Wait for the green check. Open the workflow run and download the `VitodensSmart-Windows` artifact. Unzip it to obtain `VitodensSmart.exe`.
4. On Windows, set `VIESSMANN_CLIENT_ID` in your environment to the public OAuth client ID from the Viessmann developer portal. Register `http://localhost:5000/callback` as your redirect URI if the portal permits it. Optionally set `FLASK_SECRET_KEY` to a long random string. Start the EXE; it will open `http://127.0.0.1:5000` in your browser. Keep the console window open for scheduling.

Example PowerShell for a single session:

```powershell
$env:VIESSMANN_CLIENT_ID='YOUR_CLIENT_ID'
$env:FLASK_SECRET_KEY='REPLACE_WITH_LONG_RANDOM_STRING'
.\VitodensSmart.exe
```

This packages the local web server, not a native desktop UI. The server must remain running for scheduled changes and boosts. Log in again after restarting; boost restoration can fail if the process stops. Do not expose port 5000 publicly. Validate API capabilities and safe temperatures with your actual boiler before relying on schedules. GitHub Actions builds are not a deployment or automatic update service.

## First-time Viessmann API connection

1. Confirm the boiler is online in ViCare and that you can log in with the account that owns it.
2. Open https://developer.viessmann-climatesolutions.com/ and sign in; follow the portal's current instructions to register an API/OAuth client.
3. For the local app, register redirect/callback URI exactly `http://localhost:5000/callback` if the portal accepts it. If it does not, stop and check the portal's supported redirect URI requirements; do not substitute a different URI without configuring the app too.
4. Copy the **Client ID** (not your password or a client secret). Do not post your credentials in GitHub.
5. Extract the Windows build artifact and put `VitodensSmart.exe` in its own folder. In that folder open PowerShell and run:

```powershell
$env:VIESSMANN_CLIENT_ID = 'PASTE_CLIENT_ID_HERE'
$env:FLASK_SECRET_KEY = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
.\VitodensSmart.exe
```

6. When your browser opens `http://127.0.0.1:5000`, choose **Connect**. You will be redirected to the official Viessmann sign-in page and then back to the app.
7. Check whether your boiler exposes supported DHW and heating controls. Not every API client or device exposes every function; access limits or subscription requirements may apply.

**Important:** This local prototype does not persist OAuth tokens across restarts; sign in again after restarting. The EXE must remain running for timed programs and boost restoration. Test the scheduler with safe settings while supervising it before relying on unattended temperature changes.
