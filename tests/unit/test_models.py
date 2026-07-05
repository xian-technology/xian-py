from decimal import Decimal

from xian_py.models import DexCandle, IndexedEvent, IndexedTransaction, StateEntry


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


def test_indexed_event_from_dict_ignores_non_mapping_json_payload_fields() -> None:
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
    tx = IndexedTransaction.from_dict({"tx_hash": "abc", "created_at": "2026-03-24T00:00:00Z"})
    event = IndexedEvent.from_dict(
        {"id": 1, "event": "Issue", "created_at": "2026-03-24T00:00:01Z"}
    )
    state = StateEntry.from_dict({"key": "a", "value": "b", "created_at": "2026-03-24T00:00:02Z"})

    assert tx.created == "2026-03-24T00:00:00Z"
    assert event.created == "2026-03-24T00:00:01Z"
    assert state.created == "2026-03-24T00:00:02Z"


def test_dex_candle_from_dict_preserves_precise_numeric_strings() -> None:
    candle = DexCandle.from_dict(
        {
            "source": "xian_pairs_v1",
            "market_id": "7",
            "pair_id": "7",
            "bucket_start": "2026-01-01T00:00:00Z",
            "bucket_end": "2026-01-01T00:05:00Z",
            "open": Decimal("1.234567890123456789"),
            "high": "1.5",
            "low": "1.2",
            "close": "1.4",
            "volume_token0": Decimal("12.000000000000000001"),
            "volume_token1": "16.8",
            "trade_count": "3",
            "first_block_height": "100",
            "last_block_height": "101",
            "first_event_id": "40",
            "last_event_id": "42",
        }
    )

    assert candle.source == "xian_pairs_v1"
    assert candle.market_id == "7"
    assert candle.pair_id == 7
    assert candle.open == "1.234567890123456789"
    assert candle.volume_token0 == "12.000000000000000001"
    assert candle.trade_count == 3
    assert candle.last_event_id == 42
