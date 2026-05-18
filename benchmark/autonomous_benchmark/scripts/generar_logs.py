"""Genera logs simulados, extrae errores con grep, comprime y elimina originales."""
import os
import random
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

SEED = 42
random.seed(SEED)

LOGS_DIR = Path(__file__).parent.parent / "logs"
OUTPUT_DIR = Path(__file__).parent.parent

LEVELS = ["INFO", "WARNING", "ERROR", "CRITICAL", "DEBUG"]
WEIGHTS = [60, 20, 12, 5, 3]

SERVICES = ["auth-service", "payment-api", "inventory-mgr", "notify-worker", "db-pool"]
MESSAGES: dict[str, list[str]] = {
    "INFO": [
        "Request processed successfully",
        "User authenticated: user_id={}",
        "Cache hit ratio: {}%",
        "Heartbeat OK",
        "Connection pool: {}/{} active",
        "Task completed in {}ms",
    ],
    "WARNING": [
        "Slow query detected: {}ms",
        "Retry attempt {}/3 for endpoint {}",
        "Memory usage at {}%",
        "Queue depth: {} pending items",
        "Token expiry approaching: {}s remaining",
    ],
    "ERROR": [
        "Failed to connect to DB: Connection refused",
        "Timeout after {}ms on endpoint /api/v2/{}",
        "Unhandled exception in handler: NullPointerError",
        "Payment gateway returned 503",
        "Redis SETEX failed: OOM command not allowed",
        "Validation error: field '{}' is required",
        "Circuit breaker OPEN for service {}",
    ],
    "CRITICAL": [
        "SYSTEM ALERT: Disk usage > 95% on /var/data",
        "Deadlock detected in transaction TX-{}",
        "Unexpected shutdown: signal SIGKILL received",
        "Data corruption detected in shard-{}",
        "Master-replica sync FAILED: 3 consecutive failures",
    ],
    "DEBUG": [
        "Entering handler with args={}",
        "Cache key generated: {}",
        "SQL: SELECT * FROM orders WHERE id={}",
    ],
}


def _rand_val() -> str:
    opts = [
        str(random.randint(1, 9999)),
        f"product-{random.randint(100, 999)}",
        f"order_{random.randint(10000, 99999)}",
        f"{random.randint(10, 99)}",
        f"svc-{random.randint(1, 5)}",
    ]
    return random.choice(opts)


def _gen_line(ts: datetime, service: str, level: str) -> str:
    msgs = MESSAGES[level]
    template = random.choice(msgs)
    # fill {} placeholders
    count = template.count("{}")
    for _ in range(count):
        template = template.replace("{}", _rand_val(), 1)
    pid = random.randint(1000, 9999)
    return f"{ts.strftime('%Y-%m-%d %H:%M:%S')} [{level:8s}] [{service}] PID={pid} | {template}"


