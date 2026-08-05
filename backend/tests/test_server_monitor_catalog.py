import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from services.server_monitor.catalog import (
    AccountConfig,
    MemberConfig,
    MemberRegistry,
    PhysicalServerConfig,
    ServerMonitorCatalog,
    catalog_digest,
    load_catalog,
    load_member_registry,
    member_registry_digest,
)


EXPECTED_PHYSICAL_IDS = [
    "dell",
    "dell-gpu",
    "dawn4",
    "dawn5",
    "sugon",
    "jingzhun",
    "jingzhun-gpu",
    "shuangyiliu-huayuan",
    "shuangyiliu-hfnl",
    "scnet",
    "wuxi",
    "dongfang",
]

EXPECTED_SOURCES = [
    "Dell",
    "Dell-GPU",
    "Dawn4",
    "Dawn5",
    "Sugon",
    "Jingzhun-xjwu",
    "Jingzhun-jbwu",
    "Jingzhun-GPU",
    "Shuangyiliu-huayuan",
    "Shuangyiliu-HFNL-xjwu",
    "Shuangyiliu-HFNL-hflv",
    "Shuangyiliu-HFNL-wjb",
    "SCNet",
    "Wuxi",
    "Dongfang-xjwu",
    "Dongfang-yang4",
]

EXPECTED_MEMBERS = [
    "Pwjb",
    "Pwjx",
    "Pwxm",
    "ies",
    "Pchenxj",
    "Pgaoyan",
    "Pjzh",
    "Plyf",
    "Psunmiao",
    "Pxpb",
    "Pbpf",
    "Pcheyx",
    "Pgyh",
    "Pwyt",
    "Plfx",
    "Psxz",
    "Pzhangka",
    "Pzxp",
    "Pcato",
    "Pcxy",
    "Phflv",
    "Pliyuxuan",
    "Pwangdy",
    "Pwyl",
    "Pzzy",
    "Pczp",
    "Pjyq",
    "Pluoxiao",
]


def _account(**overrides):
    account = {
        "id": "account-a",
        "display_name": "Account A",
        "source_id": "Source-A",
        "mode": "node21_pull",
        "transport": "local",
        "expected_interval_minutes": 30,
        "stale_after_minutes": 90,
    }
    account.update(overrides)
    return account


def _catalog_payload(*physical_servers):
    return {"schema_version": 1, "physical_servers": list(physical_servers)}


def _physical(**overrides):
    physical = {
        "id": "physical-a",
        "display_name": "Physical A",
        "scheduler": "pbs",
        "accounts": [_account()],
    }
    physical.update(overrides)
    return physical


def test_default_catalog_has_required_servers_sources_and_account_group_order():
    catalog = load_catalog()

    assert catalog.schema_version == 1
    assert [server.id for server in catalog.physical_servers] == EXPECTED_PHYSICAL_IDS
    assert [
        account.source_id
        for server in catalog.physical_servers
        for account in server.accounts
    ] == EXPECTED_SOURCES
    assert len(catalog.physical_servers) == 12
    assert len(EXPECTED_SOURCES) == 16

    confirmed_account_groups = [
        (server.id, [account.id for account in server.accounts])
        for server in catalog.physical_servers
        if len(server.accounts) > 1
    ]
    assert confirmed_account_groups == [
        ("jingzhun", ["xjwu", "jbwu"]),
        ("shuangyiliu-hfnl", ["xjwu", "hflv", "wjb"]),
        ("dongfang", ["xjwu", "yang4"]),
    ]


def test_catalog_lookup_and_jingzhun_gpu_are_unambiguous():
    catalog = load_catalog()

    assert catalog.physical("dell").display_name == "Dell服务器"
    assert catalog.account_by_source("Dawn4").host == "222.195.80.62"
    assert catalog.account_by_legacy_source("Jingzhun-jbwu").login == "wujiabao"
    assert catalog.physical("missing") is None
    assert catalog.account_by_source("missing") is None
    assert catalog.account_by_legacy_source("missing") is None

    gpu = catalog.physical("jingzhun-gpu")
    assert gpu.display_name == "精准平台 GPU"
    assert [account.source_id for account in gpu.accounts] == ["Jingzhun-GPU"]
    assert gpu.accounts[0].setup_state == "account_unconfirmed"
    assert gpu.accounts[0].login is None
    assert catalog.physical("jingzhun").accounts[0].source_id == "Jingzhun-xjwu"


