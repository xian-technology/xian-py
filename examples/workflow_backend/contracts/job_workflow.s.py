metadata = Hash()
workers = Hash(default_value=False)
items = Hash()

ItemSubmittedEvent = LogEvent(
    "ItemSubmitted",
    {
        "item_id": {"type": str, "idx": True},
        "kind": {"type": str, "idx": True},
        "requester": {"type": str, "idx": True},
    },
)

ItemClaimedEvent = LogEvent(
    "ItemClaimed",
    {
        "item_id": {"type": str, "idx": True},
        "worker": {"type": str, "idx": True},
        "requester": {"type": str},
    },
)

ItemCompletedEvent = LogEvent(
    "ItemCompleted",
    {
        "item_id": {"type": str, "idx": True},
        "worker": {"type": str, "idx": True},
        "result_uri": {"type": str},
    },
)

ItemFailedEvent = LogEvent(
    "ItemFailed",
    {
        "item_id": {"type": str, "idx": True},
        "worker": {"type": str, "idx": True},
        "reason": {"type": str},
    },
)

ItemCancelledEvent = LogEvent(
    "ItemCancelled",
    {
        "item_id": {"type": str, "idx": True},
        "actor": {"type": str, "idx": True},
        "reason": {"type": str},
    },
)

WorkerAddedEvent = LogEvent(
    "WorkerAdded",
    {
        "account": {"type": str, "idx": True},
        "actor": {"type": str, "idx": True},
    },
)

WorkerRemovedEvent = LogEvent(
    "WorkerRemoved",
    {
        "account": {"type": str, "idx": True},
        "actor": {"type": str, "idx": True},
    },
)


@construct
def seed(
    name: str = "Job Workflow",
    operator: str = None,
):
    operator = operator or ctx.caller
    metadata["name"] = name
    metadata["operator"] = operator
    workers[operator] = True


def require_operator():
    assert ctx.caller == metadata["operator"], "Only operator can manage workers."


def require_worker():
    assert workers[ctx.caller], "Only worker can process workflow items."


@export
def add_worker(account: str):
    require_operator()
    workers[account] = True
    WorkerAddedEvent({"account": account, "actor": ctx.caller})


@export
def remove_worker(account: str):
    require_operator()
    assert account != metadata["operator"], "Operator must remain a worker."
    workers[account] = False
    WorkerRemovedEvent({"account": account, "actor": ctx.caller})


@export
def submit_item(
    item_id: str,
    payload_uri: str,
    kind: str = "job",
    metadata_ref: str = "",
):
    assert items[item_id, "status"] is None, "Item already exists."
    kind = kind or "job"
    metadata_ref = metadata_ref or ""
    items[item_id, "requester"] = ctx.caller
    items[item_id, "kind"] = kind
    items[item_id, "payload_uri"] = payload_uri
    items[item_id, "metadata_ref"] = metadata_ref
    items[item_id, "status"] = "submitted"
    items[item_id, "worker"] = ""
    items[item_id, "result_uri"] = ""
    items[item_id, "failure_reason"] = ""
    items[item_id, "created_at"] = str(now)
    items[item_id, "updated_at"] = str(now)
    ItemSubmittedEvent(
        {
            "item_id": item_id,
            "kind": kind,
            "requester": ctx.caller,
        }
    )


@export
def claim_item(item_id: str):
    require_worker()
    assert items[item_id, "status"] == "submitted", "Item is not claimable."
    items[item_id, "status"] = "processing"
    items[item_id, "worker"] = ctx.caller
    items[item_id, "updated_at"] = str(now)
    ItemClaimedEvent(
        {
            "item_id": item_id,
            "worker": ctx.caller,
            "requester": items[item_id, "requester"],
        }
    )


@export
def complete_item(item_id: str, result_uri: str):
    require_worker()
    assert items[item_id, "status"] == "processing", "Item is not processing."
    assert items[item_id, "worker"] == ctx.caller, "Only assigned worker can complete."
    items[item_id, "status"] = "completed"
    items[item_id, "result_uri"] = result_uri
    items[item_id, "updated_at"] = str(now)
    ItemCompletedEvent(
        {
            "item_id": item_id,
            "worker": ctx.caller,
            "result_uri": result_uri,
        }
    )


@export
def fail_item(item_id: str, reason: str):
    require_worker()
    assert items[item_id, "status"] == "processing", "Item is not processing."
    assert items[item_id, "worker"] == ctx.caller, "Only assigned worker can fail."
    items[item_id, "status"] = "failed"
    items[item_id, "failure_reason"] = reason
    items[item_id, "updated_at"] = str(now)
    ItemFailedEvent(
        {
            "item_id": item_id,
            "worker": ctx.caller,
            "reason": reason,
        }
    )


@export
def cancel_item(item_id: str, reason: str = ""):
    assert items[item_id, "status"] == "submitted", "Only submitted items can be cancelled."
    assert (
        ctx.caller == items[item_id, "requester"] or ctx.caller == metadata["operator"]
    ), "Only requester or operator can cancel."
    items[item_id, "status"] = "cancelled"
    items[item_id, "failure_reason"] = reason
    items[item_id, "updated_at"] = str(now)
    ItemCancelledEvent(
        {
            "item_id": item_id,
            "actor": ctx.caller,
            "reason": reason,
        }
    )


@export
def get_item(item_id: str):
    return {
        "item_id": item_id,
        "requester": items[item_id, "requester"],
        "kind": items[item_id, "kind"],
        "payload_uri": items[item_id, "payload_uri"],
        "metadata_ref": items[item_id, "metadata_ref"],
        "status": items[item_id, "status"],
        "worker": items[item_id, "worker"],
        "result_uri": items[item_id, "result_uri"],
        "failure_reason": items[item_id, "failure_reason"],
        "created_at": items[item_id, "created_at"],
        "updated_at": items[item_id, "updated_at"],
    }


@export
def is_worker(account: str):
    return workers[account]
