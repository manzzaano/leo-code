from leo_code.session.compactor import compact_history


def _msg(text: str) -> dict:
    return {"role": "user", "content": text}


def _msgs(n: int) -> list[dict]:
    return [_msg(f"mensaje numero {i}") for i in range(n)]


class TestCompactHistory:
    def test_vacio(self):
        assert compact_history([]) == []

    def test_10_mensajes_sin_compactar(self):
        msgs = _msgs(10)
        result = compact_history(msgs, max_messages=30)
        assert result is msgs

    def test_50_mensajes_se_compacta(self):
        msgs = _msgs(50)
        result = compact_history(msgs, max_messages=30)
        assert result is not msgs
        assert len(result) < 30
        assert result[0]["role"] == "system"
        assert "[Resumen de conversacion anterior]" in result[0]["content"]
        assert "Mensajes omitidos" in result[0]["content"]
