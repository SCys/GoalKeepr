import argparse
import logging
import os.path
import sys
from configparser import ConfigParser
from typing import Optional

from aiogram import Bot, Dispatcher, types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("goalkeepr")


class Manager:
    config = ConfigParser()
    bot: Optional[Bot] = None
    dp: Optional[Dispatcher] = None

    def load_config(self):
        config = self.config

        for key, section in {"default": {"debug": False}, "telegram": {"token": ""}}.items():
            config.setdefault(key, section)

        # load file
        if os.path.isfile("main.ini"):
            try:
                with open("main.ini", "r") as fobj:
                    config.read_file(fobj)
            except IOError:
                pass

        # load cmd arguments
        parser = argparse.ArgumentParser(description="goalkeepr arguments:")
        parser.add_argument("--token", dest="token", help="telegram bot token", type=str)
        args = parser.parse_args()
        if args.token:
            config["telegram"]["token"] = args.token

        args = argparse.ArgumentParser()

        if config["default"]["debug"]:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.INFO)

    def setup(self):
        token = manager.config["telegram"]["token"]
        if not token:
            logger.error("[Manager]telegram token is missing")
            sys.exit(1)

        self.bot = Bot(token=token)
        self.dp = Dispatcher(self.bot)
        logger.info("[Manager]bot is setup")

    async def is_admin(self, chat: types.Chat, member: types.User):
        admins = await self.bot.get_chat_administrators(chat.id)
        return len([i for i in admins if i.is_chat_admin() and i.user.id == member.id]) > 0


manager = Manager()
