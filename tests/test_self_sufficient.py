"""self_sufficient (vía MCP): el contexto incluye cuerpos y no manda a read_file.

Motivación (benchmark M0): el agente MCP llamaba get_context y RELEÍA archivos
igualmente (hasta 15 relecturas/tarea) porque el contexto era firma+docstring.
"""

from leo_code.rag.compressor import compress
from leo_code.core.parser import Capsule


def _cap(name: str, body: str) -> Capsule:
    return Capsule(
        id=name, type="function", name=name, file_path=f"src/{name}.py",
        start_line=1, end_line=50, language="python",
        signature=f"def {name}()", content=body, docstring=f"doc de {name}",
        calls=[], imports=[],
    )


def test_code_edit_self_sufficient_incluye_cuerpo_y_no_manda_a_read_file():
    caps = [_cap("target_fn", "def target_fn():\n    return 42\n" * 30)]
    default = compress(caps, caps, task_type="code_edit")
    ss = compress(caps, caps, task_type="code_edit", self_sufficient=True)

    assert "return 42" not in default          # antes: solo firma+docstring
    assert "read_file" in default              # antes: footer invitaba a releer
    assert "return 42" in ss                   # ahora: cuerpo incluido
    assert "read_file" not in ss               # y sin invitación a releer

    # cuerpos largos: cap 2500 (medido en c5b: respuestas gordas ceban mas
    # exploracion en vez de sustituirla)
    big = [_cap("big_fn", "x = 1\n" * 2000)]  # 12000 chars
    ss_big = compress(big, big, task_type="debug", self_sufficient=True)
    body = ss_big.split("content")[1] if "content" in ss_big else ss_big
    assert 2000 < len(body) < 4000


def test_default_no_cambia_para_agente_nativo():
    caps = [_cap("f", "def f():\n    pass")]
    assert compress(caps, caps, task_type="code_edit") == compress(
        caps, caps, task_type="code_edit", self_sufficient=False)


if __name__ == "__main__":
    test_code_edit_self_sufficient_incluye_cuerpo_y_no_manda_a_read_file()
    test_default_no_cambia_para_agente_nativo()
    print("OK")
