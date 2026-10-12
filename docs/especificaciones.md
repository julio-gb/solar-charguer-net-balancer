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

- Coche: Citroën ë-C4 (2021). Batería ~50 kWh brutos / ~46 kWh útiles (dato de fabricante, a confirmar). Cargador embarcado ≥ 7,4 kW monofásico (21 A no limita).
- Instalación FV: ~2,45 kWp; potencia máxima observada ~1,8 kW.
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

## 4. Uso del coche
- Laborables: conectado desde ~14:30. Fines de semana: casi todo el día.
- ~550 km/mes (algunos meses ~1.100 km por viajes).
- Necesidad estimada: ~90–110 kWh/mes (≈ 3–3,5 kWh/día); el doble en meses de viaje. Estimación con ~16–18 kWh/100 km + pérdidas; a validar con datos reales.

- Nivel de batería (SoC) del coche: entidad disponible pero se actualiza poco; fiable al apagar el coche (envía SoC y ubicación).
  - Propuesta: tomar el SoC recibido al aparcar como punto de partida y estimar el SoC durante la carga sumando la energía del cargador × eficiencia / capacidad útil (parámetros configurables).
  - Opcional: aviso si el SoC estimado baja de un umbral y no hay previsión solar suficiente.

## 4b. Objetivos
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

## 8. Dashboard de seguimiento (propuesta, pendiente de validar)
- Estado actual: modo (solar / forzado / pausado / error), amperios, potencia FV, hogar, cargador, red.
- Hora en curso: balance neto acumulado (Wh), previsión al cierre, minutos restantes.
- Cobertura solar: hoy, mes, año (vs. objetivo 60 %), con proyección a fin de año.
- Gráficos: generación vs. consumo (hogar + cargador) y balance por hora (día/semana/mes).
- Energía cargada al coche: total y % solar; SoC estimado.
- Ahorro estimado (€) según tarifa y compensación configuradas.
- Controles: carga forzada (inicio, duración, intensidad, cancelar), activar/desactivar addon.
- Incidencias: últimas desconexiones del cargador y log de decisiones.
- Lovelace con tarjetas HACS (ApexCharts, Mushroom; instalación a verificar).
- Uso en móvil y escritorio: diseño responsive.
- Maqueta visual previa para validación.

## 9. Arquitectura
- Exposición de entidades del addon en HA: MQTT Discovery (broker Mosquitto ya instalado).

## 10. Riesgos / mejoras posibles
- Potencia FV pequeña (máx. ~1,8 kW) frente al mínimo de carga (1,4 kW): el excedente rara vez supera 1,4 kW de forma continua; el balance horario (carga a 6 A durante parte de la hora) es clave.
- Objetivo del 60 % potencialmente inalcanzable con la instalación actual sin batería: validar con consumo anual del hogar y producción anual real (datos no disponibles por ahora).
- Comportamiento del ë-C4 ante paradas/arranques repetidos (posible que no reanude tras una pausa larga): validar en pruebas reales.
- Invierno: entre 14:30 y la puesta de sol queda poco margen solar en laborables.
- Los últimos minutos de cada hora dejan poco margen de corrección: aplicar margen de seguridad. Propuesta: en los últimos X min (parametrizable, p. ej. 10) solo se arranca si el excedente ya acumulado cubre la carga hasta el final de la hora.
- Exceso de potencia contratada: mitigado por el balanceo de carga del propio cargador (no es responsabilidad del addon).
- Ahorro estimado por kWh cargado con solar en lugar de con red (sin impuestos): ~0,067 € frente a valle (0,087 − 0,02), ~0,099 € frente a 0,119 y ~0,178 € frente a 0,198.
- Excedente < ~1,4 kW: no se puede cargar solo con solar (mínimo 6 A). Hay que decidir: pausar o completar con red.
- Evitar arranques/paradas frecuentes (histéresis y tiempos mínimos) para proteger cargador y coche.
- Resolución de 5 min: reacción lenta ante nubes o picos de consumo.
- Mejora opcional: lectura local Modbus TCP (integración `huawei_solar`), pendiente de viabilidad con el instalador.

## 11. Estado de implementación (v0.1.0)
- Implementado: balance neto horario, ventana final de la hora, tiempos mínimos, carga forzada puntual,
  tolerancia a microcortes y reaplicación de estado, cobertura anual con proyección, SoC estimado,
  ahorro estimado, entidades MQTT Discovery y dashboard (`dashboards/solar_charger.yaml`).
- Añadido en desarrollo: la hora anterior se cierra con 10 min de retraso (parametrizable) y las
  lecturas tardías se reparten entre horas según su marca de tiempo.
- No incluido: término de potencia (no afecta a las decisiones de carga).
- Pendiente de validar en instalación real: construcción de la imagen Docker, nombres de entidades
  de la integración Beny WiFi y comportamiento del ë-C4 ante pausas.
