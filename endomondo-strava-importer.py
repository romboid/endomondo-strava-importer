import os
import requests
import time
import shutil
from datetime import datetime

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
    res = requests.post("https://www.strava.com/oauth/token", data=payload)
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
    def __init__(self):
        self.short_usage = 0
        self.long_usage = 0

    def update_usage(self, headers):
        usage = headers.get('X-RateLimit-Usage')
        if usage:
            try:
                self.short_usage, self.long_usage = map(int, usage.split(','))
            except: pass

    def check_and_wait(self):
        if self.short_usage >= 90:
            log("⚠️ Limit 90% (15 min). Spím na 15 minút...")
            time.sleep(15 * 60)
            self.short_usage = 0
        if self.long_usage >= 950:
            log("🛑 Limit 95% (deň). Končím.")
            return False
        return True

def get_access_token(c_id, c_secret, r_token):
    res = requests.post("https://www.strava.com/oauth/token", data={
        'client_id': c_id, 'client_secret': c_secret,
        'refresh_token': r_token, 'grant_type': 'refresh_token'
    })
    if res.status_code != 200:
        log(f"❌ Chyba autorizácie: {res.text}")
        res.raise_for_status()
    return res.json()['access_token']

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
    
    processed_path = os.path.join(dir_path, "processed")
    if not os.path.exists(processed_path): os.makedirs(processed_path)

    try:
        acc_token = get_access_token(c_id, c_secret, r_token)
        limiter = StravaLimiter()
        files = [f for f in os.listdir(dir_path) if f.lower().endswith('.tcx')]
        
        log(f"Nájdených {len(files)} súborov.")

        for filename in files:
            if not limiter.check_and_wait(): break
            
            tc_path = os.path.join(dir_path, filename)
            js_path = tc_path.rsplit('.', 1)[0] + ".json"

            log(f"Nahrávam: {filename}")
            with open(tc_path, 'rb') as f:
                res = requests.post("https://www.strava.com/api/v3/uploads",
                    headers={'Authorization': f'Bearer {acc_token}'},
                    data={'data_type': 'tcx'}, files={'file': f})

            limiter.update_usage(res.headers)

            if res.status_code == 201:
                log(f"✅ OK ({limiter.short_usage}/100)")
                shutil.move(tc_path, os.path.join(processed_path, filename))
                if os.path.exists(js_path): shutil.move(js_path, os.path.join(processed_path, os.path.basename(js_path)))
            else:
                log(f"❌ Chyba: {res.text}")

            time.sleep(1.5)

    except Exception as e:
        log(f"Kritická chyba: {e}")
    
    input("\nHotovo. Enter pre ukončenie...")

if __name__ == "__main__":
    main()