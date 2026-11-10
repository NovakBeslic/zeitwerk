# ⏱ Zeitwerk

Automatisches Zeit-Tracking für macOS, komplett lokal. Zeitwerk merkt sich im
Hintergrund, welche App, welches Fenster und welche Website du gerade nutzt, und
zeigt dir, wie viel davon produktiv war.

Gestaltet nach den [Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/):

- **Menüleiste:** ein SF Symbol als Vorlage-Bild, ein Menü statt Popover. Oben eine
  Tagesübersicht mit Balken, darunter die Kategorien mit der meisten Zeit,
  „Übersicht öffnen“ (⌘O), „Pausieren“ (15 Minuten, 1 Stunde, für heute, bis zum
  Fortsetzen), „Einstellungen …“ (⌘,).
- **Übersicht:** natives Fenster mit Seitenleiste und Vibrancy, Titel und Datum in
  der Titelleiste, Systemschrift und Systemfarben, passt sich Hell/Dunkel und deiner
  Akzentfarbe an. Diagramme haben Titel und Zusammenfassung, Säulen starten bei
  null, die Stundenansicht hat eine feste Skala von 0 bis 60 Minuten, und
  Farbe trägt nie allein eine Information.
- **Einstellungen:** eigenes Fenster mit Bereichen in der Werkzeugleiste
  (Allgemein, Erfassung, Kategorien). Es öffnet den zuletzt benutzten Bereich und
  passt seine Größe an. Änderungen gelten sofort.
- **Du entscheidest**, ob das Symbol in der Menüleiste erscheint. Ausgeblendet
  öffnet ein Start über Spotlight die Übersicht.
- **Willkommensfenster** beim ersten Start mit den wichtigsten Entscheidungen.

## Installation

1. `Zeitwerk-Installer-<version>.zip` herunterladen und doppelklicken. Es entsteht
   **Zeitwerk installieren**.
2. **Zeitwerk installieren** öffnen und „Installieren“ wählen.

Der Installer legt Zeitwerk in deinen Programme-Ordner und lädt beim ersten Mal
ein eigenes Python mit den nötigen Bibliotheken (etwa 150 MB, 1–2 Minuten).
Homebrew oder das Terminal brauchst du nicht. Danach kannst du den Installer
löschen.

**Wenn macOS das Öffnen blockiert:** Der Installer ist nicht bei Apple
registriert, deshalb warnt macOS beim ersten Öffnen.

- macOS 15 und neuer: Meldung schließen, dann Systemeinstellungen →
  Datenschutz & Sicherheit → ganz unten bei „Zeitwerk installieren“ auf
  **Dennoch öffnen** klicken und bestätigen.
- macOS 14 und älter: im Finder mit gedrückter ctrl-Taste auf
  „Zeitwerk installieren“ klicken → **Öffnen** → **Öffnen**.

Das ist nur einmal nötig. Die installierte Zeitwerk-App entsteht auf deinem Mac
und startet danach ohne Warnung.

**Aktualisieren** funktioniert genauso: neuen Installer öffnen,
„Aktualisieren“ wählen. Erfasste Zeit, Regeln und Einstellungen bleiben
erhalten. Nach einem Update musst du die Bildschirmaufnahme eventuell neu
erlauben, weil macOS die neue Version als neue App sieht.

Protokoll des Installers: `~/Library/Logs/Zeitwerk-Installer.log`.

## Berechtigungen

| Was | Berechtigung | Ohne sie |
|---|---|---|
| App-Name, Pausen | keine | – |
| Fenstertitel | Datenschutz & Sicherheit → **Bildschirm- & Systemaudioaufnahme** | Titel bleibt leer, Apps werden trotzdem erfasst |
| Browser-Domain | **Automation**. macOS fragt beim ersten Mal pro Browser nach | Browser zählt als eine App |

