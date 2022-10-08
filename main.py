#!/usr/bin/python3

from handlers import *  # noqa
from manager import manager
import asyncio


async def main():
    manager.load_config()
    await manager.setup()
    manager.load_handlers()

    try:
        manager.is_running = True

        manager.start()
    except KeyboardInterrupt:
        manager.stop()
    except InterruptedError:
        manager.stop()


if __name__ == "__main__":
    asyncio.run(main())
