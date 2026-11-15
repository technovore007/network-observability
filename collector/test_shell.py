
"""Interactive SSH shell diagnostics for Nokia and Huawei routers."""

import os
import time
import paramiko


ROUTERS = {
    "nokia": {
        "host": "192.168.1.1",
        "username": "admin",
        "legacy_rsa": False,
        "commands": ["enable", "show", "cpu", "mem"],
    },
    "huawei": {
        "host": "192.168.1.2",
        "username": "root",
        "legacy_rsa": True,
        "commands": ["su", "display cpu info", "display memory info"],
    },
}


def read_shell(channel, timeout=10, idle=0.8):
    """Read shell output until the channel becomes idle."""

    output = []
    start = time.monotonic()
    last_data = start

    while time.monotonic() - start < timeout:
        if channel.recv_ready():
            data = channel.recv(65535).decode(
                "utf-8", errors="replace"
            )
            output.append(data)
            last_data = time.monotonic()

        elif output and time.monotonic() - last_data >= idle:
            break

        time.sleep(0.05)

    return "".join(output)


def run_router_test(name, config):
    password = os.environ.get(f"{name.upper()}_PASSWORD")

    if not password:
        print(f"{name}: credentials missing")
        return

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(
            hostname=config["host"],
            username=config["username"],
            password=password,
            timeout=10,
            banner_timeout=10,
            auth_timeout=10,
            look_for_keys=False,
            allow_agent=False,
            disabled_algorithms=(
                {"keys": ["rsa-sha2-256", "rsa-sha2-512"]}
                if config["legacy_rsa"] else None
            ),
        )

        print(f"\n{'=' * 45}")
        print(f"{name.upper()} INTERACTIVE SHELL")
        print("=" * 45)

        channel = client.invoke_shell(
            term="vt100",
            width=160,
            height=48,
        )

        print("\n[Initial prompt]")
        print(read_shell(channel))

        for command in config["commands"]:
            print(f"\n[Sending: {command}]")
            channel.send(command + "\n")

            output = read_shell(channel)
            print(output)

        channel.close()

    except Exception as exc:
        print(f"{name}: {type(exc).__name__}: {exc}")

    finally:
        client.close()


if __name__ == "__main__":
    for name, config in ROUTERS.items():
        run_router_test(name, config)
