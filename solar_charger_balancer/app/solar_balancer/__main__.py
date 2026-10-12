"""Punto de entrada del addon."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from zoneinfo import ZoneInfo

import aiohttp

from .config import ConfigError, load_config
from .ha_client import HAClient, HAError, get_mqtt_service
from .mqtt_bridge import MqttBridge
from .service import Balancer
from .storage import load_state

_LOGGER = logging.getLogger("solar_balancer")


async def _retry(what: str, func):
    delay = 5
    while True:
        try:
            return await func()
        except (HAError, aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.warning("%s no disponible (%s); reintento en %s s", what, err, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 120)


async def main() -> int:
    try:
        config = load_config()
    except (ConfigError, OSError, ValueError, KeyError) as err:
        logging.basicConfig(level=logging.INFO)
        _LOGGER.error("Configuración no válida: %s", err)
        return 1
    logging.basicConfig(level=config.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    async with aiohttp.ClientSession() as session:
        ha = HAClient(session)
        ha_config = await _retry("Home Assistant", ha.get_config)
        tz = ZoneInfo(ha_config.get("time_zone") or "Europe/Madrid")
        mqtt_conf = await _retry("Servicio MQTT", lambda: get_mqtt_service(session))

        balancer = Balancer(config, ha, tz)
        balancer.restore(load_state(), balancer.now())
        bridge = MqttBridge(loop, balancer.handle_command,
                            {"forced_current": (config.min_current, config.max_current)})
        balancer.pub = bridge
        bridge.connect(mqtt_conf.get("host", "core-mosquitto"), int(mqtt_conf.get("port", 1883)),
                       mqtt_conf.get("username"), mqtt_conf.get("password"))
        _LOGGER.info("Solar Charger Balancer iniciado (zona horaria %s)", tz)
        try:
            await balancer.run(stop)
        finally:
            bridge.stop()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
