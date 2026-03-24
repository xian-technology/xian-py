from __future__ import annotations

try:
    from .projector_worker import main
except ImportError:
    from projector_worker import main  # type: ignore


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
