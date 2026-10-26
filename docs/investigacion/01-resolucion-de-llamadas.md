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

## 6. Dónde está el cuello de botella (19/10/2026)

leo resuelve como el ACG de JavaScript (Feldthaus et al., ICSE 2013): une por nombre de
propiedad. Su fallo conocido es el mismo que medimos, mezclar propiedades homónimas de
objetos distintos (una evaluación de 2014 da 43% de precisión y 91% de recall por esa
causa). Una réplica avisa además de lo que ya vimos: promediar por sitio de llamada da
cifras mucho mejores que contar aristas. Por eso se informan las dos.

Llamadas juzgadas que no salen exactas, por forma (muestra fija de 5.000 por repo):

| Forma | django: no exactas | django: destinos falsos | sympy: no exactas | sympy: destinos falsos | Qué la arregla |
|---|---|---|---|---|---|
| `foo()` importado | 42 | 189 | 175 | 954 | Tabla de imports |
| `modulo.foo()` | 7 | 46 | 43 | 3.137 | Tabla de imports |
| `foo()` del propio archivo | 4 | 8 | 45 | 132 | Ámbito del archivo |
| `self.foo()` | 48 | 186 | 127 | 1.261 | Jerarquía de clases |
| `super().foo()` | 22 | **7.473** | 9 | 1.579 | Jerarquía + MRO |
| `var.foo()` | 45 | 1.294 | 119 | 3.087 | Tipo del objeto |
| `self.attr.foo()` | 37 | 1.349 | 11 | 75 | Tipo del atributo |
| `expr.foo()` | 19 | 402 | 52 | 973 | Tipo de la expresión |
| **Total** | **224** | **10.947** | **581** | **11.198** | |

Lectura:
1. **Lo que nota quien pregunta (llamadas no exactas)** está repartido. Imports, ámbito y
   jerarquía de clases cubren 123 de 224 en django (55%) y 399 de 581 en sympy (69%).
2. **El ruido (destinos falsos)** está concentrado: en django, 22 llamadas a
   `super().__init__()` aportan el 68% de todos los destinos falsos, porque cada una
   se une con los ~80 `__init__` del repo.
3. **Los imports son el único arreglo que también recupera dependientes perdidos**
   (los alias).
4. **El tipo del objeto (`var.foo()`) no se arregla con anotaciones donde más falla:**
   django tiene un 0% de parámetros anotados y sympy un 16% (leo-code 73%, NEXUS 95%).
   Lo que sí aparece en django es el objeto creado en la misma función (`x = Clase()`):
   el 26% de sus `var.foo()` ambiguas.
5. **El juez solo ve una parte.** Jedi da veredicto en el 9-20% de las llamadas de los
   repos grandes, y lo que resuelve tiende a ser lo fácil. Las cifras anteriores son una
   cota de lo que se puede ganar, no una promesa.

Técnicas que encajan, de menos a más coste:

| Técnica | Origen | Qué cubre | Coste para leo |
|---|---|---|---|
| Ámbito del archivo + imports con alias | Regla IMPORT de PyCG, resolución de nombres de stack graphs | `foo()`, `modulo.foo()`, alias | Tabla por archivo; ya se parsean los imports |
| Jerarquía de clases (CHA) + MRO | Dean, Grove y Chambers (CHA, 1995); `getClassAttrObject` de PyCG | `self.foo()`, `super().foo()` | Bases por nombre (`hereda_de` ya existe), resueltas con la tabla de imports |
| Tipo declarado o por constructor, dentro de la función | Variable/Declared Type Analysis (Sundaresan et al., OOPSLA 2000) | `x = Clase(); x.foo()`, parámetros anotados | Un recorrido por función |
| Tipo de los atributos y retornos | Inferencia de Pyright (unión de asignaciones) | `self.attr.foo()`, `x = crear()` | Alto: entre archivos, y Pyright avisa de que es caro |

Una regla de CHA que hay que respetar para no perder dependientes: `self.foo()` dentro de
la clase base puede ejecutar la versión de una subclase (patrón *template method*). El
destino de `self.foo()` es el método que da la MRO **más** las sobrescrituras en
subclases, no solo el primero. (Corrección del 20/10: esta nota citaba el caso
`base_class_calls_child` del micro-benchmark, pero ahí `child` es un atributo asignado en
las subclases, no un método. Eso es flujo de atributos, del paso 3, y la CHA no lo resuelve.)

Para hacerlo hay que guardar la forma de la llamada en la cápsula. Eso cambia el formato
del índice, así que hay que subir su versión para que se reconstruya.

## 7. Fase 1, paso 1: ámbito del archivo + imports (19/10/2026)

Qué se hizo:

