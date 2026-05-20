"""LLM Judge — evalúa respuestas del benchmark con criterios objetivos.

Evalúa cada respuesta en 4 dimensiones (1-10):
- relevancia: ¿aborda exactamente lo pedido?
- correccion: ¿es técnicamente correcto?
- completitud: ¿cubre todos los aspectos?
- accionabilidad: ¿se puede ejecutar/implementar directamente?
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

JUDGE_SYSTEM = """Eres un juez experto en código y agentes de programación. Evalúas respuestas de agentes 
de código contra criterios objetivos. Sé estricto pero justo. 
Responde SOLO con JSON: {"relevancia": N, "correccion": N, "completitud": N, "accionabilidad": N}
donde N es un entero de 1 a 10."""


def judge(response: str, task: dict, model: str = "deepseek/deepseek-v4-flash") -> dict:
    """Evalúa una respuesta contra los criterios de la tarea."""
    if not response or len(response) < 10:
        return {"relevancia": 1, "correccion": 1, "completitud": 1, "accionabilidad": 1, "error": "empty_response"}

    prompt = f"""Evalúa esta respuesta de un agente de código para la siguiente tarea.

TAREA: {task['query']}

CRITERIOS DE EVALUACIÓN: {task['judge_criteria']}

RESPUESTA DEL AGENTE:
{response[:4000]}

Evalúa la respuesta en 4 dimensiones (1-10):
1. Relevancia: ¿La respuesta aborda EXACTAMENTE lo pedido? ¿O se va por las ramas?
2. Corrección: ¿La respuesta es técnicamente correcta? ¿Hay errores factuales?
3. Completitud: ¿Cubre TODOS los aspectos mencionados en los criterios?
4. Accionabilidad: ¿Se puede ejecutar o implementar directamente? ¿O es vaga?

Responde SOLO con JSON. No añadas texto antes ni después."""

    try:
        from leo_code.rag.llm import get_provider
        provider = get_provider("openai",
            api_key=os.getenv("DEEPSEEK_API_KEY", os.getenv("OPENAI_API_KEY", "")),
            base_url="https://api.deepseek.com",
            model="deepseek-chat")

        import asyncio
        async def _eval():
            resp = await provider.generate(
                [{"role": "system", "content": JUDGE_SYSTEM},
                 {"role": "user", "content": prompt}],
                tools=[], temperature=0.1,
            )
            text = resp.text or "{}"
            try:
                return json.loads(text.strip().strip("`").strip("json").strip())
            except json.JSONDecodeError:
                nums = {}
                for dim in ["relevancia", "correccion", "completitud", "accionabilidad"]:
                    import re
                    m = re.search(rf'"{dim}"\s*:\s*(\d+)', text)
                    if m:
                        nums[dim] = int(m.group(1))
                return nums if len(nums) == 4 else {"relevancia": 5, "correccion": 5, "completitud": 5, "accionabilidad": 5}

        return asyncio.run(_eval())
    except Exception as e:
        return {"relevancia": 5, "correccion": 5, "completitud": 5, "accionabilidad": 5, "error": str(e)}


def score_summary(scores: dict) -> float:
    """Score compuesto 0-10."""
    weights = {"relevancia": 0.30, "correccion": 0.30, "completitud": 0.25, "accionabilidad": 0.15}
    total = 0
    for dim, w in weights.items():
        total += scores.get(dim, 0) * w
    return round(total, 2)


if __name__ == "__main__":
    tasks = json.loads(Path("benchmark/tasks.json").read_text())
    print(f"Judge ready: {len(tasks)} tasks")
