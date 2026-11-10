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

Voraussetzungen: macOS 12 oder neuer und Python 3.11+ (`python3 --version`;
falls es fehlt: [python.org](https://www.python.org/downloads/) oder
`brew install python`).

```bash
git clone https://github.com/NovakBeslic/zeitwerk.git
cd zeitwerk
./install.sh
```

Beim ersten Mal legt `install.sh` eine eigene Python-Umgebung unter
`~/Library/Application Support/Zeitwerk/runtime` an (etwa 1–2 Minuten), baut
`/Applications/Zeitwerk.app` und startet Zeitwerk. Ein Willkommensfenster
fragt nach Menüleisten-Symbol und Autostart. Die Aufzeichnung beginnt bei null,
und die Regelvorlage wird in deinen Datenordner kopiert (siehe
[Kategorien anpassen](#kategorien-anpassen)).

**Aktualisieren:** `git pull` und noch einmal `./install.sh`. Erfasste Zeit,
Regeln und Einstellungen bleiben erhalten. Nach einem Update musst du die
Bildschirmaufnahme eventuell neu erlauben.

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

Zeitwerk startet mit einer Vorlage, die viele verbreitete Apps und Websites
kennt: Programmieren, Lernen, Office, Design, Video, Musikproduktion,
Kommunikation, Social Media, Streaming, Gaming und mehr. **Was produktiv ist,
hängt aber von dir ab.** Für eine Spieleentwicklerin ist Steam vielleicht Arbeit,
für einen Social-Media-Manager Instagram. Nimm dir deshalb nach ein, zwei Tagen
fünf Minuten Zeit für deine Regeln:

1. **Übersicht → Kategorien:** Was unter **Nicht zugeordnet** steht, zählt neutral.
   Das sind die Apps und Websites, die der Vorlage noch fehlen.
2. **Einstellungen → Kategorien → Regeln bearbeiten …** öffnet
   `~/Library/Application Support/Zeitwerk/rules.toml` im Texteditor.
3. Fehlende Apps/Websites in eine passende Kategorie eintragen, Werte umstufen,
   eigene Kategorien anlegen. Speichern genügt, Zeitwerk liest die Datei beim
   nächsten Aktualisieren neu ein.

Jede Kategorie hat einen Produktivitätswert von `-2` (sehr ablenkend) bis `2`
(sehr produktiv) und passt über App-Namen, Domains oder Fenstertitel (Regex):

```toml
[[category]]
name = "Fotografie"
productivity = 2
apps = ["Adobe Lightroom Classic", "Capture One"]   # Name wie in der Menüleiste
domains = ["500px.com"]                             # Subdomains zählen mit
```

- **Eigene Uni/FH/Firma:** in „Lernen & Studium“ die Domain ergänzen, etwa
  `meine-uni.at`. Dann zählen `moodle.meine-uni.at` und Co. automatisch mit.
- **Umstufen:** einfach `productivity` ändern, zum Beispiel Gaming auf `2`, wenn
  Spiele dein Job sind.
- Regeln für Apps, die du nie benutzt, stören nicht. Sie greifen einfach nie.
- Mit `require_all = true` müssen alle Bedingungen gleichzeitig passen, z. B.
  YouTube **und** „Tutorial“ im Titel (braucht die Bildschirmaufnahme-Berechtigung,
  siehe oben).
- Domains ohne Pfad angeben (`linkedin.com`, nicht `linkedin.com/learning`):
  Zeitwerk vergleicht nur den Host.

Änderungen gelten auch für bereits erfasste Zeit.

Deine `rules.toml` gehört dir: Updates von Zeitwerk überschreiben sie nicht. Die
Vorlage im Repo wird nur beim allerersten Start kopiert.

## Produktivitätswert

0–100, gewichtet nach Zeit: 100 = nur sehr produktiv, 50 = neutral,
0 = nur sehr ablenkend.

## Deinstallieren

1. Zeitwerk über die Menüleiste beenden (**Zeitwerk beenden**).
2. `/Applications/Zeitwerk.app` löschen und den Autostart entfernen:
   `rm -f ~/Library/LaunchAgents/at.kyrie.zeitwerk.plist`
3. Optional alle Daten (erfasste Zeit, Regeln, Einstellungen, Python-Umgebung)
   löschen: `rm -rf ~/Library/Application\ Support/Zeitwerk`

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
| `zeitwerk/summary.py` | Tageswerte für Menü und Widget |
| `zeitwerk/deskwidget.py` | Widget auf dem Schreibtisch |
| `install.sh` | installiert bzw. aktualisiert die App aus diesem Repo |
| `macos/` | Info.plist, Startskript und Symbol der App |
| `tests/` | `python -m pytest tests` |

## Entwicklung

Der Quellcode liegt in diesem Repo, nicht in der App. Ablauf:

1. Code hier ändern.
2. `./install.sh` – lässt die Tests laufen (falls pytest installiert ist),
   kopiert den Code nach `/Applications/Zeitwerk.app` und startet Zeitwerk neu.
3. Committen.

Tests von Hand: `"$HOME/Library/Application Support/Zeitwerk/runtime/venv/bin/python" -m pytest tests`
(pytest muss dafür in Zeitwerks Python installiert sein).

`rules.toml` im Repo ist nur die Vorlage für neue Installationen. Deine eigenen
Regeln liegen in `~/Library/Application Support/Zeitwerk/rules.toml`.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
