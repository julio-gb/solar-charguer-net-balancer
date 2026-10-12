"""Entidades del addon en Home Assistant mediante MQTT Discovery."""
from __future__ import annotations

import asyncio
import json
import logging
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)

DEVICE_NAME = "Solar Charger"
PREFIX = "solar_charger_balancer"
DISCOVERY = "homeassistant"
AVAILABILITY = f"{PREFIX}/status"


def slugify(text: str) -> str:
    """Aproximación al slug que HA usa para generar entity_id a partir del nombre."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    out, prev_us = [], False
    for ch in ascii_text.lower():
        if ch.isalnum():
            out.append(ch)
            prev_us = False
        elif not prev_us:
            out.append("_")
            prev_us = True
    return "".join(out).strip("_")


@dataclass(frozen=True)
class Entity:
    component: str  # sensor, binary_sensor, switch, number, text, button
    key: str
    name: str
    extra: dict = field(default_factory=dict)

    @property
    def entity_id(self) -> str:
        return f"{self.component}.{slugify(DEVICE_NAME + ' ' + self.name)}"

    @property
    def state_topic(self) -> str:
        return f"{PREFIX}/{self.key}/state"

    @property
    def command_topic(self) -> str:
        return f"{PREFIX}/{self.key}/set"


def _sensor(key, name, unit=None, device_class=None, state_class=None, icon=None, precision=None, attrs=False):
    extra = {}
    if unit:
        extra["unit_of_measurement"] = unit
    if device_class:
        extra["device_class"] = device_class
    if state_class:
        extra["state_class"] = state_class
    if icon:
        extra["icon"] = icon
    if precision is not None:
        extra["suggested_display_precision"] = precision
    if attrs:
        extra["json_attributes_topic"] = f"{PREFIX}/{key}/attributes"
    return Entity("sensor", key, name, extra)


ENTITIES: list[Entity] = [
    _sensor("mode", "Modo", icon="mdi:solar-power-variant", attrs=True),
    _sensor("power_generation", "Potencia placas", "kW", "power", "measurement", "mdi:solar-panel", 2),
    _sensor("power_home", "Potencia hogar", "kW", "power", "measurement", "mdi:home-lightning-bolt", 2),
    _sensor("power_charger", "Potencia cargador", "kW", "power", "measurement", "mdi:ev-station", 2),
    _sensor("power_grid", "Potencia red", "kW", "power", "measurement", "mdi:transmission-tower", 2),
    _sensor("target_current", "Intensidad objetivo", "A", "current", "measurement", precision=0),
    _sensor("hour_balance", "Balance hora", "Wh", None, None, "mdi:scale-balance", 0),
    _sensor("hour_forecast", "Previsión cierre hora", "Wh", None, None, "mdi:crystal-ball", 0),
    _sensor("hour_minutes_left", "Minutos restantes hora", "min", None, "measurement", "mdi:timer-sand", 0),
    _sensor("hour_generation", "Generación hora", "kWh", "energy", "total_increasing", precision=3),
    _sensor("hour_home", "Consumo hogar hora", "kWh", "energy", "total_increasing", precision=3),
    _sensor("hour_charger", "Consumo cargador hora", "kWh", "energy", "total_increasing", precision=3),
    _sensor("hour_balance_closed", "Saldo última hora", "Wh", None, None, "mdi:history", 0, attrs=True),
    _sensor("coverage_today", "Cobertura solar hoy", "%", None, "measurement", "mdi:solar-power", 0),
    _sensor("coverage_month", "Cobertura solar mes", "%", None, "measurement", "mdi:solar-power", 0),
    _sensor("coverage_year", "Cobertura solar año", "%", None, "measurement", "mdi:solar-power", 1),
    _sensor("coverage_year_projection", "Proyección cobertura año", "%", None, "measurement", "mdi:chart-line", 1),
    _sensor("self_consumed_year", "Autoconsumo año", "kWh", "energy", "total_increasing", precision=0),
    _sensor("consumption_year", "Consumo total año", "kWh", "energy", "total_increasing", precision=0),
    _sensor("kwh_to_target", "Faltan para objetivo", "kWh", None, None, "mdi:flag-checkered", 0),
    _sensor("ev_today", "Coche cargado hoy", "kWh", "energy", "total_increasing", precision=2),
    _sensor("ev_solar_share_today", "Coche solar hoy", "%", None, "measurement", "mdi:car-electric", 0),
    _sensor("ev_month", "Coche cargado mes", "kWh", "energy", "total_increasing", precision=1),
    _sensor("ev_solar_share_month", "Coche solar mes", "%", None, "measurement", "mdi:car-electric", 0),
    _sensor("soc_estimated", "Batería coche estimada", "%", "battery", "measurement", precision=0, attrs=True),
    _sensor("savings_today", "Ahorro hoy", "EUR", "monetary", None, precision=2),
    _sensor("savings_month", "Ahorro mes", "EUR", "monetary", None, precision=2),
    _sensor("savings_year", "Ahorro año", "EUR", "monetary", None, precision=2),
    _sensor("current_price", "Precio actual", "EUR/kWh", None, None, "mdi:cash", 3),
    _sensor("forced_status", "Carga forzada estado", icon="mdi:calendar-clock"),
    _sensor("last_event", "Último evento", icon="mdi:text-box-outline", attrs=True),
    Entity("binary_sensor", "charger_online", "Cargador en línea", {"device_class": "connectivity"}),
    Entity("switch", "enabled", "Control automático", {"icon": "mdi:robot"}),
    Entity("text", "forced_start", "Carga forzada inicio",
           {"icon": "mdi:clock-start", "pattern": r"^\s*(\d{4}-\d{2}-\d{2}[ T])?\d{1,2}:\d{2}\s*$", "max": 20}),
    Entity("number", "forced_hours", "Carga forzada duración",
           {"min": 0.5, "max": 12, "step": 0.5, "unit_of_measurement": "h", "mode": "box", "icon": "mdi:timer"}),
    Entity("number", "forced_current", "Carga forzada intensidad",
           {"step": 1, "unit_of_measurement": "A", "mode": "slider", "icon": "mdi:current-ac"}),
    Entity("button", "forced_schedule", "Programar carga forzada", {"icon": "mdi:calendar-plus"}),
    Entity("button", "forced_cancel", "Cancelar carga forzada", {"icon": "mdi:calendar-remove"}),
]

BY_KEY = {e.key: e for e in ENTITIES}
COMMANDABLE = {"switch", "number", "text", "button"}


class MqttBridge:
    def __init__(self, loop: asyncio.AbstractEventLoop, on_command: Callable[[str, str], None],
                 number_limits: dict[str, tuple[float, float]] | None = None):
        self._loop = loop
        self._on_command = on_command
        self._number_limits = number_limits or {}
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=PREFIX)
        self._client.will_set(AVAILABILITY, "offline", retain=True)
        self._client.on_connect = self._handle_connect
        self._client.on_message = self._handle_message
        self._last: dict[str, str] = {}

    def connect(self, host: str, port: int, username: str | None, password: str | None) -> None:
        if username:
            self._client.username_pw_set(username, password)
        self._client.reconnect_delay_set(1, 60)
        self._client.connect_async(host, port, keepalive=60)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.publish(AVAILABILITY, "offline", retain=True)
        self._client.loop_stop()
        self._client.disconnect()

    def _device(self) -> dict:
        return {"identifiers": [PREFIX], "name": DEVICE_NAME, "manufacturer": "Solar Charger Net Balancer",
                "model": "Addon Home Assistant", "sw_version": "0.2.0"}

    def _discovery(self, entity: Entity) -> dict:
        payload: dict[str, Any] = {
            "name": entity.name,
            "unique_id": f"{PREFIX}_{entity.key}",
            "device": self._device(),
            "availability_topic": AVAILABILITY,
            "has_entity_name": True,
            **entity.extra,
        }
        if entity.component != "button":
            payload["state_topic"] = entity.state_topic
        if entity.component in COMMANDABLE:
            payload["command_topic"] = entity.command_topic
        if entity.component in ("binary_sensor", "switch"):
            payload.update({"payload_on": "ON", "payload_off": "OFF"})
        if entity.key in self._number_limits:
            payload["min"], payload["max"] = self._number_limits[entity.key]
        return payload

    def set_number_limits(self, limits: dict[str, tuple[float, float]]) -> None:
        """Actualiza los límites de las entidades number y vuelve a publicar su descubrimiento."""
        if limits == self._number_limits:
            return
        self._number_limits = dict(limits)
        if self._client.is_connected():
            for key in limits:
                entity = BY_KEY[key]
                topic = f"{DISCOVERY}/{entity.component}/{PREFIX}/{entity.key}/config"
                self._client.publish(topic, json.dumps(self._discovery(entity)), retain=True)

    def publish_unconfigured(self, reason: str | None) -> None:
        self.publish_state("mode", "Sin configurar", {"motivo": reason})

    def _handle_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            _LOGGER.error("Conexión MQTT rechazada: %s", reason_code)
            return
        _LOGGER.info("Conectado a MQTT; publicando entidades")
        for entity in ENTITIES:
            topic = f"{DISCOVERY}/{entity.component}/{PREFIX}/{entity.key}/config"
            client.publish(topic, json.dumps(self._discovery(entity)), retain=True)
            if entity.component in COMMANDABLE:
                client.subscribe(entity.command_topic)
        client.publish(AVAILABILITY, "online", retain=True)
        for topic, value in self._last.items():
            client.publish(topic, value, retain=True)

    def _handle_message(self, client, userdata, msg):
        key = msg.topic.split("/")[1]
        payload = msg.payload.decode("utf-8", "ignore")
        self._loop.call_soon_threadsafe(self._on_command, key, payload)

    def publish_state(self, key: str, value: Any, attributes: dict | None = None) -> None:
        entity = BY_KEY[key]
        if value is None:
            text = "unknown" if entity.component == "sensor" else ""
        elif isinstance(value, bool):
            text = "ON" if value else "OFF"
        elif isinstance(value, float):
            text = f"{value:.4f}".rstrip("0").rstrip(".")
        else:
            text = str(value)
        self._send(entity.state_topic, text)
        if attributes is not None:
            self._send(f"{PREFIX}/{key}/attributes", json.dumps(attributes, ensure_ascii=False, default=str))

    def _send(self, topic: str, payload: str) -> None:
        if self._last.get(topic) == payload:
            return
        self._last[topic] = payload
        self._client.publish(topic, payload, retain=True)
