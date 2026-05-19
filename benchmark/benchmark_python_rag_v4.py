"""Benchmark v4 HARD: leo-code KC-RAG vs opencode CLI vs no_ctx.
20 tareas cross-module chain-of-thought.
Criterios codificados en base64 para evitar contaminacion via lectura de archivo.
"""
import json, os, sys, time, subprocess, statistics, httpx, base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(r'C:\Users\Ismael\Desktop\RAG\.env')
sys.path.insert(0, r'C:\Users\Ismael\Desktop\kc-core')
sys.path.insert(0, r'C:\Users\Ismael\Desktop\kc-code')
from kc_core.benchmark import score_answer
from openai import OpenAI

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
LLM          = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
MODEL        = "deepseek-chat"
TEMPERATURE  = 0.2
SIDECAR      = "http://localhost:9898"
BUN          = r"C:\Users\Ismael\.bun\bin\bun.exe"
LEO_SRC      = r"C:\Users\Ismael\Desktop\leo-code\packages\leo-code"
LEO_REPO     = r"C:\Users\Ismael\Desktop\RAG"
WSL_REPO     = "/mnt/c/Users/Ismael/Desktop/RAG"
TIMEOUT_LEO  = 180
TIMEOUT_OC   = 180
RUNS_DIR     = Path(__file__).parent / "runs_pyrag_v4"
RUNS_DIR.mkdir(exist_ok=True)

_BUN_ENV = {
    **os.environ,
    "PYTHONIOENCODING": "utf-8",
    "PATH": BUN.replace("bun.exe", "") + os.pathsep + os.environ.get("PATH", ""),
    "DEEPSEEK_API_KEY": DEEPSEEK_KEY,
    "LEO_MCP_URL": SIDECAR,
    "LEO_REPO_PATH": LEO_REPO,
}
_WSL_ENV = {
    **os.environ,
    "DEEPSEEK_API_KEY": DEEPSEEK_KEY,
    "WSLENV": "DEEPSEEK_API_KEY/u:OC_QUERY/u",
}