- El parser guarda la forma de cada llamada (`foo()`, `X.foo()` o otro receptor) y el
  enlace de cada import, con alias, nivel relativo e imports dentro de funciones.
- `GraphQuery` resuelve:
  - `foo()` contra el import local, luego una def del mismo archivo, luego un import
    del archivo;
  - `X.foo()` cuando `X` es un módulo importado;
  - los re-exports de un `__init__.py`.
- Un import de la stdlib o de un paquete que no está en el repo no crea aristas al repo.
  Un builtin tampoco.
- Lo demás sigue uniéndose por nombre: `self.foo()`, `obj.foo()`, y nombres sin enlace.
- El índice pasa al formato 3.

Resultado con el mismo oráculo (f), la misma muestra y la misma semilla que la §5:

| Repo | Exactas antes → ahora | Precisión antes → ahora | Recall antes → ahora |
|---|---|---|---|
| NEXUS | 92.1% → 92.1% | 92.7% → 92.7% | 100% → 100% |
| leo-code | 81.8% → 86.5% | 52.5% → 56.7% | 99.4% → 100% |
| sympy | 45.5% → 65.1% | 8.6% → 9.5% | 99.8% → 100% |
| django | 49.9% → 60.9% | 3.9% → 4.0% | 99.1% → 100% |

Micro-benchmark de PyCG: igual que antes (114/119 completos, 101/119 sonidos). Sus fallos
son llamadas de orden superior y MRO, que este paso no toca.

Lectura:

- **Exactas** sube 5-20 puntos.
- **Recall** llega al 100% en los cuatro repos. Los destinos que se perdían eran los
  alias de import.
- **Precisión** casi no se mueve. Los destinos falsos vienen sobre todo de `super()`,
  `self.foo()` y `var.foo()`, como predijo la §6, y son el objetivo de los pasos 2 y 3.
- La cota de la §6 para los pasos 1+2 juntos era django ~76% y sympy ~82%. Con el paso 1
  solo, sympy ya recupera dos tercios de esa ganancia y django algo menos de la mitad.

## 8. Paso 2: jerarquía de clases para `self`, `cls` y `super()` (20/10/2026)

### Semántica que hay que respetar

Según la documentación de Python (`super()` y *The Python 2.3 Method Resolution Order*):

- `obj.foo` busca `foo` en `type(obj).__mro__`, en orden.
- `super().foo` busca en la misma MRO, pero empieza **después** de la clase que encierra
  el método.
- La MRO es la linealización C3 (Barrett et al., OOPSLA 1996).

La documentación avisa de que, con herencia múltiple, ese orden "puede incluir clases
hermanas desconocidas antes de la ejecución".

Dos consecuencias para un análisis estático:

1. `self.foo()` en la clase `C` no siempre va a `C.foo`. `self` puede ser cualquier
   subclase `S` de `C`, y entonces va al primer `foo` de la MRO de `S`. Eso es la regla de
   Class Hierarchy Analysis (Dean, Grove y Chambers, ECOOP 1995).
2. `super().foo()` en `C` puede ir a una clase **hermana**. Con `class D(Left, Right)`, un
   `super().hook()` dentro de `Left` ejecuta `Right.hook`, que no es ancestro de `Left`.

### El juez no ve el despacho dinámico

Comprobado con jedi 0.19: en esos dos casos `goto` devuelve solo el método de la clase
estática (`Base.hook`). No ve la sobrescritura en la subclase ni la clase hermana. Por eso
el oráculo (f) contará como "falsos" destinos que en ejecución son reales. El oráculo
tiene que separarlos: un destino extra que es el mismo método en una clase emparentada
por herencia con la del destino de jedi se cuenta aparte, como "despacho dinámico".

### Regla que se implementa

Para una llamada dentro de un método de la clase `C`:

- **`self.foo()` / `cls.foo()`** (el receptor es el primer parámetro del método): la unión,
  para cada `S` en `{C} ∪ subclases(C)`, del primer `foo` de `MRO(S)`.
- **`super().foo()`**: lo mismo, pero buscando en `MRO(S)` solo **después** de `C`.
- **`Clase.foo()`** con `Clase` una clase del repo: el primer `foo` de `MRO(Clase)`, sin
  subclases, porque la clase es explícita.
- Si no se encuentra `foo` (atributo asignado, base fuera del repo o desconocida), la
  llamada va por nombre, como hoy. Nunca se quita una arista posible.

Las bases se resuelven con la tabla de imports del paso 1. El parser las guarda con la
misma forma que las llamadas (`Base`, `modulo.Base`, y de `Generic[T]` se toma `Generic`),
en vez de partir el texto de `hereda_de`.

Si C3 falla (la clase no compila en Python, o faltan bases), se usa el orden en
profundidad de izquierda a derecha sin repetidos. Es una aproximación y queda marcada en
el código.

