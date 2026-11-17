"""MQTT notification channel (PRD 17.2).

One `MqttSession` per enabled channel: a paho 2.x client in its own network
thread (`loop_start`), connected with `connect_async` so nothing here ever
waits on the broker from the caller's thread. paho reconnects with its own
exponential backoff (`reconnect_delay_set`).

Availability: the will is `<base>/status` = `offline` (retained); `online`
(retained) is published on every (re)connect; a clean stop publishes `offline`
itself (a clean disconnect does not fire the will).

The password is never logged, returned or put in an error message.

`client_factory(client_id) -> paho-like client` is injectable so tests never
open a socket. Importing this module does not import paho; only the default
factory does.
"""

import json
import logging
import re
import threading
from datetime import datetime, timezone

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

logger = logging.getLogger(__name__)

TYPE = "mqtt"
DEFAULT_BASE_TOPIC = "std"
TEST_TIMEOUT_SECONDS = 8
PUBLISH_WAIT_SECONDS = 5
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class MqttConfig(BaseModel):
    """Non-secret MQTT settings. `extra="forbid"`: unknown keys are errors.

    `port` None resolves to 1883 (8883 with TLS) at validation, so the stored
    config always carries the port. `client_id` None means `std-<instance>`
    at connect time. The `ha_*` fields belong to Home Assistant discovery
    (notif-03); they are accepted and stored now so that step needs no config
    reshuffle, and nothing reads them yet.
    """

    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    tls: bool = False
    tls_insecure: bool = False
    username: str | None = Field(default=None, max_length=128)
    client_id: str | None = None
    base_topic: str = DEFAULT_BASE_TOPIC
    qos: int = Field(default=1, ge=0, le=1)
    keepalive: int = Field(default=60, ge=5, le=3600)
    # Reserved for notif-03 (Home Assistant discovery); unused in this step.
    ha_discovery: bool = False
    ha_prefix: str = Field(default="homeassistant", min_length=1, max_length=64)
    ha_device_prefix: str = Field(default="STD", min_length=1, max_length=32)

    @field_validator("host")
    @classmethod
    def _host(cls, v):
        v = v.strip()
        if not v or re.search(r"\s", v) or "://" in v or "/" in v:
            raise ValueError("must be a host name or IP address (no scheme, path or spaces)")
        return v

    @field_validator("username", "client_id", mode="before")
    @classmethod
    def _blank_is_none(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("client_id")
    @classmethod
    def _client_id(cls, v):
        if v is not None and not _CLIENT_ID_RE.match(v):
            raise ValueError("use 1-64 letters, digits, '.', '_' or '-'")
        return v

    @field_validator("base_topic")
    @classmethod
    def _base_topic(cls, v):
        v = v.strip().rstrip("/")
        if not v:
            raise ValueError("cannot be empty")
        if len(v) > 128:
            raise ValueError("is limited to 128 characters")
        if v.startswith("/") or v.startswith("$") or "+" in v or "#" in v or "\x00" in v or "//" in v:
            raise ValueError("must not start with '/' or '$', or contain '+', '#' or '//'")
        return v

    @model_validator(mode="after")
    def _port_default(self):
        if self.port is None:
            self.port = 8883 if self.tls else 1883
        if self.tls_insecure and not self.tls:
            raise ValueError("tls_insecure only makes sense with tls enabled")
        return self


def clean_config(config: dict) -> dict:
    """Validated, canonical config dict. Raises pydantic `ValidationError`."""
    return MqttConfig.model_validate(config).model_dump()


def defaults() -> dict:
    return MqttConfig(host="localhost").model_dump() | {"host": ""}


def error_list(exc: ValidationError) -> list[dict]:
    """pydantic errors as `{field, message}` under `config.`."""
    out = []
    for e in exc.errors():
        loc = ".".join(str(p) for p in e.get("loc", ()) if p != "__root__")
        msg = str(e.get("msg", "invalid")).removeprefix("Value error, ")
        out.append({"field": f"config.{loc}" if loc else "config", "message": msg})
    return out


def default_client_factory(client_id):
    import paho.mqtt.client as mqtt

    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)