# Criterios y ground_truth codificados en base64 para evitar contaminacion
_EVAL_B64 = 'eyJZMSI6IHsiYyI6IFsidmFsaWRhdGVfcXVlcnkiLCAiZ2V0X2NhY2hlZF9yZXN1bHQiLCAibG9nX3F1ZXJ5IiwgInNhbml0aXplIiwgImF1ZGl0Il0sICJndCI6ICJwaXBlbGluZS5weSBsbGFtYSB2YWxpZGF0ZV9xdWVyeShzZWN1cml0eS5zYW5pdGl6ZSksIGdldF9jYWNoZWRfcmVzdWx0KGNhY2hlLnJlZGlzX2NhY2hlKSwgbG9nX3F1ZXJ5KHNlY3VyaXR5LmF1ZGl0KS4ifSwgIlkyIjogeyJjIjogWyIwIiwgInRva2Vuc19sbG0iLCAiY2FjaGVfaGl0IiwgIl9tZXRhIiwgImNhcGEiXSwgImd0IjogIkN1YW5kbyBjYWNoZV9oaXQ9VHJ1ZSwgdG9rZW5zX2xsbT0wIGVuIF9tZXRhLiBMYSBjYXBhIGVzIGxhIG1pc21hIGRlIGxhIHJlc3B1ZXN0YSBjYWNoZWFkYS4ifSwgIlkzIjogeyJjIjogWyIwLjEiLCAiaWd1YWwiLCAiZXh0cmFjdF9lbnRpdGllcyIsICJzeW50aGVzaXplIiwgInRlbXBlcmF0dXJlIl0sICJndCI6ICJBbWJhcyB1c2FuIHRlbXBlcmF0dXJlPTAuMS4gTGEgdGVtcGVyYXR1cmEgZXMgaWd1YWwgZW4gZXh0cmFjdF9lbnRpdGllcygpIHkgc3ludGhlc2l6ZSgpLiJ9LCAiWTQiOiB7ImMiOiBbIkNPTkZJREVOQ0VfTUFQIiwgIkhJR0giLCAiMC45NSIsICJwcmVjaXNpb25fY3JpdGljYWwiLCAiVHJ1ZSJdLCAiZ3QiOiAiQ29uc3RhbnRlcyAoaXN1cHBlcj1UcnVlKSB0aWVuZW4gcHJlY2lzaW9uX2NyaXRpY2FsPVRydWUgeSBDT05GSURFTkNFX01BUFtISUdIXT0wLjk1LiJ9LCAiWTUiOiB7ImMiOiBbIkNBU0UgV0hFTiIsICJjb25maWRlbmNlIiwgIlRIRU4iLCAiRUxTRSIsICJNQVRDSCJdLCAiZ3QiOiAiT04gTUFUQ0g6IGNvbmZpZGVuY2UgPSBDQVNFIFdIRU4gID4gZS5jb25maWRlbmNlIFRIRU4gIEVMU0UgZS5jb25maWRlbmNlIEVORC4ifSwgIlk2IjogeyJjIjogWyJjb2RlIiwgIjAuNjUiLCAiMC4xMCIsICJtaW4iLCAiMC45NSJdLCAiZ3QiOiAiU2kgY29kZV9zY29yZSA+IDA6IGNvbmZpZGVuY2UgPSBtaW4oMC42NSArIGNvZGVfc2NvcmUgKiAwLjEwLCAwLjk1KS4ifSwgIlk3IjogeyJjIjogWyJzdWJncmFwaDoiLCAicXVlcnk6IiwgIm1kNSIsICJoYXNobGliIiwgIl9xdWVyeV9rZXkiXSwgImd0IjogIl9xdWVyeV9rZXk6IHByZWZpam8gcXVlcnk6ICsgbWQ1LiBfc3ViZ3JhcGhfa2V5OiBwcmVmaWpvIHN1YmdyYXBoOntlbnRpdHlfaWR9LiJ9LCAiWTgiOiB7ImMiOiBbIjAiLCAidG9rZW5zX2xsbSIsICJpbnB1dF90b2tlbnMiLCAib3V0cHV0X3Rva2VucyIsICJjYXBhIl0sICJndCI6ICJDYXBhIDAgZmFzdC1wYXRoOiB0b2tlbnNfbGxtPTAsIGlucHV0X3Rva2Vucz0wLCBvdXRwdXRfdG9rZW5zPTAgZW4gX21ldGEuIGNhcGE9MC4ifSwgIlk5IjogeyJjIjogWyJwcmVmaXgiLCAiZW1wdHkiLCAiX3Vwc2VydF9lbnRpdGllc19yZWxhdGlvbnMiLCAic291cmNlX2RvY19pZCIsICJzb3VyY2VfaGFzaCJdLCAiZ3QiOiAiX3Vwc2VydF9lbnRpdGllc19yZWxhdGlvbnMoZW50aXRpZXMsIHJlbGF0aW9ucywgc291cmNlX2RvY19pZCwgc291cmNlX2hhc2gsIHByZWZpeD1cIlwiKS4gRGVmYXVsdCBwcmVmaXggZXMgc3RyaW5nIHZhY2lvLiJ9LCAiWTEwIjogeyJjIjogWyJsaXN0W2RpY3RdIiwgIm5vZGVzX2RhdGEiLCAidXBzZXJ0X25vZGVzX2JhdGNoIiwgImJhdGNoIiwgImxpc3Rbc3RyXSJdLCAiZ3QiOiAidXBzZXJ0X25vZGVzX2JhdGNoKG5vZGVzX2RhdGE6IGxpc3RbZGljdF0pIC0+IGxpc3Rbc3RyXS4gUmVjaWJlIGxpc3RhIGRlIGRpY3RzLiJ9LCAiWTExIjogeyJjIjogWyJzZW1hbnRpYyIsICIwLjY1IiwgImNsYXNzaWZ5X2ludGVudCIsICJyZWxhdGlvbmFsIiwgImludGVudCJdLCAiZ3QiOiAiQ3VhbmRvIG5vIGhheSBzY29yZSBlbiBuaW5ndW5hIGNhdGVnb3JpYTogaW50ZW50PXNlbWFudGljLCBjb25maWRlbmNlPTAuNjUuIn0sICJZMTIiOiB7ImMiOiBbIi0xIiwgImNhcGEiLCAiVmFsdWVFcnJvciIsICJ2YWxpZGF0aW9uIiwgImVycm9yIl0sICJndCI6ICJTaSB2YWxpZGF0ZV9xdWVyeSgpIGxhbnphIFZhbHVlRXJyb3I6IF9tZXRhLmNhcGE9LTEsIF9tZXRhLmVycm9yPXZhbGlkYXRpb24sIGdyb3VuZGluZy5zY29yZT0wLjAuIn0sICJZMTMiOiB7ImMiOiBbIk5vbmUiLCAiaXNfYXZhaWxhYmxlIiwgIl9nZXRfY2xpZW50IiwgInNvY2tldF9jb25uZWN0X3RpbWVvdXQiLCAiMC4xIl0sICJndCI6ICJTaSBSZWRpcyBubyBkaXNwb25pYmxlOiBfZ2V0X2NsaWVudCgpIHJldG9ybmEgTm9uZSwgZ2V0X2NhY2hlZF9yZXN1bHQoKSByZXRvcm5hIE5vbmUuIHNvY2tldF9jb25uZWN0X3RpbWVvdXQ9MC4xLiJ9LCAiWTE0IjogeyJjIjogWyJBQ1RJVkUiLCAic3RhdHVzIiwgIk9OIENSRUFURSIsICJTRVQiLCAiY3JlYXRlZF9hdCJdLCAiZ3QiOiAiT04gQ1JFQVRFIFNFVCBzdGF0dXM9QUNUSVZFLCBjcmVhdGVkX2F0PSRub3cuIEVzIGVsIGVzdGFkbyBpbmljaWFsIGRlIG5vZG8gbnVldm8uIn0sICJZMTUiOiB7ImMiOiBbIlNlcnZpY2lvIiwgIlRhcmlmYSIsICJDb25kaWNpb24iLCAiQ2xpZW50ZSIsICJDb250cmF0byJdLCAiZ3QiOiAiRVhUUkFDVElPTl9QUk9NUFQgbGlzdGEgMTAgdGlwb3M6IFNlcnZpY2lvLCBUYXJpZmEsIENvbmRpY2lvbiwgQ2xpZW50ZSwgQ29udHJhdG8sIEZ1bmNpb24sIENsYXNlLCBSZWdsYSwgUmVzdHJpY2Npb24sIENvbmNlcHRvLiJ9LCAiWTE2IjogeyJjIjogWyJ0cnlfcmVzb2x2ZSIsICJyZXRyaWV2ZV9zdWJncmFwaCIsICJyb3V0ZV9wYXJhbGxlbCIsICJhc3luY2lvIiwgInBhcmFsbGVsIl0sICJndCI6ICJyb3V0ZV9wYXJhbGxlbChxdWVyeSwgY2FwYTBfZm49dHJ5X3Jlc29sdmUsIGNhcGEyX2ZuPXJldHJpZXZlX3N1YmdyYXBoKS4gTGxhbWFkYSB2aWEgYXN5bmNpby5ydW4oKSBlbiBwaXBlbGluZS4ifSwgIlkxNyI6IHsiYyI6IFsicXVlcnk6IiwgIm1kNSIsICJoYXNobGliIiwgImxvd2VyIiwgInN0cmlwIl0sICJndCI6ICJfcXVlcnlfa2V5OiBxdWVyeTogKyBoYXNobGliLm1kNShxdWVyeS5sb3dlcigpLnN0cmlwKCkuZW5jb2RlKCkpLmhleGRpZ2VzdCgpLiJ9LCAiWTE4IjogeyJjIjogWyJsb2dzL2F1ZGl0LmxvZyIsICJGaWxlSGFuZGxlciIsICIlKG1lc3NhZ2UpcyIsICJJTkZPIiwgInV0Zi04Il0sICJndCI6ICJGaWxlSGFuZGxlcihsb2dzL2F1ZGl0LmxvZywgZW5jb2Rpbmc9dXRmLTgpLiBGb3JtYXR0ZXI6ICUobWVzc2FnZSlzLiBMZXZlbDogSU5GTy4ifSwgIlkxOSI6IHsiYyI6IFsiY29uZmlkZW5jZSIsICIxLjAiLCAicHJlY2lzaW9uX2NyaXRpY2FsIiwgIkZhbHNlIiwgImFsaWFzZXMiXSwgImd0IjogInVwc2VydF9ub2RlIHRpZW5lIDMgcGFyYW1zIGNvbiBkZWZhdWx0OiBjb25maWRlbmNlPTEuMCwgcHJlY2lzaW9uX2NyaXRpY2FsPUZhbHNlLCBhbGlhc2VzPU5vbmUuIn0sICJZMjAiOiB7ImMiOiBbImFzeW5jaW8ucnVuIiwgInJvdXRlX3BhcmFsbGVsIiwgInRyeV9yZXNvbHZlIiwgInJldHJpZXZlX3N1YmdyYXBoIiwgInBhcmFsbGVsIl0sICJndCI6ICJhc3luY2lvLnJ1bihyb3V0ZV9wYXJhbGxlbCh1c2VyX3F1ZXJ5LCB0cnlfcmVzb2x2ZSwgcmV0cmlldmVfc3ViZ3JhcGgpKSBjdWFuZG8gaW50ZW50PT1wYXJhbGxlbC4ifX0='
_EVAL = json.loads(base64.b64decode(_EVAL_B64).decode())

