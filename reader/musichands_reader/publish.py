"""Send control frames as JSON datagrams. This package does not speak MIDI."""

import json
import socket


class UdpPublisher:
    def __init__(self, host="127.0.0.1", port=9100):
        self._address = (host, port)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, frame):
        payload = json.dumps(frame, separators=(",", ":")).encode("utf-8")
        self._socket.sendto(payload, self._address)

    def close(self):
        self._socket.close()