def client_id_for(config: dict, instance_id: str, suffix: str = "") -> str:
    base = config.get("client_id") or f"std-{instance_id.replace('-', '')[:8]}"
    return f"{base}{suffix}"[:64]


def _build_client(config, secret, instance_id, factory, suffix="", will=True):
    client = factory(client_id_for(config, instance_id, suffix))
    if config.get("username"):
        client.username_pw_set(config["username"], secret or None)
    if config.get("tls"):
        client.tls_set()
        if config.get("tls_insecure"):
            client.tls_insecure_set(True)
    if will:
        client.will_set(f"{config['base_topic']}/status", "offline", qos=config["qos"], retain=True)
    client.reconnect_delay_set(min_delay=1, max_delay=60)
    return client


def _reason_failed(reason_code) -> bool:
    failed = getattr(reason_code, "is_failure", None)
    return bool(failed) if failed is not None else bool(reason_code)


def _payload(value):
    if isinstance(value, (str, bytes)):
        return value
    return json.dumps(value, separators=(",", ":"), default=str)


class MqttSession:
    """A live connection for one channel. `status()` -> {state, last_error, since}
    with state one of connecting | connected | error | stopped."""

    def __init__(self, channel_id, name, config, secret, instance_id, factory=None, on_connected=None):
        self.channel_id = channel_id
        self.name = name
        self.type = TYPE
        self.config = config
        self._secret = secret
        self._instance_id = instance_id
        self._factory = factory or default_client_factory
        self._on_connected = on_connected
        self._client = None
        self._lock = threading.Lock()
        self._state = "connecting"
        self._error = None
        self._since = datetime.now(timezone.utc)
        self._stopping = False

    # -- state --------------------------------------------------------------

    def _set(self, state, error=None):
        """Record a state change; log only when state or error actually changes
        (paho retries forever, and retries must not spam the log)."""
        with self._lock:
            if (state, error) == (self._state, self._error):
                return
            changed_state = state != self._state
            self._state, self._error = state, error
            if changed_state:
                self._since = datetime.now(timezone.utc)
        where = f"{self.config['host']}:{self.config['port']}"
        if state == "connected":
            logger.info("MQTT channel '%s' connected to %s", self.name, where)
        elif state == "error":
            logger.warning("MQTT channel '%s' (%s): %s", self.name, where, error)
        elif state == "stopped":
            logger.info("MQTT channel '%s' stopped", self.name)

    def status(self) -> dict:
        with self._lock:
            return {"state": self._state, "last_error": self._error,
                    "since": self._since.strftime("%Y-%m-%dT%H:%M:%SZ")}

    # -- lifecycle ----------------------------------------------------------

    def start(self):
        cfg = self.config
        client = _build_client(cfg, self._secret, self._instance_id, self._factory)
        client.on_connect = self._handle_connect
        client.on_disconnect = self._handle_disconnect
        client.on_connect_fail = self._handle_connect_fail
        self._client = client
        try:
            client.connect_async(cfg["host"], cfg["port"], cfg["keepalive"])
            client.loop_start()
        except Exception as exc:
            self._set("error", f"could not start: {exc}")

    def stop(self):
        """Publish `offline` (a clean disconnect does not fire the will), then
        disconnect and stop the network thread. Bounded: never waits long."""
        self._stopping = True
        client = self._client
        if client is None:
            return
        try:
            if self.status()["state"] == "connected":
                info = client.publish(self._topic("status"), "offline",
                                      qos=self.config["qos"], retain=True)
                info.wait_for_publish(timeout=2)
        except Exception as exc:
            logger.debug("MQTT channel '%s': offline publish failed: %s", self.name, exc)
        try:
            client.disconnect()
            client.loop_stop()
        except Exception as exc:
            logger.debug("MQTT channel '%s': disconnect failed: %s", self.name, exc)
        self._set("stopped")

    # -- callbacks (paho thread) --------------------------------------------

    def _handle_connect(self, client, userdata, flags, reason_code, properties=None):
        if _reason_failed(reason_code):
            self._set("error", f"broker refused the connection: {reason_code}")
            return
        self._set("connected")
        try:
            client.publish(self._topic("status"), "online", qos=self.config["qos"], retain=True)
        except Exception as exc:
            logger.warning("MQTT channel '%s': could not publish online: %s", self.name, exc)
        if self._on_connected:
            try:
                self._on_connected(self)
            except Exception:
                logger.exception("MQTT on-connect hook failed for channel '%s'", self.name)

    def _handle_disconnect(self, client, userdata, disconnect_flags, reason_code=None, properties=None):
        if self._stopping:
            return
        self._set("error", f"disconnected from the broker: {reason_code}")

    def _handle_connect_fail(self, client, userdata):
        if self._stopping:
            return
        self._set("error", f"cannot reach the broker at {self.config['host']}:{self.config['port']}")

    # -- publishing ---------------------------------------------------------

    def _topic(self, suffix):
        return f"{self.config['base_topic']}/{suffix}"

    def publish(self, event: dict):
        """Publish one event `{"topic": <suffix under base>, "payload": str|dict|list,
        "retain": bool (default False)}`. Anything else is ignored. Never raises."""
        try:
            suffix = event.get("topic")
            if not isinstance(suffix, str) or not suffix.strip("/"):
                return
            self._client.publish(self._topic(suffix.strip("/")), _payload(event.get("payload", "")),
                                 qos=self.config["qos"], retain=bool(event.get("retain", False)))
        except Exception as exc:
            logger.debug("MQTT channel '%s': publish failed: %s", self.name, exc)


