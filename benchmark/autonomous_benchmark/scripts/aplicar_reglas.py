"""Aplicador de reglas de negocio TiendaMax — lee reglas_negocio.md y las aplica."""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DOCS_DIR = Path(__file__).parent.parent / "docs"
REGLAS_FILE = DOCS_DIR / "reglas_negocio.md"

# --- Tablas de reglas (derivadas del documento) ---

MULTIPLICADORES_CATEGORIA: dict[str, float] = {
    "electronica": 1.20,
    "ropa": 0.90,
    "hogar": 1.05,
    "libros": 0.85,
    "lujo": 2.50,
    "alimentacion": 1.00,
    "deportes": 1.10,
}

DESCUENTOS_VOLUMEN: list[tuple[int, float]] = [
    (100, 0.30),
    (50, 0.20),
    (25, 0.12),
    (10, 0.05),
    (0, 0.00),
]

DESCUENTOS_MEMBRESIA: dict[str, float] = {
    "basico": 0.00,
    "silver": 0.05,
    "gold": 0.10,
    "platinum": 0.15,
}

IVA_REGION: dict[str, float] = {
    "PE": 0.21,
    "IC": 0.07,
    "CE": 0.00,
    "ME": 0.00,
    "BA": 0.21,
    "EU": 0.00,
}

IVA_REDUCIDO_LIBROS = 0.04
PRECIO_MINIMO_RATIO = 0.40
CANTIDAD_MAXIMA = 500


@dataclass
class Pedido:
    producto_id: str
    categoria: str
    precio_base: float
    cantidad: int
    stock_disponible: int
    tier_membresia: str
    region: str
    acepta_parcial: bool = False
    aprobacion_manual: bool = False
    motivo_devolucion: Optional[str] = None
    dias_desde_compra: Optional[int] = None


@dataclass
class ResultadoPedido:
    producto_id: str
    precio_base: float
    precio_categoria: float
    descuento_volumen_pct: float
    descuento_membresia_pct: float
    precio_antes_iva: float
    iva_pct: float
    precio_final: float
    estado_stock: str
    alertas: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    ok: bool = True


def _descuento_volumen(cantidad: int) -> float:
    for minimo, pct in DESCUENTOS_VOLUMEN:
        if cantidad >= minimo:
            return pct
    return 0.0


def _estado_stock(stock: int) -> str:
    if stock == 0:
        return "SIN_STOCK"
    if stock <= 4:
        return "ALERTA_ROJA"
    if stock <= 19:
        return "ALERTA_AMARILLA"
    return "NORMAL"


def _iva(categoria: str, region: str) -> float:
    if region not in IVA_REGION:
        raise ValueError(f"REGION_INVALIDA: {region}")
    iva_base = IVA_REGION[region]
    if categoria == "libros" and region in ("PE", "BA"):
        return IVA_REDUCIDO_LIBROS
    return iva_base


