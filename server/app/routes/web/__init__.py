"""HTML-роуты GuardStar."""

from __future__ import annotations

from app.routes.web.blueprint import web_bp

from app.routes.web import admin_routes  # noqa: F401,E402
from app.routes.web import public_routes  # noqa: F401,E402

__all__ = ["web_bp"]
