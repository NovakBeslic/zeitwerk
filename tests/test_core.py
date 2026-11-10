import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zeitwerk.analysis import load_events, productivity_score  # noqa: E402
from zeitwerk.classify import UNCATEGORIZED, Classifier  # noqa: E402
from zeitwerk.config import Settings  # noqa: E402
from zeitwerk.db import Store  # noqa: E402
from zeitwerk.macos import Snapshot, domain_from_url  # noqa: E402
from zeitwerk.tracker import Tracker  # noqa: E402


@pytest.fixture
def clf():
    return Classifier.from_file(ROOT / "rules.toml")


class FakeSampler:
    def __init__(self):
        self.next = None

    def set(self, app, bid=None, title=None, domain=None, idle=0.0, locked=False):
        self.next = Snapshot(app, bid, 1, title, domain, idle, locked)

    def snapshot(self):
        return self.next


class Clock:
    def __init__(self, t=1_700_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def rows(path):
    with sqlite3.connect(path) as c:
        return c.execute("SELECT start, end, app, title, domain FROM events ORDER BY id").fetchall()


def make(tmp_path, **kw):
    clock, sampler = Clock(), FakeSampler()
    t = Tracker(Store(tmp_path / "t.db"), sampler, Settings(**kw), clock=clock)
    return t, sampler, clock, tmp_path / "t.db"


# ---------------------------------------------------------------- Klassifizierung
def test_app_rule(clf):
    assert clf.classify("FL Studio") == ("Musikproduktion", 2)


def test_bundle_id_case_insensitive(clf):
    assert clf.classify("Whatever", "COM.apple.Safari")[0] == UNCATEGORIZED
    assert clf.classify("Code")[0] == "Programmieren"


def test_domain_beats_app_and_matches_subdomain(clf):
    assert clf.classify("Google Chrome", "com.google.Chrome", "x", "m.youtube.com") == ("YouTube", -1)
    assert clf.classify("Safari", None, None, "notyoutube.com")[0] == UNCATEGORIZED


def test_require_all_tutorial(clf):
    assert clf.classify("Arc", None, "Mixing Tutorial - YouTube", "youtube.com") == ("YouTube-Tutorials", 1)
    # Titel allein (ohne YouTube-Domain) reicht nicht
    assert clf.classify("Arc", None, "Mixing Tutorial", "example.com")[0] == UNCATEGORIZED


def test_javascript_title_not_studium(clf):
    assert clf.classify("Code", None, "app.js — JavaScript")[0] == "Programmieren"


def test_unknown(clf):
    assert clf.classify("Mystery App") == (UNCATEGORIZED, 0)


# ---------------------------------------------------------------- Tracker / Speicher
def test_merge_same_window(tmp_path):
    t, s, clock, db = make(tmp_path)
    s.set("FL Studio")
    for _ in range(4):
        t.tick()
        clock.t += 5
    r = rows(db)
    assert len(r) == 1 and r[0][1] - r[0][0] == 15


def test_switch_has_no_gap(tmp_path):
    t, s, clock, db = make(tmp_path)
    s.set("FL Studio"); t.tick(); clock.t += 5
    s.set("Code"); t.tick(); clock.t += 5
    t.tick()
    r = rows(db)
    assert [x[2] for x in r] == ["FL Studio", "Code"]
    assert r[0][1] == r[1][0]  # FL Studio endet genau dort, wo Code beginnt


def test_idle_cuts_back(tmp_path):
    t, s, clock, db = make(tmp_path, idle_threshold=60)
    s.set("Code")
    for _ in range(30):  # 150 s
        t.tick(); clock.t += 5
    s.set("Code", idle=100)  # letzte Eingabe vor 100 s
    t.tick()
    start, end, *_ = rows(db)[0]
    assert end == pytest.approx(clock.t - 100)


def test_lock_and_sleep_gap(tmp_path):
    t, s, clock, db = make(tmp_path)
    s.set("Code"); t.tick(); clock.t += 5; t.tick()
    clock.t += 3600  # Mac schläft eine Stunde
    t.tick()
    r = rows(db)
    assert len(r) == 2 and r[0][1] - r[0][0] == 5  # keine Stunde zugerechnet
    clock.t += 5
    s.set("loginwindow", "com.apple.loginwindow", locked=True)
    t.tick()
    assert len(rows(db)) == 2


def test_private_app_drops_title(tmp_path):
    t, s, clock, db = make(tmp_path, private_apps=("1password",))
    s.set("1Password", title="Bank Login", domain="bank.at")
    t.tick()
    assert rows(db)[0][3:] == (None, None)


def test_domain_from_url():
    assert domain_from_url("https://www.youtube.com/watch?v=1") == "youtube.com"
    assert domain_from_url("about:blank") is None
    assert domain_from_url(None) is None


# ---------------------------------------------------------------- Auswertung
def test_midnight_split_and_score(tmp_path, clf):
    db = tmp_path / "a.db"
    store = Store(db)
    t0 = datetime(2026, 10, 12, 23, 30).timestamp()
    store.conn.execute("INSERT INTO events (start,end,app) VALUES (?,?,?)", (t0, t0 + 3600, "FL Studio"))
    store.conn.execute("INSERT INTO events (start,end,app,domain) VALUES (?,?,?,?)",
                       (t0 + 3600, t0 + 7200, "Safari", "instagram.com"))
    store.conn.commit()
    df = load_events(db, datetime(2026, 10, 12), datetime(2026, 10, 14), clf)
    assert df["day"].nunique() == 2
    assert df["seconds"].sum() == 7200
    assert productivity_score(df) == pytest.approx(50)  # +2 und -2 je 1 h


# ---------------------------------------------------------------- Vorlage für neue Installationen
@pytest.mark.parametrize("args, expected", [
    (("FL Studio",), "Musikproduktion"),
    (("Visual Studio Code",), "Programmieren"),
    (("Microsoft Excel",), "Office & Dokumente"),
    (("Adobe Lightroom",), "Design"),
    (("DaVinci Resolve",), "Video & Content"),
    (("Slack",), "Kommunikation"),
    (("Steam",), "Gaming"),
    (("Safari", None, None, "de.wikipedia.org"), "Nachschlagen"),
    (("Safari", None, None, "studio.youtube.com"), "Video & Content"),  # nicht „YouTube“
    (("Safari", None, None, "www.coursera.org"), "Lernen & Studium"),
    (("Safari", None, None, "docs.google.com"), "Office & Dokumente"),
])
def test_template_covers_common_apps(clf, args, expected):
    assert clf.classify(*args)[0] == expected


def test_template_domains_have_no_paths():
    import tomllib
    raw = tomllib.loads((ROOT / "rules.toml").read_text())
    bad = [d for c in raw["category"] for d in c.get("domains", []) if "/" in d]
    assert not bad, f"Domains dürfen keinen Pfad enthalten (es wird nur der Host verglichen): {bad}"
