# endomondo-strava-importer

Konzolový nástroj na dávkovú migráciu tréningov z Endomondo exportu do Stravy.
Prechádza adresár s `.tcx` súbormi, nahráva ich cez Strava API v3 a rešpektuje
pritom rate limity Stravy.

## Ako to funguje

- Načíta všetky `.tcx` súbory v zadanom adresári a postupne ich nahráva na
  endpoint `POST /api/v3/uploads`.
- **Overí výsledok importu.** HTTP 201 znamená len zaradenie do frontu, preto
  sa skript následne doptáva na `GET /api/v3/uploads/{id}`, kým Strava nevráti
  `activity_id` (úspech) alebo `error`.
- **Presúva len skutočne naimportované súbory** do `processed/` (aj s párovým
  `.json`). Duplikáty idú do `duplicates/`, pretože v Strave už sú a opakovaný
  upload by nemal zmysel. Súbory, ktoré zlyhali, zostávajú na mieste, takže sa
  pri ďalšom behu skúsia znova — beh je teda **obnoviteľný**.
- **Sám si obnovuje access token.** Ten platí 6 hodín; skript ho obnoví pred
  expiráciou aj po odmietnutí requestu s HTTP 401, takže dlhý beh neprepadne.
  Ak Strava vydá nový refresh token, skript ho vypíše.
- Rate limity číta z hlavičiek `X-RateLimit-Limit` a `X-RateLimit-Usage`, čiže
  sa prispôsobí limitom tvojej aplikácie. Pri 90 % 15-minútového okna dospí
  zvyšok okna, pri 90 % denného limitu korektne skončí.
- Na konci vypíše súhrn: koľko aktivít sa naimportovalo, koľko bolo duplikátov
  a koľko zlyhalo.

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

Samostatný `.exe` pre Windows sa vytvára PyInstallerom. Najjednoduchšie cez
priložený skript, ktorý doinštaluje závislosti aj PyInstaller a spustí build:

```powershell
.\build.ps1
```

Ekvivalent naruby:

```bash
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean endomondo-strava-importer.spec
```

Výsledok je `dist/endomondo-strava-importer.exe` (~12 MB, Python na cieľovom
stroji netreba). Konfigurácia buildu je v `endomondo-strava-importer.spec`.
Adresáre `build/` a `dist/` sú zámerne v `.gitignore` — binárky patria do
GitHub Releases, nie do repozitára.

## Známe obmedzenia

- Spracúvajú sa len `.tcx` súbory a len v zadanom adresári, nie v podadresároch.
- Pri prechodných chybách (429, 5xx) sa upload neopakuje — súbor však zostane
  na mieste, takže ho zachytí ďalší beh.
- Ak Strava import nedokončí do ~50 sekúnd, výsledok sa vyhodnotí ako neznámy
  a súbor zostane na mieste. Pri ďalšom behu sa nahrá znova a skončí ako
  duplikát.
- Client Secret sa zadáva cez bežný `input()`, čiže je vidieť v konzole.

## Licencia

[MIT](LICENSE)
