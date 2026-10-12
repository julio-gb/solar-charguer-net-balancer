# Especificaciones – Solar Charger Net Balancer (addon Home Assistant)

## 1. Entidades de entrada (seleccionables en la configuración del addon)

| # | Entidad | Unidad | Frecuencia aprox. |
|---|---------|--------|-------------------|
| 1 | Potencia generada (placas solares, instantánea) | kW | ~5 min |
| 2 | Potencia consumida por el hogar | kW | ~5 min |
| 3 | Potencia consumida por el cargador del coche | kW | ~5 min |

- Además, sensores de energía acumulada (kWh) para las tres métricas (generación, hogar, cargador), también seleccionables. Fuente principal para el balance horario.
- Las entidades 2 y 3 son independientes: consumo total = hogar + cargador.
- Excedente disponible = generación − consumo hogar.

## 2. Hardware
- Inversor: Huawei. Datos obtenidos vía nube FusionSolar (perfil de solo consulta), resolución ~5 min.
- Cargador: Velo HOME-I, modelo BCP-A2N-L. Monofásico. Conectado a la red local.
  - Integración HA: Beny WiFi (app móvil: Z-Box).
  - Control desde HA: encendido/apagado y amperaje máximo.
  - Rango de intensidad: 6 A (mínimo del cargador) – 21 A (límite configurado).
  - Equivalencia aprox. a 230 V: 6 A ≈ 1,4 kW · 21 A ≈ 4,8 kW · 1 A ≈ 0,23 kW.
  - Balanceo de carga propio: mide hogar + cargador, no supera 21 A totales y pausa la carga si quedan < 6 A disponibles.
  - Su sensor de potencia lo proporciona el propio cargador (posible actualización más rápida, pendiente confirmar).

- Sin batería doméstica.
- Potencia contratada: 4,9 kW, igual en punta y valle (se quiere reducir; el límite de 21 A del cargador debe ajustarse en consecuencia).

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
- Compensación de excedentes: 0,02 €/kWh (parametrizable), con batería virtual (descuenta energía y potencia; no se pierden excedentes).
- Precios sin impuestos.
- Objetivo del usuario: autoconsumir toda la generación posible.
- Requisitos: tramos horarios editables, distinción laborable/festivo, precio de compensación editable, potencia contratada editable.

## 4. Objetivos
- Autoconsumir toda la generación posible.
- Alcanzar ≥ 60 % del consumo cubierto directamente por solar (ventajas fiscales). Umbral parametrizable.
  - Indicador: cobertura solar = energía solar autoconsumida / (consumo hogar + consumo cargador).
    - Por hora de reloj (balance neto horario): autoconsumo_h = mín(E_generada_h, E_hogar_h + E_cargador_h); red_h = máx(0, E_hogar_h + E_cargador_h − E_generada_h).
  - Criterio: maximizar la cobertura solar minimizando la energía importada de red.
  - Periodo: anual. Cobertura anual = Σ autoconsumo_h / Σ (E_hogar_h + E_cargador_h).
  - El addon debe guardar el histórico horario para calcularla (persistente ante reinicios).
  - Año natural (1 enero – 31 diciembre).
  - Pendiente: fuente de datos oficial.
  - Propuesta: el addon publica en HA un sensor con el % acumulado y su tendencia.
  - Implicación: cada kWh cargado de red (también de noche) reduce el %.

## 5. Reglas de control
- Balance neto horario: lo que cuenta es la energía neta de cada hora de reloj (hh:00–hh:59), no la potencia instantánea.
- Ciclo de decisión: cada 5 min (ritmo de las entidades más lentas).
- En cada ciclo el addon:
  1. Calcula la energía de la hora en curso (generación, hogar, cargador) como diferencia de los sensores de energía acumulada respecto al inicio de la hora.
  2. Estima la energía que falta generar/consumir hasta el final de la hora.
  3. Decide arrancar, parar o ajustar amperios (6–21 A) para que el balance de la hora acabe ≥ 0 y lo más cerca posible de 0.
- Excedente < 1,4 kW: permitido cargar a 6 A durante parte de la hora (p. ej. 0,7 kW de excedente → ~30 min a 1,4 kW), siempre que el balance horario cierre sin importar de red.
- Al final de cada hora, el balance se reinicia.
- Parámetros: tiempo mínimo encendido/apagado, margen de seguridad (Wh), umbral de cobertura.

- Últimos minutos de la hora: en los últimos X min (parametrizable, p. ej. 10) solo se arranca si el excedente ya acumulado cubre la carga hasta el final de la hora. (Aprobado)

## 6. Carga forzada (modo necesidad)
- Permite programar una carga que ignora las reglas solares, a la intensidad máxima configurada (actualmente 21 A).
- Parámetros: hora de inicio, duración (y/o hora de fin) e intensidad (por defecto la máxima).
- Ejemplo: esta noche desde las 00:00 durante 4 h a 21 A.
- Controlable desde HA (entidades del addon: activar/cancelar, inicio, duración, intensidad).
- La energía de red consumida computa en la cobertura anual.
- Programación puntual (no recurrente): se introduce desde HA cuando se necesita y se elimina al terminar.
- Hora de fin fija: si hay desconexiones durante la carga, NO se recupera el tiempo perdido (el cargador sigue cargando aunque pierda la conexión WiFi).
- La programación debe persistir ante reinicios de HA/addon.
- Al terminar o cancelarse, el addon vuelve al modo solar.

## 7. Gestión de errores: desconexión del cargador
- Contexto: cobertura WiFi deficiente, microcortes frecuentes.
- Detectar entidades del cargador en estado `unavailable`/`unknown`.
- Reintentos de comandos con espera progresiva.
- Al reconectar: leer el estado real del cargador y reaplicar el estado deseado (encendido/apagado, amperios).
- Microcortes breves (< tiempo de tolerancia parametrizable): no cambiar de estado ni alertar.
- Cortes largos: notificación en HA.
- El balance horario usa contadores acumulados, por lo que tolera huecos de lectura sin perder energía.
- Registro (log) de incidencias.

## 8. Riesgos / mejoras posibles
- Los últimos minutos de cada hora dejan poco margen de corrección: aplicar margen de seguridad. Propuesta: en los últimos X min (parametrizable, p. ej. 10) solo se arranca si el excedente ya acumulado cubre la carga hasta el final de la hora.
- Exceso de potencia contratada: mitigado por el balanceo de carga del propio cargador (no es responsabilidad del addon).
- Ahorro estimado por kWh cargado con solar en lugar de con red (sin impuestos): ~0,067 € frente a valle (0,087 − 0,02), ~0,099 € frente a 0,119 y ~0,178 € frente a 0,198.
- Excedente < ~1,4 kW: no se puede cargar solo con solar (mínimo 6 A). Hay que decidir: pausar o completar con red.
- Evitar arranques/paradas frecuentes (histéresis y tiempos mínimos) para proteger cargador y coche.
- Resolución de 5 min: reacción lenta ante nubes o picos de consumo.
- Mejora opcional: lectura local Modbus TCP (integración `huawei_solar`), pendiente de viabilidad con el instalador.
