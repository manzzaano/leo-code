"""Tests: instincts / aprendizaje continuo — confidence bidireccional + gate + scope."""

from leo_code.learning import (
    AUTONOMOUS_GATE,
    CONF_START,
    InstinctStore,
)


def _store(tmp_path, project="repoA"):
    return InstinctStore(base_dir=str(tmp_path), project_id=project)


def test_reinforce_creates_and_raises_confidence(tmp_path):
    s = _store(tmp_path)
    i1 = s.reinforce("ejecutar tests", "usa pytest -q")
    assert i1.confidence == CONF_START
    i2 = s.reinforce("ejecutar tests", "usa pytest -q")
    assert i2.confidence > i1.confidence
    assert i2.evidence == 2


def test_confidence_caps_at_max(tmp_path):
    s = _store(tmp_path)
    for _ in range(20):
        inst = s.reinforce("t", "a")
    assert inst.confidence <= 0.9


def test_penalize_lowers_confidence(tmp_path):
    s = _store(tmp_path)
    for _ in range(5):
        s.reinforce("t", "a")          # sube
    before = s.reinforce("t", "a").confidence
    after = s.penalize("t", "a").confidence
    assert after < before


def test_gate_autonomous_vs_suggestion(tmp_path):
    s = _store(tmp_path)
    inst = s.reinforce("t", "a")
    assert not inst.applies()           # 0.3 < gate
    for _ in range(6):
        inst = s.reinforce("t", "a")
    assert inst.confidence >= AUTONOMOUS_GATE
    assert inst.applies()


def test_relevant_filters_by_overlap_and_confidence(tmp_path):
    s = _store(tmp_path)
    s.reinforce("correr los tests del proyecto", "usa pytest -q")
    s.reinforce("formatear codigo python", "usa black")
    hits = s.relevant("como corro los tests")
    assert any("pytest" in h.action for h in hits)
    assert all("black" not in h.action for h in hits)


def test_inject_block_tags(tmp_path):
    s = _store(tmp_path)
    for _ in range(6):
        s.reinforce("desplegar la app", "usa el script deploy.sh")
    block = s.inject_block("como desplegar")
    assert "[auto]" in block
    assert "deploy.sh" in block


def test_promotion_to_global_across_projects(tmp_path):
    sa = _store(tmp_path, "repoA")
    sa.reinforce("patron comun", "haz X")
    sb = _store(tmp_path, "repoB")
    sb.reinforce("patron comun", "haz X")   # 2º proyecto → promueve a global
    g = sb._load("global")
    assert any(i.action == "haz X" for i in g.values())


def test_observe_writes_jsonl(tmp_path):
    s = _store(tmp_path)
    s.observe({"tool": "read_file", "args": {"file_path": "a.py"}})
    obs = s._obs_path().read_text(encoding="utf-8").strip().splitlines()
    assert len(obs) == 1
    assert "read_file" in obs[0]


def test_mine_observations_creates_instinct(tmp_path):
    s = _store(tmp_path)
    for _ in range(3):
        s.observe({"tool": "find_symbol", "ok": True})
    s.observe({"tool": "read_file", "ok": False})  # error, no cuenta
    learned = s.mine_observations(trigger="buscar simbolo", min_count=3)
    assert any("find_symbol" in i.action for i in learned)
    # y queda disponible para inyección
    assert "find_symbol" in s.inject_block("buscar simbolo")


def test_decay_lowers_stale(tmp_path):
    s = _store(tmp_path)
    s.reinforce("viejo", "accion")
    for _ in range(4):
        s.reinforce("viejo", "accion")
    before = s.relevant("viejo")[0].confidence
    s.decay(max_age_s=-1)   # todo se considera viejo
    after = s.relevant("viejo")[0].confidence
    assert after < before
