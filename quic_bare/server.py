"""
Minimal HTTP/3 (QUIC) server using aioquic.

Run:
    python3 server.py

Listens on UDP port 4433 and responds "Hello, HTTP/3!" to any GET request.
"""

import asyncio

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import H3Event, HeadersReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import QuicEvent

HOST = "0.0.0.0"
PORT = 4433


class Http3ServerProtocol(QuicConnectionProtocol):
    """Handles one QUIC connection and speaks HTTP/3 over it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._http = H3Connection(self._quic)

    def quic_event_received(self, event: QuicEvent) -> None:
        # Feed every QUIC-level event into the HTTP/3 layer.
        for http_event in self._http.handle_event(event):
            self._h3_event_received(http_event)

    def _h3_event_received(self, event: H3Event) -> None:
        if isinstance(event, HeadersReceived):
            stream_id = event.stream_id

            # Log the request line for visibility.
            headers = {k.decode(): v.decode() for k, v in event.headers}
            print(f"Request: {headers.get(':method')} {headers.get(':path')}")

            body = f"Hello, HTTP/3! You asked for {headers.get(':path')}\n".encode()

            self._http.send_headers(
                stream_id=stream_id,
                headers=[
                    (b":status", b"200"),
                    (b"content-type", b"text/plain"),
                    (b"content-length", str(len(body)).encode()),
                ],
            )
            self._http.send_data(stream_id=stream_id, data=body, end_stream=True)

            # Push the queued frames out onto the wire.
            self.transmit()


async def main() -> None:
    configuration = QuicConfiguration(
        alpn_protocols=["h3"],
        is_client=False,
    )
    configuration.load_cert_chain("cert.pem", "key.pem")

    await serve(
        HOST,
        PORT,
        configuration=configuration,
        create_protocol=Http3ServerProtocol,
    )

    print(f"HTTP/3 server listening on udp://{HOST}:{PORT}")
    await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