### Bases que no se pueden seguir (revisión)

La revisión encontró dos huecos de recall en la primera versión, y se cerraron con tests:

- **Base desconocida en la MRO.** `class A(a.b.Mixin)`, `class A(with_metaclass(...))` o
  una base re-exportada con `import *` se descartaban sin más. Así, un `self.helper()`
  podía resolverse a un override de una subclase y perder el `helper` que quizá vive en esa
  base. Ahora una base que no se sabe qué es entra en la MRO como un nodo propio, en su
  sitio de C3. Si la búsqueda llega a ese nodo antes de encontrar el método, la llamada va
  por nombre. Las bases externas conocidas (builtins, stdlib, paquetes de fuera) no abren
  la clase, porque no pueden definir un método del repo.
- **Subclase con base desconocida.** Con `class D(mod.C)` y `mod` imposible de seguir, D
  no aparecía entre las subclases de C y se perdían sus overrides. Ahora D cuenta como
  subclase de cada clase del repo llamada `C`. De `with_metaclass(Meta, Base)` cuentan
  todos sus argumentos. Esto puede añadir algún override de más, pero no quita ninguno.

### El oráculo, corregido

La primera regla del oráculo ("despacho dinámico" = mismo método en una clase emparentada
con la del destino de jedi) era demasiado blanda. Mirando los ejemplos de django,
contaba como despacho homónimos que esa llamada no puede alcanzar. Por ejemplo, para un
`super().clean()` en `GeometryField` contaba `SimpleArrayField.clean`. Pasaba porque se
apoyaba en las uniones por nombre de leo, que son una suposición y no herencia vista.

La regla estricta exige que el destino esté en la MRO de una subclase S de la clase C
que hace la llamada, que S contenga de verdad a C en su MRO, y que con `super()` el
destino vaya detrás de C. Con esa regla, django pasa de 68 a 47 destinos de despacho, y
los ejemplos son overrides reales (`Serializer.getvalue` en json/jsonl).

### Resultados (20/10/2026, muestra 5000, semilla 0)

| Repo | Exactas paso 1 → paso 2 | Precisión paso 1 → paso 2 | Recall | Despacho dinámico |
|---|---|---|---|---|
| NEXUS | 92,1% → **96,0%** | 92,7% → **96,2%** | 100% | 0 |
| leo-code | 86,5% → **91,4%** | 56,8% → **82,5%** | 100% | 0 |
| django | 60,9% → **72,3%** | 4,0% → **10,0%** | 100% | 47 (con ellos: 76,3% exactas) |
| sympy | 65,1% → **79,5%** | 9,5% → **31,3%** | 100% | 69 (con ellos: 81,2% exactas) |

- Destinos falsos: django pasa de 10745 a 4022 y sympy de 9721 a 2223.
- leo-code se mide sobre sí mismo, así que su muestra cambia con cada commit.
- PyCG micro no cambia: 114/119 completas y 101 sound.

**Coste (gate (e), django).** La primera versión no pasaba el gate: daba 29–31 µs/símbolo
con un límite de 21. Hubo dos causas:

1. El GC. Las claves `(archivo, clase)` y una lista por método eran ~66k contenedores vivos
   más. Se cambiaron por claves str y por la def suelta o una tupla.
2. Cada despacho hacía una búsqueda por subclase. django tiene jerarquías de ~2000
   subclases (los `Model` y `TestCase` de sus tests). Una subclase con una sola base que no
   redefine el método tiene la MRO de su padre, que ya entra en la cuenta, así que se salta
   sin calcularla.

Tras los dos cambios: **14,2 / 17,2 / 19,5 µs/símbolo** (HEAD daba 13–18 en la misma
máquina). Sin GC, GraphQuery cuesta 5,8 µs/símbolo, frente a 5,2–6,3 en HEAD.

**Lo que queda.** Casi todos los falsos de django y sympy son llamadas sobre variables y
atributos (`obj.foo()`, `self.x.foo()`), que siguen yendo por nombre. Eso es el paso 3:
tipos locales.

## 9. Paso 3: tipos locales para `x.foo()` (26/10/2026)

### Medición previa: cuánto puede dar cada fuente de tipos

Antes de escribir código se clasificaron con `ast` todas las llamadas `x.foo()` y
`self.x.foo()` a métodos con nombre repetido, según de dónde sale el tipo del receptor. Se
pondera por destinos falsos (homónimos − 1), que es lo que mide el oráculo:

