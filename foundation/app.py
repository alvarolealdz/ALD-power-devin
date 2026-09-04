from typing import Annotated

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.routing import NoMatchFound
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from starlette.exceptions import HTTPException as StarletteHTTPException

from foundation import audit_view, auth, discovery, forms
from foundation.config import CURRENT_USER_COOKIE, TEMPLATES_DIR
from foundation.deps import CurrentUser, DbSession
from foundation.models import AuditLog
from foundation.templating import refresh_loader, templates

STATIC_DIR = TEMPLATES_DIR.parent / "static"

app = FastAPI(title="PowerDevin")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def mount_apps() -> None:
    """Whatever is in apps/ is part of the site. Nothing here names any of them."""
    refresh_loader()
    mounted = discovery.mount(app)
    templates.env.globals["nav_apps"] = [
        {"title": item.title, "path": item.router.prefix or f"/{item.name}"} for item in mounted
    ]


mount_apps()


def _error_status_text(status_code: int) -> str:
    if status_code == 404:
        return "Not found"
    if status_code in {401, 403}:
        return "Not allowed"
    return "Something went wrong"


def _accepts_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if not _accepts_html(request):
        return JSONResponse(
            {"detail": exc.detail},
            status_code=exc.status_code,
            headers=exc.headers,
        )
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "status_code": exc.status_code,
            "status_text": _error_status_text(exc.status_code),
            "detail": exc.detail,
        },
        status_code=exc.status_code,
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    detail = exc.errors()
    if not _accepts_html(request):
        return JSONResponse({"detail": detail}, status_code=422)
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "status_code": 400,
            "status_text": "Something went wrong",
            "detail": "The request could not be understood.",
        },
        status_code=400,
    )


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
    entries = list(session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(25)))
    admin = auth.is_admin(current_user)
    mounted = discovery.discover()
    apps = []
    for item in mounted:
        model = item.model
        count = session.scalar(select(func.count()).select_from(model)) if model else 0
        open_count = None
        if model and item.workflow:
            workflow_field, open_states = item.workflow
            open_count = session.scalar(
                select(func.count()).where(getattr(model, workflow_field).in_(open_states))
            )
        apps.append(
            {
                "title": item.title,
                "description": item.description,
                "count": count or 0,
                "open": open_count,
                "path": item.router.prefix or f"/{item.name}",
            }
        )
    feed = []
    for entry in entries:
        href = None
        target_label = entry.table_name.replace("_", " ").capitalize()
        for item in mounted:
            model = item.model
            if model is None or model.__tablename__ != entry.table_name:
                continue
            target_label = item.singular
            if entry.action != AuditLog.ACTION_DELETE:
                try:
                    href = str(
                        request.url_for(
                            f"{item.name}_detail",
                            **{f"{model.__tablename__}_id": entry.row_id},
                        )
                    )
                except NoMatchFound:
                    pass
            break
        feed.append(
            {
                "actor": entry.actor_label,
                "verb": {
                    AuditLog.ACTION_INSERT: "created",
                    AuditLog.ACTION_UPDATE: "updated",
                    AuditLog.ACTION_DELETE: "deleted",
                }.get(entry.action, entry.action),
                "target": f"{target_label} #{entry.row_id}",
                "href": href,
                "when": forms.display(entry.created_at),
                "changes": (
                    audit_view.changes(entry, admin=admin, session=session)
                    if entry.action == AuditLog.ACTION_UPDATE
                    else []
                ),
            }
        )
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "current_user": current_user,
            "apps": apps,
            "feed": feed,
        },
    )


@app.post("/switch-user", name="switch_user")
def switch_user(session: DbSession, user_id: Annotated[int, Form()]):
    user = auth.resolve_user(session, user_id)
    response = RedirectResponse(url="/", status_code=303)
    if user is not None:
        response.set_cookie(CURRENT_USER_COOKIE, str(user.id), httponly=True, samesite="lax")
    return response
