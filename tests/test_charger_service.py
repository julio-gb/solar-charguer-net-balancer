import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from solar_balancer.charger import Charger
from solar_balancer.service import Balancer

from helpers import make_config

TZ = ZoneInfo("Europe/Madrid")


class FakeHA:
    def __init__(self):
        self.states = {}
        self.calls = []

    def set(self, entity, state, unit=None, stamp="2026-10-10T13:00:00+02:00"):
        attrs = {"unit_of_measurement": unit} if unit else {}
        self.states[entity] = {"state": str(state), "attributes": attrs, "last_updated": stamp}

    async def get_state(self, entity_id):
        return self.states.get(entity_id)

    async def call_service(self, domain, service, data):
        self.calls.append((domain, service, data))
        entity = data["entity_id"]
        if service == "set_value":
            self.states[entity]["state"] = str(data["value"])
        elif service in ("turn_on", "turn_off"):
            self.states[entity]["state"] = "on" if service == "turn_on" else "off"

    async def notify(self, *args):
        self.calls.append(("notify",))

    async def dismiss(self, *args):
        self.calls.append(("dismiss",))


def run(coro):
    return asyncio.run(coro)


def test_charger_reapplies_after_reconnect():
    ha = FakeHA()
    ha.set("switch.ev", "off")
    ha.set("number.ev", 6)
    ch = Charger(ha, "switch.ev", "number.ev")
    now = datetime(2026, 10, 10, 13, 0, tzinfo=TZ)
    ch.set_desired(True, 8)
    assert ch.read(None, None, now) == "offline"
    assert run(ch.reconcile(now)) is None and ha.calls == []
    assert ch.read(ha.states["switch.ev"], ha.states["number.ev"], now + timedelta(seconds=40)) == "online"
    assert run(ch.reconcile(now + timedelta(seconds=40))) == "8 A, encender"
    ch.read(ha.states["switch.ev"], ha.states["number.ev"], now)
    assert ch.in_sync()


class Clock:
    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t


def make_balancer():
    ha = FakeHA()
    for e, v, u in [("sensor.pv_power", 1.0, "kW"), ("sensor.home_power", 300, "W"), ("sensor.ev_power", 0, "kW"),
                    ("sensor.pv_energy", 1000.0, "kWh"), ("sensor.home_energy", 500.0, "kWh"),
                    ("sensor.ev_energy", 200.0, "kWh"), ("switch.ev_charger", "off", None), ("number.ev_current", 6, "A")]:
        ha.set(e, v, u)
    b = Balancer(make_config(), ha, TZ)
    b.now = Clock(datetime(2026, 10, 10, 13, 0, 30, tzinfo=TZ))
    return b, ha


def test_poll_starts_charging_with_surplus_and_closes_hour():
    b, ha = make_balancer()
    run(b.poll())
    assert b.mode == "Solar · cargando"
    assert ("switch", "turn_on", {"entity_id": "switch.ev_charger"}) in ha.calls
    # FusionSolar reporta a las 14:03 la energía de 13:58–14:03: 2/5 corresponden a las 13 h.
    ha.set("sensor.pv_energy", 1000.0, "kWh", "2026-10-10T13:58:00+02:00")
    b.now.t = datetime(2026, 10, 10, 13, 59, 0, tzinfo=TZ)
    run(b.poll())
    ha.set("sensor.pv_energy", 1000.1, "kWh", "2026-10-10T14:03:00+02:00")
    b.now.t = datetime(2026, 10, 10, 14, 3, 30, tzinfo=TZ)
    run(b.poll())
    assert b.records == [] and b.prev is not None          # la hora 13 sigue abierta
    b.now.t = datetime(2026, 10, 10, 14, 10, 30, tzinfo=TZ)
    run(b.poll())
    assert len(b.records) == 1
    assert round(b.records[0].gen, 3) == 0.04 and round(b.acc["gen"], 3) == 0.06


def test_forced_charge_commands_and_fixed_end():
    b, ha = make_balancer()
    b.handle_command("forced_start", "2026-10-10 13:00")
    b.handle_command("forced_hours", "1")
    b.handle_command("forced_current", "40")      # se limita a 21 A
    b.handle_command("forced_schedule", "PRESS")
    run(b.poll())
    assert b.mode == "Carga forzada" and b.charger.desired_current == 21
    b.now.t = datetime(2026, 10, 10, 14, 0, 0, tzinfo=TZ)
    run(b.poll())
    assert b.forced is None and b.mode.startswith("Solar")


def test_disabled_control_leaves_charger_alone():
    b, ha = make_balancer()
    b.handle_command("enabled", "OFF")
    run(b.poll())
    assert ha.calls == []


def test_state_roundtrip():
    b, _ = make_balancer()
    run(b.poll())
    b2, _ = make_balancer()
    b2.restore(b.snapshot(), b.now.t)
    assert b2.hour == b.hour and b2.counters["gen"].last == 1000.0
