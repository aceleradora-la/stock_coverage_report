# Stock Coverage Report (`stock_coverage_report`)

Módulo Odoo 19 (Community y Enterprise) que agrega el tablero **Inventario → Reportes → Cobertura de stock**:
un Kanban de productos comprables almacenables agrupado por semáforo (rojo / amarillo / verde) según cuántos
días de stock quedan con el consumo reciente.

- Rama: `19.0` · Licencia: LGPL-3 · Dependencias: `stock`, `purchase_stock` (ambas existen en Community y Enterprise).

## Qué calcula

Por cada variante (`product.product`) almacenable, activa y comprable:

| Métrica | Cálculo |
|---|---|
| Consumo diario | Salidas *done* desde ubicaciones internas hacia ubicaciones no internas y no de tránsito, en los últimos **N días cerrados** (TZ de la compañía, sin incluir hoy), dividido por N. |
| Días de cobertura (real) | Cantidad a la mano / consumo diario. Sin consumo: `∞` (verde) si hay stock, `—` (sin datos) si no hay. |
| Días de cobertura (pronóstico) | Cantidad pronosticada (`virtual_available`) / consumo diario, con el mismo semáforo. |

**Semáforo** (igual para real y pronóstico):

- **Plazo** = `delay` del primer proveedor (`product.supplierinfo`, orden `sequence, min_qty desc, price, id`); 0 si no hay.
- **Bloque interno** = `days_to_purchase` de la compañía (+ `po_lead` si `purchase.use_po_lead` está activo y el campo existe; en Odoo 19 estándar no existe). Si da 0 se usa 0,01 para conservar una banda amarilla mínima.
- Rojo: días ≤ plazo · Amarillo: plazo < días ≤ plazo + bloque interno · Verde: días > plazo + bloque interno.

El tablero agrupa por el semáforo **real** (columnas fijas Rojo → Amarillo → Verde, ordenadas por días ascendente) y la
tarjeta muestra también el pronóstico. Los productos "sin datos" quedan fuera del tablero.

## Parámetros

| Dónde | Campo | Efecto |
|---|---|---|
| Categoría de producto | Días ventana consumo (`stock_cover_window_days`) | Ventana N para los productos de la categoría y sus subcategorías. Vacío = hereda de la categoría padre más cercana que la tenga; si ninguna de la cadena la tiene, 7 días. |
| Producto (pestaña Inventario) | Días ventana consumo (`stock_cover_window_days`) | Pisa la de la categoría. Vacío = usar la categoría. |
| Compañía (pestaña Cobertura de stock) | Categorías (`stock_cover_category_ids`) | Si hay categorías, el tablero solo muestra variantes de esas categorías (y subcategorías). Vacío = todas. |
| Ajustes de Compras / compañía | `days_to_purchase` | Ancho de la banda amarilla. |

Acceso: el menú pide `stock.group_stock_user`; el menú padre estándar **Inventario → Reportes** de Odoo 19 es
visible solo para `stock.group_stock_manager`.

## Instalación

Agregar el repo al `addons_path` y instalar `stock_coverage_report` (Apps o `-i stock_coverage_report`).
Al instalarse recalcula los semáforos de todas las variantes almacenables en tandas de 2000.

## Tests

```bash
odoo-bin -d <db> -i stock_coverage_report --test-enable --test-tags /stock_coverage_report --stop-after-init
```

Cubren: semáforo rojo/amarillo/verde/sin datos, umbrales (proveedor, `days_to_purchase`, parámetro `use_po_lead`
heredado), fallback de ventana producto → categoría → categorías padre → 7, constraints, ventana de días cerrados (hoy no cuenta),
orden fijo de columnas y filtro por categorías de la compañía.

### Checklist Community / Enterprise

En una base limpia de cada edición (Enterprise: `addons_path` con `enterprise/`, `web_enterprise` y
`stock_enterprise` instalados):

- [ ] Instala sin errores y pasan los tests.
- [ ] Inventario → Reportes → Cobertura de stock abre el Kanban con columnas Rojo / Amarillo / Verde.
- [ ] Colores de discos y tarjetas correctos en tema claro y oscuro.
- [ ] Pestaña "Cobertura de stock" en la compañía, campo en la categoría y en la pestaña Inventario del producto.
