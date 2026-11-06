"""Bounded Source RCON client, used only with owned game-network addresses."""

import socket
import struct
import time


class RconError(ValueError):
    pass


class RconClient:
    def __init__(self, host, port, password, timeout=3):
        self.host, self.port, self.password, self.timeout = host, port, password, timeout
        self._sock = None
        self.deadline = 0

    def _packet(self, rid, kind, body):
        data = body.encode() + b"\0\0"
        return struct.pack("<iii", len(data) + 8, rid, kind) + data

    def _recvall(self, size):
        output = bytearray()
        while len(output) < size:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise RconError("RCON deadline exceeded")
            self._sock.settimeout(remaining)
            chunk = self._sock.recv(size - len(output))
            if not chunk:
                raise RconError("Truncated RCON packet")
            output.extend(chunk)
        return bytes(output)

    def _read_packet(self):
        size, rid, kind = struct.unpack("<iii", self._recvall(12))
        if not 10 <= size <= 1024 * 1024:
            raise RconError("Invalid RCON packet size")
        data = self._recvall(size - 8)
        if not data.endswith(b"\0\0"):
            raise RconError("Invalid RCON terminator")
        return rid, kind, data[:-2].decode("utf-8", errors="replace")

    def connect(self):
        self.deadline = time.monotonic() + self.timeout
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock.sendall(self._packet(1, 3, self.password))
        for _ in range(2):
            rid, kind, _ = self._read_packet()
            if rid == -1:
                raise RconError("RCON authentication failed")
            if rid == 1 and kind == 2:
                return
        raise RconError("Invalid RCON authentication response")

    def exec(self, command):
        self.deadline = time.monotonic() + self.timeout
        self._sock.sendall(self._packet(2, 2, command))
        rid, _, body = self._read_packet()
        # Palworld v1.0.5 replies with ID 0 rather than echoing the request ID.
        # Each helper connection executes exactly one command, so accept that known variant.
        if rid not in (0, 2):
            raise RconError("Unexpected RCON response ID")
        return body

    def close(self):
        if self._sock:
            self._sock.close()
        self._sock = None

    def __enter__(self):
        try:
            self.connect()
        except (OSError, ValueError):
            self.close()
            raise
        return self

    def __exit__(self, *args):
        self.close()


def rcon_command(host, port, password, command, timeout=3):
    with RconClient(host, port, password, timeout) as client:
        return client.exec(command)
