"""The dependencies every route needs, in a module apps can import safely.

They live here rather than in ``foundation.app`` so that an app's ``routes.py``
can import them while ``foundation.app`` is still busy mounting that very app.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from foundation import auth
from foundation.models import User

DbSession = Annotated[Session, Depends(auth.get_db)]
CurrentUser = Annotated[User | None, Depends(auth.get_current_user)]
