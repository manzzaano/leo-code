# Resolución de llamadas: a qué función va cada llamada

Investigación del 19/10/2026. Pregunta: el 100% de la auditoría (a) mide que leo
anota todas las llamadas escritas, pero no si sabe **a qué definición** va cada una.
¿Cómo lo resuelve el estado del arte y qué debe hacer leo?

## 1. Dónde está leo hoy (medido)

- El parser Python guarda cada llamada como un **nombre suelto**: `obj.save()` queda
  como `save` y se pierde el receptor (`leo_code/core/parser.py:37-49`). TS/JS igual
  (`parser_ts.py:67`).
- `GraphQuery` une llamada y definición **por nombre** (`graphquery.py:119`). Con
  nombres únicos es exacto; con nombres repetidos devuelve todos los homónimos.
- Los imports ya se parsean (`parser.py:66-85`), pero no se usan para resolver.
- El oráculo (a) compara nombres sueltos contra nombres sueltos, así que no puede
  ver este problema.

Llamadas a funciones del propio repo que caen en un nombre repetido:

| Repo | Llamadas internas | Con nombre repetido |
|---|---|---|
| NEXUS | 259 | 16 (6%) |
| leo-code | 2.821 | 688 (24%) |

Forma de esas llamadas (leo_code, 330 llamadas a nombres repetidos, medido con `ast`):

| Forma | % | Qué hace falta para resolverla |
|---|---|---|
| `obj.foo()` | 55% | Saber el tipo de `obj` |
| `foo()` | 15% | Ámbito del archivo + imports |
| `self.foo()` | 15% | Clase actual + herencia |
| `modulo.foo()` | 11% | Imports |
| `super().foo()` | 5% | Herencia (MRO) |

## 2. Estado del arte

| Enfoque | Ejemplo | Resultado medido | Estado | Lo que aprendemos |
|---|---|---|---|---|
| Por nombre (búsqueda) | Sourcegraph search-based, ctags | Falla más con nombres comunes (`Get`), lo dicen sus docs | En uso | Es lo que hace leo hoy. Sourcegraph enseña primero lo preciso y después lo aproximado |
| Ámbitos + grafo de asignaciones, sin flujo | PyCG (ICSE 2021) | 99,2% precisión, 69,9% recall en 5 proyectos reales; 111/112 micro-tests completos | Archivado (nov. 2023) | Ámbitos, imports con alias, MRO y `__init__` dan casi toda la precisión. Ignora `if`/bucles y tipos de builtins |
| Igual + sensible al flujo | Jarvis (2023) | Precisión 0,99 y recall 0,82 (PyCG 0,76) en 6 proyectos | Código publicado, sin señales de mantenimiento | El flujo sube el recall unos 6 puntos con mucha más complejidad |
| Grafos de nombres sobre tree-sitter | GitHub stack graphs | Movía la navegación precisa de GitHub en Python y TS | Archivado (sep. 2025) | Incremental por archivo, como el índice de leo. Depender de él es heredar un proyecto muerto |
| Comprobador de tipos completo | Pyright → scip-python (Sourcegraph); `tsc` | Calidad de IDE | Mantenido | Sirve de juez. Meterlo en el producto añade Node y segundos por índice |
| LLM | Estudio de 2024 sobre Python y JS | PyCG supera a los LLM construyendo grafos de llamadas | — | Descartado: además leo no llama a ningún LLM |

Fallos comunes incluso en PyCG y Jarvis: funciones guardadas en listas o diccionarios,
`getattr`/`eval`, módulos nativos (`.so`). PyCG además se quedó sin memoria en 3 de 9
proyectos grandes según el artículo de Jarvis.

## 3. Conclusiones aplicables a leo

1. **No hace falta un análisis completo como PyCG.** Su precisión sale sobre todo de
   tres cosas baratas: ámbitos por archivo, imports con alias y jerarquía de clases
   con MRO. Su punto fijo entre funciones es lo que lo hace lento y lo que lo tumbó
   en proyectos grandes, y leo tiene un presupuesto de ≤20 µs/símbolo por edición
   (gate (e)) y <50 ms por consulta (gate (d)).
2. **Hay que guardar la forma de la llamada**, no solo el nombre: `foo`, `m.foo`,
   `self.foo`, `super().foo`, `x.foo`. Sin eso no se puede resolver nada.
3. **Lo que no se resuelva se queda por nombre y se marca.** Igual que Sourcegraph:
   primero lo exacto, después lo aproximado. Nunca se tira una arista; `impact` y
   `guard` siguen sin perder dependientes.
4. **Tipos locales baratos para parte de `obj.foo()`:** `x = Clase()` en la misma
   función y anotaciones de tipo (`def f(repo: Repo)`). No se hace inferencia entre
   funciones.
5. **El juez tiene que ser externo y con verdad conocida.** Hoy no hay ninguno.

## 4. Propuesta

**Fase 0, el juez (antes de tocar el motor):**
- Oráculo (f) de resolución con dos fuentes:
  - el micro-benchmark de PyCG (112 programas con su grafo hecho a mano, Apache-2.0),
    para saber qué categorías resuelve leo;
  - Pyright/scip-python sobre django, sympy, leo-code y NEXUS, para medir a escala
    qué porcentaje de callers es correcto.
