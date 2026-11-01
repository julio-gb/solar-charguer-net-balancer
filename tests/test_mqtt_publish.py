import asyncio

from solar_balancer.mqtt_bridge import MqttBridge


class FakeClient:
    def __init__(self):
        self.sent = []

    def publish(self, topic, payload, retain=False):
        self.sent.append((topic, payload))


def _bridge():
    bridge = MqttBridge(asyncio.new_event_loop(), lambda *_: None)
    bridge._client = FakeClient()
    return bridge


def test_redondea_a_la_precision_mostrada_y_no_repite():
    bridge = _bridge()
    bridge.publish_state("power_home", 0.2491)   # precisión 2 -> "0.25"
    bridge.publish_state("power_home", 0.2523)   # sigue siendo "0.25": no se publica
    bridge.publish_state("power_home", 0.2651)   # "0.27"
    assert [p for _, p in bridge._client.sent] == ["0.25", "0.27"]


def test_precision_cero_y_menos_cero():
    bridge = _bridge()
    bridge.publish_state("hour_balance", 12.4)
    bridge.publish_state("hour_balance", -0.3)
    assert [p for _, p in bridge._client.sent] == ["12", "0"]


def test_sensor_sin_dato_se_publica_como_none():
    bridge = _bridge()
    bridge.publish_state("power_generation", None)
    assert bridge._client.sent == [("solar_charger_balancer/power_generation/state", "None")]
