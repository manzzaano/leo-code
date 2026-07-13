"""Fix (c) prerequisito: serialize_context no debe aplastar 'content' (cuerpo de
codigo) al cap generico de 120 chars — si no, include_body=True (debug/optimize/
desambiguacion) manda ~120 chars planos en vez del cuerpo real."""

from leo_code.core.context import serialize_context


def test_content_not_flattened_to_120_chars():
    body = "def foo():\n" + "\n".join(f"    x{i} = {i}" for i in range(30))
    assert len(body) > 200
    node = {"id": "n1", "name": "foo", "type": "function",
            "properties": {"content": body, "signature": "def foo()"}}
    out = serialize_context([node])
    assert body in out                       # cuerpo completo presente, no truncado
    assert "```" in out                       # renderizado en bloque de codigo


def test_content_over_8000_chars_gets_truncated_with_marker():
    # Red de seguridad: los productores (compressor) capan antes con body_chars;
    # 8000 aqui solo protege de un productor sin cap.
    body = "x" * 9000
    node = {"id": "n1", "name": "foo", "type": "function", "properties": {"content": body}}
    out = serialize_context([node])
    assert "[truncado]" in out
    assert "x" * 8000 in out
    assert "x" * 8001 not in out


def test_other_properties_still_capped_at_120():
    long_doc = "y" * 300
    node = {"id": "n1", "name": "foo", "type": "function",
            "properties": {"descripcion": long_doc}}
    out = serialize_context([node])
    assert "y" * 300 not in out               # sigue truncado
    assert "..." in out
