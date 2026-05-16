import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=getattr(logging, (os.getenv("LOG_LEVEL") or "INFO").upper(), logging.INFO),
    format="%(levelname)s %(name)s: %(message)s",
)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from database.base import Base  # noqa: E402
from database.session import engine  # noqa: E402
from config import log_database_target  # noqa: E402
from models import (  # noqa: F401, E402
    chat_session,
    connected_card,
    message,
    payment_extraction,
    payment_transaction,
    saved_recipient,
    uploaded_file,
    user as user_model,
    price_report,
    whatsapp_session,
)
from routers import auth as auth_router  # noqa: E402
from routers import chat as chat_router  # noqa: E402
from routers import integrations as integrations_router  # noqa: E402
from routers import webhooks as webhooks_router  # noqa: E402
from routers import whatsapp as whatsapp_router  # noqa: E402
from services.whatsapp_service import subscribe_app_to_waba  # noqa: E402

_access_logger = logging.getLogger("confam.access")


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request so webhook delivery is visible in the terminal."""

    async def dispatch(self, request: Request, call_next):
        client = request.client.host if request.client else "?"
        _access_logger.info("%s %s from %s", request.method, request.url.path, client)
        return await call_next(request)


def _warn_webhook_reachability() -> None:
    public = (os.getenv("WEBHOOK_PUBLIC_URL") or os.getenv("BACKEND_PUBLIC_URL") or "").strip().rstrip("/")
    if not public or "127.0.0.1" in public or "localhost" in public.lower():
        logging.getLogger(__name__).warning(
            "WhatsApp webhooks will NOT reach this machine until Meta can POST to a public HTTPS URL. "
            "Use ngrok (e.g. ngrok http 8000) and set that URL + /webhook in Meta → WhatsApp → Configuration. "
            "Current BACKEND_PUBLIC_URL=%s",
            public or "(unset)",
        )
    else:
        logging.getLogger(__name__).info(
            "WhatsApp webhook callback should be: %s/webhook",
            public,
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log_database_target()
    _warn_webhook_reachability()
    Base.metadata.create_all(bind=engine)
    await subscribe_app_to_waba()
    yield


def _cors_origins() -> list[str]:
    raw = os.getenv("FRONTEND_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app = FastAPI(
    title="Confam API",
    version="1.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLogMiddleware)

app.include_router(auth_router.router, prefix="/auth", tags=["auth"])
app.include_router(chat_router.router)
app.include_router(integrations_router.router)
app.include_router(webhooks_router.router)
app.include_router(whatsapp_router.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
