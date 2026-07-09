# -*- coding: utf-8 -*-
"""Lectura y agregacion de ~/.leo-code/usage.jsonl (dia/semana/mes).

Portado de meter.py de claude-code-meter (MIT) — sum_period/days_of_week/
days_of_month/fmt/meter_color/load_cfg/save_cfg son agnosticos a la fuente de
datos y se reusan casi verbatim. Reader es especifico de leo-code: un solo
archivo (no un glob de muchos .jsonl) con un solo total de tokens por linea
(no desglose input/output/cache como en Claude Code).
"""
import json
import os
from datetime import date, datetime
from pathlib import Path

from leo_code.core.metrics import USAGE_LOG_PATH

CONFIG = Path.home() / ".leo-code" / "meter_config.json"

DEFAULT_CFG = {
    "daily_budget": None,          # objetivo diario; si None = semanal / 7
    "weekly_budget": 10_000_000,   # objetivo semanal en tokens
    "monthly_budget": 60_000_000,  # objetivo mensual en tokens
    "refresh_sec": 60,
    "x": None, "y": None,          # posicion guardada del panel
}


def load_cfg() -> dict:
    cfg = dict(DEFAULT_CFG)
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_cfg(cfg: dict) -> None:
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def fmt(n: float) -> str:
    """1234567 -> '1.23M' · 12345 -> '12.3K'."""
    n = float(n)
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{int(n)}"


def meter_color(pct: float) -> str:
    return "#4caf7d" if pct < 70 else ("#e0a63a" if pct < 90 else "#e05a54")


def days_of_week(today: date) -> list[str]:
    iso_y, iso_w, iso_d = today.isocalendar()
    monday = date.fromordinal(today.toordinal() - (iso_d - 1))
    return [date.fromordinal(monday.toordinal() + i).isoformat() for i in range(7)]


def days_of_month(today: date) -> list[str]:
    import calendar
    n = calendar.monthrange(today.year, today.month)[1]
    return [date(today.year, today.month, d).isoformat() for d in range(1, n + 1)]


def sum_period(daily: dict[str, int], days: list[str]) -> int:
    return sum(daily.get(d, 0) for d in days)


class Reader:
    """Agrega tokens por dia desde usage.jsonl. Reparsea solo si el archivo cambio."""

    def __init__(self, path: Path | None = None):
        self.path = path or USAGE_LOG_PATH
        self._cache: tuple[float, int, dict[str, int]] | None = None

    def _parse_file(self) -> dict[str, int]:
        daily: dict[str, int] = {}
        try:
            with open(self.path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue
                    ts = entry.get("ts")
                    tokens = entry.get("tokens")
                    if not ts or tokens is None:
                        continue
                    try:
                        dt = datetime.fromisoformat(ts).astimezone()
                    except Exception:
                        continue
                    key = dt.date().isoformat()
                    daily[key] = daily.get(key, 0) + int(tokens)
        except Exception:
            pass
        return daily

    def collect(self) -> dict[str, int]:
        try:
            st = os.stat(self.path)
        except OSError:
            return {}
        sig = (st.st_mtime, st.st_size)
        if self._cache and (self._cache[0], self._cache[1]) == sig:
            return self._cache[2]
        daily = self._parse_file()
        self._cache = (sig[0], sig[1], daily)
        return daily
