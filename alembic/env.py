import asyncio
from logging.config import fileConfig

from sqlalchemy import Column, MetaData, String, Table, inspect, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from alembic.script import ScriptDirectory

# Import all models to ensure they're registered with SQLAlchemy metadata
import src.models.property  # noqa: F401
import src.models.lease  # noqa: F401
import src.models.market  # noqa: F401
import src.models.expense  # noqa: F401
import src.models.valuation  # noqa: F401
import src.models  # noqa: F401,E402
from src.models.base import Base
from src.config import settings

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    # Early OpenDCF installs used metadata.create_all and therefore shipped an empty initial
    # Alembic revision. Bootstrap only a genuinely empty database from today's authoritative
    # metadata; existing databases continue through the incremental migration chain normally.
    application_tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
    if not application_tables:
        with context.begin_transaction():
            Base.metadata.create_all(connection)
            version_table = Table(
                "alembic_version",
                MetaData(),
                Column("version_num", String(32), nullable=False),
            )
            version_table.create(connection, checkfirst=True)
            connection.execute(version_table.delete())
            heads = ScriptDirectory.from_config(config).get_heads()
            connection.execute(version_table.insert(), [{"version_num": head} for head in heads])
            connection.commit()
        return
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
