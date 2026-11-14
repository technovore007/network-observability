
import os
import paramiko

ROUTERS = {
    "nokia": {
        "host": "192.168.1.1",
        "username": "admin",
        "legacy_rsa": False,
    },
    "huawei": {
        "host": "192.168.1.2",
        "username": "root",
        "legacy_rsa": True,
    },
}

for name, config in ROUTERS.items():
    password = os.environ.get(f"{name.upper()}_PASSWORD")

    if not password:
        print(f"{name}: password environment variable missing")
        continue

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

        print(f"{name}: SSH authentication successful")

        transport = client.get_transport()
        print(f"{name}: SSH transport active = {transport.is_active()}")

    except Exception as exc:
        print(f"{name}: connection failed: {type(exc).__name__}: {exc}")

    finally:
        client.close()
