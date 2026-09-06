"""数据库创建、pgvector 初始化和 SQLAlchemy 会话工厂。"""

from __future__ import annotations

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker

from backend.config import Settings
from backend.models import Base


def create_database_and_schema(settings: Settings) -> None:
    """安全地创建目标数据库，并幂等初始化 vector 扩展和表结构。"""
    # CREATE DATABASE 不能处于事务块中，因此管理连接必须显式使用 autocommit。
    with psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname="postgres",
        user=settings.postgres_user,
        password=settings.postgres_password,
        autocommit=True,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (settings.postgres_db,))
            if cursor.fetchone() is None:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(settings.postgres_db)))

    engine = create_engine(settings.database_url(), future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            Base.metadata.create_all(connection)
            _upgrade_sha256_column(connection)
            _ensure_sha256_check_constraint(connection)
            _upgrade_image_metadata_columns(connection)
    finally:
        engine.dispose()


def create_session_factory(settings: Settings) -> sessionmaker[Session]:
    """创建不自动提交的会话工厂，事务边界交由调用方控制。"""
    engine = create_engine(settings.database_url(), future=True)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def dispose_session_factory(factory: sessionmaker[Session]) -> None:
    """显式释放会话工厂绑定的连接池，供短命令和测试 fixture 在结束时调用。"""
    engine = factory.kw.get("bind")
    if engine is not None:
        engine.dispose()


def _upgrade_sha256_column(connection: Connection) -> None:
    """仅在旧开发 schema 已存在时，将安全的 64 位哈希列升级为 char(64)。"""
    column_type = connection.execute(
        text(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'images' AND column_name = 'sha256'
            """
        )
    ).scalar_one()
    if column_type == "character":
        return

    has_invalid_hash = connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM images WHERE length(sha256) <> 64)")
    ).scalar_one()
    if has_invalid_hash:
        raise RuntimeError("现有 images.sha256 含非 64 位哈希，拒绝自动升级列类型。")
    connection.execute(
        text("ALTER TABLE images ALTER COLUMN sha256 TYPE CHAR(64) USING sha256::CHAR(64)")
    )


def _ensure_sha256_check_constraint(connection: Connection) -> None:
    """为既有开发 schema 补充哈希格式约束，坏数据存在时拒绝悄然修改。"""
    constraint_exists = connection.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_images_sha256_lower_hex' AND conrelid = 'images'::regclass)"
        )
    ).scalar_one()
    if constraint_exists:
        return
    has_invalid_hash = connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM images WHERE sha256 !~ '^[0-9a-f]{64}$')")
    ).scalar_one()
    if has_invalid_hash:
        raise RuntimeError("现有 images.sha256 含无效哈希，拒绝自动添加格式约束。")
    connection.execute(
        text("ALTER TABLE images ADD CONSTRAINT ck_images_sha256_lower_hex CHECK (sha256 ~ '^[0-9a-f]{64}$')")
    )


def _upgrade_image_metadata_columns(connection: Connection) -> None:
    """为旧 images 表幂等补齐选填商品元数据，并安全添加价格约束。"""
    for statement in (
        "ALTER TABLE images ADD COLUMN IF NOT EXISTS sku TEXT",
        "ALTER TABLE images ADD COLUMN IF NOT EXISTS product_name TEXT",
        "ALTER TABLE images ADD COLUMN IF NOT EXISTS size TEXT",
        "ALTER TABLE images ADD COLUMN IF NOT EXISTS price NUMERIC(12, 2)",
        "ALTER TABLE images ADD COLUMN IF NOT EXISTS room TEXT",
        "ALTER TABLE images ADD COLUMN IF NOT EXISTS style TEXT",
        "ALTER TABLE images ADD COLUMN IF NOT EXISTS color TEXT",
        "ALTER TABLE images ADD COLUMN IF NOT EXISTS stock TEXT",
        "ALTER TABLE images ADD COLUMN IF NOT EXISTS selling_point TEXT",
    ):
        connection.execute(text(statement))

    constraint_exists = connection.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_constraint "
            "WHERE conname = 'ck_images_price_nonnegative' AND conrelid = 'images'::regclass)"
        )
    ).scalar_one()
    if constraint_exists:
        return
    has_invalid_price = connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM images WHERE price IS NOT NULL AND price < 0)")
    ).scalar_one()
    if has_invalid_price:
        raise RuntimeError("现有 images.price 含负数，拒绝自动添加非负价格约束。")
    connection.execute(
        text(
            "ALTER TABLE images ADD CONSTRAINT ck_images_price_nonnegative "
            "CHECK (price IS NULL OR price >= 0)"
        )
    )
