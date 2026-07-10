"""Fast start: con el encoder frío, compute_context NO debe bloquear ~9s cargando
pesos — sirve con las patas estructurales y calienta en background (encoder.py:
Encoder.is_warm/warm_bg; engine.py: gating de vs.search)."""

import threading

from leo_code.rag.encoder import Encoder


def _reset_encoder(monkeypatch):
    monkeypatch.setattr(Encoder, "_warm", False)
    monkeypatch.setattr(Encoder, "_warm_started", False)
    monkeypatch.setattr(Encoder, "_shared", {})


def test_is_warm_false_until_model_loaded(monkeypatch):
    _reset_encoder(monkeypatch)
    assert Encoder.is_warm() is False


def test_model_load_sets_warm_and_shares_across_instances(monkeypatch):
    _reset_encoder(monkeypatch)
    fake = object()
    # inyecta el modelo directamente en el cache compartido (sin cargar 9s de pesos)
    Encoder._shared["all-MiniLM-L6-v2"] = fake
    monkeypatch.setattr(Encoder, "_warm", True)
    a, b = Encoder(), Encoder()
    assert a.model is fake and b.model is fake  # compartido, sin recarga por instancia
    assert Encoder.is_warm() is True


def test_warm_bg_is_idempotent(monkeypatch):
    _reset_encoder(monkeypatch)
    started = []
    class _FakeThread:
        def __init__(self, target=None, daemon=None):
            started.append(target)
        def start(self):
            pass
    monkeypatch.setattr(threading, "Thread", _FakeThread)
    Encoder.warm_bg()
    Encoder.warm_bg()  # segunda llamada: no lanza otro thread
    assert len(started) == 1
    # y con el encoder ya caliente, tampoco
    monkeypatch.setattr(Encoder, "_warm", True)
    monkeypatch.setattr(Encoder, "_warm_started", False)
    Encoder.warm_bg()
    assert len(started) == 1
