
"""Runtime entry point for router telemetry and Prometheus exporter."""

import logging
import signal
import threading

from collector.device_inventory import IntegratedRouterMetricsExporter
from collector.scheduler import RouterScheduler
from collector.state import TelemetryState


logger = logging.getLogger("router_exporter")


def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    configure_logging()

    stop_event = threading.Event()

    def handle_shutdown(signum, frame):
        logger.info("Received signal %s; shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    state = TelemetryState()
    scheduler = RouterScheduler(state=state)

    exporter = IntegratedRouterMetricsExporter(
        state=state,
        host="0.0.0.0",
        port=9200,
    )

    refresh_thread = threading.Thread(
        target=exporter.run_refresh_loop,
        kwargs={
            "stop_event": stop_event,
            "interval": 5,
        },
        name="metrics-refresh",
        daemon=True,
    )

    try:
        exporter.start()
        refresh_thread.start()
        scheduler.start()

        logger.info("Router telemetry service started")
        logger.info("Prometheus metrics available on port 9200")
        logger.info("Persistent device inventory enabled")

        while not stop_event.wait(1):
            if not scheduler.is_alive():
                logger.error("All router workers have stopped")
                break

    except Exception:
        logger.exception("Router telemetry service failed")
        raise

    finally:
        logger.info("Stopping router telemetry service")

        stop_event.set()
        scheduler.stop(timeout=15)
        refresh_thread.join(timeout=5)

        logger.info("Router telemetry service stopped")


if __name__ == "__main__":
    main()
