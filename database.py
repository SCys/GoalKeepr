import aiosqlite


def connection():
    return aiosqlite.connect("./data/main.db")
