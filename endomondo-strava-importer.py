import os
import requests
import time
import shutil
from datetime import datetime

TOKEN_URL = "https://www.strava.com/oauth/token"
UPLOADS_URL = "https://www.strava.com/api/v3/uploads"

# Strava spracúva upload asynchrónne, takže na výsledok sa treba doptať.
# Postupne narastajúce pauzy medzi dotazmi, spolu max ~51 sekúnd na súbor.
POLL_DELAYS = (2, 3, 5, 8, 13, 20)

def log(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

def exchange_code_for_token(c_id, c_secret, auth_code):
    """Pomocná funkcia na získanie prvého Refresh Tokenu."""
    log("Vymieňam autorizačný kód za Refresh Token...")
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
        print(f"TVOJ REFRESH TOKEN: {data['refresh_token']}")
        print("="*50)
        print("Tento kód si ulož! Použiješ ho pri štarte migrácie.\n")
        return data['refresh_token']
    else:
        log(f"❌ Chyba pri výmene: {res.text}")
        return None

class StravaLimiter:
    """Sleduje spotrebu rate limitov podľa hlavičiek, ktoré vracia Strava."""

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
        """Uspí, ak sa blíži 15-minútový limit. False znamená vyčerpaný deň."""
        if self.daily_usage >= self.daily_limit * self.SAFETY_RATIO:
            return False
        if self.short_usage >= self.short_limit * self.SAFETY_RATIO:
            # Okná sú zarovnané na celé štvrťhodiny, takže stačí dospať zvyšok.
            pause = self.SHORT_WINDOW - (time.time() % self.SHORT_WINDOW) + 5
            log(f"⚠️ 15-min limit ({self.short_usage}/{self.short_limit}). "
                f"Spím {pause / 60:.1f} min...")
            time.sleep(pause)
            self.short_usage = 0
        return True

class StravaAuth:
    """Drží access token a obnovuje ho, kým je refresh token platný."""

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
            log(f"❌ Chyba autorizácie: {res.text}")
            res.raise_for_status()
        data = res.json()
        self._access_token = data['access_token']
        self._expires_at = data.get('expires_at', time.time() + 6 * 3600)
        rotated = data.get('refresh_token')
        if rotated and rotated != self.refresh_token:
            self.refresh_token = rotated
            log(f"ℹ️ Strava vydala nový Refresh Token, ulož si ho: {rotated}")
        valid_to = datetime.fromtimestamp(self._expires_at).strftime("%H:%M:%S")
        log(f"🔑 Access token obnovený, platí do {valid_to}.")

def api_get(url, auth, limiter):
    """GET s jedným opakovaním po 401, aby expirovaný token beh nezhodil."""
    for attempt in (1, 2):
        token = auth.access_token(force=attempt == 2)
        res = requests.get(url, headers={'Authorization': f'Bearer {token}'},
                           timeout=60)
        limiter.update(res.headers)
        if res.status_code != 401 or attempt == 2:
            return res
        log("🔑 Strava odmietla token, obnovujem a skúšam znova...")

def upload_tcx(path, auth, limiter):
    """Nahrá súbor. Súbor sa otvára v každom pokuse, aby sa dal poslať znova."""
    for attempt in (1, 2):
        token = auth.access_token(force=attempt == 2)
        with open(path, 'rb') as f:
            res = requests.post(UPLOADS_URL,
                headers={'Authorization': f'Bearer {token}'},
                data={'data_type': 'tcx'}, files={'file': f}, timeout=300)
        limiter.update(res.headers)
        if res.status_code != 401 or attempt == 2:
            return res
        log("🔑 Strava odmietla token, obnovujem a skúšam znova...")

def wait_for_import(upload_id, auth, limiter):
    """Čaká na výsledok importu.

    Vracia (stav, detail), kde stav je 'imported', 'duplicate', 'failed'
    alebo 'unknown'. HTTP 201 znamená len zaradenie do frontu, nie import.
    """
    for delay in POLL_DELAYS:
        time.sleep(delay)
        if not limiter.wait_if_needed():
            return 'unknown', "denný limit vyčerpaný počas kontroly stavu"

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

    return 'unknown', "Strava import nedokončila v časovom limite"

def move_pair(tcx_path, target_dir):
    """Presunie .tcx aj jeho párový .json do cieľového adresára."""
    os.makedirs(target_dir, exist_ok=True)
    shutil.move(tcx_path, os.path.join(target_dir, os.path.basename(tcx_path)))
    json_path = tcx_path.rsplit('.', 1)[0] + ".json"
    if os.path.exists(json_path):
        shutil.move(json_path, os.path.join(target_dir, os.path.basename(json_path)))

def migrate(auth, dir_path):
    limiter = StravaLimiter()
    files = sorted(f for f in os.listdir(dir_path) if f.lower().endswith('.tcx'))
    log(f"Nájdených {len(files)} súborov.")

    counts = {'imported': 0, 'duplicate': 0, 'failed': 0, 'unknown': 0}

    for filename in files:
        if not limiter.wait_if_needed():
            log(f"🛑 Denný limit ({limiter.daily_usage}/{limiter.daily_limit}). "
                f"Pokračuj zajtra, nespracované súbory zostávajú na mieste.")
            break

        tcx_path = os.path.join(dir_path, filename)
        log(f"Nahrávam: {filename}")
        res = upload_tcx(tcx_path, auth, limiter)

        if res.status_code != 201:
            counts['failed'] += 1
            log(f"❌ Upload zamietnutý: {res.text.strip()}")
            continue

        upload_id = res.json().get('id')
        status, detail = wait_for_import(upload_id, auth, limiter)
        counts[status] += 1

        if status == 'imported':
            move_pair(tcx_path, os.path.join(dir_path, "processed"))
            log(f"✅ Naimportované – {detail} ({limiter.short_usage}/{limiter.short_limit})")
        elif status == 'duplicate':
            # Aktivita v Strave už je, opakovaný upload by nemal zmysel.
            move_pair(tcx_path, os.path.join(dir_path, "duplicates"))
            log(f"⏭️ Duplikát, presúvam do duplicates/ – {detail}")
        else:
            log(f"❌ Neúspech ({status}), súbor nechávam na mieste – {detail}")

        time.sleep(1.5)

    print("\n" + "="*50)
    log(f"Naimportované: {counts['imported']}")
    log(f"Duplikáty: {counts['duplicate']}")
    log(f"Chyby: {counts['failed'] + counts['unknown']} (súbory zostali na mieste)")
    print("="*50)

def main():
    log("=== Endomondo PRO Migrator ===")

    print("\nVyber si akciu:")
    print("1. Spustiť migráciu (mám Refresh Token)")
    print("2. Získať Refresh Token (mám len 'code' z prehliadača)")
    choice = input("Voľba (1/2): ").strip()

    c_id = input("Client ID: ").strip()
    c_secret = input("Client Secret: ").strip()

    if choice == "2":
        auth_code = input("Vlož 'code' z URL (za code=): ").strip()
        exchange_code_for_token(c_id, c_secret, auth_code)
        input("Stlač Enter pre ukončenie...")
        return

    r_token = input("Refresh Token: ").strip()
    dir_path = input("Cesta k exportu: ").strip()

    try:
        migrate(StravaAuth(c_id, c_secret, r_token), dir_path)
    except Exception as e:
        log(f"Kritická chyba: {e}")

    input("\nHotovo. Enter pre ukončenie...")

if __name__ == "__main__":
    main()
