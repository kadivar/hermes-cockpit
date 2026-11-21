# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A minimal Chrome DevTools Protocol client over a WebSocket (RFC 6455), standard library only.

Cockpit's runtime carries no WebSocket package, and `cockpit record` needs only this: open a page target's
webSocketDebuggerUrl on loopback, send commands, and read their answers and the events in between.
"""

import base64
import hashlib
import json
import os
import socket
import struct
from urllib.parse import urlparse

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def encode_frame(payload: bytes, opcode: int = 1, mask: bool = True) -> bytes:
    """One final frame. A client masks what it sends; a server (the tests' fake target) does not."""
    head = bytes([0x80 | opcode])
    size = len(payload)
    bit = 0x80 if mask else 0
    if size < 126:
        head += bytes([bit | size])
    elif size < 1 << 16:
        head += bytes([bit | 126]) + struct.pack("!H", size)
    else:
        head += bytes([bit | 127]) + struct.pack("!Q", size)
    if not mask:
        return head + payload
    key = os.urandom(4)
    return head + key + bytes(byte ^ key[index % 4] for index, byte in enumerate(payload))


def decode_frame(buffer: bytes):
    """(fin, opcode, payload, used) of the first whole frame in buffer, or None while it is incomplete."""
    if len(buffer) < 2:
        return None
    fin, opcode = buffer[0] & 0x80, buffer[0] & 0x0F
    masked, size = buffer[1] & 0x80, buffer[1] & 0x7F
    at = 2
    if size == 126:
        if len(buffer) < 4:
            return None
        size, at = struct.unpack("!H", buffer[2:4])[0], 4
    elif size == 127:
        if len(buffer) < 10:
            return None
        size, at = struct.unpack("!Q", buffer[2:10])[0], 10
    key = b""
    if masked:
        if len(buffer) < at + 4:
            return None
        key, at = buffer[at : at + 4], at + 4
    if len(buffer) < at + size:
        return None
    payload = buffer[at : at + size]
    if masked:
        payload = bytes(byte ^ key[index % 4] for index, byte in enumerate(payload))
    return bool(fin), opcode, payload, at + size


class Closed(Exception):
    """The target closed the connection."""


class Socket:
    """One CDP connection. call() answers a command; poll() returns the next event (or None after the timeout)."""

    def __init__(self, url: str, timeout: float = 10.0):
        parsed = urlparse(url)
        if parsed.scheme != "ws" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError(f"not a loopback DevTools socket: {url}")
        self.sock = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        request = (
            f"GET {path or '/'} HTTP/1.1\r\nHost: {parsed.hostname}:{parsed.port or 80}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        self.buffer = b""
        while b"\r\n\r\n" not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise Closed("the target closed the handshake")
            self.buffer += chunk
        head, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        if " 101 " not in lines[0] + " ":
            raise Closed(f"the target refused the WebSocket: {lines[0]}")
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode(), usedforsecurity=False).digest()).decode()
        headers = {
            line.split(":", 1)[0].strip().lower(): line.split(":", 1)[1].strip() for line in lines[1:] if ":" in line
        }
        if headers.get("sec-websocket-accept") != accept:
            raise Closed("the target answered the handshake with a wrong key")
        self.next_id = 0
        self.events = []
        self.parts = b""

    def send(self, message: dict) -> None:
        self.sock.sendall(encode_frame(json.dumps(message).encode()))

    def _message(self, timeout: float):
        """The next whole text message, or None after timeout. Pings are answered; a close raises Closed."""
        self.sock.settimeout(timeout)
        while True:
            frame = decode_frame(self.buffer)
            if frame is None:
                try:
                    chunk = self.sock.recv(65536)
                except TimeoutError:
                    return None
                if not chunk:
                    raise Closed("the target closed the connection")
                self.buffer += chunk
                continue
            fin, opcode, payload, used = frame
            self.buffer = self.buffer[used:]
            if opcode == 8:
                raise Closed("the target closed the connection")
            if opcode == 9:
                self.sock.sendall(encode_frame(payload, opcode=10))
                continue
            if opcode == 10:
                continue
            self.parts += payload
            if not fin:
                continue
            text, self.parts = self.parts, b""
            try:
                return json.loads(text.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

    def call(self, method: str, params=None, timeout: float = 10.0) -> dict:
        """Send one command and wait for its answer; events read meanwhile wait in self.events."""
        self.next_id += 1
        mine = self.next_id
        self.send({"id": mine, "method": method, "params": params or {}})
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self._message(max(0.05, deadline - time.monotonic()))
            if message is None:
                continue
            if message.get("id") == mine:
                if message.get("error"):
                    raise RuntimeError(f"{method}: {message['error'].get('message') or message['error']}")
                return message.get("result") or {}
            if "method" in message:
                self.events.append(message)
        raise TimeoutError(f"{method}: no answer within {timeout} s")

    def poll(self, timeout: float = 0.5):
        """The next event, or None when none came within timeout."""
        if self.events:
            return self.events.pop(0)
        message = self._message(timeout)
        while message is not None and "method" not in message:
            message = self._message(0.01)
        return message

    def close(self) -> None:
        try:
            self.sock.sendall(encode_frame(b"", opcode=8))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
