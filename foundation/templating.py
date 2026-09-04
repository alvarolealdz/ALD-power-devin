"""One Jinja environment for the foundation and every discovered app.

Foundation templates are addressed as they always were (``layout.html``,
``partials/table.html``). An app's own templates live beside its code and are
addressed under its name: ``items/list.html`` is ``apps/items/templates/list.html``.
Apps can therefore extend and include foundation partials without knowing where
they are on disk.
"""

from jinja2 import ChoiceLoader, FileSystemLoader, PrefixLoader
from starlette.templating import Jinja2Templates

from foundation import discovery
from foundation.config import TEMPLATES_DIR

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def refresh_loader() -> None:
    """Rebuild the loader so newly generated apps become renderable."""
    app_loaders = {
        app.name: FileSystemLoader(str(app.templates_dir))
        for app in discovery.discover()
        if app.templates_dir.is_dir()
    }
    templates.env.loader = ChoiceLoader(
        [FileSystemLoader(str(TEMPLATES_DIR)), PrefixLoader(app_loaders, delimiter="/")]
    )


refresh_loader()
