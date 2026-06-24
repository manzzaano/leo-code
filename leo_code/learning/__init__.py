"""Aprendizaje continuo / instincts (ECC continuous-learning-v2).

Mecanismo:
- Observación en tool boundaries → `observations.jsonl` por scope.
- Instincts (patrones reutilizables) con **confidence bidireccional** (0.3–0.9):
  sube por recurrencia/aceptación, baja por corrección/desuso (decay).
- Gate de aplicación: <0.7 = sugerir; ≥0.7 = aplicar autónomo.
- Almacén YAML scoped: project (por repo) y global. Promoción a global si el
  patrón aparece en ≥2 proyectos.

Sin LLM en el core: la extracción de patrones repetitivos es determinista. Un
extractor LLM puede añadirse como hook, pero no es necesario para operar.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

import yaml

CONF_MIN = 0.3
CONF_MAX = 0.9
CONF_START = 0.3
CONF_REINFORCE = 0.1
CONF_PENALTY = 0.2
CONF_DECAY = 0.05
AUTONOMOUS_GATE = 0.7  # ≥ → aplicar; < → solo sugerir


def _clamp(v: float) -> float:
    return max(0.0, min(CONF_MAX, v))


def _instinct_id(trigger: str, action: str) -> str:
    return hashlib.sha256(f"{trigger}|{action}".encode()).hexdigest()[:12]


@dataclass
class Instinct:
    id: str
    trigger: str            # texto/keywords que disparan el patrón
    action: str             # guía a inyectar
    scope: str = "project"  # project | global
    confidence: float = CONF_START
    evidence: int = 1
    projects: list[str] = field(default_factory=list)
    created_at: float = 0.0
    last_seen: float = 0.0

    def applies(self) -> bool:
        return self.confidence >= AUTONOMOUS_GATE


class InstinctStore:
    """Almacén de instincts con confidence. YAML scoped project/global."""

    def __init__(self, base_dir: str, project_id: str = "default"):
        self.base = Path(base_dir)
        self.project_id = project_id
        self.proj_dir = self.base / "projects" / _hash(project_id)
        self.proj_dir.mkdir(parents=True, exist_ok=True)
        (self.base / "global").mkdir(parents=True, exist_ok=True)

    # ── paths ──
    def _yaml_path(self, scope: str) -> Path:
        if scope == "global":
            return self.base / "global" / "instincts.yaml"
        return self.proj_dir / "instincts.yaml"

    def _obs_path(self) -> Path:
        return self.proj_dir / "observations.jsonl"

    # ── observación ──
    def observe(self, event: dict) -> None:
        """Registra un evento (tool call/prompt) en observations.jsonl."""
        event = {**event, "ts": time.time(), "project": self.project_id}
        with self._obs_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    # ── persistencia ──
    def _load(self, scope: str) -> dict[str, Instinct]:
        p = self._yaml_path(scope)
        if not p.exists():
            return {}
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or []
        out = {}
        for d in raw:
            out[d["id"]] = Instinct(**d)
        return out

    def _save(self, scope: str, items: dict[str, Instinct]) -> None:
        p = self._yaml_path(scope)
        data = [asdict(i) for i in items.values()]
        p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # ── API de aprendizaje ──
    def reinforce(self, trigger: str, action: str, scope: str = "project") -> Instinct:
        """Crea o refuerza un instinct. Sube confidence y cuenta evidencia.
        Promueve a global si el patrón se ve en ≥2 proyectos."""
        iid = _instinct_id(trigger, action)
        items = self._load(scope)
        now = time.time()
        inst = items.get(iid)
        if inst is None:
            inst = Instinct(id=iid, trigger=trigger, action=action, scope=scope,
                            confidence=CONF_START, evidence=1,
                            projects=[self.project_id], created_at=now, last_seen=now)
        else:
            inst.confidence = _clamp(inst.confidence + CONF_REINFORCE)
            inst.evidence += 1
            inst.last_seen = now
            if self.project_id not in inst.projects:
                inst.projects.append(self.project_id)
        items[iid] = inst
        self._save(scope, items)
        # Ledger global cross-proyecto: acumula qué proyectos han visto el patrón.
        # Solo se "promueve" (aplica a otros repos) con ≥2 proyectos — ver relevant().
        if scope == "project":
            self._track_global(inst)
        return inst

    def penalize(self, trigger: str, action: str, scope: str = "project") -> Optional[Instinct]:
        """Baja la confidence de un instinct (corrección del usuario)."""
        iid = _instinct_id(trigger, action)
        items = self._load(scope)
        inst = items.get(iid)
        if inst is None:
            return None
        inst.confidence = _clamp(inst.confidence - CONF_PENALTY)
        items[iid] = inst
        self._save(scope, items)
        return inst

    def decay(self, scope: str = "project", max_age_s: float = 0.0) -> None:
        """Reduce confidence de instincts no vistos recientemente (desuso)."""
        items = self._load(scope)
        now = time.time()
        for inst in items.values():
            if max_age_s and (now - inst.last_seen) > max_age_s:
                inst.confidence = _clamp(inst.confidence - CONF_DECAY)
        self._save(scope, items)

    def _track_global(self, inst: Instinct) -> None:
        """Upsert al ledger global acumulando los proyectos que han visto el patrón."""
        g = self._load("global")
        existing = g.get(inst.id)
        if existing is None:
            g[inst.id] = Instinct(**{**asdict(inst), "scope": "global"})
        else:
            for pid in inst.projects:
                if pid not in existing.projects:
                    existing.projects.append(pid)
            existing.confidence = max(existing.confidence, inst.confidence)
            existing.evidence += 1
            existing.last_seen = inst.last_seen
        self._save("global", g)

    def mine_observations(self, trigger: str, min_count: int = 3) -> list[Instinct]:
        """Extracción determinista: tools usadas ≥min_count veces con éxito en las
        observaciones se convierten en un instinct reforzado bajo `trigger`.
        (Hook LLM para patrones más ricos: correcciones/errores — futuro.)"""
        p = self._obs_path()
        if not p.exists():
            return []
        counts: dict[str, int] = {}
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("ok") and ev.get("tool"):
                counts[ev["tool"]] = counts.get(ev["tool"], 0) + 1
        learned = []
        for tool, n in counts.items():
            if n >= min_count:
                action = f"Para '{trigger[:40]}', la herramienta '{tool}' suele resolver."
                learned.append(self.reinforce(trigger, action))
        return learned

    # ── recuperación / inyección ──
    def relevant(self, query: str, min_confidence: float = CONF_START) -> list[Instinct]:
        """Instincts (project+global) cuyo trigger solapa con la query, ordenados
        por confidence desc. Filtra por confidence mínima."""
        from leo_code.rag.scorer import tokenize
        q = set(tokenize(query or ""))
        if not q:
            return []
        merged: dict[str, Instinct] = {}
        # global: solo instincts promovidos (vistos en ≥2 proyectos) aplican cross-repo.
        for inst in self._load("global").values():
            if len(inst.projects) >= 2:
                merged[inst.id] = inst
        # project pisa global (más específico) e incluye los propios aún no promovidos.
        for inst in self._load("project").values():
            merged[inst.id] = inst
        hits = []
        for inst in merged.values():
            if inst.confidence < min_confidence:
                continue
            if q & set(tokenize(inst.trigger)):
                hits.append(inst)
        hits.sort(key=lambda i: i.confidence, reverse=True)
        return hits

    def inject_block(self, query: str) -> str:
        """Bloque de texto con instincts relevantes para meter en el prompt.
        Marca [auto] (≥gate) vs [sugerencia] (<gate). Vacío si no hay."""
        hits = self.relevant(query)
        if not hits:
            return ""
        lines = ["Instincts aprendidos (de uso previo):"]
        for inst in hits:
            tag = "auto" if inst.applies() else "sugerencia"
            lines.append(f"- [{tag}] {inst.action}")
        return "\n".join(lines)


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]
