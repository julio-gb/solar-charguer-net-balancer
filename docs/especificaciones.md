# Especificaciones – Solar Charger Net Balancer (addon Home Assistant)

## 1. Entidades de entrada (seleccionables en la configuración del addon)

| # | Entidad | Unidad | Frecuencia aprox. |
|---|---------|--------|-------------------|
| 1 | Potencia generada (placas solares, instantánea) | kW | ~5 min |
| 2 | Potencia consumida por el hogar | kW | ~5 min |
| 3 | Potencia consumida por el cargador del coche | (pendiente confirmar) | ~5 min |

## Preguntas abiertas
- ¿El consumo del hogar (2) incluye el del cargador (3)?
- Unidad de la entidad del cargador (¿kW?).
- Actualización cada 5 min: margen de reacción limitado ante nubes/picos.
