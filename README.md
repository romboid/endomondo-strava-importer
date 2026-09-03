# endomondo-strava-importer

A console tool for bulk-migrating workouts from an Endomondo export to Strava.
It walks a directory of `.tcx` files, uploads them through the Strava API v3
and stays within Strava's rate limits.

## How it works

- Reads every `.tcx` file in the given directory and uploads them one by one to
  `POST /api/v3/uploads`.
- **Verifies the import result.** HTTP 201 only means the file was queued, so
  the script then polls `GET /api/v3/uploads/{id}` until Strava returns an
  `activity_id` (success) or an `error`.
- **Moves only genuinely imported files** to `processed/` (together with the
  paired `.json`). Duplicates go to `duplicates/`, since they are already on
  Strava and re-uploading them would be pointless. Failed files stay in place
  and are retried on the next run, which makes the migration **resumable**.
- **Renews the access token on its own.** The token is valid for 6 hours; the
  script refreshes it before it expires and also after a request is rejected
  with HTTP 401, so a long run does not fall over. If Strava issues a new
  refresh token, the script prints it.
- Reads rate limits from the `X-RateLimit-Limit` and `X-RateLimit-Usage`
  headers, so it adapts to your application's limits. At 90% of the 15-minute
  window it sleeps out the rest of the window; at 90% of the daily limit it
  stops cleanly.
- Prints a summary at the end: how many activities were imported, how many were
  duplicates and how many failed.

## Requirements

- Python 3.8+
- `pip install -r requirements.txt`

Alternatively use the standalone `.exe` (see [Build](#build)), which does not
need Python on the target machine.

## Strava API setup

1. Create an application at
   [strava.com/settings/api](https://www.strava.com/settings/api). Set
   *Authorization Callback Domain* to `localhost`.
2. Note down your **Client ID** and **Client Secret**.
3. Open the authorization URL in a browser (replace `CLIENT_ID`):

   ```
   https://www.strava.com/oauth/authorize?client_id=CLIENT_ID&redirect_uri=http://localhost&response_type=code&approval_prompt=force&scope=activity:write
   ```

   The `activity:write` scope is mandatory — uploads fail without it.
4. After you approve, Strava redirects you to a non-existent `localhost`
   address. Copy the value of the `code=` parameter from the address bar.
5. Run the script, pick option **2** and paste the `code`. The script exchanges
   it for a **refresh token** — save it, as it does not expire and you will use
   it on every subsequent run.

## Usage

```bash
python endomondo-strava-importer.py
```

Pick option **1** and enter your Client ID, Client Secret, refresh token and
the path to the directory holding the Endomondo export.

## Build

The standalone Windows `.exe` is produced by PyInstaller. The easiest way is
the bundled script, which installs the dependencies and PyInstaller and then
runs the build:

```powershell
.\build.ps1
```

The equivalent by hand:

```bash
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean endomondo-strava-importer.spec
```

The result is `dist/endomondo-strava-importer.exe` (~12 MB, no Python needed on
the target machine). The build configuration lives in
`endomondo-strava-importer.spec`. The `build/` and `dist/` directories are
deliberately in `.gitignore` — binaries belong in GitHub Releases, not in the
repository.

## Known limitations

- Only `.tcx` files are processed, and only in the given directory, not in
  subdirectories.
- Transient failures (429, 5xx) are not retried — the file stays in place
  though, so the next run picks it up.
- If Strava does not finish the import within roughly 50 seconds, the result is
  treated as unknown and the file stays in place. The next run uploads it again
  and it ends up as a duplicate.
- The Client Secret is read with a plain `input()`, so it is visible in the
  console.

## License

[MIT](LICENSE)