- Medir la línea base de hoy. Si sale alta en proyectos reales, la fase 1 se recorta.

**Fase 1, resolución en Python (TDD, sin dependencias nuevas):**
1. Forma de la llamada en la cápsula.
2. Ámbito por archivo: definiciones locales e imports (alias y relativos).
3. `self`/`cls`/`super()` con herencia y MRO; `Clase()` → `Clase.__init__`.
4. Tipos locales: asignación desde un constructor y anotaciones.
5. Cada caller sale marcado como `exacto` o `por nombre`.

**Fase 2, TS/JS:** lo mismo con imports ES y `this`, con `tsc` como juez (ya está en
`benchmark/ts_oracle.js`).

**Criterio para darlo por bueno:** precisión de los callers marcados `exacto` ≥99%
frente al juez; ningún dependiente real perdido (el recall de hoy se mantiene); gates
(d) y (e) en verde. En el README se publican los dos números: anota todas las
llamadas y acierta el destino en X%.

**Descartado:** usar PyCG o Jarvis como dependencia (archivado o sin mantenimiento,
y demasiado lentos para el presupuesto por edición); stack graphs (archivado);
Pyright dentro del producto (Node y segundos por índice); LLM.

## 5. Línea base medida (fase 0, 19/10/2026)

Oráculo (f): `benchmark/resolution_oracle.py`. Se puntúa por sitio de llamada
(caller, línea:columna, destino), porque a nivel de arista dos errores se tapan.

**Micro-benchmark PyCG** (commit `8d5dc40`, 119 programas con grafo hecho a mano):

| | Resultado |
|---|---|
| Tests sin aristas falsas | 114/119 |
| Tests sin aristas perdidas | 101/119 |
| Precisión / recall en las 42 aristas puntuables | 57,7% / 35,7% |
| Fuera de la puntuación | 188 llamadas desde nivel de módulo, 12 con lambdas o funciones anidadas |

Las 27 perdidas son casi todas funciones pasadas como valor (`func(param_func)`,
`kwargs`, `self.f = g`) y métodos implícitos (`__iter__`). Las falsas, homónimos.

**A escala, con jedi 0.19.2 de juez** (muestra fija de 5.000 llamadas en django y sympy;
NEXUS y leo-code enteros):

| Repo | Llamadas juzgadas | Exactas | Precisión | Recall | Destinos perdidos |
|---|---|---|---|---|---|
| NEXUS | 101 | **92,1%** | 92,7% | 100% | 0 |
| leo-code | 1.080 | **81,8%** | 52,5% | 99,4% | 7 |
| sympy (`9b67993`) | 995 | **45,5%** | 8,6% | 99,8% | 2 |
| django (`11af25c`) | 447 | **49,9%** | 3,9% | 99,1% | 4 |

Cómo leerlo:
- **Exactas** = leo da justo el destino correcto, ni más ni menos. Es lo que nota quien
  usa `who_calls`.
- La precisión baja la dominan pocos nombres con muchas definiciones: en leo-code,
  `__init__` aporta 451 de 980 destinos falsos, y `run` y `generate` unos 130 cada uno.
- El recall casi completo confirma que la resolución por nombre no pierde dependientes.
  Lo que pierde son **imports con alias** (`from benchmark.oracle import run as oracle`,
  `hermite_normal_form as _hnf`): todos los perdidos revisados son de este tipo.
- Jedi solo da veredicto en el 9-20% de las llamadas a escala. Del resto, unas 2.000
  por repo las une leo por nombre y nadie las puede juzgar: el número real de exactas
  sobre todas las llamadas no se conoce.

Fallos del juez encontrados y corregidos al medir: jedi devuelve el parámetro cuando se
llama a uno (`f(...)` con `f` parámetro) y caía en la línea del `def`; la muestra no era
reproducible porque el índice no garantiza orden. Con los dos arreglos, django da el
mismo resultado en dos ejecuciones seguidas.

scip-python 0.6.6 no funciona en Windows (`new RegExp(path.sep)` con `\`, y otro error
al indexar NEXUS); WSL no arranca en esta máquina. Por eso el juez a escala es jedi.

## Fuentes

- Salis et al., *PyCG: Practical Call Graph Generation in Python*, ICSE 2021. https://arxiv.org/abs/2103.00587
- Repositorio PyCG (archivado el 26/11/2023). https://github.com/vitsalis/PyCG
- *Jarvis: Scalable and Precise Application-Centered Call Graph Construction for Python*. https://arxiv.org/html/2305.05949v5
- Creager y van Antwerpen, *Stack graphs: Name resolution at scale*, 2023. https://arxiv.org/abs/2211.01224
- Repositorio stack-graphs (archivado el 09/09/2025). https://github.com/github/stack-graphs
- Sourcegraph, *scip-python: a precise Python indexer*. https://sourcegraph.com/blog/scip-python
- Sourcegraph, *Search-based code navigation*. https://sourcegraph.com/docs/code-navigation/search-based-code-navigation
- *An Empirical Study of Large Language Models for Type and Call Graph Analysis in Python and JavaScript*, 2024. https://arxiv.org/abs/2410.00603
- Jedi, API (`goto`, `infer`). https://jedi.readthedocs.io/en/latest/docs/api.html
