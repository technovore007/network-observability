"""Persistent MAC-address-based device identity registry."""

import copy
import json
import logging
import os
import re
import tempfile
import threading

from datetime import datetime, timezone
from pathlib import Path


logger = logging.getLogger(__name__)

MAC_PATTERN = re.compile(
    r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$"
)

OBSERVABLE_FIELDS = {
    "ip_address",
    "hostname",
    "vendor",
    "connection_type",
    "router",
    "access_point",
    "interface",
    "ssid",
    "frequency_band",
    "signal_strength",
    "status",
    "vlan_id",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def normalize_mac(mac_address):
    """Normalize a MAC address to lowercase colon-separated notation."""

    if not isinstance(mac_address, str):
        raise ValueError("MAC address must be a string")

    normalized = mac_address.strip().lower().replace("-", ":")

    if not MAC_PATTERN.fullmatch(normalized):
        raise ValueError(f"Invalid MAC address: {mac_address!r}")

    return normalized


class DeviceRegistry:
    """Thread-safe persistent registry of observed network devices.

    Device identity is keyed by MAC address.

    Automatically discovered observations are kept separate from
    user-maintained metadata such as friendly names and categories.
    """

    VERSION = 1

    def __init__(self, path=None):
        self.path = Path(
            path
            if path is not None
            else Path(__file__).resolve().parent.parent
            / "data"
            / "devices.json"
        )

        self._lock = threading.RLock()
        self._devices = {}

        self._load()

    def _load(self):
        """Load existing registry without overwriting corrupt data."""

        if not self.path.exists():
            logger.info(
                "Device registry does not exist yet: %s",
                self.path,
            )
            return

        try:
            with self.path.open("r", encoding="utf-8") as file:
                payload = json.load(file)

            if not isinstance(payload, dict):
                raise ValueError("Registry root must be an object")

            if payload.get("version") != self.VERSION:
                raise ValueError("Unsupported device registry version")

            devices = payload.get("devices")

            if not isinstance(devices, dict):
                raise ValueError("Invalid devices collection")

            loaded = {}

            for mac, device in devices.items():
                normalized_mac = normalize_mac(mac)

                if not isinstance(device, dict):
                    raise ValueError(
                        f"Invalid device record for {mac}"
                    )

                loaded[normalized_mac] = device

            self._devices = loaded

            logger.info(
                "Loaded %d device identities from %s",
                len(self._devices),
                self.path,
            )

        except Exception:
            logger.exception(
                "Could not load device registry; "
                "existing file has been left untouched"
            )
            raise

    def _save(self):
        """Persist registry atomically."""

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        payload = {
            "version": self.VERSION,
            "updated_at": utc_now(),
            "devices": self._devices,
        }

        fd, temporary_path = tempfile.mkstemp(
            prefix=".devices-",
            suffix=".tmp",
            dir=self.path.parent,
        )

        try:
            with os.fdopen(
                fd,
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    payload,
                    file,
                    indent=2,
                    sort_keys=True,
                )

                file.write("\n")
                file.flush()
                os.fsync(file.fileno())

            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self.path)

            directory_fd = os.open(
                self.path.parent,
                os.O_RDONLY,
            )

            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

        except Exception:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass

            raise

    def observe(
        self,
        mac_address,
        source,
        fields=None,
        observed_at=None,
    ):
        """Record a device observation without overwriting user metadata."""

        mac = normalize_mac(mac_address)

        if not isinstance(source, str) or not source.strip():
            raise ValueError("Observation source is required")

        fields = fields or {}

        if not isinstance(fields, dict):
            raise ValueError("Observation fields must be a dictionary")

        unknown_fields = set(fields) - OBSERVABLE_FIELDS

        if unknown_fields:
            raise ValueError(
                f"Unsupported observation fields: "
                f"{sorted(unknown_fields)}"
            )

        timestamp = observed_at or utc_now()

        observation_fields = {
            key: value
            for key, value in fields.items()
            if value is not None and value != ""
        }

        with self._lock:
            device = self._devices.get(mac)

            if device is None:
                device = {
                    "mac_address": mac,
                    "first_seen": timestamp,
                    "last_seen": timestamp,
                    "metadata": {
                        "name": None,
                        "category": None,
                        "notes": "",
                    },
                    "observations": {},
                }

                self._devices[mac] = device

            device["observations"][source] = {
                "observed_at": timestamp,
                "fields": observation_fields,
            }

            device["last_seen"] = timestamp

            self._save()

            return self._public_device(device)

    def update_metadata(
        self,
        mac_address,
        name=None,
        category=None,
        notes=None,
    ):
        """Update user-maintained device metadata."""

        mac = normalize_mac(mac_address)

        with self._lock:
            device = self._devices.get(mac)

            if device is None:
                raise KeyError(
                    f"Device {mac} has not been discovered"
                )

            metadata = device["metadata"]

            if name is not None:
                if not isinstance(name, str) or not name.strip():
                    raise ValueError(
                        "Friendly name cannot be empty"
                    )
                metadata["name"] = name.strip()

            if category is not None:
                if not isinstance(category, str):
                    raise ValueError("Category must be a string")
                metadata["category"] = category.strip() or None

            if notes is not None:
                if not isinstance(notes, str):
                    raise ValueError("Notes must be a string")
                metadata["notes"] = notes.strip()

            device["metadata_updated_at"] = utc_now()

            self._save()

            return self._public_device(device)

    @staticmethod
    def _public_device(device):
        """Return a copy with the latest known observation fields."""

        result = copy.deepcopy(device)

        latest = {}

        for source, observation in result["observations"].items():
            timestamp = observation.get("observed_at", "")

            for field, value in observation.get("fields", {}).items():
                previous = latest.get(field)

                if previous is None or timestamp >= previous[0]:
                    latest[field] = (timestamp, value)

        for field, (_, value) in latest.items():
            result[field] = value

        result["friendly_name"] = (
            result["metadata"].get("name")
            or result.get("hostname")
            or result.get("device_name")
            or result["mac_address"]
        )

        return result

    def get(self, mac_address):
        """Retrieve one device by MAC address."""

        mac = normalize_mac(mac_address)

        with self._lock:
            device = self._devices.get(mac)

            if device is None:
                return None

            return self._public_device(device)

    def list_devices(self):
        """Return all known devices."""

        with self._lock:
            devices = [
                self._public_device(device)
                for device in self._devices.values()
            ]

        return sorted(
            devices,
            key=lambda device: device["friendly_name"].lower(),
        )

    def count(self):
        with self._lock:
            return len(self._devices)
