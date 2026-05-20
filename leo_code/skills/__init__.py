"""AutoSkill System — skills markdown con YAML frontmatter que se auto-activan.

Los skills son instrucciones especializadas para el LLM en formato markdown.
Se cargan desde leo-code/skills/, ~/.leo-code/skills/, y leo_code/skills/builtin/.

Auto-activación por:
- Task type (si el skill especifica task_types que coinciden con el classifier)
- Triggers regex (si la query matchea alguno de los patterns)
- File context (si los archivos del repo matchean extensiones)

Uso:
    sm = SkillManager()
    sm.load_skills(repo_path=".")
    matched = sm.match(query="escribe tests para UserService", task_type="test_gen")
    sm.inject(matched, messages)
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    version: str = "1.0"
    triggers: list[str] = field(default_factory=list)
    task_types: list[str] = field(default_factory=list)
    file_extensions: list[str] = field(default_factory=list)
    preferred_model: str = ""
    tools_required: list[str] = field(default_factory=list)
    context_boost: dict = field(default_factory=dict)
    priority: int = 5
    body: str = ""
    source: str = ""  # "builtin", "project", "global"


class SkillManager:
    def __init__(self):
        self._skills: list[Skill] = []
        self._loaded = False

    def load_skills(self, repo_path: str = "."):
        if self._loaded:
            return
        paths = [
            (Path(__file__).parent / "builtin", "builtin"),
            (Path(repo_path) / "leo-code" / "skills", "project"),
            (Path.home() / ".leo-code" / "skills", "global"),
        ]
        for base, source in paths:
            if base.exists():
                for md_file in sorted(base.rglob("*.md")):
                    try:
                        skill = _parse_skill_file(md_file)
                        if skill:
                            skill.source = source
                            self._skills.append(skill)
                    except Exception:
                        pass
        self._skills.sort(key=lambda s: -s.priority)
        self._loaded = True

    def match(self, query: str, task_type: str = "",
              file_context: list[str] | None = None) -> list[Skill]:
        matched = []
        qlower = query.lower()
        for skill in self._skills:
            score = 0
            # Task type match: highest weight
            if task_type and task_type in skill.task_types:
                score += 100
            # Trigger match: regex or substring
            for trigger in skill.triggers:
                try:
                    if re.search(trigger, qlower, re.IGNORECASE):
                        score += 50
                        break
                except re.error:
                    if trigger.lower() in qlower:
                        score += 50
                        break
            # File context match
            if file_context and skill.file_extensions:
                exts = [f.replace(".", "").lower() for f in file_context]
                if any(ext in skill.file_extensions for ext in exts):
                    score += 30
            if score > 0:
                matched.append((score, skill))
        matched.sort(key=lambda x: -x[0])
        return [s for _, s in matched[:3]]  # max 3 skills para no saturar contexto

    def inject(self, matched: list[Skill], messages: list[dict]):
        for skill in matched:
            prompt = f"[Skill: {skill.name}] {skill.body[:2000]}"
            messages.append({"role": "system", "content": prompt})

    def list_all(self) -> list[Skill]:
        return self._skills


def _parse_skill_file(filepath: Path) -> Skill | None:
    text = filepath.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    frontmatter = parts[1].strip()
    body = parts[2].strip()

    import yaml
    try:
        meta = yaml.safe_load(frontmatter) or {}
    except Exception:
        meta = {}
        for line in frontmatter.split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()

    return Skill(
        name=meta.get("name", filepath.stem),
        description=meta.get("description", ""),
        version=str(meta.get("version", "1.0")),
        triggers=meta.get("triggers") or [],
        task_types=meta.get("task_types") or [],
        file_extensions=meta.get("file_extensions") or [],
        preferred_model=meta.get("preferred_model", ""),
        tools_required=meta.get("tools_required") or [],
        context_boost=meta.get("context_boost") or {},
        priority=meta.get("priority", 5),
        body=body,
    )