Unter **Einstellungen → Erfassung** siehst du, ob die Bildschirmaufnahme erlaubt
ist, und kommst direkt zur passenden Stelle in den Systemeinstellungen. Nach dem
Erlauben Zeitwerk einmal beenden und neu öffnen. Zeitwerk liest nur Fenstertitel,
es macht nie Bildschirmfotos.

## Kategorien anpassen

**Einstellungen → Kategorien → Regeln bearbeiten …** öffnet
`~/Library/Application Support/Zeitwerk/rules.toml`. Jede Kategorie hat einen
Produktivitätswert von `-2` (sehr ablenkend) bis `2` (sehr produktiv) und passt
über App-Namen, Domains oder Fenstertitel (Regex):

```toml
[[category]]
name = "Musikproduktion"
productivity = 2
apps = ["FL Studio", "Ableton Live"]
domains = ["splice.com"]
```

Mit `require_all = true` müssen alle Bedingungen gleichzeitig passen, z. B.
YouTube **und** „Tutorial“ im Titel. Was noch keiner Regel entspricht, zeigt die
Übersicht unter **Nicht zugeordnet**. Änderungen gelten auch für bereits erfasste
Zeit.

## Produktivitätswert

0–100, gewichtet nach Zeit: 100 = nur sehr produktiv, 50 = neutral,
0 = nur sehr ablenkend.

## Deinstallieren

Installer öffnen → **Deinstallieren …** → „Daten behalten“ oder „Alles löschen“.

## Installer selbst bauen

```bash
python3 tools/build_installer.py   # → dist/Zeitwerk-Installer-<version>.zip
```

Nur Standardbibliothek, läuft auf macOS und Linux. `./install.sh` baut den
Installer und öffnet ihn direkt.

## Aufbau

| Datei | Aufgabe |
|---|---|
| `zeitwerk/menubar.py` | Menüleisten-App, startet den Tracker im Hintergrund-Thread |
| `zeitwerk/menuview.py` | Tagesübersicht mit Balken oben im Menü |
| `zeitwerk/window.py` | native Fenster (NSWindow + WKWebView) und Brücke zur Oberfläche |
| `zeitwerk/ui/app.html` | Oberfläche für Übersicht, Einstellungen und Willkommen |
| `zeitwerk/payload.py` | bereitet Zahlen und Sätze für die Oberfläche auf |
| `zeitwerk/prefs.py` | Einstellungen (`prefs.json`) und Autostart |
| `zeitwerk/macos.py` | fragt macOS ab: aktive App, Fenstertitel, Browser-URL, Idle-Zeit, Sperre |
| `zeitwerk/tracker.py` | Messschleife alle 5 s, Pausen- und Schlaf-Erkennung |
| `zeitwerk/db.py` | SQLite, verlängert Einträge statt jede Messung einzeln zu speichern |
| `zeitwerk/classify.py` | wendet `rules.toml` an |
| `installer/installer.sh` | Installer: Dialoge, Python über uv, App bauen, Aktualisieren, Deinstallieren |
| `tools/build_installer.py` | baut „Zeitwerk installieren.app“ und das Zip |
| `tests/` | `python -m pytest tests` (der Installer wird mit Attrappen getestet) |

## Entwicklung

Der Quellcode liegt in diesem Repo, nicht in der App. Ablauf:

1. Code hier ändern.
2. `./deploy.sh` – lässt die Tests laufen, kopiert den Code nach
   `/Applications/Zeitwerk.app` und startet Zeitwerk neu.
3. Committen.

Tests von Hand: `"$HOME/Library/Application Support/Zeitwerk/runtime/venv/bin/python" -m pytest tests`
(pytest muss dafür in Zeitwerks Python installiert sein).

- `zeitwerk/` – der Code (Menüleiste, Tracker, Auswertung, Widget auf dem Schreibtisch)
- `macos/` – Info.plist, Startskript und Symbol der App
- `rules.toml` – Vorlage für neue Installationen. Deine eigenen Regeln liegen in
  `~/Library/Application Support/Zeitwerk/rules.toml`.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