def test_connection(config: dict, secret, instance_id: str, factory=None) -> tuple[bool, str]:
    """Connect with a throwaway client, publish a non-retained JSON message to
    `<base>/test`, report `(ok, message)`. The client id gets `-test` so the
    broker does not drop the live connection that shares the channel's id.
    Blocks up to ~13s (called from a request thread, never the publisher)."""
    factory = factory or default_client_factory
    topic = f"{config['base_topic']}/test"
    where = f"{config['host']}:{config['port']}"
    result = {}
    done = threading.Event()
    try:
        client = _build_client(config, secret, instance_id, factory, suffix="-test", will=False)
    except Exception as exc:
        return False, f"Could not set up the connection: {exc}"

    def on_connect(client, userdata, flags, reason_code, properties=None):
        if _reason_failed(reason_code):
            result["error"] = f"broker refused the connection: {reason_code}"
        done.set()

    def on_connect_fail(client, userdata):
        result.setdefault("error", f"cannot reach the broker at {where}")
        done.set()

    client.on_connect = on_connect
    client.on_connect_fail = on_connect_fail
    started = False
    try:
        client.connect_async(config["host"], config["port"], config["keepalive"])
        client.loop_start()
        started = True
        if not done.wait(TEST_TIMEOUT_SECONDS):
            return False, f"No answer from {where} within {TEST_TIMEOUT_SECONDS} seconds."
        if "error" in result:
            return False, result["error"][0].upper() + result["error"][1:] + "."
        body = json.dumps({
            "message": "Test message from Service Tracker Dashboard",
            "instance": instance_id,
            "sent_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        info = client.publish(topic, body, qos=config["qos"], retain=False)
        info.wait_for_publish(timeout=PUBLISH_WAIT_SECONDS)
        if getattr(info, "rc", 0) != 0 or not info.is_published():
            return False, f"Connected to {where}, but the test message was not delivered to {topic}."
        return True, f"Published a test message to {topic} on {where}."
    except Exception as exc:
        return False, f"Test failed: {exc}"
    finally:
        try:
            client.disconnect()
            if started:
                client.loop_stop()
        except Exception:
            pass


class MqttChannelType:
    """Registry entry (see `notify.CHANNEL_TYPES`): validator, defaults,
    `test()` and `publish()`."""

    type = TYPE
    label = "MQTT"

    @staticmethod
    def defaults():
        return defaults()

    @staticmethod
    def validate(config):
        return clean_config(config)

    @staticmethod
    def errors(exc):
        return error_list(exc)

    @staticmethod
    def open_session(channel_id, name, config, secret, instance_id, factory, on_connected):
        return MqttSession(channel_id, name, config, secret, instance_id, factory, on_connected)

    @staticmethod
    def test(config, secret, instance_id, factory=None):
        return test_connection(config, secret, instance_id, factory)

    @staticmethod
    def publish(session, event):
        session.publish(event)