# Solo queries visibles en el script — criterios en _EVAL (codificados arriba)
TASKS = [
    {"id": "Y1",  "type": "cross_module",
     "query": "En query/pipeline.py, identifica exactamente que dos funciones del modulo security se importan y se usan en la funcion query(). Dame los nombres exactos de ambas funciones y de sus modulos de origen (security.X)."},
    {"id": "Y2",  "type": "flow_analysis",
     "query": "En query/pipeline.py, cuando use_cache=True y hay un cache hit, cuantos tokens LLM se consumen? Cual es el valor de tokens_llm en el campo _meta del resultado devuelto?"},
    {"id": "Y3",  "type": "cross_file_compare",
     "query": "Compara la temperatura de inferencia usada en extract_entities() (ingestion/extractor.py) con la de synthesize() (query/capa4.py). Son iguales o diferentes? Cuales son los valores exactos?"},
    {"id": "Y4",  "type": "constant_flow",
     "query": "En ingestion/pipeline.py, _extract_from_ast() procesa nodos AST tipo constante (is_upper=True). Cual es el valor de precision_critical que asigna? Usa CONFIDENCE_MAP? Cual seria el valor numerico de confianza para HIGH?"},
    {"id": "Y5",  "type": "cypher_detail",
     "query": "En graph/nodes.py, upsert_node() tiene logica Cypher ON MATCH. Cuando el nodo ya existe, como actualiza la confianza? Escribe la expresion Cypher exacta usada."},
    {"id": "Y6",  "type": "router_logic",
     "query": "En query/router.py, cuando classify_intent() detecta code_score > 0, cual es la base numerica de confidence y cuanto suma por cada CODE_PATTERNS matched? Cual es el maximo?"},
    {"id": "Y7",  "type": "cache_keys",
     "query": "En cache/redis_cache.py, existen dos funciones privadas para generar claves de Redis: una para queries y otra para subgrafos. Cuales son los prefijos exactos que usa cada una?"},
    {"id": "Y8",  "type": "fast_path",
     "query": "En query/pipeline.py, cuando Capa 0 resuelve la query directamente (fast-path), cuantos tokens LLM se usan? Lista los valores exactos de tokens_llm, input_tokens y output_tokens en _meta."},
    {"id": "Y9",  "type": "func_signature",
     "query": "En ingestion/pipeline.py, la funcion privada _upsert_entities_relations() tiene un parametro con string vacio como default. Cual es ese parametro y su valor exacto?"},
    {"id": "Y10", "type": "batch_detail",
     "query": "En graph/nodes.py, la funcion upsert_nodes_batch() recibe un tipo especifico. Cual es el tipo exacto del parametro nodes_data y que tipo retorna la funcion?"},
    {"id": "Y11", "type": "fallback_intent",
     "query": "En query/router.py, classify_intent() tiene un caso por defecto cuando ninguna categoria tiene score. Cual es el intent_type devuelto y cuanto vale la confidence en ese caso?"},
    {"id": "Y12", "type": "error_handling",
     "query": "En query/pipeline.py, si validate_query() lanza una excepcion ValueError, que diccionario devuelve query()? Cual es el valor del campo capa en _meta y el campo error?"},
    {"id": "Y13", "type": "redis_fallback",
     "query": "En cache/redis_cache.py, si Redis no esta disponible (no se puede conectar), que devuelve get_cached_result()? Cual es el valor de socket_connect_timeout usado al crear el cliente?"},
    {"id": "Y14", "type": "cypher_create",
     "query": "En graph/nodes.py, en el Cypher ON CREATE SET de upsert_node(), cual es el valor inicial del campo status para un nodo recien creado? Que otros campos se inicializan en ON CREATE?"},
    {"id": "Y15", "type": "prompt_types",
     "query": "En ingestion/extractor.py, EXTRACTION_PROMPT (no CODE_EXTRACTION_PROMPT) lista tipos de entidad validos. Cuantos tipos hay en total y cuales son exactamente?"},
    {"id": "Y16", "type": "async_routing",
     "query": "En query/pipeline.py, cuando intent es parallel, route_parallel() se ejecuta de manera asincrona. Que dos funciones exactas se pasan como argumentos capa0_fn y capa2_fn respectivamente?"},
    {"id": "Y17", "type": "key_format",
     "query": "En cache/redis_cache.py, _query_key() genera claves Redis. Describe el formato exacto de la clave: que prefijo usa y como transforma la query para generar el hash?"},
    {"id": "Y18", "type": "audit_config",
     "query": "En security/audit.py, log_query() usa un logger configurado en _get_logger(). Cual es el path exacto del archivo de log, el nombre del formatter pattern y el nivel de logging?"},
    {"id": "Y19", "type": "optional_params",
     "query": "En graph/nodes.py, upsert_node() tiene exactamente 3 parametros con valores por defecto. Lista los 3 con sus nombres exactos y valores default."},
    {"id": "Y20", "type": "parallel_call",
     "query": "En query/pipeline.py, cuando el routing decide intent==parallel, se usa asyncio para ejecutar route_parallel(). Escribe la llamada exacta incluyendo los argumentos pasados a route_parallel()."},
]

