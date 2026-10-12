# Especificaciones – Solar Charger Net Balancer (addon Home Assistant)

## 1. Entidades de entrada (seleccionables en la configuración del addon)

| # | Entidad | Unidad | Frecuencia aprox. |
|---|---------|--------|-------------------|
| 1 | Potencia generada (placas solares, instantánea) | kW | ~5 min |
| 2 | Potencia consumida por el hogar | kW | ~5 min |
| 3 | Potencia consumida por el cargador del coche | kW | ~5 min |

- Las entidades 2 y 3 son independientes: consumo total = hogar + cargador.
- Excedente disponible = generación − consumo hogar.

## 2. Hardware
- Inversor: Huawei. Datos obtenidos vía nube FusionSolar (perfil de solo consulta), resolución ~5 min.

## 3. Riesgos / mejoras posibles
- Resolución de 5 min: reacción lenta ante nubes o picos de consumo.
- Mejora opcional: lectura local Modbus TCP (integración `huawei_solar`), pendiente de viabilidad con el instalador.
