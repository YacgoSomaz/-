"""HTTP API for the card-key licensing service.

Run in production with:
    uvicorn --factory licensing_server.app:create_app_from_env --host 127.0.0.1 --port 9077
"""

from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from .service import LicenseError, LicenseService, LicenseSettings
from .admin_console import ADMIN_HTML
from .rate_limit import IpRateLimiter, RateLimitPolicy, client_ip_from_request


class ActivationRequest(BaseModel):
    card_key: str = Field(min_length=4, max_length=128)
    device_hash: str = Field(min_length=1, max_length=128)
    app_version: str = Field(default="", max_length=128)
    product_code: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_.-]*$")


class RefreshRequest(BaseModel):
    activation_id: str = Field(min_length=1, max_length=128)
    refresh_token: str = Field(min_length=16, max_length=256)
    device_hash: str = Field(min_length=1, max_length=128)
    app_version: str = Field(default="", max_length=128)
    product_code: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_.-]*$")


class CreateCardRequest(BaseModel):
    features: list[str] = Field(min_length=1, max_length=20)
    product_code: str = Field(default="live_replay_xia", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    max_devices: int = Field(default=1, ge=1, le=20)
    expires_at: int = Field(default=0, ge=0)
    max_active_rooms: int = Field(default=10, ge=1, le=50)
    export_watermark: bool = True
    force_upgrade_below: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=500)


class ReasonRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


class UpdateSettings(BaseModel):
    product_code: str = Field(default="live_replay_xia", max_length=64)
    latest_version: str = Field(default="", max_length=64)
    min_version: str = Field(default="", max_length=64)
    installer_url: str = Field(default="", max_length=500)
    sha256: str = Field(default="", max_length=128)
    notes: str = Field(default="", max_length=2000)
    mandatory: bool = False


def _version_parts(value: str) -> list[int]:
    parts = [int(x) for x in str(value or "").split(".") if x.isdigit()]
    return parts or [0]


def _version_lt(left: str, right: str) -> bool:
    if not right:
        return False
    a = _version_parts(left)
    b = _version_parts(right)
    width = max(len(a), len(b))
    a.extend([0] * (width - len(a)))
    b.extend([0] * (width - len(b)))
    return a < b


def _public_error(exc: LicenseError) -> HTTPException:
    text = str(exc)
    status = 403 if any(word in text for word in ("冻结", "停用", "到期", "不属于", "不匹配")) else 400
    return HTTPException(status_code=status, detail=text)


