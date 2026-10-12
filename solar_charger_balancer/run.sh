#!/usr/bin/with-contenv bashio
# with-contenv carga las variables del contenedor (incluido SUPERVISOR_TOKEN).
cd /app || exit 1
exec python3 -m solar_balancer
