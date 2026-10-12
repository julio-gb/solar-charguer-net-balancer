# Changelog

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
