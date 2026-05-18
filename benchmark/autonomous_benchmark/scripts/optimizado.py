"""Script optimizado — contraparte eficiente del script ineficiente."""
import functools
import os
import random
import time

SEED = 42
random.seed(SEED)

N = 8000
FIBO_N = 35
FILE_READS = 150

# Tiempos del script ineficiente (capturados en ejecucion previa)
TIEMPOS_BASE = {
    "sort":  6.4135,
    "fib":   0.8810,
    "io":    0.0056,
    "dup":   0.2956,
    "total": 7.5957,
}

print("=" * 60)
print("  Script OPTIMIZADO -- midiendo rendimiento")
print("=" * 60)

# --- Seccion 1: sorted() built-in (Timsort O(n log n)) ---
datos = [random.randint(0, 100_000) for _ in range(N)]
t0 = time.perf_counter()
datos_sorted = sorted(datos)
t_sort = time.perf_counter() - t0
speedup_sort = TIEMPOS_BASE["sort"] / t_sort if t_sort > 0 else float("inf")
print(f"\n[1] sorted() Timsort ({N} elem): {t_sort:.6f}s  [{speedup_sort:.0f}x mas rapido]")

# --- Seccion 2: Fibonacci con lru_cache (memoizacion) ---
@functools.lru_cache(maxsize=None)
def fib_cache(n: int) -> int:
    if n <= 1:
        return n
    return fib_cache(n - 1) + fib_cache(n - 2)

t0 = time.perf_counter()
resultado_fib = fib_cache(FIBO_N)
t_fib = time.perf_counter() - t0
speedup_fib = TIEMPOS_BASE["fib"] / t_fib if t_fib > 0 else float("inf")
print(f"[2] Fibonacci({FIBO_N}) con cache:  {t_fib:.6f}s  [{speedup_fib:.0f}x mas rapido] -> fib={resultado_fib}")

# --- Seccion 3: Lectura con cache en memoria ---
target_file = os.path.join(os.path.dirname(__file__), "..", "docs", "reglas_negocio.md")

t0 = time.perf_counter()
with open(target_file, encoding="utf-8") as f:
    content_cached = f.read()
total_chars = 0
for _ in range(FILE_READS):
    total_chars += len(content_cached)
t_io = time.perf_counter() - t0
speedup_io = TIEMPOS_BASE["io"] / t_io if t_io > 0 else float("inf")
print(f"[3] Lectura con cache x{FILE_READS}:    {t_io:.6f}s  [{speedup_io:.1f}x mas rapido] ({total_chars} chars)")

# --- Seccion 4: Duplicados con set O(n) ---
lista = [random.randint(0, 500) for _ in range(3000)]
t0 = time.perf_counter()
seen: set[int] = set()
duplicados: set[int] = set()
for v in lista:
    if v in seen:
        duplicados.add(v)
    seen.add(v)
t_dup = time.perf_counter() - t0
speedup_dup = TIEMPOS_BASE["dup"] / t_dup if t_dup > 0 else float("inf")
print(f"[4] Duplicados con set (3000 e): {t_dup:.6f}s  [{speedup_dup:.0f}x mas rapido] ({len(duplicados)} unicos)")

total = t_sort + t_fib + t_io + t_dup
speedup_total = TIEMPOS_BASE["total"] / total if total > 0 else float("inf")

print(f"\n{'='*60}")
print(f"  TIEMPO TOTAL OPTIMIZADO: {total:.6f}s")
print(f"{'='*60}")
print(f"\n  TABLA COMPARATIVA:")
print(f"  {'Seccion':<28} {'Ineficiente':>12} {'Optimizado':>12} {'Speedup':>10}")
print(f"  {'-'*64}")
print(f"  {'1. Bubble Sort vs Timsort':<28} {TIEMPOS_BASE['sort']:>11.4f}s {t_sort:>11.6f}s {speedup_sort:>9.0f}x")
print(f"  {'2. Fib recursivo vs cache':<28} {TIEMPOS_BASE['fib']:>11.4f}s {t_fib:>11.6f}s {speedup_fib:>9.0f}x")
print(f"  {'3. File x150 vs cache':<28} {TIEMPOS_BASE['io']:>11.4f}s {t_io:>11.6f}s {speedup_io:>9.1f}x")
print(f"  {'4. Duplicados O(n2) vs set':<28} {TIEMPOS_BASE['dup']:>11.4f}s {t_dup:>11.6f}s {speedup_dup:>9.0f}x")
print(f"  {'-'*64}")
print(f"  {'TOTAL':<28} {TIEMPOS_BASE['total']:>11.4f}s {total:>11.6f}s {speedup_total:>9.1f}x")
print(f"\nBENCHMARK_RESULT:optimizado:{t_sort:.6f}:{t_fib:.6f}:{t_io:.6f}:{t_dup:.6f}:{total:.6f}:{speedup_total:.1f}")
