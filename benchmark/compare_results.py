"""Compara resultados pre y post fixes."""

import json
from pathlib import Path

PRE = {
    "chat": {"score": 7.9, "tokens": 8915, "latency": 48},
    "reasoner": {"score": 7.7, "tokens": 10582, "latency": 49},
    "v4-flash": {"score": 7.8, "tokens": 10145, "latency": 57},
    "v4-pro": {"score": 7.6, "tokens": 10030, "latency": 156},
}

POST_FILE = Path("benchmark/results_final/summary.json")

if not POST_FILE.exists():
    print("No results yet. Waiting for benchmark...")
    exit(0)

data = json.loads(POST_FILE.read_text(encoding="utf-8"))

POST = {}
for model in ["deepseek-chat", "deepseek-reasoner", "deepseek-v4-flash", "deepseek-v4-pro"]:
    model_data = [r for r in data if f"/{model.split('-', 1)[-1]}" in r.get("model", "") and r.get("mode") == "rag"]
    if model_data:
        scores = [r.get("score", 0) for r in model_data]
        tokens = [r.get("tokens", 0) for r in model_data]
        latencies = [r.get("duration_s", 0) for r in model_data]
        avg_score = sum(scores) / len(scores) if scores else 0
        avg_tokens = sum(tokens) / len(tokens) if tokens else 0
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        key = model.split("-")[-1]
        POST[key] = {"score": round(avg_score, 1), "tokens": int(avg_tokens), "latency": round(avg_latency, 0)}

print("\n=== COMPARACIÓN PRE/POST FIXES ===\n")
print("| Modelo | Métrica | Antes | Después | Cambio |")
print("|--------|---------|-------|---------|--------|")

for model in ["chat", "reasoner", "v4-flash", "v4-pro"]:
    if model in POST:
        pre = PRE[model]
        post = POST[model]

        score_delta = post["score"] - pre["score"]
        token_delta = post["tokens"] - pre["tokens"]
        latency_delta = post["latency"] - pre["latency"]

        print(f"| {model:8} | Score | {pre['score']:.1f} | {post['score']:.1f} | {score_delta:+.1f} |")
        print(f"| {model:8} | Tokens | {pre['tokens']} | {post['tokens']} | {token_delta:+d} |")
        print(f"| {model:8} | Latencia | {pre['latency']:.0f}s | {post['latency']:.0f}s | {latency_delta:+.0f}s |")

print("\n")
