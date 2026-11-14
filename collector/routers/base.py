
"""Shared interactive SSH transport for network devices."""

import logging
import re
import socket
import time

import paramiko


logger = logging.getLogger(__name__)


# Remove ANSI terminal escape sequences from received output.
ANSI_ESCAPE = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"
)


class SSHRouter:

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        prompt_pattern: str,
        port: int = 22,
        timeout: int = 10,
        legacy_rsa: bool = False,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self.legacy_rsa = legacy_rsa

        self.prompt_pattern = re.compile(
            rf"(?:^|[\r\n])(?:{prompt_pattern})[ \t]*$",
            re.MULTILINE,
        )

        self.client = None
        self.channel = None

    def connect(self):
        """Establish SSH connection."""

        self.client = paramiko.SSHClient()

        # Temporary policy for initial LAN development.
        # Replace with managed host-key verification later.
        self.client.set_missing_host_key_policy(
            paramiko.AutoAddPolicy()
        )

        options = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "timeout": self.timeout,
            "banner_timeout": self.timeout,
            "auth_timeout": self.timeout,
            "look_for_keys": False,
            "allow_agent": False,
        }

        if self.legacy_rsa:
            options["disabled_algorithms"] = {
                "keys": ["rsa-sha2-256", "rsa-sha2-512"]
            }

        try:
            self.client.connect(**options)

            logger.info("SSH connected: %s", self.host)

        except (paramiko.SSHException, socket.error) as exc:
            self.close()

            raise ConnectionError(
                f"SSH connection failed for {self.host}: {exc}"
            ) from exc

    def open_shell(self):
        """Open an interactive shell and synchronize with its prompt."""

        if self.client is None:
            raise RuntimeError("SSH connection is not established")

        self.channel = self.client.invoke_shell(
            term="vt100",
            width=160,
            height=48,
        )

        self.channel.settimeout(self.timeout)

        initial_output = self._read_until_prompt(self.timeout)

        logger.debug(
            "Initial prompt received from %s: %s",
            self.host,
            initial_output[-100:],
        )

        return initial_output

    def _read_until_prompt(self, timeout=None):
        """
        Read channel output until the configured CLI prompt appears.

        Unlike idle-based reading, this waits for an actual
        command-completion signal from the router.
        """

        if self.channel is None:
            raise RuntimeError("Interactive shell is not open")

        timeout = timeout or self.timeout

        output = []
        start = time.monotonic()

        while time.monotonic() - start < timeout:

            if self.channel.closed:
                raise ConnectionError(
                    f"SSH shell closed unexpectedly: {self.host}"
                )

            if self.channel.recv_ready():

                data = self.channel.recv(65535).decode(
                    "utf-8",
                    errors="replace",
                )

                output.append(data)

                current_output = ANSI_ESCAPE.sub(
                    "",
                    "".join(output),
                )

                if self.prompt_pattern.search(current_output):
                    return current_output

            else:
                time.sleep(0.02)

        partial_output = ANSI_ESCAPE.sub(
            "",
            "".join(output),
        )

        raise TimeoutError(
            f"Prompt not received from {self.host} "
            f"within {timeout}s.\n"
            f"Partial output:\n{partial_output}"
        )

    def execute(self, command: str, timeout=None) -> str:
        """Execute one CLI command and wait for its prompt."""

        if self.channel is None or self.channel.closed:
            raise RuntimeError("Interactive shell is not available")

        logger.debug("[%s] Executing: %s", self.host, command)

        self.channel.sendall((command + "\n").encode("utf-8"))

        output = self._read_until_prompt(timeout)

        logger.debug("[%s] Command completed: %s", self.host, command)

        return output.strip()

    def close(self):
        """Close shell and SSH connection safely."""

        if self.channel is not None:
            self.channel.close()
            self.channel = None

        if self.client is not None:
            self.client.close()
            self.client = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
