#!/usr/bin/python3

from handlers import *
from manager import manager

from handlers.commands.translate import translate_setup


def main():
    manager.load_config()

    manager.setup()

    manager.load_handlers()

    translate_setup()

    try:
        manager.is_running = True

        manager.start()
    except KeyboardInterrupt:
        manager.stop()
    except InterruptedError:
        manager.stop()


if __name__ == "__main__":
    main()
