"""Script deliberadamente ineficiente para benchmark de refactorización."""
import time
import random

SEED = 42
random.seed(SEED)

N = 8000
FIBO_N = 35
FILE_READS = 150

print("=" * 60)
print("  Script INEFICIENTE — midiendo rendimiento")
print("=" * 60)

# --- Sección 1: Bubble Sort O(n²) ---
datos = [random.randint(0, 100_000) for _ in range(N)]
t0 = time.perf_counter()

for i in range(len(datos)):
    for j in range(len(datos) - 1):
        if datos[j] > datos[j + 1]:
            datos[j], datos[j + 1] = datos[j + 1], datos[j]

t_sort = time.perf_counter() - t0
print(f"\n[1] Bubble Sort ({N} elementos):  {t_sort:.4f}s")

# --- Sección 2: Fibonacci recursivo sin memoización ---
def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)

t0 = time.perf_counter()
resultado_fib = fib(FIBO_N)
t_fib = time.perf_counter() - t0
print(f"[2] Fibonacci({FIBO_N}) sin memo:  {t_fib:.4f}s  -> fib={resultado_fib}")

# --- Sección 3: Lectura repetida de archivo (sin caché) ---
import os
target_file = os.path.join(os.path.dirname(__file__), "..", "docs", "reglas_negocio.md")

t0 = time.perf_counter()
total_chars = 0
for _ in range(FILE_READS):
    with open(target_file, encoding="utf-8") as f:
        content = f.read()
    total_chars += len(content)
t_io = time.perf_counter() - t0
print(f"[3] Lectura archivo x{FILE_READS}:     {t_io:.4f}s  ({total_chars} chars leídos)")

# --- Sección 4: Búsqueda de duplicados O(n²) ---
lista = [random.randint(0, 500) for _ in range(3000)]
t0 = time.perf_counter()

duplicados = []
for i in range(len(lista)):
    for j in range(i + 1, len(lista)):
        if lista[i] == lista[j] and lista[i] not in duplicados:
            duplicados.append(lista[i])

t_dup = time.perf_counter() - t0
print(f"[4] Duplicados O(n²) (3000 elem): {t_dup:.4f}s  ({len(duplicados)} únicos)")

total = t_sort + t_fib + t_io + t_dup
print(f"\n{'='*60}")
print(f"  TIEMPO TOTAL INEFICIENTE: {total:.4f}s")
print(f"{'='*60}")
print(f"BENCHMARK_RESULT:ineficiente:{t_sort:.4f}:{t_fib:.4f}:{t_io:.4f}:{t_dup:.4f}:{total:.4f}")