def test_required_account_details_and_pending_setup_are_preserved():
    catalog = load_catalog()

    dell = catalog.account_by_source("Dell")
    assert dell.model_dump() == {
        "id": "Pwjb",
        "display_name": "Pwjb",
        "source_id": "Dell",
        "legacy_source": "Dell",
        "login": "Pwjb",
        "host": "localhost",
        "remote_path": None,
        "mode": "node21_pull",
        "transport": "local",
        "expected_interval_minutes": 30,
        "stale_after_minutes": 90,
        "snapshot_priority": 10,
        "setup_state": "configured",
    }

    pending = catalog.account_by_source("Shuangyiliu-HFNL-wjb")
    assert pending.legacy_source is None
    assert pending.remote_path is None
    assert pending.snapshot_priority == 30
    assert pending.setup_state == "pending_setup"

    for source in ("SCNet", "Wuxi"):
        account = catalog.account_by_source(source)
        assert account.mode == "windows_relay"
        assert account.transport == "ssh"
        assert account.setup_state == "account_unconfirmed"
        assert account.login is None and account.host is None and account.remote_path is None


def test_default_member_registry_has_only_the_28_canonical_members():
    registry = load_member_registry()

    assert registry.schema_version == 1
    assert [member.id for member in registry.members] == EXPECTED_MEMBERS
    assert len(registry.members) == 28
    assert registry.resolve("Pwjb").display_name == "吴佳宝"
    assert registry.resolve("Plyf").display_name == "李毅凡"
    assert registry.resolve("Pzhangka").display_name == "张凯"
    assert registry.resolve("Psunmiao").display_name == "孙淼"
    assert registry.resolve("Pbpf").display_name == "白鹏飞"
    assert registry.resolve("Phflv").display_name == "吕海峰"
    assert registry.resolve("Pwjx").display_name == "Pwjx"


@pytest.mark.parametrize(
    ("alias", "member_id"),
    [
        ("  WJB  ", "Pwjb"),
        ("WUJIABAO", "Pwjb"),
        ("lyf", "Plyf"),
        ("SUNMIAO", "Psunmiao"),
        ("xpb", "Pxpb"),
        ("bpf", "Pbpf"),
        ("yxche", "Pcheyx"),
        ("wyt", "Pwyt"),
        ("sxz", "Psxz"),
        ("pzhangkai", "Pzhangka"),
        ("hflv", "Phflv"),
        ("chenzp", "Pczp"),
    ],
)
def test_member_alias_resolution_is_trimmed_and_case_insensitive(alias, member_id):
    assert load_member_registry().resolve(alias).id == member_id


@pytest.mark.parametrize(
    "username",
    ["lil", "ll", "plil", "zhangwh", "whzhang", "qxli", "bli", "bcpan", "unknown", ""],
)
def test_external_and_unknown_users_do_not_resolve(username):
    assert load_member_registry().resolve(username) is None


@pytest.mark.parametrize(
    "payload",
    [
        _catalog_payload(_physical(), _physical(accounts=[_account(source_id="Source-B")])),
        _catalog_payload(
            _physical(
                accounts=[
                    _account(),
                    _account(id="account-b", source_id="Source-A"),
                ]
            )
        ),
        _catalog_payload(
            _physical(
                accounts=[
                    _account(),
                    _account(id="account-a", source_id="Source-B"),
                ]
            )
        ),
    ],
)
def test_catalog_rejects_duplicate_physical_source_and_local_account_ids(payload):
    with pytest.raises(ValidationError):
        ServerMonitorCatalog.model_validate(payload)


