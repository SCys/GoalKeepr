#!/usr/bin/python3

from handlers import *
from manager import manager


def main():
    manager.load_config()

    manager.setup()

    manager.load_handlers()

    try:
        manager.is_running = True

        manager.start()
    except KeyboardInterrupt:
        manager.stop()


if __name__ == "__main__":
    main()
