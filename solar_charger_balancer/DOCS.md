# Solar Charger Balancer

Carga el coche con los excedentes de las placas usando el **balance neto horario**:
lo que cuenta es que cada hora de reloj (hh:00–hh:59) cierre sin importar energía neta
de la red, aunque dentro de la hora haya momentos de importación.

## Requisitos
- Broker MQTT (complemento Mosquitto) e integración MQTT activa.
- Entidades del inversor (potencia y energía acumulada de placas y hogar).
- Integración del cargador con interruptor (`switch`) e intensidad (`number`).
- Para el dashboard: Mushroom y ApexCharts Card (HACS).

## Configuración
Abre **Solar Charger** en la barra lateral de HA. Cada entidad se elige en un desplegable
que solo muestra las compatibles (potencias en W/kW, energías en Wh/kWh, interruptores,
intensidades en A, batería en %). Marca «Mostrar todas» si la tuya no aparece.
Ahí también se editan tarifas, festivos y el resto de parámetros; al guardar se aplican
sin reiniciar. La pestaña «Configuración» del addon solo aporta los valores iniciales:
lo guardado en la página tiene prioridad.

## Cargador Beny WiFi (ejemplo)
| Campo | Entidad |
|---|---|
| Iniciar carga | `button.<serie>_start_charging` |
| Parar carga | `button.<serie>_stop_charging` |
| Estado del cargador | `sensor.<serie>_charger_state` |
| Estados «cargando» | `charging` |
| Estados «coche desconectado» | `unplugged` |
| Intensidad a enviar | `number.<serie>_max_current_control` |
| Botón para enviar la intensidad | `button.<serie>_send_max_current` |
| Intensidad actual | `sensor.<serie>_max_current` |

Si paras la carga desde la app Z-Box con el control automático activado, el addon la
volverá a iniciar si hay excedente. Desactiva «Control automático» para mandar tú.

## Cómo decide (cada 5 min por defecto)
1. Calcula la energía de la hora en curso con los contadores acumulados.
2. Disponible = saldo de la hora + (P. placas − P. hogar) × tiempo restante − margen.
3. Si el disponible permite ≥ 6 A hasta el final de la hora, ajusta la intensidad (6–21 A).
4. Si no, carga a 6 A mientras el saldo lo permita y pausa para que la hora cierre ≥ 0.
5. En los últimos minutos (10 por defecto) solo arranca si el saldo **ya acumulado** cubre la carga.
6. Respeta tiempos mínimos de encendido/apagado para no hacer ciclos continuos.

Las lecturas que llegan tarde tras el cambio de hora se reparten entre la hora anterior y
la nueva según su marca de tiempo (la hora anterior se cierra 10 min después).

## Carga forzada
Desde las entidades del addon: indica el **inicio** (`AAAA-MM-DD HH:MM` o `HH:MM`), la
**duración** y la **intensidad**, y pulsa **Programar carga forzada**. Es puntual: ignora las
reglas solares, termina a la hora fijada aunque haya cortes y después vuelve al modo solar.
**Cancelar carga forzada** la anula.

## Microcortes del cargador
- Cortes más cortos que la tolerancia: no generan aviso.
- Al reconectar, el addon lee el estado real y reenvía el estado deseado (con reintentos espaciados).
- Si el corte supera el tiempo de aviso, crea una notificación en HA.

## Control automático
El interruptor **Control automático** permite desactivar el addon sin pararlo; mientras
está apagado no envía órdenes al cargador (la carga forzada programada sí se ejecuta).
Si cambias la carga desde la app Z-Box con el control activado, el addon volverá a
aplicar su propio estado en el siguiente ciclo.

## Datos que guarda
`/data/state.json`: histórico horario (≈ 400 días), configuración de la carga forzada,
último SoC real y registro de eventos. Sobrevive a reinicios.

## Limitaciones conocidas (v0.1)
- La previsión dentro de la hora supone que la potencia solar y del hogar se mantienen.
- Comprobar en real que el ë-C4 reanuda la carga tras pausas largas.
- El ahorro se calcula sin impuestos: energía solar cargada × (precio del tramo − compensación).