def generate_log(path: Path, date: datetime, line_count: int) -> int:
    lines = []
    ts = date.replace(hour=0, minute=0, second=0)
    for _ in range(line_count):
        ts += timedelta(seconds=random.randint(1, 60))
        service = random.choice(SERVICES)
        level = random.choices(LEVELS, weights=WEIGHTS, k=1)[0]
        lines.append(_gen_line(ts, service, level))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def generate_nginx_log(path: Path, line_count: int) -> int:
    methods = ["GET", "POST", "PUT", "DELETE"]
    paths_ok = ["/api/v2/products", "/api/v2/users", "/health", "/api/v2/orders"]
    paths_err = ["/api/v2/admin", "/api/v2/internal", "/.env", "/wp-admin"]
    status_weights = [(200, 50), (201, 10), (304, 15), (404, 15), (500, 7), (503, 3)]
    codes, cweights = zip(*status_weights)
    lines = []
    base = datetime(2026, 5, 20, 6, 0, 0)
    for i in range(line_count):
        ts = base + timedelta(seconds=i * 5)
        method = random.choice(methods)
        code = random.choices(codes, weights=cweights, k=1)[0]
        ip = f"192.168.{random.randint(1, 10)}.{random.randint(1, 254)}"
        path_str = random.choice(paths_err if code >= 400 else paths_ok)
        size = random.randint(200, 50000)
        lines.append(
            f'{ip} - - [{ts.strftime("%d/%b/%Y:%H:%M:%S")} +0000] '
            f'"{method} {path_str} HTTP/1.1" {code} {size}'
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def extract_errors_grep(logs_dir: Path, output_file: Path) -> tuple[int, str]:
    """Intenta extraer errores usando grep (Git for Windows) o fallback Python."""
    grep_candidates = [
        "grep",
        r"C:\Program Files\Git\usr\bin\grep.exe",
        r"C:\Program Files (x86)\Git\usr\bin\grep.exe",
    ]
    log_files = list(logs_dir.glob("*.log"))
    method_used = "python_re"

    for grep_cmd in grep_candidates:
        try:
            result = subprocess.run(
                [grep_cmd, "-E", "-n", "ERROR|CRITICAL"] + [str(f) for f in log_files],
                capture_output=True, text=True, timeout=15, encoding="utf-8",
            )
            lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
            method_used = f"grep ({grep_cmd})"
            break
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
    else:
        # Fallback Python re
        lines = []
        pattern = re.compile(r"ERROR|CRITICAL")
        for log_file in log_files:
            text = log_file.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    lines.append(f"{log_file.name}:{i}: {line}")

    header = (
        f"# Errores extraidos de logs TiendaMax\n"
        f"# Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"# Metodo: {method_used}\n"
        f"# Total lineas con ERROR/CRITICAL: {len(lines)}\n"
        f"# Archivos procesados: {', '.join(f.name for f in log_files)}\n"
        f"{'#'*70}\n\n"
    )
    output_file.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return len(lines), method_used


def archive_and_cleanup(logs_dir: Path, zip_path: Path) -> list[str]:
    log_files = list(logs_dir.glob("*.log"))
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for log_file in log_files:
            zf.write(log_file, arcname=log_file.name)
    archived = [f.name for f in log_files]
    # Safety: verify zip is valid before deleting
    with zipfile.ZipFile(zip_path, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP corrupto, archivo comprometido: {bad}")
    shutil.rmtree(logs_dir)
    return archived


def main() -> None:
    print("\n" + "=" * 60)
    print("  Fase 3: Sistema — Generacion y Procesamiento de Logs")
    print("=" * 60)

    LOGS_DIR.mkdir(exist_ok=True)

    # Generar logs
    specs = [
        (LOGS_DIR / "app_2026-05-18.log", datetime(2026, 5, 18), 150),
        (LOGS_DIR / "app_2026-05-19.log", datetime(2026, 5, 19), 160),
        (LOGS_DIR / "app_2026-05-20.log", datetime(2026, 5, 20), 140),
        (LOGS_DIR / "worker_error.log",   datetime(2026, 5, 20), 80),
    ]
    total_lines = 0
    for path, date, count in specs:
        n = generate_log(path, date, count)
        total_lines += n
        print(f"  [CREADO] {path.name}: {n} lineas")

    nginx_path = LOGS_DIR / "nginx_access.log"
    n_nginx = generate_nginx_log(nginx_path, 120)
    total_lines += n_nginx
    print(f"  [CREADO] {nginx_path.name}: {n_nginx} lineas")
    print(f"\n  Total lineas generadas: {total_lines}")

    # Extraer errores
    output_errors = OUTPUT_DIR / "errores_extraidos.txt"
    print("\n  Extrayendo errores (ERROR|CRITICAL)...")
    n_errors, method = extract_errors_grep(LOGS_DIR, output_errors)
    print(f"  [EXTRAIDO] {n_errors} lineas de error -> errores_extraidos.txt")
    print(f"  Metodo usado: {method}")

    # Comprimir y limpiar
    zip_path = OUTPUT_DIR / "logs_archive.zip"
    print("\n  Comprimiendo logs con zipfile...")
    archived = archive_and_cleanup(LOGS_DIR, zip_path)
    zip_size = zip_path.stat().st_size / 1024
    print(f"  [ZIP] logs_archive.zip ({zip_size:.1f} KB) — {len(archived)} archivos")
    print(f"  [ELIMINADO] directorio logs/ con {len(archived)} archivos")
    print(f"\n  Archivos en ZIP: {', '.join(archived)}")

    print(f"\n  Sistema completado:")
    print(f"    - {total_lines} lineas de log generadas")
    print(f"    - {n_errors} errores extraidos a errores_extraidos.txt")
    print(f"    - {len(archived)} logs archivados en logs_archive.zip")
    print(f"    - Directorio logs/ eliminado")
    print(f"\nSISTEMA_RESULT:{total_lines}:{n_errors}:{len(archived)}:{method}")


if __name__ == "__main__":
    main()
