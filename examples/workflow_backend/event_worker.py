from __future__ import annotations

try:
    from .processor_worker import main
except ImportError:
    from processor_worker import main  # type: ignore


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
