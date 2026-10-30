"""Route one public HTTP endpoint to the local Streamlit and LINE webhook apps."""

from __future__ import annotations

from urllib.parse import urlsplit

from tornado.httpclient import AsyncHTTPClient, HTTPRequest
from tornado.httpserver import HTTPServer
from tornado.ioloop import IOLoop
from tornado.web import Application, RequestHandler
from tornado.websocket import WebSocketClosedError, WebSocketHandler, websocket_connect


WEBHOOK_PREFIX = "/callback"
STREAMLIT_UPSTREAM = "http://127.0.0.1:8501"
WEBHOOK_UPSTREAM = "http://127.0.0.1:8001"

_HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def _is_webhook_path(path: str) -> bool:
    return path == WEBHOOK_PREFIX or path.startswith(WEBHOOK_PREFIX + "/")


def _copy_request_headers(headers):
    return {
        name: value
        for name, value in headers.get_all()
        if name.lower() not in _HOP_BY_HOP_HEADERS
        and not name.lower().startswith("sec-websocket-")
    }


class HttpProxyHandler(RequestHandler):
    async def _proxy(self):
        parsed = urlsplit(self.request.uri)
        upstream = WEBHOOK_UPSTREAM if _is_webhook_path(parsed.path) else STREAMLIT_UPSTREAM
        url = upstream + self.request.uri
        body = self.request.body if self.request.body else None
        request = HTTPRequest(
            url=url,
            method=self.request.method,
            headers=_copy_request_headers(self.request.headers),
            body=body,
            follow_redirects=False,
            allow_nonstandard_methods=True,
            decompress_response=False,
            request_timeout=120.0,
        )

        try:
            response = await AsyncHTTPClient().fetch(request, raise_error=False)
        except Exception as exc:
            self.set_status(502)
            self.finish(f"Local upstream unavailable: {exc}")
            return

        self.set_status(response.code)
        for name, value in response.headers.get_all():
            if name.lower() not in _HOP_BY_HOP_HEADERS:
                self.add_header(name, value)
        if self.request.method == "HEAD" or response.code in (204, 304):
            self.finish()
        else:
            self.finish(response.body or b"")

    get = _proxy
    post = _proxy
    put = _proxy
    patch = _proxy
    delete = _proxy
    options = _proxy
    head = _proxy


class WebSocketProxyHandler(WebSocketHandler):
    def check_origin(self, origin: str) -> bool:
        # The public hostname is supplied by ngrok/Cloudflare and differs from localhost.
        return True

    async def open(self, *_args):
        self._client_closed = False
        self._pending_client_messages = []
        upstream_url = "ws://127.0.0.1:8501" + self.request.uri
        headers = _copy_request_headers(self.request.headers)
        headers["Origin"] = STREAMLIT_UPSTREAM
        request = HTTPRequest(
            url=upstream_url,
            headers=headers,
            connect_timeout=10.0,
            request_timeout=120.0,
        )
        try:
            self._upstream_ws = await websocket_connect(request)
        except Exception:
            self.close(code=1011, reason="Streamlit websocket upstream unavailable")
            return
        for message in self._pending_client_messages:
            IOLoop.current().spawn_callback(
                self._upstream_ws.write_message,
                message,
                binary=isinstance(message, bytes),
            )
        self._pending_client_messages.clear()
        self._upstream_reader = IOLoop.current().spawn_callback(self._read_upstream)

    async def _read_upstream(self):
        try:
            while not self._client_closed:
                message = await self._upstream_ws.read_message()
                if message is None:
                    break
                await self.write_message(message, binary=isinstance(message, bytes))
        except WebSocketClosedError:
            self._client_closed = True
        except Exception:
            pass
        finally:
            if not self._client_closed:
                self._client_closed = True
                self.close()
            if getattr(self, "_upstream_ws", None) is not None:
                self._upstream_ws.close()

    def on_message(self, message):
        upstream = getattr(self, "_upstream_ws", None)
        if upstream is not None and not self._client_closed:
            IOLoop.current().spawn_callback(
                upstream.write_message,
                message,
                binary=isinstance(message, bytes),
            )
        elif not self._client_closed:
            self._pending_client_messages.append(message)

    def on_close(self):
        self._client_closed = True
        upstream = getattr(self, "_upstream_ws", None)
        if upstream is not None:
            upstream.close()


def run_public_router(port: int = 8502) -> None:
    app = Application(
        [
            (r"/_stcore/stream", WebSocketProxyHandler),
            (r"/.*", HttpProxyHandler),
        ]
    )
    app.settings["websocket_ping_interval"] = 30
    server = HTTPServer(app)
    server.listen(port, address="127.0.0.1")
    IOLoop.current().start()


if __name__ == "__main__":
    run_public_router()
