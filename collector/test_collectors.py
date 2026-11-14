
"""Integration test for Nokia and Huawei interactive collectors."""

import os
import logging

from collector.routers.nokia import NokiaRouter
from collector.routers.huawei import HuaweiRouter


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

ROUTERS = {
    "nokia": {
        "class": NokiaRouter,
        "host": "192.168.1.1",
        "username": "admin",
        "commands": ["cpu", "mem", "sysinfo"],
    },
    "huawei": {
        "class": HuaweiRouter,
        "host": "192.168.1.2",
        "username": "root",
        "commands": [
            "display cpu info",
            "display memory info",
            "display sysinfo",
        ],
    },
}


def test_router(name, config):

    password = os.environ.get(f"{name.upper()}_PASSWORD")

    if not password:
        print(f"{name}: credentials unavailable")
        return

    router = config["class"](
        host=config["host"],
        username=config["username"],
        password=password,
    )

    print(f"\n{'=' * 55}")
    print(f" TESTING {name.upper()}")
    print("=" * 55)

    try:
        router.connect()
        router.open_cli()

        for command in config["commands"]:

            print(f"\n--- COMMAND: {command} ---")

            output = router.execute(command)

            print(output)

    except Exception as exc:
        logging.exception("%s test failed: %s", name, exc)

    finally:
        router.close()


if __name__ == "__main__":

    for name, config in ROUTERS.items():
        test_router(name, config)
