"""manager.send_photo 行为测试：bytes 必须以图片（而非 document）形式发送。"""

import io
from unittest.mock import AsyncMock, MagicMock

from manager.manager import Manager


def _make_manager():
    mgr = object.__new__(Manager)  # 绕过 __init__，仅注入 client
    resp = MagicMock()
    resp.id = 42
    mgr.client = MagicMock()
    mgr.client.send_file = AsyncMock(return_value=resp)
    return mgr


async def test_send_photo_png_bytes_send_as_photo():
    mgr = _make_manager()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

    msg_id = await mgr.send_photo(123, png, caption="c")

    assert msg_id == 42
    args, _ = mgr.client.send_file.call_args
    file_arg = args[1]
    assert isinstance(file_arg, io.BytesIO)
    # Telethon 依据文件后缀判断图片类型，png 字节必须带 .png 名字
    assert file_arg.name == "image.png"


async def test_send_photo_jpeg_bytes_send_as_photo():
    mgr = _make_manager()
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 16

    msg_id = await mgr.send_photo(123, jpeg)

    assert msg_id == 42
    file_arg = mgr.client.send_file.call_args[0][1]
    assert file_arg.name == "image.jpg"


async def test_send_photo_propagates_flood_wait():
    from telethon.errors import FloodWaitError

    mgr = _make_manager()
    mgr.client.send_file = AsyncMock(side_effect=FloodWaitError(5))

    try:
        await mgr.send_photo(123, b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    except FloodWaitError:
        return
    raise AssertionError("FloodWaitError should propagate")