| Receptor | django | sympy |
|---|---|---|
| `x = C(...)` en la misma función | **20,1%** | **9,1%** |
| `self.x` con `self.x = C(...)` o `x: C` en la clase | <1% | <1% |
| parámetro anotado, `x: C = …`, retorno anotado | <1% | ~1% |
| cadenas `a.b.foo()` (django: `Modelo.objects.…`, el manager que añade la metaclase) | 26,6% | 3,0% |
| `f().foo()`, `x = otra_cosa()`, parámetros sin anotar, globales | resto | resto |

Conclusión: en estos repos casi no hay anotaciones (cuadra con Di Grazia y Pradel, 2022),
así que lo único que vale la pena es `x = C(...)`. Lo demás se descarta por ahora (YAGNI):
`self.x`, anotaciones y retornos juntos no llegan al 2%. `Modelo.objects` necesita saber
cómo funciona Django, y eso no es un tipo local.

### Regla

Es la de las dos fuentes. En PyCG, el grafo de asignaciones guarda para cada identificador el
**conjunto** de objetos a los que puede apuntar (`AssignG = Obj → P(Obj)`), con un análisis
insensible al contexto. Pyright, para una variable sin tipo declarado: "The inferred type of
the variable is the union of all such types".

- Si **todas** las asignaciones de `x` en la función son `x = C(...)` o `x = m.C(...)`,
  `x.foo()` va al primer `foo` de la MRO de cada `C`. No se incluyen subclases, porque el
  constructor da el tipo exacto.
- Cualquier otra forma de ligar `x` descarta la variable, también dentro de funciones
  anidadas: parámetro, bucle, `with`, `except`, import, `global`/`nonlocal`, desempaquetado,
  `del` o un `x = f()` cualquiera. Así la unión puede salir más grande, pero nunca más
  pequeña de lo real.
- Si alguna `C` no es una clase del repo, o el método no aparece antes de una base
  desconocida, la llamada va por nombre, como antes.
- Techo conocido: un `metaclass.__call__` o un `__new__` que devuelve otro tipo engaña a la
  regla. Está marcado en el código.

### Resultados (muestra 5000, semilla 0)

| Repo | Exactas paso 2 → paso 3 | Precisión | Destinos falsos | Recall |
|---|---|---|---|---|
| django | 72,3% → **74,9%** | 10,0% → 10,7% | 4022 → 3730 | 100% |
| sympy | 79,5% → **80,2%** | 31,3% → 31,8% | 2223 → 2182 | 100% |

Coste: con el mínimo de 5 reconstrucciones en CPU, intercalando A/B, la reconstrucción de
django sale igual que en HEAD (9,85 frente a 9,85 µs/símbolo). Índice en formato 6.

**Lo que queda.** Los falsos que siguen son sobre todo:
- cadenas de atributos (`Modelo.objects.create`, que es el 27% en django);
- `f().foo()`;
- variables asignadas desde llamadas cuyo retorno no se conoce.

Para resolverlos haría falta propagar entre funciones (como hace PyCG) o modelar Django. Las
dos cosas chocan con el presupuesto del gate (e), así que no se hacen sin una decisión
explícita.

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
- Feldthaus et al., *Efficient Construction of Approximate Call Graphs for JavaScript IDE Services*, ICSE 2013. https://2013.icse-conferences.org/content/efficient-construction-approximate-call-graphs-javascript-ide-services.html
- Réplica en Rascal del ACG (CWI). https://ir.cwi.nl/pub/23115
- Dijkstra, *Evaluation of Static JavaScript Call Graph Algorithms*, 2014. https://www.scribd.com/document/312776719/Evaluation-of-Static-Javascript-Call-Graph-Algorithms
- Dean, Grove y Chambers, *Optimization of Object-Oriented Programs Using Static Class Hierarchy Analysis*, ECOOP 1995. https://doi.org/10.1007/3-540-49538-X_5
- Barrett et al., *A Monotonic Superclass Linearization for Dylan*, OOPSLA 1996. https://doi.org/10.1145/236337.236343
- Python, `super()`. https://docs.python.org/3/library/functions.html#super
- Python, *The Python 2.3 Method Resolution Order*. https://docs.python.org/3/howto/mro.html
- Sundaresan et al., *Practical virtual method call resolution for Java*, OOPSLA 2000. https://doi.org/10.1145/353171.353189
- Tip y Palsberg, *Scalable propagation-based call graph construction algorithms*, OOPSLA 2000. https://access.archive-ouverte.unige.ch/access/metadata/56f27ea0-bb6c-4815-859e-dfeb42ee190d/download
- Pyright, *Type inference*. https://github.com/microsoft/pyright/blob/main/docs/type-inference.md
- Di Grazia y Pradel, *The Evolution of Type Annotations in Python*, ESEC/FSE 2022. https://2022.esec-fse.org/details/fse-2022-research-papers/36/The-Evolution-of-Type-Annotations-in-Python-An-Empirical-Study