def create_app(
    service: LicenseService,
    *,
    admin_token: str,
    update_settings: UpdateSettings | None = None,
    rate_limiter: IpRateLimiter | None = None,
    trusted_proxies: set[str] | None = None,
) -> FastAPI:
    if len(admin_token.strip()) < 16:
        raise ValueError("LICENSE_ADMIN_TOKEN 必须至少 16 个字符")
    app = FastAPI(title="直播复盘侠授权服务", version="1.0.0", docs_url=None, redoc_url=None)
    limiter = rate_limiter or IpRateLimiter()
    proxy_ips = trusted_proxies or {"127.0.0.1", "::1"}
    updates = update_settings or UpdateSettings()

    @app.middleware("http")
    async def rate_limit_public_license_requests(request: Request, call_next):
        remote_ip = request.client.host if request.client else ""
        client_ip = client_ip_from_request(
            remote_ip,
            request.headers.get("x-forwarded-for", ""),
            proxy_ips,
        )
        allowed, retry_after = limiter.allow(path=request.url.path, client_ip=client_ip)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试"},
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)

    def require_admin(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {admin_token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="管理员授权无效")

    @app.get("/v1/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/v1/update")
    def update_manifest(
        product_code: str = Query(default="live_replay_xia", max_length=64, pattern=r"^[A-Za-z0-9_.-]+$"),
        current_version: str = Query(default="", max_length=64),
    ) -> dict[str, object]:
        configured_product = (updates.product_code or service.settings.product_code).strip()
        if product_code != configured_product:
            raise HTTPException(status_code=404, detail="暂无该产品更新")
        if not updates.latest_version or not updates.installer_url or not updates.sha256:
            return {
                "ok": True,
                "has_update": False,
                "latest_version": "",
                "current_version": current_version,
            }
        has_update = _version_lt(current_version, updates.latest_version)
        mandatory = updates.mandatory or _version_lt(current_version, updates.min_version)
        return {
            "ok": True,
            "has_update": has_update,
            "product_code": configured_product,
            "current_version": current_version,
            "latest_version": updates.latest_version,
            "min_version": updates.min_version,
            "mandatory": mandatory,
            "installer_url": updates.installer_url,
            "sha256": updates.sha256.lower(),
            "notes": updates.notes,
        }

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/admin", status_code=302)

    @app.post("/v1/activate")
    def activate(payload: ActivationRequest) -> dict[str, object]:
        try:
            return service.activate(
                card_key=payload.card_key,
                device_hash=payload.device_hash,
                product_code=payload.product_code,
                app_version=payload.app_version,
            )
        except LicenseError as exc:
            raise _public_error(exc) from exc

    @app.post("/v1/refresh")
    def refresh(payload: RefreshRequest) -> dict[str, object]:
        try:
            return service.refresh(
                activation_id=payload.activation_id,
                refresh_token=payload.refresh_token,
                device_hash=payload.device_hash,
                product_code=payload.product_code,
                app_version=payload.app_version,
            )
        except LicenseError as exc:
            raise _public_error(exc) from exc

    @app.get("/admin", response_class=HTMLResponse)
    def admin_console() -> str:
        return ADMIN_HTML

    @app.post("/admin/card-keys", dependencies=[Depends(require_admin)])
    def create_card(payload: CreateCardRequest) -> dict[str, str]:
        try:
            card_key = service.create_card_key(
                features=set(payload.features),
                product_code=payload.product_code,
                max_devices=payload.max_devices,
                expires_at=payload.expires_at,
                policy={
                    "max_active_rooms": payload.max_active_rooms,
                    "export_watermark": payload.export_watermark,
                    "force_upgrade_below": payload.force_upgrade_below,
                },
                note=payload.note,
            )
        except LicenseError as exc:
            raise _public_error(exc) from exc
        return {"card_key": card_key}

    @app.get("/admin/cards", dependencies=[Depends(require_admin)])
    def list_cards(limit: int = 200) -> dict[str, object]:
        return {"cards": service.list_cards(limit=limit)}

    @app.get("/admin/public-key", dependencies=[Depends(require_admin)])
    def public_key() -> dict[str, str]:
        return {"public_key": service.public_key_b64url()}

    @app.get("/admin/activations", dependencies=[Depends(require_admin)])
    def list_activations(limit: int = 200) -> dict[str, object]:
        return {"activations": service.list_activations(limit=limit)}

    @app.post("/admin/activations/{activation_id}/freeze", dependencies=[Depends(require_admin)])
    def freeze(activation_id: str, payload: ReasonRequest) -> dict[str, bool]:
        try:
            service.freeze_activation(activation_id, reason=payload.reason)
        except LicenseError as exc:
            raise _public_error(exc) from exc
        return {"ok": True}

    @app.post("/admin/activations/{activation_id}/unbind", dependencies=[Depends(require_admin)])
    def unbind(activation_id: str, payload: ReasonRequest) -> dict[str, bool]:
        try:
            service.unbind_activation(activation_id, reason=payload.reason)
        except LicenseError as exc:
            raise _public_error(exc) from exc
        return {"ok": True}

    return app


def create_app_from_env() -> FastAPI:
    signing_private_key = os.environ.get("LICENSE_SIGNING_PRIVATE_KEY", "").strip()
    token_hash_secret = os.environ.get("LICENSE_TOKEN_HASH_SECRET", "").strip()
    admin_token = os.environ.get("LICENSE_ADMIN_TOKEN", "").strip()
    settings = LicenseSettings(
        db_path=Path(os.environ.get("LICENSE_DB_PATH", "./license_data/licenses.db")).expanduser(),
        signing_private_key=signing_private_key,
        token_hash_secret=token_hash_secret,
        product_code=os.environ.get("LICENSE_PRODUCT_CODE", "live_replay_xia").strip() or "live_replay_xia",
        license_days=int(os.environ.get("LICENSE_DOCUMENT_DAYS", "3")),
        grace_days=int(os.environ.get("LICENSE_GRACE_DAYS", "1")),
    )
    policy = RateLimitPolicy(
        window_seconds=int(os.environ.get("LICENSE_RATE_LIMIT_WINDOW_SEC", "60")),
        activate_attempts=int(os.environ.get("LICENSE_RATE_LIMIT_ACTIVATE", "8")),
        refresh_attempts=int(os.environ.get("LICENSE_RATE_LIMIT_REFRESH", "60")),
    )
    trusted_proxies = {
        value.strip()
        for value in os.environ.get("LICENSE_TRUSTED_PROXY_IPS", "127.0.0.1,::1").split(",")
        if value.strip()
    }
    return create_app(
        LicenseService(settings),
        admin_token=admin_token,
        update_settings=UpdateSettings(
            product_code=os.environ.get("LICENSE_UPDATE_PRODUCT_CODE", settings.product_code).strip() or settings.product_code,
            latest_version=os.environ.get("LICENSE_UPDATE_LATEST_VERSION", "").strip(),
            min_version=os.environ.get("LICENSE_UPDATE_MIN_VERSION", "").strip(),
            installer_url=os.environ.get("LICENSE_UPDATE_INSTALLER_URL", "").strip(),
            sha256=os.environ.get("LICENSE_UPDATE_INSTALLER_SHA256", "").strip(),
            notes=os.environ.get("LICENSE_UPDATE_NOTES", "").strip(),
            mandatory=os.environ.get("LICENSE_UPDATE_MANDATORY", "").strip().lower() in {"1", "true", "yes", "on"},
        ),
        rate_limiter=IpRateLimiter(policy),
        trusted_proxies=trusted_proxies,
    )
