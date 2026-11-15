
"""Thread-safe shared state for router telemetry collection."""

from copy import deepcopy
from threading import RLock
from time import monotonic, time


class TelemetryState:
    """Store latest telemetry, freshness, and collection health."""

    def __init__(self):
        self._lock = RLock()
        self._routers = {}

    def _router(self, router):
        return self._routers.setdefault(
            router,
            {
                "groups": {},
                "last_attempt_timestamp": None,
                "last_success_timestamp": None,
                "last_error": None,
            },
        )

    def update_group(
        self,
        router,
        group,
        data,
        duration_seconds=0.0,
        collected_at=None,
    ):
        """Record a successful collection without resetting failure history."""

        now = time()
        monotonic_now = monotonic()

        with self._lock:
            state = self._router(router)
            previous = state["groups"].get(group, {})

            state["groups"][group] = {
                "data": deepcopy(data),
                "success_timestamp": collected_at or now,
                "updated_monotonic": monotonic_now,
                "duration_seconds": max(0.0, duration_seconds),
                "failure_count": previous.get("failure_count", 0),
                "last_attempt_timestamp": now,
                "status": "success",
                "error": None,
            }

            state["last_attempt_timestamp"] = now
            state["last_success_timestamp"] = now
            state["last_error"] = None

    def record_failure(
        self,
        router,
        group,
        error,
        duration_seconds=0.0,
    ):
        """Record one failed attempt while preserving successful telemetry."""

        now = time()

        with self._lock:
            state = self._router(router)
            previous = state["groups"].get(group, {})

            state["groups"][group] = {
                **previous,
                "status": "error",
                "error": str(error),
                "failure_count": previous.get("failure_count", 0) + 1,
                "last_attempt_timestamp": now,
                "last_attempt_duration_seconds": max(
                    0.0, duration_seconds
                ),
            }

            state["last_attempt_timestamp"] = now
            state["last_error"] = str(error)

    def snapshot(self):
        """Return a consistent snapshot with calculated telemetry ages."""

        monotonic_now = monotonic()

        with self._lock:
            result = deepcopy(self._routers)

        for router_state in result.values():
            for group_state in router_state["groups"].values():
                updated = group_state.get("updated_monotonic")

                group_state["age_seconds"] = (
                    max(0.0, monotonic_now - updated)
                    if updated is not None
                    else None
                )

                group_state.pop("updated_monotonic", None)

        return result

    def get_group(self, router, group):
        """Return one group's latest state."""

        with self._lock:
            state = self._routers.get(router, {})
            group_state = state.get("groups", {}).get(group)

            if group_state is None:
                return None

            result = deepcopy(group_state)
            updated = result.pop("updated_monotonic", None)

        result["age_seconds"] = (
            max(0.0, monotonic() - updated)
            if updated is not None
            else None
        )

        return result
