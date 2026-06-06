metadata = Hash()
signers = Hash(default_value=False)
proposals = Hash()
proposal_votes = Hash(default_value=False)
proposal_vote_count = Hash(default_value=0)

proposal_count = Variable()
signer_count = Variable()

ProposalSubmittedEvent = LogEvent(
    "ProposalSubmitted",
    {
        "proposal_id": {"type": int, "idx": True},
        "action": {"type": str, "idx": True},
        "record_id": {"type": str, "idx": True},
        "proposer": {"type": str},
    },
)

ProposalApprovedEvent = LogEvent(
    "ProposalApproved",
    {
        "proposal_id": {"type": int, "idx": True},
        "approver": {"type": str, "idx": True},
        "approved_count": {"type": int},
    },
)

ProposalExecutedEvent = LogEvent(
    "ProposalExecuted",
    {
        "proposal_id": {"type": int, "idx": True},
        "action": {"type": str, "idx": True},
        "record_id": {"type": str, "idx": True},
        "executor": {"type": str},
    },
)

SignerAddedEvent = LogEvent(
    "SignerAdded",
    {
        "account": {"type": str, "idx": True},
        "actor": {"type": str, "idx": True},
    },
)

SignerRemovedEvent = LogEvent(
    "SignerRemoved",
    {
        "account": {"type": str, "idx": True},
        "actor": {"type": str, "idx": True},
    },
)

ThresholdChangedEvent = LogEvent(
    "ThresholdChanged",
    {
        "threshold": {"type": int},
        "actor": {"type": str, "idx": True},
    },
)


@construct
def seed(
    registry_contract: str,
    operator: str = None,
    threshold: int = 1,
):
    operator = operator or ctx.caller
    metadata["operator"] = operator
    metadata["registry_contract"] = registry_contract
    metadata["threshold"] = threshold
    signers[operator] = True
    signer_count.set(1)
    proposal_count.set(0)


def require_operator():
    assert ctx.caller == metadata["operator"], "Only operator can manage signers."


def require_signer():
    assert signers[ctx.caller], "Only signer can submit or approve proposals."


def validate_threshold(new_threshold: int):
    assert new_threshold > 0, "Threshold must be positive."
    assert (
        new_threshold <= signer_count.get()
    ), "Threshold exceeds current signer count."


@export
def set_registry_contract(registry_contract_name: str):
    require_operator()
    metadata["registry_contract"] = registry_contract_name


@export
def add_signer(account: str):
    require_operator()
    assert not signers[account], "Already a signer."
    signers[account] = True
    signer_count.set(signer_count.get() + 1)
    SignerAddedEvent({"account": account, "actor": ctx.caller})


@export
def remove_signer(account: str):
    require_operator()
    assert signers[account], "Not a signer."
    assert account != metadata["operator"], "Operator must remain a signer."
    new_signer_count = signer_count.get() - 1
    assert (
        metadata["threshold"] <= new_signer_count
    ), "Remove signer only after lowering threshold."
    signers[account] = False
    signer_count.set(new_signer_count)
    SignerRemovedEvent({"account": account, "actor": ctx.caller})


@export
def set_threshold(new_threshold: int):
    require_operator()
    validate_threshold(new_threshold)
    metadata["threshold"] = new_threshold
    ThresholdChangedEvent({"threshold": new_threshold, "actor": ctx.caller})


def create_proposal(
    action: str,
    record_id: str,
    owner: str = "",
    uri: str = "",
    checksum: str = "",
    description: str = "",
    reason: str = "",
):
    require_signer()
    next_id = proposal_count.get() + 1
    proposal_count.set(next_id)
    proposals[next_id, "action"] = action
    proposals[next_id, "record_id"] = record_id
    proposals[next_id, "owner"] = owner
    proposals[next_id, "uri"] = uri
    proposals[next_id, "checksum"] = checksum
    proposals[next_id, "description"] = description
    proposals[next_id, "reason"] = reason
    proposals[next_id, "proposer"] = ctx.caller
    proposals[next_id, "executed"] = False
    proposals[next_id, "created_at"] = str(now)
    ProposalSubmittedEvent(
        {
            "proposal_id": next_id,
            "action": action,
            "record_id": record_id,
            "proposer": ctx.caller,
        }
    )
    approve_and_maybe_execute(next_id)
    return next_id


@export
def propose_upsert(
    record_id: str,
    owner: str,
    uri: str,
    checksum: str,
    description: str = "",
):
    return create_proposal(
        "upsert",
        record_id,
        owner=owner,
        uri=uri,
        checksum=checksum,
        description=description,
    )


@export
def propose_revoke(record_id: str, reason: str):
    return create_proposal("revoke", record_id, reason=reason)


@export
def approve(proposal_id: int):
    require_signer()
    assert proposals[proposal_id, "action"], "Proposal does not exist."
    assert not proposals[proposal_id, "executed"], "Proposal already executed."
    return approve_and_maybe_execute(proposal_id)


def approve_and_maybe_execute(proposal_id: int):
    assert not proposal_votes[proposal_id, ctx.caller], "Already approved."
    proposal_votes[proposal_id, ctx.caller] = True
    proposal_vote_count[proposal_id] += 1
    ProposalApprovedEvent(
        {
            "proposal_id": proposal_id,
            "approver": ctx.caller,
            "approved_count": proposal_vote_count[proposal_id],
        }
    )

    if proposal_vote_count[proposal_id] >= metadata["threshold"]:
        execute_proposal(proposal_id)

    return {
        "proposal_id": proposal_id,
        "approved_count": proposal_vote_count[proposal_id],
        "executed": proposals[proposal_id, "executed"],
    }


def execute_proposal(proposal_id: int):
    registry = importlib.import_module(metadata["registry_contract"])
    action = proposals[proposal_id, "action"]
    record_id = proposals[proposal_id, "record_id"]

    if action == "upsert":
        registry.apply_upsert(
            record_id=record_id,
            owner=proposals[proposal_id, "owner"],
            uri=proposals[proposal_id, "uri"],
            checksum=proposals[proposal_id, "checksum"],
            description=proposals[proposal_id, "description"],
        )
    elif action == "revoke":
        registry.apply_revoke(
            record_id=record_id,
            reason=proposals[proposal_id, "reason"],
        )
    else:
        assert False, "Unsupported proposal action."

    proposals[proposal_id, "executed"] = True
    proposals[proposal_id, "executed_at"] = str(now)
    ProposalExecutedEvent(
        {
            "proposal_id": proposal_id,
            "action": action,
            "record_id": record_id,
            "executor": ctx.caller,
        }
    )


@export
def is_signer(account: str):
    return signers[account]


@export
def get_proposal(proposal_id: int):
    return {
        "proposal_id": proposal_id,
        "action": proposals[proposal_id, "action"],
        "record_id": proposals[proposal_id, "record_id"],
        "owner": proposals[proposal_id, "owner"],
        "uri": proposals[proposal_id, "uri"],
        "checksum": proposals[proposal_id, "checksum"],
        "description": proposals[proposal_id, "description"],
        "reason": proposals[proposal_id, "reason"],
        "proposer": proposals[proposal_id, "proposer"],
        "approved_count": proposal_vote_count[proposal_id],
        "threshold": metadata["threshold"],
        "executed": proposals[proposal_id, "executed"],
        "created_at": proposals[proposal_id, "created_at"],
        "executed_at": proposals[proposal_id, "executed_at"],
    }
