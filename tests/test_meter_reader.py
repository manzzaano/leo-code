"""Bucketing dia/semana/mes y helpers puros de leo_code/meter/reader.py.
Sin llamadas a LLM: escribe un usage.jsonl sintetico directamente."""
import json
from datetime import date, datetime, timedelta, timezone

from leo_code.meter.reader import (
    Reader, sum_period, days_of_week, days_of_month, fmt, meter_color,
)


def _write_jsonl(path, entries):
    lines = [json.dumps(e) for e in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _entry(days_ago: int, tokens: int) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {"ts": ts, "repo_path": "x", "model": "m", "tokens": tokens, "latency_ms": 1}


def test_reader_bucketea_por_dia(tmp_path):
    log = tmp_path / "usage.jsonl"
    _write_jsonl(log, [_entry(0, 100), _entry(0, 50), _entry(1, 30)])

    daily = Reader(log).collect()

    today = datetime.now().astimezone().date().isoformat()
    assert daily[today] == 150


def test_reader_ignora_lineas_malformadas(tmp_path):
    log = tmp_path / "usage.jsonl"
    log.write_text('{"ts": "not-json"\n{"bad": true}\n' + json.dumps(_entry(0, 10)) + "\n",
                    encoding="utf-8")

    daily = Reader(log).collect()

    today = datetime.now().astimezone().date().isoformat()
    assert daily.get(today, 0) == 10


def test_reader_devuelve_vacio_si_no_existe_el_archivo(tmp_path):
    daily = Reader(tmp_path / "no_existe.jsonl").collect()
    assert daily == {}


def test_reader_cachea_por_mtime_size(tmp_path):
    log = tmp_path / "usage.jsonl"
    _write_jsonl(log, [_entry(0, 10)])
    reader = Reader(log)
    first = reader.collect()

    # Reescribir sin cambiar contenido -> mismo (mtime, size) es poco fiable en
    # tests rapidos; en cambio verificamos que un cambio real SI se refleja.
    _write_jsonl(log, [_entry(0, 10), _entry(0, 20)])
    second = reader.collect()

    today = datetime.now().astimezone().date().isoformat()
    assert first[today] == 10
    assert second[today] == 30


def test_sum_period_suma_solo_los_dias_pedidos():
    daily = {"2026-01-01": 100, "2026-01-02": 50, "2026-01-10": 999}
    assert sum_period(daily, ["2026-01-01", "2026-01-02"]) == 150
    assert sum_period(daily, ["2026-01-01"]) == 100
    assert sum_period(daily, ["2026-02-01"]) == 0


def test_days_of_week_devuelve_7_dias_lun_a_dom():
    days = days_of_week(date(2026, 7, 8))  # miercoles
    assert len(days) == 7
    assert days[0] == "2026-07-06"  # lunes
    assert days[-1] == "2026-07-12"  # domingo


def test_days_of_month_devuelve_todos_los_dias_del_mes():
    days = days_of_month(date(2026, 2, 15))  # 2026 no es bisiesto
    assert len(days) == 28
    assert days[0] == "2026-02-01"
    assert days[-1] == "2026-02-28"


def test_fmt_formatea_con_sufijos():
    assert fmt(500) == "500"
    assert fmt(12345) == "12.3K"
    assert fmt(1234567) == "1.23M"
    assert fmt(1_234_567_890) == "1.23B"


def test_meter_color_umbrales():
    assert meter_color(0) == "#4caf7d"
    assert meter_color(69.9) == "#4caf7d"
    assert meter_color(70) == "#e0a63a"
    assert meter_color(89.9) == "#e0a63a"
    assert meter_color(90) == "#e05a54"
    assert meter_color(150) == "#e05a54"
