# endomondo-strava-importer

Konzolový nástroj na dávkovú migráciu tréningov z Endomondo exportu do Stravy.
Prechádza adresár s `.tcx` súbormi, nahráva ich cez Strava API v3 a rešpektuje
pritom rate limity Stravy.

## Ako to funguje

- Načíta všetky `.tcx` súbory v zadanom adresári a postupne ich nahráva na
  endpoint `POST /api/v3/uploads`.
- Po každom úspešnom nahraní presunie súbor (aj jeho párový `.json`, ak
  existuje) do podadresára `processed/`. Vďaka tomu je beh **obnoviteľný** —
  po prerušení stačí skript spustiť znova a pokračuje tam, kde skončil.
- Sleduje hlavičku `X-RateLimit-Usage`. Pri 90 requestoch v 15-minútovom okne
  zaspí na 15 minút, pri 950 requestoch za deň korektne skončí (pokračuj na
  druhý deň).
- Medzi jednotlivými uploadmi drží pauzu 1,5 s.

## Požiadavky

- Python 3.8+
- `pip install -r requirements.txt`

Alternatívne sa dá použiť samostatné `.exe` (viď [Build](#build)), ktoré
Python na cieľovom stroji nepotrebuje.

## Nastavenie Strava API

1. Na [strava.com/settings/api](https://www.strava.com/settings/api) vytvor
   aplikáciu. Ako *Authorization Callback Domain* zadaj `localhost`.
2. Odpíš si **Client ID** a **Client Secret**.
3. V prehliadači otvor autorizačnú URL (nahraď `CLIENT_ID`):

   ```
   https://www.strava.com/oauth/authorize?client_id=CLIENT_ID&redirect_uri=http://localhost&response_type=code&approval_prompt=force&scope=activity:write
   ```

   Scope `activity:write` je povinný — bez neho nahrávanie zlyhá.
4. Po potvrdení ťa Strava presmeruje na neexistujúcu `localhost` adresu.
   Z URL v adresnom riadku skopíruj hodnotu parametra `code=`.
5. Spusti skript, zvoľ možnosť **2** a vlož `code`. Skript ho vymení za
   **Refresh Token**, ktorý si ulož — platí trvalo a použiješ ho pri každom
   ďalšom behu.

## Použitie

```bash
python endomondo-strava-importer.py
```

Zvoľ možnosť **1** a zadaj Client ID, Client Secret, Refresh Token a cestu
k adresáru s exportom z Endomonda.

## Build

Samostatný `.exe` pre Windows:

```bash
pip install pyinstaller
pyinstaller endomondo-strava-importer.spec
```

Výsledok je v `dist/`. Adresáre `build/` a `dist/` sú zámerne v `.gitignore` —
binárky patria do GitHub Releases, nie do repozitára.

## Známe obmedzenia

- **Access token expiruje po 6 hodinách.** Získava sa raz pri štarte, takže
  veľmi dlhý beh (s 15-minútovými pauzami na rate limit) môže naraziť na 401
  pri zvyšných súboroch. Riešenie: skript zastaviť a spustiť znova.
- **HTTP 201 neznamená hotový import.** Strava súbor iba zaradí do frontu;
  skutočný výsledok (vrátane `duplicate of activity X`) sa dá zistiť až
  dotazom na `/uploads/{id}`, ktorý skript nerobí. Súbor sa teda presunie do
  `processed/` aj vtedy, keď ho Strava následne zamietne.
- Spracúvajú sa len `.tcx` súbory a len v zadanom adresári, nie v podadresároch.
- Pri prechodných chybách (429, 5xx) sa upload neopakuje.

## Licencia

[MIT](LICENSE)
