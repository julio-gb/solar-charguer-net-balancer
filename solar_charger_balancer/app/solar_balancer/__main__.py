"""Punto de entrada del addon."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import web

from .config import Config, ConfigError
from .ha_client import HAClient, HAError, get_mqtt_service, supervisor_token
from .mqtt_bridge import MqttBridge
from .service import Balancer
from .settings import check, load_raw, validate
from .storage import load_state
from .web import create_app

_LOGGER = logging.getLogger("solar_balancer")
INGRESS_PORT = 8099


async def _retry(what: str, func):
    delay = 5
    while True:
        try:
            return await func()
        except (HAError, aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.warning("%s no disponible (%s); reintento en %s s", what, err, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 120)


def load_effective() -> tuple[Config | None, str | None]:
    """Configuración efectiva (opciones del addon + página web) o el motivo por el que no es válida."""
    try:
        clean, errors = check(load_raw())
        if errors:
            return None, "; ".join(f"{k}: {v}" for k, v in errors.items())
        return validate(clean), None
    except (ConfigError, OSError, ValueError, KeyError) as err:
        return None, str(err)


class Runner:
    """Mantiene el ciclo de control y lo reinicia en caliente cuando se guarda la configuración."""

    def __init__(self, ha: HAClient, tz: ZoneInfo, bridge: MqttBridge):
        self.ha, self.tz, self.bridge = ha, tz, bridge
        self.balancer: Balancer | None = None
        self.state: dict | None = None
        self.error: str | None = None
        self.restart = asyncio.Event()

    def handle_command(self, key: str, payload: str) -> None:
        if self.balancer:
            self.balancer.handle_command(key, payload)

    def status(self) -> dict:
        if self.balancer:
            return {"configured": True, "mode": self.balancer.mode}
        return {"configured": False, "error": self.error}

    def diagnostics(self) -> dict:
        if self.balancer:
            return self.balancer.diagnostics()
        return {"modo": "Sin configurar", "error": self.error}

    def reload(self) -> None:
        self.restart.set()

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            self.restart.clear()
            config, self.error = load_effective()
            if config is None:
                _LOGGER.warning("Configuración incompleta (%s). Abre la página del addon para completarla.", self.error)
                self.bridge.publish_unconfigured(self.error)
                await _wait_any(stop, self.restart)
                continue
            logging.getLogger().setLevel(config.log_level.upper())
            balancer = Balancer(config, self.ha, self.tz, self.bridge)
            balancer.restore(self.state if self.state is not None else load_state(), balancer.now())
            self.bridge.set_number_limits({"forced_current": (config.min_current, config.max_current)})
            self.balancer = balancer
            _LOGGER.info("Control en marcha con la configuración actual")
            session_stop = asyncio.Event()
            watcher = asyncio.ensure_future(_relay(session_stop, stop, self.restart))
            try:
                await balancer.run(session_stop)
            finally:
                watcher.cancel()
                self.state = balancer.snapshot()
                self.balancer = None


async def _wait_any(*events: asyncio.Event) -> None:
    tasks = [asyncio.ensure_future(e.wait()) for e in events]
    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in tasks:
        t.cancel()


async def _relay(target: asyncio.Event, *sources: asyncio.Event) -> None:
    await _wait_any(*sources)
    target.set()


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    if not supervisor_token():
        _LOGGER.error("No se encuentra SUPERVISOR_TOKEN: el addon no puede comunicarse con Home Assistant")
    async with aiohttp.ClientSession() as session:
        ha = HAClient(session)
        ha_config = await _retry("Home Assistant", ha.get_config)
        tz = ZoneInfo(ha_config.get("time_zone") or "Europe/Madrid")
        mqtt_conf = await _retry("Servicio MQTT", lambda: get_mqtt_service(session))

        runner: Runner
        bridge = MqttBridge(loop, lambda key, payload: runner.handle_command(key, payload))
        runner = Runner(ha, tz, bridge)
        bridge.connect(mqtt_conf.get("host", "core-mosquitto"), int(mqtt_conf.get("port", 1883)),
                       mqtt_conf.get("username"), mqtt_conf.get("password"))

        app = create_app(ha, runner.reload, runner.status, diagnostics=runner.diagnostics)
        web_runner = web.AppRunner(app)
        await web_runner.setup()
        await web.TCPSite(web_runner, "0.0.0.0", INGRESS_PORT).start()
        _LOGGER.info("Solar Charger Balancer iniciado (zona horaria %s); página de configuración activa", tz)
        try:
            await runner.run(stop)
        finally:
            await web_runner.cleanup()
            bridge.stop()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
