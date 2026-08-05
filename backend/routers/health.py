import os

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from database import engine
from digest_database import digest_engine
from competition_runtime import deployment_metadata


router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", include_in_schema=False)
def live():
    response = {"status": "ok"}
    if os.getenv("LMATELAB_EDITION") == "107cup":
        response.update(deployment_metadata())
    return response


def database_readiness(primary_engine=engine, digest_database_engine=digest_engine):
    checks = (
        (primary_engine, "users"),
        (digest_database_engine, "daily_digests"),
    )
    for database_engine, table_name in checks:
        with database_engine.connect() as connection:
            connection.execute(text(f"SELECT 1 FROM {table_name} LIMIT 1"))
    return {"status": "ready"}


@router.get("/ready", include_in_schema=False)
def ready():
    try:
        return database_readiness()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="database not ready") from None
