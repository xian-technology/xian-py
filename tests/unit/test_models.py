from xian_py.models import IndexedEvent, IndexedTransaction, StateEntry


def test_indexed_event_from_dict_decodes_json_payload_fields() -> None:
    event = IndexedEvent.from_dict(
        {
            "id": 7,
            "event": "Issue",
            "data": '{"amount": "12.5"}',
            "data_indexed": '{"to": "alice"}',
        }
    )

    assert event.data == {"amount": "12.5"}
    assert event.data_indexed == {"to": "alice"}


def test_indexed_event_from_dict_ignores_non_mapping_json_payload_fields() -> (
    None
):
    event = IndexedEvent.from_dict(
        {
            "id": 8,
            "event": "Issue",
            "data": '["unexpected"]',
            "data_indexed": '"alice"',
        }
    )

    assert event.data is None
    assert event.data_indexed is None


def test_indexed_models_fall_back_to_created_at() -> None:
    tx = IndexedTransaction.from_dict(
        {"tx_hash": "abc", "created_at": "2026-03-24T00:00:00Z"}
    )
    event = IndexedEvent.from_dict(
        {"id": 1, "event": "Issue", "created_at": "2026-03-24T00:00:01Z"}
    )
    state = StateEntry.from_dict(
        {"key": "a", "value": "b", "created_at": "2026-03-24T00:00:02Z"}
    )

    assert tx.created == "2026-03-24T00:00:00Z"
    assert event.created == "2026-03-24T00:00:01Z"
    assert state.created == "2026-03-24T00:00:02Z"
