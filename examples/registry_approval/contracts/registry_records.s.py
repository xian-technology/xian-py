metadata = Hash()
records = Hash()

RecordUpsertedEvent = LogEvent(
    "RecordUpserted",
    {
        "record_id": {"type": str, "idx": True},
        "owner": {"type": str, "idx": True},
        "version": {"type": int},
        "actor": {"type": str, "idx": True},
    },
)

RecordRevokedEvent = LogEvent(
    "RecordRevoked",
    {
        "record_id": {"type": str, "idx": True},
        "reason": {"type": str},
        "actor": {"type": str, "idx": True},
    },
)


@construct
def seed(
    name: str = "Shared Registry",
    operator: str = None,
):
    operator = operator or ctx.caller
    metadata["name"] = name
    metadata["operator"] = operator
    metadata["approval_contract"] = None


def require_operator():
    assert ctx.caller == metadata["operator"], "Only operator can configure registry."


def require_approval_contract():
    assert metadata["approval_contract"], "Approval contract is not configured."
    assert (
        ctx.caller == metadata["approval_contract"]
    ), "Only approval contract can mutate records."


@export
def set_approval_contract(approval_contract: str):
    require_operator()
    metadata["approval_contract"] = approval_contract


@export
def apply_upsert(
    record_id: str,
    owner: str,
    uri: str,
    checksum: str,
    description: str = "",
):
    require_approval_contract()
    version = (records[record_id, "version"] or 0) + 1
    records[record_id, "owner"] = owner
    records[record_id, "uri"] = uri
    records[record_id, "checksum"] = checksum
    records[record_id, "description"] = description
    records[record_id, "status"] = "active"
    records[record_id, "revoked_reason"] = ""
    records[record_id, "version"] = version
    records[record_id, "updated_at"] = str(now)
    RecordUpsertedEvent(
        {
            "record_id": record_id,
            "owner": owner,
            "version": version,
            "actor": ctx.caller,
        }
    )


@export
def apply_revoke(record_id: str, reason: str):
    require_approval_contract()
    assert records[record_id, "status"] == "active", "Record is not active."
    records[record_id, "status"] = "revoked"
    records[record_id, "revoked_reason"] = reason
    records[record_id, "updated_at"] = str(now)
    RecordRevokedEvent(
        {
            "record_id": record_id,
            "reason": reason,
            "actor": ctx.caller,
        }
    )


@export
def get_record(record_id: str):
    return {
        "record_id": record_id,
        "owner": records[record_id, "owner"],
        "uri": records[record_id, "uri"],
        "checksum": records[record_id, "checksum"],
        "description": records[record_id, "description"],
        "status": records[record_id, "status"],
        "revoked_reason": records[record_id, "revoked_reason"],
        "version": records[record_id, "version"] or 0,
        "updated_at": records[record_id, "updated_at"],
    }


@export
def is_active(record_id: str):
    return records[record_id, "status"] == "active"