SYSTEM_INSTR = (
    "Eres experto en Python y sistemas de recuperacion de informacion. "
    "Responde en espanol. Da los nombres EXACTOS de funciones, parametros y valores. "
    "Si no tienes informacion especifica del codigo, di 'No tengo acceso a ese fichero'."
)

# ---------------------------------------------------------------------------
# Runner COMPLETO
# ---------------------------------------------------------------------------
def _run_complete(cmd, cwd, env, timeout=180) -> str:
    try:
        result = subprocess.run(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, cwd=cwd, env=env, timeout=timeout,
        )
        return result.stdout.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired as e:
        return (e.stdout or b"").decode("utf-8", errors="replace")
    except Exception:
        return ""

def _parse_json_output(stdout: str) -> tuple[str, int, int]:
    text_parts = []
    total_input = total_output = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
            ev_type = ev.get("type", "")
            if ev_type == "text":
                part = ev.get("part", {})
                if isinstance(part, dict):
                    text_parts.append(part.get("text", ""))
            elif ev_type == "assistant":
                for part in ev.get("content", []):
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
            elif ev_type == "step_finish":
                toks = ev.get("part", {}).get("tokens", {})
                out = toks.get("output", 0) + toks.get("reasoning", 0)
                inp = toks.get("total", 0) - out
                if inp > 0 or out > 0:
                    total_output += out
                    total_input  += inp
        except Exception:
            pass
    seen = set()
    unique_parts = []
    for part in text_parts:
        if part not in seen:
            seen.add(part)
            unique_parts.append(part)
    return "".join(unique_parts).strip(), total_input, total_output

