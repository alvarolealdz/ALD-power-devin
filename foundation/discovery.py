"""Finds the apps sitting in apps/ and mounts them.

The generator never edits foundation. An app is mounted because it exists: a
directory under ``apps/`` holding a ``routes.py`` that exposes ``router``, and
usually a ``model.py`` and a ``templates/`` directory beside it.

Import failures are deliberately not swallowed. A broken app is a broken app,
and finding out at startup beats finding out from a 404.
"""

import importlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, FastAPI

from foundation.config import APPS_DIR


@dataclass(frozen=True)
class DiscoveredApp:
    name: str
    path: Path

    @property
    def templates_dir(self) -> Path:
        return self.path / "templates"

    @property
    def has_model(self) -> bool:
        return (self.path / "model.py").exists()

    def module(self, name: str):
        return importlib.import_module(f"{APPS_DIR.name}.{self.name}.{name}")

    @property
    def router(self) -> APIRouter:
        return self.module("routes").router

    @property
    def title(self) -> str:
        """What the nav calls it. Apps set ``TITLE`` in routes.py; this is the fallback."""
        return getattr(self.module("routes"), "TITLE", self.name.replace("_", " ").capitalize())

    @property
    def description(self) -> str:
        return getattr(self.module("routes"), "DESCRIPTION", "")

    @property
    def singular(self) -> str:
        return getattr(self.module("routes"), "SINGULAR", self.name.replace("_", " ").capitalize())

    @property
    def workflow(self) -> tuple[str, tuple[str, ...]] | None:
        module = self.module("routes")
        field = getattr(module, "WORKFLOW_FIELD", None)
        open_states = getattr(module, "OPEN_STATES", None)
        if not field or not open_states:
            return None
        return field, tuple(open_states)

    @property
    def model(self):
        return getattr(self.module("routes"), "MODEL", None)


def discover(apps_dir: Path = APPS_DIR) -> list[DiscoveredApp]:
    """Every importable app directory, in a stable order."""
    return sorted(_candidates(apps_dir), key=lambda app: app.name)


def _candidates(apps_dir: Path) -> Iterator[DiscoveredApp]:
    if not apps_dir.is_dir():
        return
    for path in apps_dir.iterdir():
        if not path.is_dir() or path.name.startswith((".", "_")):
            continue
        if (path / "routes.py").exists():
            yield DiscoveredApp(name=path.name, path=path)


def import_models(apps_dir: Path = APPS_DIR) -> None:
    """Import every app model so its table lands in ``Base.metadata``.

    Alembic needs this for autogenerate; nothing else should have to care.
    """
    for app in discover(apps_dir):
        if app.has_model:
            app.module("model")


def mount(api: FastAPI, apps_dir: Path = APPS_DIR) -> list[DiscoveredApp]:
    """Include every discovered app's router. Returns what was mounted."""
    mounted = discover(apps_dir)
    for app in mounted:
        api.include_router(app.router)
    return mounted
