"""
Minimal HTTP/3 (QUIC) client using aioquic.

Run:
    python3 client.py <server_host> [port] [path]

Examples:
    python3 client.py 203.0.113.10                 # GET / on port 4433
    python3 client.py 203.0.113.10 4433 /hello      # GET /hello
    python3 client.py my-server.example.com

Connects to the given server and prints the response body.
"""

import asyncio
import ssl
import sys

from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import DataReceived, H3Event, HeadersReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import QuicEvent

DEFAULT_PORT = 4433


class Http3ClientProtocol(QuicConnectionProtocol):
    """Speaks HTTP/3 over an established QUIC connection."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._http = H3Connection(self._quic)
        self._waiters: dict[int, asyncio.Future] = {}
        self._buffers: dict[int, bytearray] = {}

    async def get(self, path: str, authority: str) -> bytes:
        stream_id = self._quic.get_next_available_stream_id()
        self._buffers[stream_id] = bytearray()

        self._http.send_headers(
            stream_id=stream_id,
            headers=[
                (b":method", b"GET"),
                (b":scheme", b"https"),
                (b":authority", authority.encode()),
                (b":path", path.encode()),
            ],
            end_stream=True,
        )

        waiter = asyncio.get_event_loop().create_future()
        self._waiters[stream_id] = waiter
        self.transmit()

        return await waiter

    def quic_event_received(self, event: QuicEvent) -> None:
        for http_event in self._http.handle_event(event):
            self._h3_event_received(http_event)

    def _h3_event_received(self, event: H3Event) -> None:
        if isinstance(event, HeadersReceived):
            status = next(
                (v for k, v in event.headers if k == b":status"), b"?"
            )
            print(f"Response status: {status.decode()}")

        elif isinstance(event, DataReceived):
            stream_id = event.stream_id
            if stream_id in self._buffers:
                self._buffers[stream_id].extend(event.data)
                if event.stream_ended:
                    waiter = self._waiters.pop(stream_id)
                    waiter.set_result(bytes(self._buffers.pop(stream_id)))


def parse_args() -> tuple[str, int, str]:
    if len(sys.argv) < 2:
        print(f"Usage: python3 {sys.argv[0]} <server_host> [port] [path]")
        sys.exit(1)

    host = sys.argv[1]
    port = DEFAULT_PORT
    path = "/"

    rest = sys.argv[2:]
    if rest and rest[0].isdigit():
        port = int(rest[0])
        rest = rest[1:]
    if rest:
        path = rest[0]

    return host, port, path


async def main() -> None:
    host, port, path = parse_args()

    configuration = QuicConfiguration(
        alpn_protocols=["h3"],
        is_client=True,
    )
    # Self-signed cert for this demo -> skip verification.
    # For a real deployment, keep verification on and use a trusted,
    # CA-signed certificate and remove this line.
    configuration.verify_mode = ssl.CERT_NONE

    print(f"Connecting to {host}:{port} ...")
    async with connect(
        host,
        port,
        configuration=configuration,
        create_protocol=Http3ClientProtocol,
    ) as client:
        response = await client.get(path, authority=host)
        print(response.decode())


if __name__ == "__main__":
    asyncio.run(main())