def _judge_fn(prompt: str) -> str:
    resp = LLM.chat.completions.create(
        model=MODEL, messages=[{"role": "user", "content": prompt}],
        temperature=0.0, max_tokens=5,
    )
    return resp.choices[0].message.content or ""

def judge_with_truth(answer: str, ground_truth: str, criterios: list[str]) -> bool:
    crit_str = ", ".join(criterios)
    prompt = (
        f"Evalua si la siguiente respuesta es correcta.\n\n"
        f"Ground truth:\n{ground_truth}\n\n"
        f"Criterios (al menos 60% deben aparecer): {crit_str}\n\n"
        f"Respuesta:\n{answer[:3000]}\n\n"
        "Responde solo 'OK' si correcta. 'FAIL' si no."
    )
    return "OK" in _judge_fn(prompt).upper()

# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------
def run_leo(query: str, task_id: str) -> dict:
    t0 = time.time()
    stdout = _run_complete(
        [BUN, "run", "--conditions=browser", "src/index.ts",
         "run", query, "--format", "json", "--model", "deepseek/deepseek-chat",
         "--dangerously-skip-permissions"],
        cwd=LEO_SRC, env=_BUN_ENV, timeout=TIMEOUT_LEO,
    )
    latency = round(time.time() - t0, 3)
    respuesta, inp, out = _parse_json_output(stdout)
    if not respuesta and inp == 0:
        time.sleep(2)
        stdout2 = _run_complete(
            [BUN, "run", "--conditions=browser", "src/index.ts",
             "run", query, "--format", "json", "--model", "deepseek/deepseek-chat",
             "--dangerously-skip-permissions"],
            cwd=LEO_SRC, env=_BUN_ENV, timeout=TIMEOUT_LEO,
        )
        respuesta, inp, out = _parse_json_output(stdout2)
        latency = round(time.time() - t0, 3)
    (RUNS_DIR / f"leo_{task_id}.json").write_text(
        json.dumps({"query": query, "response": respuesta[:600],
                    "input_tokens": inp, "output_tokens": out},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return {"respuesta": respuesta, "input_tokens": inp, "output_tokens": out, "latency_s": latency}

def run_opencode_wsl(query: str, task_id: str) -> dict:
    t0 = time.time()
    env = {**_WSL_ENV, "OC_QUERY": query}
    bash_cmd = (
        f'cd "{WSL_REPO}" && '
        'opencode run "$OC_QUERY" '
        '--format json '
        '--model deepseek/deepseek-chat '
        '--dangerously-skip-permissions 2>/dev/null'
    )
    stdout = _run_complete(
        ["wsl", "-d", "Ubuntu", "bash", "-c", bash_cmd],
        cwd=None, env=env, timeout=TIMEOUT_OC,
    )
    latency = round(time.time() - t0, 3)
    respuesta, inp, out = _parse_json_output(stdout)
    (RUNS_DIR / f"oc_{task_id}.json").write_text(
        json.dumps({"query": query, "response": respuesta[:600],
                    "input_tokens": inp, "output_tokens": out},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return {"respuesta": respuesta, "input_tokens": inp, "output_tokens": out, "latency_s": latency}

def run_no_ctx(query: str) -> dict:
    t0 = time.time()
    try:
        resp = LLM.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_INSTR},
                {"role": "user", "content": query},
            ],
            temperature=TEMPERATURE, max_tokens=1024,
        )
        answer = resp.choices[0].message.content or ""
        inp, out = resp.usage.prompt_tokens, resp.usage.completion_tokens
    except Exception as e:
        answer, inp, out = f"Error: {e}", 0, 0
    return {"respuesta": answer, "input_tokens": inp, "output_tokens": out,
            "latency_s": round(time.time() - t0, 3)}

# ---------------------------------------------------------------------------
# Task runner
# ---------------------------------------------------------------------------
def run_task(task: dict) -> dict:
    tid   = task["id"]
    query = task["query"]
    ev    = _EVAL[tid]
    crit, truth = ev["c"], ev["gt"]
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_leo = ex.submit(run_leo, query, tid)
        f_oc  = ex.submit(run_opencode_wsl, query, tid)
        f_nc  = ex.submit(run_no_ctx, query)
        r_leo, r_oc, r_nc = f_leo.result(), f_oc.result(), f_nc.result()

    def _score(r):
        ans = r["respuesta"]
        return {
            "tokens":   r["input_tokens"] + r["output_tokens"],
            "latency":  r["latency_s"],
            "criteria": score_answer(ans, crit)["score"] if ans else 0.0,
            "judge":    judge_with_truth(ans, truth, crit) if ans else False,
            "answer":   ans[:300],
        }
    return {"id": tid, "type": task["type"], "query": query,
            "leo": _score(r_leo), "opencode": _score(r_oc), "no_ctx": _score(r_nc)}

def compute_and_print(results: list[dict], label: str = "") -> dict:
    modes = ("leo", "opencode", "no_ctx")
    total = {m: 0 for m in modes}
    lat   = {m: 0.0 for m in modes}
    crit  = {m: [] for m in modes}
    judge = {m: 0 for m in modes}
    n     = len(results)
    for r in results:
        for m in modes:
            total[m] += r[m]["tokens"]
            lat[m]   += r[m]["latency"]
            crit[m].append(r[m]["criteria"])
            judge[m] += int(r[m]["judge"])
    avg_crit = {m: statistics.mean(crit[m]) for m in modes}
    m_data = {
        "n_tasks": n, "total_tokens": total,
        "latency": {m: round(lat[m], 2) for m in modes},
        "avg_criteria": {m: round(avg_crit[m], 3) for m in modes},
        "judge_ok": judge,
        "leo_vs_oc_criteria":    round(avg_crit["leo"] - avg_crit["opencode"], 3),
        "leo_vs_noctx_criteria": round(avg_crit["leo"] - avg_crit["no_ctx"], 3),
        "leo_judge_vs_oc":       judge["leo"] - judge["opencode"],
        "leo_judge_vs_noctx":    judge["leo"] - judge["no_ctx"],
    }
    W = 119
    print("\n" + "=" * W)
    print(f"  BENCHMARK v4 HARD — leo-code KC-RAG vs opencode CLI  {label}")
    print(f"  Target: {LEO_REPO} | 20 tareas cross-module | Criterios: codificados (no contaminacion)")
    print("=" * W)
    tk, lk, ac, jk = m_data["total_tokens"], m_data["latency"], m_data["avg_criteria"], m_data["judge_ok"]
    print(f"\n  {'Metrica':<48} {'leo-code':>10} {'opencode':>10} {'no-ctx':>8}")
    print(f"  {'-'*78}")
    print(f"  {'Tokens totales':<48} {tk['leo']:>10,} {tk['opencode']:>10,} {tk['no_ctx']:>8,}")
    print(f"  {'Latencia total (s)':<48} {lk['leo']:>10.1f} {lk['opencode']:>10.1f} {lk['no_ctx']:>8.1f}")
    print(f"  {'Criteria avg':<48} {ac['leo']:>9.1%} {ac['opencode']:>10.1%} {ac['no_ctx']:>8.1%}")
    print(f"  {'LLM judge OK':<48} {jk['leo']:>9}/{n} {jk['opencode']:>9}/{n} {jk['no_ctx']:>6}/{n}")
    print(f"  {'Leo vs opencode (criteria)':<48} {m_data['leo_vs_oc_criteria']:>+10.1%}")
    print(f"  {'Leo vs no-ctx   (criteria)':<48} {m_data['leo_vs_noctx_criteria']:>+10.1%}")
    print(f"  {'Leo vs opencode (judge)':<48} {m_data['leo_judge_vs_oc']:>+10}")
    print()
    print(f"  {'ID':<6} {'Tipo':<18} {'Pregunta':<38} {'LEOc':>5} {'OCc':>5} {'NCc':>5} {'LEOj':>5} {'OCj':>5} {'LEOtok':>8} {'OCtok':>8}")
    print(f"  {'-'*109}")
    for r in results:
        qshort = r["query"][:36]
        lc = f"{r['leo']['criteria']:.0%}"
        oc = f"{r['opencode']['criteria']:.0%}"
        nc = f"{r['no_ctx']['criteria']:.0%}"
        lj = "OK" if r["leo"]["judge"] else "--"
        oj = "OK" if r["opencode"]["judge"] else "--"
        print(f"  {r['id']:<6} {r['type']:<18} {qshort:<38} {lc:>5} {oc:>5} {nc:>5} {lj:>5} {oj:>5} {r['leo']['tokens']:>8,} {r['opencode']['tokens']:>8,}")
    print()
    leo_wins_oc   = m_data["leo_vs_oc_criteria"] > 0
    leo_wins_nc   = m_data["leo_vs_noctx_criteria"] > 0
    leo_judge_win = m_data["leo_judge_vs_oc"] >= 0
    print(f"  --- Resultado ---")
    print(f"  Leo > opencode criteria: {'SI' if leo_wins_oc else 'NO'} ({m_data['leo_vs_oc_criteria']:+.1%})")
    print(f"  Leo > no-ctx criteria:   {'SI' if leo_wins_nc else 'NO'} ({m_data['leo_vs_noctx_criteria']:+.1%})")
    print(f"  Leo >= opencode judge:   {'SI' if leo_judge_win else 'NO'} ({m_data['leo_judge_vs_oc']:+d}/{n})")
    all_win = leo_wins_oc and leo_wins_nc and leo_judge_win
    print(f"  LEO GANA TODO:           {'[WIN]' if all_win else '[FAIL]'}")
    return {**m_data, "tasks": results, "leo_wins_all": all_win}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    n  = len(TASKS)
    print(f"\n[{ts}] Python RAG Benchmark v4: {n} tareas | leo-code vs opencode")
    print(f"  Tareas cross-module, criterios codificados (no contaminacion posible)")
    print(f"  Target: {LEO_REPO}")

    try:
        r = httpx.get(f"{SIDECAR}/health", timeout=5).json()
        print(f"  KC-RAG sidecar: {r}")
    except Exception as e:
        print(f"  KC-RAG ERROR: {e}")
        sys.exit(1)
    try:
        ri = httpx.post(f"{SIDECAR}/index", json={"repo_path": LEO_REPO}, timeout=60).json()
        print(f"  [index] KC-RAG: {ri}")
    except Exception as e:
        print(f"  [index] ERROR: {e}")

    import subprocess as _sp
    try:
        ov = _sp.run(["wsl", "-d", "Ubuntu", "opencode", "--version"],
                     capture_output=True, text=True, timeout=10).stdout.strip()
        print(f"  opencode WSL: {ov}")
    except Exception as e:
        print(f"  opencode WSL: ERROR {e}")

    print(f"\n  [Benchmark] {n} tareas x 3 modos en paralelo...")
    results = []
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = {ex.submit(run_task, t): t for t in TASKS}
        for fut in as_completed(futs):
            r = fut.result()
            lj = "OK" if r["leo"]["judge"] else "--"
            oj = "OK" if r["opencode"]["judge"] else "--"
            print(f"  [done] {r['id']} ({r['type']}) leo={r['leo']['criteria']:.0%}({lj},{r['leo']['tokens']}tok) oc={r['opencode']['criteria']:.0%}({oj},{r['opencode']['tokens']}tok)")
            results.append(r)
    results.sort(key=lambda r: r["id"])

    m = compute_and_print(results, label=f"[{ts}]")
    out_path = Path(__file__).parent / "pyrag_v4_results.json"
    out_path.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Guardado: {out_path}")
    print(f"  LEO_WINS_ALL: {m['leo_wins_all']}")
    return m

if __name__ == "__main__":
    m = main()
    sys.exit(0 if m["leo_wins_all"] else 1)
