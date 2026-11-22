from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xian_py.models import DexCandle, DexCandlePage

MARKET_HISTORY_QUERY = """
query DexMarketHistory(
  $tokenA: String!, $tokenB: String!, $first: Int!, $after: Cursor,
  $start: Datetime, $end: Datetime, $interval: Int!, $size: Int!, $before: Datetime
) {
  dexMarket(tokenA: $tokenA, tokenB: $tokenB) {
    pair_id: pairId
    token0
    token1
    indexed_height: indexedHeight
    trades(first: $first, after: $after, startTime: $start, endTime: $end) {
      pageInfo { hasNextPage endCursor }
      nodes {
        event_id: eventId
        tx_hash: txHash
        block_height: blockHeight
        block_time: blockTime
        event_index: eventIndex
        tx_index: txIndex
        amount0_in: amount0In
        amount1_in: amount1In
        amount0_out: amount0Out
        amount1_out: amount1Out
        signer
        recipient
      }
    }
    candles(intervalSeconds: $interval, pageSize: $size, before: $before) {
      indexed_height: indexedHeight
      next_before: nextBefore
      items {
        bucket_start: bucketStart
        bucket_end: bucketEnd
        open high low close
        volume_token0: volumeToken0
        volume_token1: volumeToken1
        trade_count: tradeCount
        first_block_height: firstBlockHeight
        last_block_height: lastBlockHeight
        first_event_id: firstEventId
        last_event_id: lastEventId
      }
    }
  }
}
"""


@dataclass(frozen=True)
class DexPoolFill:
    event_id: int
    tx_hash: str
    block_height: int
    block_time: str
    event_index: int
    tx_index: int
    amount0_in: str
    amount1_in: str
    amount0_out: str
    amount1_out: str
    signer: str
    recipient: Any

    @classmethod
    def from_graphql(cls, item: dict[str, Any]) -> DexPoolFill:
        return cls(
            **{**item, "event_id": int(item["event_id"]), "block_height": int(item["block_height"])}
        )


@dataclass(frozen=True)
class DexMarketHistory:
    pair_id: str
    token0: str
    token1: str
    indexed_height: int
    trades: list[DexPoolFill]
    next_after: str | None
    candles: DexCandlePage

    @classmethod
    def from_graphql(cls, market: dict[str, Any]) -> DexMarketHistory:
        trades = market["trades"]
        page_info = trades["pageInfo"]
        page = market["candles"]
        pair_id = market["pair_id"]
        return cls(
            pair_id=pair_id,
            token0=market["token0"],
            token1=market["token1"],
            indexed_height=int(market["indexed_height"]),
            trades=[DexPoolFill.from_graphql(item) for item in trades["nodes"]],
            next_after=page_info["endCursor"] if page_info["hasNextPage"] else None,
            candles=DexCandlePage(
                items=[
                    DexCandle.from_dict(
                        {
                            **item,
                            "pair_id": pair_id,
                            "market_id": pair_id,
                            "source": "xian_pairs_v1",
                        }
                    )
                    for item in page["items"]
                ],
                indexed_height=int(page["indexed_height"]),
                next_before=page["next_before"],
            ),
        )
