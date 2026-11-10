"""Ordnet Einträge Kategorien und Produktivitätswerten zu (siehe rules.toml)."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

UNCATEGORIZED = "Nicht zugeordnet"
WEIGHTS = {"domain": 3, "title": 2, "app": 1}

LEVELS = {2: "Sehr produktiv", 1: "Produktiv", 0: "Neutral", -1: "Ablenkend", -2: "Sehr ablenkend"}


@dataclass
class Category:
    name: str
    productivity: int
    apps: set[str] = field(default_factory=set)
    domains: list[str] = field(default_factory=list)
    titles: list[re.Pattern] = field(default_factory=list)
    require_all: bool = False
    examples: list[str] = field(default_factory=list)

    def score(self, app: str, bundle_id: Optional[str], title: Optional[str],
              domain: Optional[str]) -> int:
        checks = {}
        if self.apps:
            checks["app"] = app.lower() in self.apps or (bundle_id or "").lower() in self.apps
        if self.domains:
            d = (domain or "").lower()
            checks["domain"] = bool(d) and any(d == x or d.endswith("." + x) for x in self.domains)
        if self.titles:
            checks["title"] = bool(title) and any(p.search(title) for p in self.titles)
        if not checks or (self.require_all and not all(checks.values())):
            return 0
        return sum(WEIGHTS[k] for k, hit in checks.items() if hit)


class Classifier:
    def __init__(self, categories: list[Category]):
        self.categories = categories
        self._cache: dict[tuple, tuple[str, int]] = {}

    @classmethod
    def from_file(cls, path: Path) -> "Classifier":
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        cats = []
        for c in raw.get("category", []):
            prod = int(c.get("productivity", 0))
            if prod not in LEVELS:
                raise ValueError(f"Kategorie {c.get('name')}: productivity muss -2..2 sein")
            cats.append(Category(
                name=c["name"],
                productivity=prod,
                apps={a.lower() for a in c.get("apps", [])},
                domains=[d.lower().removeprefix("www.") for d in c.get("domains", [])],
                titles=[re.compile(t) for t in c.get("titles", [])],
                require_all=bool(c.get("require_all", False)),
                examples=list(c.get("apps", []))[:2] + list(c.get("domains", []))[:2],
            ))
        return cls(cats)

    def classify(self, app: str, bundle_id: Optional[str] = None, title: Optional[str] = None,
                 domain: Optional[str] = None) -> tuple[str, int]:
        key = (app, bundle_id, title, domain)
        if key in self._cache:
            return self._cache[key]
        best: tuple[str, int] = (UNCATEGORIZED, 0)
        best_score = 0
        for cat in self.categories:
            s = cat.score(app, bundle_id, title, domain)
            if s > best_score:  # ">" → bei Gleichstand bleibt die frühere Kategorie
                best, best_score = (cat.name, cat.productivity), s
        self._cache[key] = best
        return best
