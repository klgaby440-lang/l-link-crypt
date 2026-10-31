"""Protections ASGI communes aux routes HTTP."""

from starlette.responses import JSONResponse


class RequestBodyTooLarge(Exception):
    """Signal interne : le flux HTTP dépasse la taille maximale configurée."""


class RequestBodyLimitMiddleware:
    """Limite le corps HTTP avant que FastAPI ne le parse ou ne l'enregistre."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    response = JSONResponse(
                        status_code=413,
                        content={"detail": "Corps de requête trop volumineux."},
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                response = JSONResponse(
                    status_code=400,
                    content={"detail": "En-tête Content-Length invalide."},
                )
                await response(scope, receive, send)
                return

        received_bytes = 0

        async def limited_receive():
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_bytes:
                    raise RequestBodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLarge:
            response = JSONResponse(
                status_code=413,
                content={"detail": "Corps de requête trop volumineux."},
            )
            await response(scope, receive, send)
