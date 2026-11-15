"""Shared interactive SSH transport for network devices."""

import logging
import re
import socket
import time

import paramiko


logger = logging.getLogger(__name__)

ANSI_ESCAPE = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"
)
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

DEVICE_ERROR_MARKERS = (
    "ERROR::",
    "ErrCode =",
    "Error:",
    "Unknown command",
    "Invalid command",
    "Command not found",
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

        # Match the final prompt line, not the entire terminal transcript.
        # Device-specific patterns are supplied by NokiaRouter/HuaweiRouter.
        self.prompt_pattern = re.compile(prompt_pattern)

        self.client = None
        self.channel = None

    @staticmethod
    def _clean_output(output: str) -> str:
        output = ANSI_ESCAPE.sub("", output)
        output = CONTROL_CHARS.sub("", output)
        return output.replace("\r", "")

    def _is_prompt_received(self, output: str) -> bool:
        lines = output.rstrip().splitlines()
        if not lines:
            return False
        final_line = lines[-1].strip()
        return bool(self.prompt_pattern.fullmatch(final_line))

    def connect(self):
        """Establish SSH connection."""
        self.client = paramiko.SSHClient()

        # Temporary LAN-development policy. Use pinned host keys in production.
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

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
            "Initial prompt received from %s: %r",
            self.host,
            initial_output[-100:],
        )
        return initial_output

    def _read_until_prompt(self, timeout=None):
        """Read output until the final line matches the router prompt."""
        if self.channel is None:
            raise RuntimeError("Interactive shell is not open")

        timeout = self.timeout if timeout is None else timeout
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
                cleaned = self._clean_output("".join(output))

                if self._is_prompt_received(cleaned):
                    return cleaned
            else:
                time.sleep(0.02)

        partial_output = self._clean_output("".join(output))
        logger.error(
            "[%s] Prompt detection failed. Last output: %r",
            self.host,
            partial_output[-160:],
        )
        raise TimeoutError(
            f"Prompt not received from {self.host} within {timeout}s.\n"
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

    def collect_raw_commands(self, commands):
        """Collect optional command outputs without aborting the whole batch.

        Each item is (key, command) or (key, command, timeout).
        Device-level CLI errors are distinguished from SSH transport success.
        """
        results = {}

        for item in commands:
            key, command = item[0], item[1]
            command_timeout = item[2] if len(item) > 2 else self.timeout

            try:
                output = self.execute(command, timeout=command_timeout)
                has_device_error = any(
                    marker.lower() in output.lower()
                    for marker in DEVICE_ERROR_MARKERS
                )

                results[key] = {
                    "command": command,
                    "status": "command_error" if has_device_error else "success",
                    "output": output,
                    "error": (
                        "Router returned a CLI error; inspect output."
                        if has_device_error else None
                    ),
                }
            except Exception as exc:
                logger.exception(
                    "[%s] Optional telemetry command failed: %s",
                    self.host,
                    command,
                )
                results[key] = {
                    "command": command,
                    "status": "collection_error",
                    "output": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }

        return results

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
