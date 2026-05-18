# Reglas de Negocio — TiendaMax E-Commerce

**Versión:** 3.2.1  
**Vigencia:** 2026-01-01 al 2026-12-31  
**Departamento:** Comercial y Operaciones

---

## 1. Estructura de Precios

### 1.1 Precio Base
Cada producto tiene un `precio_base` definido en el catálogo. Este precio es el punto de partida antes de aplicar cualquier modificador.

### 1.2 Multiplicadores por Categoría

| Categoría         | Multiplicador | Justificación                          |
|-------------------|---------------|----------------------------------------|
| `electronica`     | ×1.20         | Margen técnico + garantía extendida    |
| `ropa`            | ×0.90         | Alta rotación, descuento estructural   |
| `hogar`           | ×1.05         | Logística voluminosa                   |
| `libros`          | ×0.85         | Política cultural de acceso al conocimiento |
| `lujo`            | ×2.50         | Prima de exclusividad y servicio VIP   |
| `alimentacion`    | ×1.00         | Sin modificador (precio de mercado)    |
| `deportes`        | ×1.10         | Margen estándar                        |

El precio tras categoría: `precio_categoria = precio_base × multiplicador_categoria`

---

## 2. Descuentos por Volumen

Los descuentos por volumen se aplican sobre `precio_categoria` y son **excluyentes** (se aplica el mayor descuento correspondiente, no se acumulan).

| Cantidad mínima | Descuento |
|-----------------|-----------|
| < 10 unidades   | 0%        |
| ≥ 10 unidades   | 5%        |
| ≥ 25 unidades   | 12%       |
| ≥ 50 unidades   | 20%       |
| ≥ 100 unidades  | 30%       |

Fórmula: `precio_volumen = precio_categoria × (1 - descuento_volumen)`

---

## 3. Tiers de Membresía

Los clientes tienen un nivel de membresía que genera un descuento adicional. Este descuento se aplica DESPUÉS del descuento por volumen.

| Tier       | Descuento adicional |
|------------|---------------------|
| `basico`   | 0%                  |
| `silver`   | 5%                  |
| `gold`     | 10%                 |
| `platinum` | 15%                 |

Fórmula: `precio_membresia = precio_volumen × (1 - descuento_membresia)`

---

## 4. Impuestos por Región

Los impuestos se aplican sobre el precio final (después de todos los descuentos).

| Región              | IVA    | Código |
|---------------------|--------|--------|
| Península            | 21%    | `PE`   |
| Islas Canarias       | 7%     | `IC`   |
| Ceuta               | 0%     | `CE`   |
| Melilla             | 0%     | `ME`   |
| Baleares            | 21%    | `BA`   |
| Export (UE)         | 0%     | `EU`   |

**Excepción:** Libros y material educativo tienen IVA reducido del 4% en Península y Baleares, independientemente del IVA general.

Fórmula: `precio_final = precio_membresia × (1 + iva)`

---

## 5. Reglas de Stock y Alertas

| Nivel de stock | Estado          | Acción                                       |
|----------------|-----------------|----------------------------------------------|
| > 20 unidades  | `NORMAL`        | Sin restricción                              |
| 5–19 unidades  | `ALERTA_AMARILLA` | Mostrar aviso "Pocas unidades disponibles"  |
| 1–4 unidades   | `ALERTA_ROJA`   | Mostrar aviso "Últimas unidades", no vender más de stock disponible |
| 0 unidades     | `SIN_STOCK`     | Bloquear venta, activar lista de espera      |

**Regla adicional:** Si el pedido solicitado excede el stock disponible, se debe rechazar la orden completa (no se permite pedido parcial salvo que el cliente lo indique explícitamente con flag `acepta_parcial=True`).

---

## 6. Política de Devoluciones

El porcentaje de reembolso depende de los días transcurridos desde la compra:

| Días desde compra | Reembolso | Condición adicional                  |
|-------------------|-----------|--------------------------------------|
| 0–29 días         | 100%      | Producto en estado original          |
| 30–60 días        | 50%       | Sin uso y con embalaje               |
| > 60 días         | 0%        | No admitido (salvo defecto de fábrica) |

**Excepción defecto de fábrica:** Si el motivo es `defecto_fabrica`, el reembolso es 100% independientemente de los días, durante los primeros 24 meses (garantía legal).

**Categoría `alimentacion`:** No admite devolución bajo ninguna circunstancia una vez entregado.

---

## 7. Reglas Cruzadas (Restricciones)

Estas reglas tienen **prioridad máxima** y anulan cualquier cálculo previo si se incumplen:

### 7.1 Platinum + Electrónica + Volumen
**RESTRICCIÓN:** El descuento de membresía `platinum` NO es acumulable con descuento por volumen para la categoría `electronica`.

- Si `tier == platinum` AND `categoria == electronica` AND `cantidad >= 10`:
  - Se aplica **únicamente** el mayor de los dos descuentos (no ambos).
  - El mayor suele ser el descuento de volumen para pedidos ≥ 25 uds, y el de platinum para pedidos de 10–24 uds.

### 7.2 Precio Mínimo Garantizado
**RESTRICCIÓN:** Ningún producto puede venderse por debajo del 40% de su `precio_base`, independientemente de los descuentos acumulados.

- Si `precio_final_antes_iva < precio_base × 0.40`: rechazar la operación con error `PRECIO_MINIMO_VIOLADO`.

### 7.3 Cantidad Máxima por Pedido
**RESTRICCIÓN:** Un único pedido no puede superar 500 unidades del mismo producto. Pedidos mayores requieren aprobación manual (flag `aprobacion_manual=True`).

### 7.4 Libros con Membresía Platinum en Export
**RESTRICCIÓN:** La combinación `libros + platinum + region EU` tiene descuento máximo del 25% total (cualquier otro cálculo que supere este umbral se recorta al 25%).

---

## 8. Flujo de Cálculo Obligatorio

El orden de aplicación es estricto:

```
1. precio_categoria  = precio_base × multiplicador_categoria
2. precio_volumen    = precio_categoria × (1 - descuento_volumen)   [si aplica regla 7.1: elegir mayor]
3. precio_membresia  = precio_volumen × (1 - descuento_membresia)   [si aplica regla 7.1: 0% si ya usó volumen]
4. Validar precio_membresia >= precio_base × 0.40                    [regla 7.2]
5. precio_final      = precio_membresia × (1 + iva)
6. Validar stock y cantidad                                          [reglas 5 y 7.3]
7. Generar alerta de stock si aplica
```

---

## 9. Códigos de Error

| Código                  | Descripción                                             |
|-------------------------|---------------------------------------------------------|
| `SIN_STOCK`             | Producto agotado, venta bloqueada                       |
| `STOCK_INSUFICIENTE`    | Cantidad pedida supera stock disponible                 |
| `PRECIO_MINIMO_VIOLADO` | El precio final sería inferior al mínimo permitido      |
| `CANTIDAD_EXCEDIDA`     | Pedido supera límite de 500 uds sin aprobación manual   |
| `DEVOLUCION_EXPIRADA`   | Período de devolución superado (>60 días)               |
| `DEVOLUCION_BLOQUEADA`  | Categoría no admite devoluciones (alimentación)         |
| `CATEGORIA_INVALIDA`    | La categoría del producto no está definida en el sistema|
| `REGION_INVALIDA`       | El código de región no está reconocido                  |
