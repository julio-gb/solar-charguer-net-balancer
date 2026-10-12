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
- Cargador: Velo HOME-I, modelo BCP-A2N-L. Monofásico. Conectado a la red local.
  - Integración HA: Beny WiFi (app móvil: Z-Box).
  - Control desde HA: encendido/apagado y amperaje máximo.
  - Rango de intensidad: 6 A (mínimo del cargador) – 26 A (límite configurado).
  - Equivalencia aprox. a 230 V: 6 A ≈ 1,4 kW · 26 A ≈ 6,0 kW · 1 A ≈ 0,23 kW.
  - Su sensor de potencia lo proporciona el propio cargador (posible actualización más rápida, pendiente confirmar).

## 3. Riesgos / mejoras posibles
- Excedente < ~1,4 kW: no se puede cargar solo con solar (mínimo 6 A). Hay que decidir: pausar o completar con red.
- Evitar arranques/paradas frecuentes (histéresis y tiempos mínimos) para proteger cargador y coche.
- Resolución de 5 min: reacción lenta ante nubes o picos de consumo.
- Mejora opcional: lectura local Modbus TCP (integración `huawei_solar`), pendiente de viabilidad con el instalador.