def test_catalog_rejects_stale_threshold_shorter_than_expected_interval():
    payload = _catalog_payload(
        _physical(accounts=[_account(expected_interval_minutes=91, stale_after_minutes=90)])
    )

    with pytest.raises(ValidationError, match="stale_after_minutes"):
        ServerMonitorCatalog.model_validate(payload)


@pytest.mark.parametrize("field", ["expected_interval_minutes", "stale_after_minutes"])
def test_catalog_rejects_non_positive_intervals(field):
    payload = _catalog_payload(_physical(accounts=[_account(**{field: 0})]))

    with pytest.raises(ValidationError):
        ServerMonitorCatalog.model_validate(payload)


def test_schema_version_and_nonempty_server_and_account_lists_are_enforced():
    for payload in (
        {"schema_version": 2, "physical_servers": [_physical()]},
        {"schema_version": 1, "physical_servers": []},
        _catalog_payload(_physical(accounts=[])),
    ):
        with pytest.raises(ValidationError):
            ServerMonitorCatalog.model_validate(payload)


@pytest.mark.parametrize(
    "members",
    [
        [
            {"id": "Alpha", "aliases": ["Alpha", "shared"]},
            {"id": "Beta", "aliases": ["Beta", "SHARED"]},
        ],
        [{"id": "Alpha", "aliases": []}],
        [{"id": "Alpha", "aliases": ["Alpha", "   "]}],
    ],
)
def test_member_registry_rejects_casefolded_collisions_and_empty_aliases(members):
    with pytest.raises(ValidationError):
        MemberRegistry.model_validate({"schema_version": 1, "members": members})


def test_explicit_paths_and_environment_overrides_do_not_contaminate_loads(tmp_path, monkeypatch):
    catalog_a_path = tmp_path / "catalog-a.json"
    catalog_b_path = tmp_path / "catalog-b.json"
    registry_a_path = tmp_path / "members-a.json"
    registry_b_path = tmp_path / "members-b.json"
    catalog_a_path.write_text(json.dumps(_catalog_payload(_physical(id="a"))), encoding="utf-8")
    catalog_b_path.write_text(json.dumps(_catalog_payload(_physical(id="b"))), encoding="utf-8")
    registry_a_path.write_text(
        json.dumps({"schema_version": 1, "members": [{"id": "Alpha", "aliases": ["Alpha"]}]}),
        encoding="utf-8",
    )
    registry_b_path.write_text(
        json.dumps({"schema_version": 1, "members": [{"id": "Beta", "aliases": ["Beta"]}]}),
        encoding="utf-8",
    )

    monkeypatch.setenv("SERVER_MONITOR_CATALOG_PATH", str(catalog_a_path))
    monkeypatch.setenv("SERVER_MONITOR_MEMBERS_PATH", str(registry_a_path))
    assert load_catalog().physical("a") is not None
    assert load_member_registry().resolve("alpha").id == "Alpha"
    assert load_catalog(catalog_b_path).physical("b") is not None
    assert load_member_registry(registry_b_path).resolve("beta").id == "Beta"
    assert load_catalog().physical("a") is not None
    assert load_member_registry().resolve("alpha").id == "Alpha"


