"""Tests für das Widget auf dem Schreibtisch: summary.desk() und die Skalierung."""
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zeitwerk.classify import Category, Classifier  # noqa: E402
from zeitwerk.summary import desk  # noqa: E402

NOW = datetime(2026, 11, 10, 15, 0)
clf = Classifier([Category("Code", 2, apps={"code", "terminal"}),
                  Category("Video", -2, apps={"youtube"})])


def make_db(rows):
    d = Path(tempfile.mkdtemp()) / "z.db"
    c = sqlite3.connect(d)
    c.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, start REAL, end REAL, app TEXT,"
              " bundle_id TEXT, title TEXT, domain TEXT)")
    for start, minutes, app, *domain in rows:
        c.execute("INSERT INTO events (start,end,app,bundle_id,domain) VALUES (?,?,?,?,?)",
                  (start.timestamp(), (start + timedelta(minutes=minutes)).timestamp(), app, f"id.{app}",
                   domain[0] if domain else None))
    c.commit()
    c.close()
    return d


def at(days_ago, h, m=0):
    return datetime.combine(NOW.date() - timedelta(days=days_ago), datetime.min.time()) + timedelta(hours=h, minutes=m)


def test_empty_db():
    s = desk(Path(tempfile.mkdtemp()) / "missing.db", clf, NOW)
    assert s.day.empty and s.top_apps == [] and s.current is None
    assert len(s.week) == 7 and all(sec == 0 for _, sec in s.week)


def test_top_apps_by_app_not_category():
    db = make_db([(at(0, 9), 60, "Code"), (at(0, 10), 30, "Terminal"), (at(0, 11), 45, "YouTube"),
                  (at(0, 12), 5, "A"), (at(0, 12, 10), 4, "B"), (at(0, 12, 20), 3, "C")])
    s = desk(db, clf, NOW)
    assert [a for a, _, _ in s.top_apps] == ["Code", "YouTube", "Terminal", "A", "B"]
    assert s.top_apps[0][1] == "id.Code" and s.top_apps[0][2] == 3600
    assert s.day.total == (60 + 30 + 45 + 5 + 4 + 3) * 60
    assert s.day.productive == 90 * 60 and s.day.distracting == 45 * 60


def test_week_and_yesterday_same_time():
    db = make_db([(at(0, 9), 60, "Code"),
                  (at(1, 9), 30, "Code"), (at(1, 20), 120, "Code"),   # gestern: 30 min bis 15 Uhr
                  (at(6, 9), 90, "Code"), (at(7, 9), 120, "Code")])   # vor 7 Tagen: nicht mehr dabei
    s = desk(db, clf, NOW)
    assert [d.date() for d, _ in s.week][-1] == NOW.date()
    assert [sec / 60 for _, sec in s.week] == [90, 0, 0, 0, 0, 150, 60]
    assert s.yesterday_same_time == 30 * 60
    assert s.week_avg == (90 + 150) / 2 * 60  # Ø nur über vergangene Tage mit Daten


def test_current_app_and_since():
    db = make_db([(at(0, 14, 0), 20, "Code"), (at(0, 14, 20), 25, "Terminal"),
                  (at(0, 14, 45, ), 15, "Terminal")])  # endet genau jetzt (15:00)
    s = desk(db, clf, NOW)
    assert s.current == ("Terminal", at(0, 14, 20))


def test_browser_split_by_website():
    db = make_db([(at(0, 9), 30, "Dia", "youtube.com"), (at(0, 10), 20, "Dia", "github.com"),
                  (at(0, 11), 10, "Dia"), (at(0, 12), 25, "Code"), (at(0, 14, 50), 10, "Dia", "youtube.com")])
    s = desk(db, clf, NOW)
    assert [(a, b) for a, b, _ in s.top_apps] == [
        ("youtube.com", "id.Dia"), ("Code", "id.Code"), ("github.com", "id.Dia"), ("Dia", "id.Dia")]
    assert s.top_apps[0][2] == 40 * 60
    assert s.current == ("youtube.com", at(0, 14, 50))


def test_no_current_when_idle():
    db = make_db([(at(0, 13), 30, "Code")])  # letzte Aktivität 13:30
    assert desk(db, clf, NOW).current is None


def test_widget_scale_from_grip_bottom_left():
    # macOS-unabhängig nur die Rechnung testen (deskwidget braucht AppKit)
    pytest = __import__("pytest")
    dw = pytest.importorskip("zeitwerk.deskwidget")
    f, W, H = dw.scale_for_drag, dw.W, dw.H
    assert f(1, 0, 0) == 1
    assert f(1, -W * 0.5, 0) == 1.5        # nach links: größer
    assert f(1, W * 0.2, 0) == 0.8         # nach rechts: kleiner
    assert f(1, 0, -H * 0.25) == 1.25      # nach unten: größer
    assert f(1, W, 0) == 0.75              # Untergrenze
    assert f(1.5, -W * 2, -H * 2) == 1.8   # Obergrenze


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, type(e).__name__, e)
    sys.exit(1 if fails else 0)
