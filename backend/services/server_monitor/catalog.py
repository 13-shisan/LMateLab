import hashlib
import json
import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    StringConstraints,
    field_validator,
    model_validator,
)


_BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_PATH = _BACKEND_ROOT / "config" / "server_monitor_catalog.json"
DEFAULT_MEMBERS_PATH = _BACKEND_ROOT / "config" / "server_monitor_members.json"


StableId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]


class StrictCatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AccountConfig(StrictCatalogModel):
    id: StableId
    display_name: str
    source_id: StableId
    legacy_source: StableId | None = None
    login: str | None = None
    host: str | None = None
    remote_path: str | None = None
    mode: Literal["node21_pull", "windows_relay", "manual_upload"]
    transport: Literal["local", "rsync", "ssh", "upload"]
    expected_interval_minutes: int = Field(gt=0)
    stale_after_minutes: int = Field(gt=0)
    snapshot_priority: int = 100
    setup_state: Literal["configured", "pending_setup", "account_unconfirmed"] = (
        "configured"
    )

    @model_validator(mode="after")
    def validate_account_configuration(self):
        if self.stale_after_minutes < self.expected_interval_minutes:
            raise ValueError(
                "stale_after_minutes must be at least expected_interval_minutes"
            )

        valid_transports = {
            "node21_pull": {"local", "rsync"},
            "windows_relay": {"ssh"},
            "manual_upload": {"upload"},
        }
        if self.transport not in valid_transports[self.mode]:
            raise ValueError(
                f"mode {self.mode} is incompatible with transport {self.transport}"
            )

        if self.setup_state != "configured":
            return self

        def missing(value: str | None) -> bool:
            return value is None or not value.strip()

        if self.transport == "rsync" and any(
            missing(value) for value in (self.login, self.host, self.remote_path)
        ):
            raise ValueError(
                "configured rsync accounts require login, host, and remote_path"
            )
        if self.transport == "ssh" and any(
            missing(value) for value in (self.login, self.host)
        ):
            raise ValueError("configured ssh accounts require login and host")
        if self.transport == "upload" and any(
            value is not None for value in (self.login, self.host, self.remote_path)
        ):
            raise ValueError(
                "configured upload accounts must not define SSH endpoint fields"
            )
        return self


class PhysicalServerConfig(StrictCatalogModel):
    id: StableId
    display_name: str
    scheduler: Literal["pbs", "slurm", "unknown"]
    accounts: tuple[AccountConfig, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_account_ids(self):
        account_ids = [account.id for account in self.accounts]
        if len(account_ids) != len(set(account_ids)):
            raise ValueError(f"duplicate account id in physical server {self.id}")
        return self


class ServerMonitorCatalog(StrictCatalogModel):
    schema_version: Literal[1]
    physical_servers: tuple[PhysicalServerConfig, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_global_identifiers(self):
        physical_ids = [server.id for server in self.physical_servers]
        if len(physical_ids) != len(set(physical_ids)):
            raise ValueError("duplicate physical server id")

        source_ids = [
            account.source_id
            for server in self.physical_servers
            for account in server.accounts
        ]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("duplicate account source id")

        legacy_sources = [
            account.legacy_source
            for server in self.physical_servers
            for account in server.accounts
            if account.legacy_source is not None
        ]
        if len(legacy_sources) != len(set(legacy_sources)):
            raise ValueError("duplicate account legacy source")
        return self

    def physical(self, physical_id: str) -> PhysicalServerConfig | None:
        return next(
            (server for server in self.physical_servers if server.id == physical_id),
            None,
        )

    def account_by_source(self, source_id: str) -> AccountConfig | None:
        return next(
            (
                account
                for server in self.physical_servers
                for account in server.accounts
                if account.source_id == source_id
            ),
            None,
        )

    def account_by_legacy_source(self, legacy_source: str) -> AccountConfig | None:
        return next(
            (
                account
                for server in self.physical_servers
                for account in server.accounts
                if account.legacy_source == legacy_source
            ),
            None,
        )


class MemberConfig(StrictCatalogModel):
    id: StableId
    display_name: str = ""
    aliases: tuple[str, ...] = Field(min_length=1)

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, aliases: tuple[str, ...]) -> tuple[str, ...]:
        if any(not alias.strip() for alias in aliases):
            raise ValueError("aliases must not be empty")
        return aliases

    @model_validator(mode="after")
    def default_display_name(self):
        if not self.display_name:
            object.__setattr__(self, "display_name", self.id)
        return self


class MemberRegistry(StrictCatalogModel):
    schema_version: Literal[1]
    members: tuple[MemberConfig, ...] = Field(min_length=1)
    _alias_index: dict[str, MemberConfig] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_members_and_aliases(self):
        member_ids = [member.id for member in self.members]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("duplicate member id")

        alias_index: dict[str, MemberConfig] = {}
        for member in self.members:
            for alias in member.aliases:
                normalized = alias.strip().casefold()
                if normalized in alias_index:
                    raise ValueError("duplicate member alias")
                alias_index[normalized] = member
        self._alias_index = alias_index
        return self

    def resolve(self, username: str) -> MemberConfig | None:
        normalized = username.strip().casefold()
        if not normalized:
            return None
        return self._alias_index.get(normalized)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_catalog(path: str | Path | None = None) -> ServerMonitorCatalog:
    resolved = Path(
        path
        or os.getenv("SERVER_MONITOR_CATALOG_PATH")
        or DEFAULT_CATALOG_PATH
    )
    return ServerMonitorCatalog.model_validate(_load_json(resolved))


def load_member_registry(path: str | Path | None = None) -> MemberRegistry:
    resolved = Path(
        path
        or os.getenv("SERVER_MONITOR_MEMBERS_PATH")
        or DEFAULT_MEMBERS_PATH
    )
    return MemberRegistry.model_validate(_load_json(resolved))


def _canonical_digest(model: BaseModel) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def catalog_digest(
    catalog: ServerMonitorCatalog | None = None,
    *,
    path: str | Path | None = None,
) -> str:
    return _canonical_digest(catalog or load_catalog(path))


def member_registry_digest(
    registry: MemberRegistry | None = None,
    *,
    path: str | Path | None = None,
) -> str:
    return _canonical_digest(registry or load_member_registry(path))