def test_digests_are_stable_across_json_formatting(tmp_path):
    catalog_payload = _catalog_payload(_physical())
    members_payload = {
        "schema_version": 1,
        "members": [{"id": "Alpha", "aliases": ["Alpha", "a"]}],
    }
    compact_catalog = tmp_path / "catalog-compact.json"
    pretty_catalog = tmp_path / "catalog-pretty.json"
    compact_members = tmp_path / "members-compact.json"
    pretty_members = tmp_path / "members-pretty.json"
    compact_catalog.write_text(json.dumps(catalog_payload, separators=(",", ":")), encoding="utf-8")
    pretty_catalog.write_text(json.dumps(catalog_payload, indent=4), encoding="utf-8")
    compact_members.write_text(json.dumps(members_payload, separators=(",", ":")), encoding="utf-8")
    pretty_members.write_text(json.dumps(members_payload, indent=4), encoding="utf-8")

    assert catalog_digest(path=compact_catalog) == catalog_digest(path=pretty_catalog)
    assert member_registry_digest(path=compact_members) == member_registry_digest(path=pretty_members)
    assert len(catalog_digest(path=compact_catalog)) == 64
    assert len(member_registry_digest(path=compact_members)) == 64


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            ServerMonitorCatalog,
            {**_catalog_payload(_physical()), "unexpected": True},
        ),
        (
            ServerMonitorCatalog,
            _catalog_payload(_physical(unexpected=True)),
        ),
        (
            ServerMonitorCatalog,
            _catalog_payload(_physical(accounts=[_account(unexpected=True)])),
        ),
        (
            MemberRegistry,
            {
                "schema_version": 1,
                "members": [{"id": "Alpha", "aliases": ["Alpha"]}],
                "unexpected": True,
            },
        ),
        (
            MemberRegistry,
            {
                "schema_version": 1,
                "members": [
                    {"id": "Alpha", "aliases": ["Alpha"], "unexpected": True}
                ],
            },
        ),
    ],
)
def test_catalog_models_reject_unknown_top_level_and_nested_fields(model, payload):
    with pytest.raises(ValidationError, match="extra_forbidden"):
        model.model_validate(payload)


@pytest.mark.parametrize(
    "physical_servers",
    [
        [
            _physical(
                accounts=[
                    _account(
                        id="account-a",
                        source_id="Source-A",
                        legacy_source="Legacy-A",
                    ),
                    _account(
                        id="account-b",
                        source_id="Source-B",
                        legacy_source="Legacy-A",
                    ),
                ]
            )
        ],
        [
            _physical(
                id="physical-a",
                accounts=[_account(source_id="Source-A", legacy_source="Legacy-A")],
            ),
            _physical(
                id="physical-b",
                accounts=[_account(source_id="Source-B", legacy_source="Legacy-A")],
            ),
        ],
    ],
)
def test_catalog_rejects_duplicate_non_null_legacy_sources_globally(physical_servers):
    with pytest.raises(ValidationError, match="legacy source"):
        ServerMonitorCatalog.model_validate(_catalog_payload(*physical_servers))


@pytest.mark.parametrize("invalid_id", ["", "   ", "../escape", "a/b", "a\\b"])
@pytest.mark.parametrize(
    ("model", "payload", "field"),
    [
        (PhysicalServerConfig, _physical(), "id"),
        (AccountConfig, _account(), "id"),
        (AccountConfig, _account(), "source_id"),
        (AccountConfig, _account(legacy_source="Legacy-A"), "legacy_source"),
        (MemberConfig, {"id": "Alpha", "aliases": ["Alpha"]}, "id"),
    ],
)
def test_stable_ids_reject_empty_whitespace_and_path_like_values(
    model, payload, field, invalid_id
):
    payload = dict(payload)
    payload[field] = invalid_id

    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    ("mode", "transport"),
    [
        ("node21_pull", "ssh"),
        ("node21_pull", "upload"),
        ("windows_relay", "local"),
        ("windows_relay", "rsync"),
        ("windows_relay", "upload"),
        ("manual_upload", "local"),
        ("manual_upload", "rsync"),
        ("manual_upload", "ssh"),
    ],
)
def test_account_rejects_invalid_mode_transport_pairs(mode, transport):
    with pytest.raises(ValidationError, match="mode.*transport"):
        AccountConfig.model_validate(_account(mode=mode, transport=transport))


@pytest.mark.parametrize(
    "account",
    [
        _account(
            mode="node21_pull",
            transport="rsync",
            login=None,
            host="example.org",
            remote_path="/remote/status",
        ),
        _account(
            mode="node21_pull",
            transport="rsync",
            login="user",
            host=None,
            remote_path="/remote/status",
        ),
        _account(
            mode="node21_pull",
            transport="rsync",
            login="user",
            host="example.org",
            remote_path=None,
        ),
        _account(
            mode="windows_relay",
            transport="ssh",
            login=None,
            host="example.org",
        ),
        _account(
            mode="windows_relay",
            transport="ssh",
            login="user",
            host=None,
        ),
        _account(
            mode="manual_upload",
            transport="upload",
            login="user",
        ),
        _account(
            mode="manual_upload",
            transport="upload",
            host="example.org",
        ),
        _account(
            mode="manual_upload",
            transport="upload",
            remote_path="/remote/status",
        ),
    ],
)
def test_configured_accounts_reject_missing_or_forbidden_endpoint_metadata(account):
    with pytest.raises(ValidationError, match="configured"):
        AccountConfig.model_validate(account)


