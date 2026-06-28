"""Regression: el detector de bucles SOLO penaliza la misma tool con args IDÉNTICOS
repetida ≥3×. Misma tool con args distintos nunca colisiona (el bug que se reportó)."""

from leo_code.rag.agent.loop import _loop_key, _LOOP_BLOCK_THRESHOLD


def test_diff_args_diff_key():
    # read_file(calc.py) vs read_file(main.py) → claves DISTINTAS (no se penaliza)
    assert _loop_key("read_file", {"file_path": "calc.py"}) != \
           _loop_key("read_file", {"file_path": "main.py"})
    # read_file(calc.py) vs read_file(calc.py, 1, 50) → distintas
    assert _loop_key("read_file", {"file_path": "calc.py"}) != \
           _loop_key("read_file", {"file_path": "calc.py", "start_line": 1, "end_line": 50})


def test_same_call_stable_key_regardless_of_order():
    assert _loop_key("f", {"a": 1, "b": 2}) == _loop_key("f", {"b": 2, "a": 1})


def test_blocks_only_on_third_identical():
    counts: dict[str, int] = {}

    def call(name, args):
        k = _loop_key(name, args)
        counts[k] = counts.get(k, 0) + 1
        return counts[k] >= _LOOP_BLOCK_THRESHOLD   # True = bloqueado

    assert call("read_file", {"file_path": "a.py"}) is False   # 1ª: permitida
    assert call("read_file", {"file_path": "a.py"}) is False   # 2ª: reintento legítimo
    assert call("read_file", {"file_path": "a.py"}) is True    # 3ª idéntica: bucle → bloqueo
    assert call("read_file", {"file_path": "b.py"}) is False   # otros args: nunca afectados
