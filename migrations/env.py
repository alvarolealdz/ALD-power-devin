from logging.config import fileConfig

from alembic import context

import foundation.models  # noqa: F401  registers the foundation tables on Base.metadata
from foundation import discovery
from foundation.config import DATABASE_URL
from foundation.db import Base, make_engine
from foundation.write_guard import raw_writes_allowed

discovery.import_models()  # whatever sits in apps/ joins Base.metadata too

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = make_engine(DATABASE_URL)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        # Migrations are the one place allowed to write outside foundation.audit.
        with raw_writes_allowed(), context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