def test_non_configured_account_may_omit_connection_metadata_for_valid_pair():
    account = AccountConfig.model_validate(
        _account(
            mode="windows_relay",
            transport="ssh",
            setup_state="pending_setup",
            login=None,
            host=None,
            remote_path=None,
        )
    )

    assert account.setup_state == "pending_setup"


def test_dongfang_accounts_wait_for_windows_preflight():
    accounts = load_catalog().physical("dongfang").accounts

    assert [account.id for account in accounts] == ["xjwu", "yang4"]
    assert [account.setup_state for account in accounts] == [
        "pending_setup",
        "pending_setup",
    ]
    assert all(account.host is None and account.remote_path is None for account in accounts)


def test_member_registry_requires_at_least_one_member():
    with pytest.raises(ValidationError):
        MemberRegistry.model_validate({"schema_version": 1, "members": []})


def test_repeated_member_resolution_preserves_public_behavior_and_digest():
    registry = MemberRegistry.model_validate(
        {
            "schema_version": 1,
            "members": [
                {"id": "Alpha", "aliases": ["Alpha", "alpha-alias"]},
                {"id": "Beta", "aliases": ["Beta"]},
            ],
        }
    )
    before = member_registry_digest(registry)

    first = registry.resolve(" alpha-alias ")
    second = registry.resolve("ALPHA-ALIAS")

    assert first.id == second.id == "Alpha"
    assert registry.resolve("missing") is None
    assert member_registry_digest(registry) == before
    assert set(registry.model_dump()) == {"schema_version", "members"}


def test_loaded_catalog_models_reject_field_reassignment_without_digest_change():
    catalog = load_catalog()
    account = catalog.account_by_source("Dell")
    before = catalog_digest(catalog)

    with pytest.raises(ValidationError, match="frozen_instance"):
        catalog.schema_version = 1
    with pytest.raises(ValidationError, match="frozen_instance"):
        account.host = "mutated.example.org"

    assert catalog.account_by_source("Dell").host == "localhost"
    assert catalog_digest(catalog) == before


def test_loaded_member_models_reject_field_reassignment_without_behavior_change():
    registry = load_member_registry()
    member = registry.resolve("wjb")
    before = member_registry_digest(registry)

    with pytest.raises(ValidationError, match="frozen_instance"):
        registry.schema_version = 1
    with pytest.raises(ValidationError, match="frozen_instance"):
        member.display_name = "Mutated"
    with pytest.raises(ValidationError, match="frozen_instance"):
        member.aliases = (*member.aliases, "mutated-alias")

    assert registry.resolve("wjb").display_name == "吴佳宝"
    assert registry.resolve("mutated-alias") is None
    assert member_registry_digest(registry) == before


def test_loaded_catalog_collections_are_tuples_without_append():
    catalog = load_catalog()
    server = catalog.physical("dell")
    before = catalog_digest(catalog)

    assert isinstance(catalog.physical_servers, tuple)
    assert isinstance(server.accounts, tuple)
    with pytest.raises(AttributeError):
        catalog.physical_servers.append(server)
    with pytest.raises(AttributeError):
        server.accounts.append(server.accounts[0])

    assert catalog_digest(catalog) == before


def test_loaded_member_collections_are_tuples_without_append():
    registry = load_member_registry()
    member = registry.resolve("wjb")
    before = member_registry_digest(registry)

    assert isinstance(registry.members, tuple)
    assert isinstance(member.aliases, tuple)
    with pytest.raises(AttributeError):
        registry.members.append(member)
    with pytest.raises(AttributeError):
        member.aliases.append("mutated-alias")

    assert registry.resolve("mutated-alias") is None
    assert member_registry_digest(registry) == before