def calcular_pedido(pedido: Pedido) -> ResultadoPedido:
    alertas: list[str] = []
    errores: list[str] = []

    if pedido.categoria not in MULTIPLICADORES_CATEGORIA:
        return ResultadoPedido(
            producto_id=pedido.producto_id,
            precio_base=pedido.precio_base,
            precio_categoria=0, descuento_volumen_pct=0,
            descuento_membresia_pct=0, precio_antes_iva=0,
            iva_pct=0, precio_final=0, estado_stock="?",
            errores=[f"CATEGORIA_INVALIDA: {pedido.categoria}"], ok=False,
        )

    if pedido.region not in IVA_REGION:
        return ResultadoPedido(
            producto_id=pedido.producto_id,
            precio_base=pedido.precio_base,
            precio_categoria=0, descuento_volumen_pct=0,
            descuento_membresia_pct=0, precio_antes_iva=0,
            iva_pct=0, precio_final=0, estado_stock="?",
            errores=[f"REGION_INVALIDA: {pedido.region}"], ok=False,
        )

    # Paso 1: precio por categoría
    mult = MULTIPLICADORES_CATEGORIA[pedido.categoria]
    precio_categoria = pedido.precio_base * mult

    # Paso 2 y 3: descuentos (con regla cruzada 7.1)
    desc_vol = _descuento_volumen(pedido.cantidad)
    desc_mem = DESCUENTOS_MEMBRESIA.get(pedido.tier_membresia, 0.0)

    regla_71 = (
        pedido.tier_membresia == "platinum"
        and pedido.categoria == "electronica"
        and pedido.cantidad >= 10
    )

    if regla_71:
        # Solo el mayor descuento
        if desc_vol >= desc_mem:
            desc_mem_aplicado = 0.0
            alertas.append("Regla 7.1: platinum+electrónica — se aplica descuento volumen (mayor), membresía anulada")
        else:
            desc_vol = 0.0
            desc_mem_aplicado = desc_mem
            alertas.append("Regla 7.1: platinum+electrónica — se aplica descuento membresía (mayor), volumen anulado")
    else:
        desc_mem_aplicado = desc_mem

    precio_volumen = precio_categoria * (1 - desc_vol)
    precio_membresia = precio_volumen * (1 - desc_mem_aplicado)

    # Regla cruzada 7.4: libros + platinum + EU
    if pedido.categoria == "libros" and pedido.tier_membresia == "platinum" and pedido.region == "EU":
        descuento_total = 1 - (precio_membresia / precio_categoria)
        if descuento_total > 0.25:
            precio_membresia = precio_categoria * 0.75
            alertas.append("Regla 7.4: libros+platinum+EU — descuento recortado al 25% máximo")

    # Paso 4: validar precio mínimo (regla 7.2)
    precio_minimo = pedido.precio_base * PRECIO_MINIMO_RATIO
    if precio_membresia < precio_minimo:
        errores.append(f"PRECIO_MINIMO_VIOLADO: precio {precio_membresia:.2f} < mínimo {precio_minimo:.2f}")
        return ResultadoPedido(
            producto_id=pedido.producto_id, precio_base=pedido.precio_base,
            precio_categoria=round(precio_categoria, 2),
            descuento_volumen_pct=desc_vol, descuento_membresia_pct=desc_mem_aplicado,
            precio_antes_iva=round(precio_membresia, 2), iva_pct=0, precio_final=0,
            estado_stock=_estado_stock(pedido.stock_disponible),
            alertas=alertas, errores=errores, ok=False,
        )

    # Paso 5: IVA
    iva = _iva(pedido.categoria, pedido.region)
    precio_final = precio_membresia * (1 + iva)

    # Paso 6: validar stock y cantidad
    estado_stock = _estado_stock(pedido.stock_disponible)

    if estado_stock == "SIN_STOCK":
        errores.append("SIN_STOCK: producto agotado, venta bloqueada")
        return ResultadoPedido(
            producto_id=pedido.producto_id, precio_base=pedido.precio_base,
            precio_categoria=round(precio_categoria, 2),
            descuento_volumen_pct=desc_vol, descuento_membresia_pct=desc_mem_aplicado,
            precio_antes_iva=round(precio_membresia, 2), iva_pct=iva,
            precio_final=round(precio_final, 2),
            estado_stock=estado_stock, alertas=alertas, errores=errores, ok=False,
        )

    if pedido.cantidad > pedido.stock_disponible and not pedido.acepta_parcial:
        errores.append(f"STOCK_INSUFICIENTE: pedido {pedido.cantidad} uds, disponible {pedido.stock_disponible}")

    if pedido.cantidad > CANTIDAD_MAXIMA and not pedido.aprobacion_manual:
        errores.append(f"CANTIDAD_EXCEDIDA: {pedido.cantidad} uds supera límite de {CANTIDAD_MAXIMA}")

    if estado_stock == "ALERTA_AMARILLA":
        alertas.append(f"Pocas unidades disponibles: {pedido.stock_disponible} en stock")
    elif estado_stock == "ALERTA_ROJA":
        alertas.append(f"ÚLTIMAS UNIDADES: solo {pedido.stock_disponible} disponibles")

    ok = len(errores) == 0

    return ResultadoPedido(
        producto_id=pedido.producto_id,
        precio_base=pedido.precio_base,
        precio_categoria=round(precio_categoria, 2),
        descuento_volumen_pct=round(desc_vol * 100, 1),
        descuento_membresia_pct=round(desc_mem_aplicado * 100, 1),
        precio_antes_iva=round(precio_membresia, 2),
        iva_pct=round(iva * 100, 1),
        precio_final=round(precio_final, 2),
        estado_stock=estado_stock,
        alertas=alertas,
        errores=errores,
        ok=ok,
    )


