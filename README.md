# Solar Charger Net Balancer

Addon de Home Assistant para cargar el coche eléctrico con los excedentes solares
aplicando el balance neto horario.

- Addon: [`solar_charger_balancer/`](solar_charger_balancer/) · documentación en [`DOCS.md`](solar_charger_balancer/DOCS.md)
- Dashboard: [`dashboards/solar_charger.yaml`](dashboards/solar_charger.yaml)
- Especificaciones: [`docs/especificaciones.md`](docs/especificaciones.md)

## Instalación
1. Ajustes → Complementos → Tienda → ⋮ → Repositorios → añadir
   `https://github.com/julio-gb/solar-charguer-net-balancer`.
2. Instalar **Solar Charger Balancer**, rellenar la configuración (entidades, tarifas,
   compensación…) e iniciar.
3. Crear un panel nuevo y pegar `dashboards/solar_charger.yaml` en el editor en bruto.

## Desarrollo
```bash
pip install aiohttp paho-mqtt pytest pyyaml
python -m pytest tests
```
