#!/usr/bin/python3

from handlers import *  # noqa
from manager import manager


async def main():
    manager.setup()

    try:
        manager.is_running = True

        await manager.start()
    except KeyboardInterrupt:
        await manager.stop()
    except InterruptedError:
        await manager.stop()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
