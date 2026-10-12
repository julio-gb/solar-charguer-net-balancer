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
  - Rango de intensidad: 6 A (mínimo del cargador) – 21 A (límite configurado).
  - Equivalencia aprox. a 230 V: 6 A ≈ 1,4 kW · 21 A ≈ 4,8 kW · 1 A ≈ 0,23 kW.
  - Su sensor de potencia lo proporciona el propio cargador (posible actualización más rápida, pendiente confirmar).

- Sin batería doméstica.
- Potencia contratada: 4,9 kW (se quiere reducir).

## 3. Tarifa y compensación (todo configurable como parámetro en el addon)
Tarifa actual de referencia: Octopus 3 (fecha final 10/01/2027).

| Día | Horario | €/kWh |
|-----|---------|-------|
| Lunes–viernes | 00:00–08:00 | 0,0870 |
| Lunes–viernes | 08:00–10:00 | 0,1190 |
| Lunes–viernes | 10:00–14:00 | 0,1980 |
| Lunes–viernes | 14:00–18:00 | 0,1190 |
| Lunes–viernes | 18:00–22:00 | 0,1980 |
| Lunes–viernes | 22:00–24:00 | 0,1190 |
| Fines de semana y festivos | 00:00–24:00 | 0,0870 |

- Término de potencia: punta 0,0970 €/kW/día · valle 0,0270 €/kW/día.
- Compensación de excedentes: ~0,07 €/kWh.
- Objetivo del usuario: autoconsumir toda la generación posible.
- Requisitos: tramos horarios editables, distinción laborable/festivo, precio de compensación editable, potencia contratada editable.

## 4. Riesgos / mejoras posibles
- Cargador a 21 A (~4,8 kW) + consumo del hogar puede superar la potencia contratada (4,9 kW): el addon debe limitar la intensidad para no superar la potencia contratada (consumo de red = hogar + cargador − generación).
- Excedente < ~1,4 kW: no se puede cargar solo con solar (mínimo 6 A). Hay que decidir: pausar o completar con red.
- Evitar arranques/paradas frecuentes (histéresis y tiempos mínimos) para proteger cargador y coche.
- Resolución de 5 min: reacción lenta ante nubes o picos de consumo.
- Mejora opcional: lectura local Modbus TCP (integración `huawei_solar`), pendiente de viabilidad con el instalador.
