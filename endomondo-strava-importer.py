import os
import requests
import time
import shutil
from datetime import datetime

TOKEN_URL = "https://www.strava.com/oauth/token"
UPLOADS_URL = "https://www.strava.com/api/v3/uploads"

# Strava processes uploads asynchronously, so the result has to be polled.
# Increasing delays between polls, roughly 51 seconds per file at most.
POLL_DELAYS = (2, 3, 5, 8, 13, 20)

def log(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

def exchange_code_for_token(c_id, c_secret, auth_code):
    """Helper for obtaining the very first refresh token."""
    log("Exchanging authorization code for a refresh token...")
    payload = {
        'client_id': c_id,
        'client_secret': c_secret,
        'code': auth_code,
        'grant_type': 'authorization_code'
    }
    res = requests.post(TOKEN_URL, data=payload, timeout=30)
    if res.status_code == 200:
        data = res.json()
        print("\n" + "="*50)
        print(f"YOUR REFRESH TOKEN: {data['refresh_token']}")
        print("="*50)
        print("Save this token! You will need it to start the migration.\n")
        return data['refresh_token']
    else:
        log(f"❌ Exchange failed: {res.text}")
        return None

class StravaLimiter:
    """Tracks rate limit usage based on the headers Strava returns."""

    SHORT_WINDOW = 15 * 60
    SAFETY_RATIO = 0.9

    def __init__(self):
        self.short_usage = 0
        self.daily_usage = 0
        self.short_limit = 100
        self.daily_limit = 1000

    def update(self, headers):
        limits = headers.get('X-RateLimit-Limit')
        if limits:
            try:
                self.short_limit, self.daily_limit = map(int, limits.split(',')[:2])
            except ValueError:
                pass
        usage = headers.get('X-RateLimit-Usage')
        if usage:
            try:
                self.short_usage, self.daily_usage = map(int, usage.split(',')[:2])
            except ValueError:
                pass

    def wait_if_needed(self):
        """Sleeps when the 15-minute limit is near. False means the day is used up."""
        if self.daily_usage >= self.daily_limit * self.SAFETY_RATIO:
            return False
        if self.short_usage >= self.short_limit * self.SAFETY_RATIO:
            # Windows are aligned to quarter hours, so sleeping out the rest is enough.
            pause = self.SHORT_WINDOW - (time.time() % self.SHORT_WINDOW) + 5
            log(f"⚠️ 15-min limit reached ({self.short_usage}/{self.short_limit}). "
                f"Sleeping for {pause / 60:.1f} min...")
            time.sleep(pause)
            self.short_usage = 0
        return True

class StravaAuth:
    """Holds the access token and renews it for as long as the refresh token is valid."""

    REFRESH_MARGIN = 300

    def __init__(self, c_id, c_secret, r_token):
        self.client_id = c_id
        self.client_secret = c_secret
        self.refresh_token = r_token
        self._access_token = None
        self._expires_at = 0

    def access_token(self, force=False):
        if force or time.time() >= self._expires_at - self.REFRESH_MARGIN:
            self._refresh()
        return self._access_token

    def _refresh(self):
        res = requests.post(TOKEN_URL, data={
            'client_id': self.client_id, 'client_secret': self.client_secret,
            'refresh_token': self.refresh_token, 'grant_type': 'refresh_token'
        }, timeout=30)
        if res.status_code != 200:
            log(f"❌ Authorization failed: {res.text}")
            res.raise_for_status()
        data = res.json()
        self._access_token = data['access_token']
        self._expires_at = data.get('expires_at', time.time() + 6 * 3600)
        rotated = data.get('refresh_token')
        if rotated and rotated != self.refresh_token:
            self.refresh_token = rotated
            log(f"ℹ️ Strava issued a new refresh token, save it: {rotated}")
        valid_to = datetime.fromtimestamp(self._expires_at).strftime("%H:%M:%S")
        log(f"🔑 Access token renewed, valid until {valid_to}.")

def api_get(url, auth, limiter):
    """GET with a single retry after a 401, so an expired token cannot kill the run."""
    for attempt in (1, 2):
        token = auth.access_token(force=attempt == 2)
        res = requests.get(url, headers={'Authorization': f'Bearer {token}'},
                           timeout=60)
        limiter.update(res.headers)
        if res.status_code != 401 or attempt == 2:
            return res
        log("🔑 Strava rejected the token, renewing and retrying...")

def upload_tcx(path, auth, limiter):
    """Uploads a file. The file is reopened on each attempt so it can be resent."""
    for attempt in (1, 2):
        token = auth.access_token(force=attempt == 2)
        with open(path, 'rb') as f:
            res = requests.post(UPLOADS_URL,
                headers={'Authorization': f'Bearer {token}'},
                data={'data_type': 'tcx'}, files={'file': f}, timeout=300)
        limiter.update(res.headers)
        if res.status_code != 401 or attempt == 2:
            return res
        log("🔑 Strava rejected the token, renewing and retrying...")

def wait_for_import(upload_id, auth, limiter):
    """Waits for the import result.

    Returns (status, detail), where status is 'imported', 'duplicate', 'failed'
    or 'unknown'. HTTP 201 only means the file was queued, not imported.
    """
    for delay in POLL_DELAYS:
        time.sleep(delay)
        if not limiter.wait_if_needed():
            return 'unknown', "daily limit used up while checking the status"

        res = api_get(f"{UPLOADS_URL}/{upload_id}", auth, limiter)
        if res.status_code != 200:
            return 'unknown', f"HTTP {res.status_code}: {res.text.strip()}"

        data = res.json()
        error = data.get('error')
        if error:
            kind = 'duplicate' if 'duplicate' in error.lower() else 'failed'
            return kind, error
        if data.get('activity_id'):
            return 'imported', f"activity {data['activity_id']}"

    return 'unknown', "Strava did not finish the import in time"

def move_pair(tcx_path, target_dir):
    """Moves the .tcx file and its paired .json into the target directory."""
    os.makedirs(target_dir, exist_ok=True)
    shutil.move(tcx_path, os.path.join(target_dir, os.path.basename(tcx_path)))
    json_path = tcx_path.rsplit('.', 1)[0] + ".json"
    if os.path.exists(json_path):
        shutil.move(json_path, os.path.join(target_dir, os.path.basename(json_path)))

def migrate(auth, dir_path):
    limiter = StravaLimiter()
    files = sorted(f for f in os.listdir(dir_path) if f.lower().endswith('.tcx'))
    log(f"Found {len(files)} files.")

    counts = {'imported': 0, 'duplicate': 0, 'failed': 0, 'unknown': 0}

    for filename in files:
        if not limiter.wait_if_needed():
            log(f"🛑 Daily limit reached ({limiter.daily_usage}/{limiter.daily_limit}). "
                f"Continue tomorrow, unprocessed files are left in place.")
            break

        tcx_path = os.path.join(dir_path, filename)
        log(f"Uploading: {filename}")
        res = upload_tcx(tcx_path, auth, limiter)

        if res.status_code != 201:
            counts['failed'] += 1
            log(f"❌ Upload rejected: {res.text.strip()}")
            continue

        upload_id = res.json().get('id')
        status, detail = wait_for_import(upload_id, auth, limiter)
        counts[status] += 1

        if status == 'imported':
            move_pair(tcx_path, os.path.join(dir_path, "processed"))
            log(f"✅ Imported – {detail} ({limiter.short_usage}/{limiter.short_limit})")
        elif status == 'duplicate':
            # The activity is already on Strava, re-uploading it would be pointless.
            move_pair(tcx_path, os.path.join(dir_path, "duplicates"))
            log(f"⏭️ Duplicate, moving to duplicates/ – {detail}")
        else:
            log(f"❌ Not imported ({status}), leaving the file in place – {detail}")

        time.sleep(1.5)

    print("\n" + "="*50)
    log(f"Imported: {counts['imported']}")
    log(f"Duplicates: {counts['duplicate']}")
    log(f"Errors: {counts['failed'] + counts['unknown']} (files left in place)")
    print("="*50)

def main():
    log("=== Endomondo PRO Migrator ===")

    print("\nChoose an action:")
    print("1. Run the migration (I have a refresh token)")
    print("2. Get a refresh token (I only have the 'code' from the browser)")
    choice = input("Choice (1/2): ").strip()

    c_id = input("Client ID: ").strip()
    c_secret = input("Client Secret: ").strip()

    if choice == "2":
        auth_code = input("Paste the 'code' from the URL (after code=): ").strip()
        exchange_code_for_token(c_id, c_secret, auth_code)
        input("Press Enter to exit...")
        return

    r_token = input("Refresh Token: ").strip()
    dir_path = input("Path to the export: ").strip()

    try:
        migrate(StravaAuth(c_id, c_secret, r_token), dir_path)
    except Exception as e:
        log(f"Critical error: {e}")

    input("\nDone. Press Enter to exit...")

if __name__ == "__main__":
    main()
