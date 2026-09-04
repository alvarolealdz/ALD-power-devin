from typing import Annotated

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from foundation import auth, discovery
from foundation.config import CURRENT_USER_COOKIE, TEMPLATES_DIR
from foundation.deps import CurrentUser, DbSession
from foundation.models import AuditLog
from foundation.templating import refresh_loader, templates

STATIC_DIR = TEMPLATES_DIR.parent / "static"

app = FastAPI(title="Foundation")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def mount_apps() -> None:
    """Whatever is in apps/ is part of the site. Nothing here names any of them."""
    refresh_loader()
    mounted = discovery.mount(app)
    templates.env.globals["nav_apps"] = [
        {"title": item.title, "path": item.router.prefix or f"/{item.name}"} for item in mounted
    ]


mount_apps()


@app.middleware("http")
async def clear_current_user(request: Request, call_next):
    token = auth.bind_actor()
    try:
        return await call_next(request)
    finally:
        auth.reset_current_user_id(token)


@app.get("/health")
def health(session: DbSession) -> dict[str, object]:
    session.execute(select(1))
    return {"status": "ok"}


@app.get("/")
def index(request: Request, session: DbSession, current_user: CurrentUser):
    users = auth.list_users(session)
    entries = list(session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(25)))
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "current_user": current_user,
            "users": users,
            "user_columns": [
                {"key": "id", "label": "ID"},
                {"key": "display_name", "label": "Name"},
                {"key": "email", "label": "Email"},
                {"key": "role", "label": "Role"},
            ],
            "user_rows": [
                {
                    "id": user.id,
                    "display_name": user.display_name,
                    "email": user.email,
                    "role": user.role.name,
                }
                for user in users
            ],
            "audit_columns": [
                {"key": "created_at", "label": "When"},
                {"key": "actor", "label": "Actor"},
                {"key": "action", "label": "Action"},
                {"key": "target", "label": "Row"},
                {"key": "before", "label": "Before"},
                {"key": "after", "label": "After"},
            ],
            "audit_rows": [
                {
                    "created_at": entry.created_at.isoformat(timespec="seconds"),
                    "actor": entry.actor_label,
                    "action": entry.action,
                    "target": f"{entry.table_name}#{entry.row_id}",
                    "before": entry.before,
                    "after": entry.after,
                }
                for entry in entries
            ],
        },
    )


@app.post("/switch-user", name="switch_user")
def switch_user(session: DbSession, user_id: Annotated[int, Form()]):
    user = auth.resolve_user(session, user_id)
    response = RedirectResponse(url="/", status_code=303)
    if user is not None:
        response.set_cookie(CURRENT_USER_COOKIE, str(user.id), httponly=True, samesite="lax")
    return response
