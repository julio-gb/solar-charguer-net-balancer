# Changelog

## 0.8.2
- Se descartan las lecturas de potencia imposibles (más de 30 kW). El Beny reportó 409,6 kW
  unos segundos con el coche parado y se contabilizó como 1,1 kWh cargados.
- Orden de mantenimiento por MQTT (`solar_charger_balancer/maintenance/set`) para corregir
  la energía del coche de una hora concreta.

## 0.8.1
- «Histórico diario» incluye el coste de la energía comprada a la red del coche y del hogar
  (precio de cada hora con impuesto eléctrico e IVA).
- Dashboard: sección «Comprado a la red · 30 días» con coche frente a hogar en kWh y €.

## 0.8.0
- Cuadre con la distribuidora: nuevo sensor «Diferencia con Datadis» que compara, hora a hora,
  el consumo del contador (estadísticas de la integración e-data) con el que mide el addon,
  y el maxímetro mensual de punta y valle. Se actualiza cada 3 horas.
- Dashboard: pestaña «Datadis» y corrección de la línea del objetivo en la cobertura diaria.

## 0.7.0
- «Histórico diario» incluye, por día y para el mes en curso, la energía con sol y de la red
  del consumo total, del coche y del hogar.
- Nueva entidad «Vista estadísticas» (General / Coche / Hogar) para el selector del dashboard.
- Dashboard: sección «Consumo» que une «Últimos 30 días» y «Coche este mes», con selector
  de vista y escalas automáticas.

## 0.6.1
- Nuevo sensor «Previsión factura mes»: lo ya consumido más la media de los últimos 7 días
  completos para los días que quedan (y los del mes sin datos). Incluye el coste por día
  del mes para las gráficas.
- Dashboard: tabla Hoy / Ayer / Mes sin textos cortados, gráficas de coste diario y
  acumulado con previsión, y ventana con el desglose de la factura.

## 0.6.0
- Factura estimada con impuestos: sensores «Coste hoy», «Coste ayer» y «Coste mes» con
  desglose (potencia, energía, excedentes, bono social, alquiler, impuesto eléctrico, IVA).
- «Valor solar autoconsumida»: lo que habría costado la solar consumida, al precio de su hora.
- «Descuento excedentes»: rebaja de la factura por la energía vertida, impuestos incluidos.
- Nueva sección «Factura» en Ajustes y en el dashboard.
- Precios por defecto ajustados a la factura de Octopus 3 (0,1976 / 0,1186 / 0,0872 €/kWh).

## 0.5.2
- El motivo del modo explica por qué no se carga (coche desconectado, control desactivado,
  carga forzada) en lugar de «Esperando la primera decisión».

## 0.5.1
- Nuevo sensor «Histórico diario» con los últimos 30 días (carga solar/red del coche y
  cobertura) en un atributo: las gráficas de 30 días se ven al momento, sin esperar a
  las estadísticas a largo plazo de HA.

## 0.5.0
- Dashboard rediseñado: menos tarjetas, sin datos repetidos y gráficas más altas
  (energía por hora apilada, saldo de cada hora en kWh y vista de 30 días).
- Nuevos sensores con el resumen del día anterior (cobertura solar, carga del coche
  solar y de red) para las gráficas de 30 días.

## 0.4.3
- Si la potencia del cargador deja de leerse (microcorte, reinicio), la energía de ese
  tramo se toma del contador para no infravalorar lo cargado.

## 0.4.2
- Una carga iniciada en los últimos minutos de la hora se detiene al empezar la siguiente
  aunque no haya pasado el tiempo mínimo encendido, si el nuevo saldo no la cubre.

## 0.4.1
- La energía del cargador se calcula integrando su potencia en cada lectura (opción
  «Cálculo de la energía del cargador»: potencia / contador). Evita el error de los
  contadores que avanzan a saltos de 0,1 kWh.

## 0.4.0
- Nueva estrategia por defecto «acumulado»: solo carga con energía ya vertida en la hora,
  sin contar con el sol que queda. Evita importar por la tarde, cuando baja la producción
  o sube el consumo de la casa con datos de FusionSolar atrasados.
- La estrategia anterior queda como «prevision», con un factor de prudencia configurable.
- Opción «Los sensores del hogar incluyen el cargador»: el addon resta el consumo del cargador.
- Traza de diagnóstico de cada decisión y botón «Descargar diagnóstico» en la página.
- Más tiempo de espera (30 s) para las órdenes al cargador y mensajes de error más claros.

## 0.3.1
- Corrige el error 401 al arrancar: el proceso no recibía el token del Supervisor.

## 0.3.0
- Soporte para cargadores con botones de iniciar/parar (p. ej. Beny WiFi), botón para
  enviar la intensidad y sensor con la intensidad aplicada.
- Sensor de estado del cargador: detecta si está cargando o si el coche está desconectado
  (no se envían órdenes sin coche). Estados configurables.
- Si el coche no inicia la carga tras 3 intentos (p. ej. batería llena) deja de insistir
  hasta que cambie el estado del cargador.
- La configuración anterior con un interruptor se migra automáticamente.

## 0.2.0
- Página de configuración en el panel lateral de HA (Ingress): entidades en desplegables
  filtrados por unidad, editor de tramos de tarifa y festivos, y resto de parámetros.
- Los cambios se aplican en caliente, sin reiniciar el addon.
- Validación de tarifas: sin huecos ni solapes y cubriendo hasta las 24:00.
- El addon arranca aunque falten entidades y muestra «Sin configurar».

## 0.1.1
- Icono y logo del addon.

## 0.1.0
- Primera versión: control de carga por balance neto horario, carga forzada puntual,
  tolerancia a microcortes del cargador, cobertura solar anual, SoC estimado, ahorro
  y entidades en HA por MQTT Discovery.
