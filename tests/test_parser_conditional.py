"""#9: defs bajo if/try/with eran invisibles: sin símbolo y sin sus llamadas."""

from leo_code.core.graphquery import GraphQuery
from leo_code.core.parser import extract_from_python

SRC = """\
def dep(): pass
if X:
    def cond():
        dep()
else:
    def cond():
        dep()
try:
    import fast
except ImportError:
    def fallback():
        dep()
    class Compat:
        def m(self):
            dep()
with ctx():
    def inside():
        dep()
class A:
    if X:
        def method(self):
            dep()
def outer():
    def nested():
        dep()
"""


def test_conditional_defs_are_indexed():
    caps = extract_from_python(SRC, "t.py")
    names = [c.name for c in caps if c.type in ("function", "class", "method")]
    assert names.count("cond") == 2
    assert {"fallback", "Compat", "m", "inside", "method"} <= set(names)
    assert "nested" not in names          # sus llamadas ya suben a `outer`


def test_conditional_def_edges_reach_impact():
    caps = extract_from_python(SRC, "t.py")
    hit = {c.name for c in GraphQuery({c.id: c for c in caps}).impact("dep").cites}
    assert {"cond", "fallback", "m", "inside", "method"} <= hit


def test_class_lists_conditional_methods():
    caps = extract_from_python(SRC, "t.py")
    assert "method" in next(c for c in caps if c.name == "A").properties["metodos"]
