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