def verificar_devolucion(dias: int, categoria: str, motivo: str = "") -> dict:
    if categoria == "alimentacion":
        return {"reembolso_pct": 0, "error": "DEVOLUCION_BLOQUEADA"}
    if motivo == "defecto_fabrica" and dias <= 730:
        return {"reembolso_pct": 100, "motivo": "garantía legal 24 meses"}
    if dias <= 29:
        return {"reembolso_pct": 100}
    if dias <= 60:
        return {"reembolso_pct": 50}
    return {"reembolso_pct": 0, "error": "DEVOLUCION_EXPIRADA"}


def leer_version_reglas() -> str:
    """Extrae la versión del documento de reglas."""
    text = REGLAS_FILE.read_text(encoding="utf-8")
    match = re.search(r"\*\*Versión:\*\*\s*([\d.]+)", text)
    return match.group(1) if match else "desconocida"


# --- Dataset de prueba ---

PEDIDOS_PRUEBA = [
    Pedido("LAPTOP-001", "electronica", 800.00, 30, 45, "platinum", "PE"),
    Pedido("CAMISETA-007", "ropa", 25.00, 5, 200, "silver", "IC"),
    Pedido("SOFA-XL", "hogar", 1200.00, 1, 3, "gold", "PE"),
    Pedido("QUIJOTE-ED", "libros", 18.00, 50, 500, "platinum", "EU"),
    Pedido("RELOJ-OMEGA", "lujo", 4500.00, 2, 0, "basico", "PE"),
    Pedido("YOGUR-BIO", "alimentacion", 1.50, 100, 800, "silver", "BA"),
    Pedido("BICI-MTB", "deportes", 650.00, 10, 15, "gold", "CE"),
    Pedido("LAPTOP-002", "electronica", 1200.00, 200, 250, "platinum", "PE"),
]


def main() -> None:
    version = leer_version_reglas()
    print(f"\n{'='*70}")
    print(f"  TiendaMax — Aplicador de Reglas de Negocio v{version}")
    print(f"{'='*70}\n")

    resultados = []
    for pedido in PEDIDOS_PRUEBA:
        res = calcular_pedido(pedido)
        resultados.append(res)

        estado = "OK" if res.ok else "ERROR"
        print(f"[{estado}] {pedido.producto_id}")
        print(f"  Precio base:      {pedido.precio_base:.2f} €")
        print(f"  Categoría:        {pedido.categoria} (×{MULTIPLICADORES_CATEGORIA.get(pedido.categoria, '?')})")
        print(f"  Precio cat.:      {res.precio_categoria:.2f} €")
        print(f"  Desc. volumen:    {res.descuento_volumen_pct}%  ({pedido.cantidad} uds)")
        print(f"  Desc. membresía:  {res.descuento_membresia_pct}%  ({pedido.tier_membresia})")
        print(f"  Precio s/IVA:     {res.precio_antes_iva:.2f} €")
        print(f"  IVA ({pedido.region}):        {res.iva_pct}%")
        print(f"  PRECIO FINAL:     {res.precio_final:.2f} €")
        print(f"  Stock:            {pedido.stock_disponible} uds — {res.estado_stock}")
        for alerta in res.alertas:
            print(f"  [!] {alerta}")
        for error in res.errores:
            print(f"  [X] {error}")
        print()

    # Guardar resultados JSON
    output_file = Path(__file__).parent.parent / "resultados_reglas.json"
    output_data = [
        {
            "producto_id": r.producto_id,
            "ok": r.ok,
            "precio_base": r.precio_base,
            "precio_final": r.precio_final,
            "estado_stock": r.estado_stock,
            "alertas": r.alertas,
            "errores": r.errores,
        }
        for r in resultados
    ]
    output_file.write_text(json.dumps(output_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Resultados guardados en: {output_file}")

    # Ejemplo de devolución
    print("\n--- Verificación de Devoluciones ---")
    casos = [
        (15, "electronica", ""),
        (45, "ropa", ""),
        (90, "deportes", ""),
        (400, "electronica", "defecto_fabrica"),
        (5, "alimentacion", ""),
    ]
    for dias, cat, motivo in casos:
        r = verificar_devolucion(dias, cat, motivo)
        print(f"  {cat:15s} {dias:3d} días  motivo={motivo or 'ninguno':20s}  → {r}")


if __name__ == "__main__":
    main()
