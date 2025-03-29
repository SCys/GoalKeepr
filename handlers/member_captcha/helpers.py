import random
from datetime import datetime, timedelta
from typing import List,  Tuple, Union

import orjson as json
from aiogram import types

from manager import manager
from ..utils import generate_text

SPAM_MODEL_NAME = "gemma-3-27b-it"

WELCOME_TEXT = (
    "欢迎 [%(title)s](tg://user?id=%(user_id)d) ，点击 *%(icon)s* 按钮后才能发言。\n\n *30秒* 内不操作即会被送走。\n\n"
    "Welcome [%(title)s](tg://user?id=%(user_id)d). \n\n"
    "You would be allowed to send the message after choosing the right option for [*%(icon)s*] through pressing the correct button"
)
DELETED_AFTER = 30

ICONS = {
    "爱心|Love": "❤️️",
    "感叹号|Exclamation mark": "❗",
    "问号|Question mark": "❓",
    "壹|One": "1⃣",
    "贰|Two": "2⃣",
    "叁|Three": "3⃣",
    "肆|Four": "4⃣",
    "伍|Five": "5⃣",
    "陆|Six": "6⃣",
    "柒|Seven": "7⃣",
    "捌|Eight": "8⃣",
    "玖|Nine": "9⃣",
    "乘号|Multiplication number": "✖",
    "加号|Plus": "➕",
    "减号|Minus": "➖",
    "除号|Divisor": "➗",
    "禁止|Prohibition": "🚫",
    "美元|US Dollar": "💲",
    "A": "🅰",
    "B": "🅱",
    "O": "🅾",
    "彩虹旗|Rainbow flag": "🏳‍🌈",
    "眼睛|Eye": "👁",
    "脚印|Footprints": "👣",
    "汽车|Car": "🚗",
    "飞机|Aircraft": "✈️",
    "火箭|Rocket": "🚀",
    "帆船|Sailboat": "⛵️",
    "警察|Police": "👮",
    "信|Letter": "✉",
    "1/2": "½",
    "雪花|Snowflake": "❄",
    "眼镜|Eyeglasses": "👓",
    "手枪|Pistol": "🔫",
    "炸弹|Bomb": "💣",
    "骷髅|Skull": "💀",
    "骰子|Dice": "🎲",
    "音乐|Music": "🎵",
    "电影|Movie": "🎬",
    "电话|Telephone": "☎️",
    "电视|Television": "📺",
    "相机|Camera": "📷",
    "计算机|Computer": "💻",
    "手机|Mobile phone": "📱",
    "钱包|Wallet": "👛",
    "钱|Money": "💰",
    "书|Book": "📖",
    "信封|Envelope": "✉️",
    "礼物|Gift": "🎁",
}


logger = manager.logger


async def build_captcha_message(
    member: Union[types.ChatMember, types.User],
    msg_timestamp: datetime,
) -> Tuple[str, types.InlineKeyboardMarkup]:
    """
    构建新用户验证信息的按钮和文字内容
    """
    if isinstance(member, (types.ChatMemberRestricted, types.ChatMemberMember)):
        member_id = member.user.id
        member_name = member.user.full_name
    elif isinstance(member, types.User):
        member_id = member.id
        member_name = member.full_name
    else:
        raise ValueError(f"Unknown member type {type(member)}")

    # 用户组
    items = random.sample(list(ICONS.items()), k=5)
    button_user_ok, _ = random.choice(items)
    buttons_user = [
        types.InlineKeyboardButton(
            text=i[1], callback_data="__".join([str(member_id), str(msg_timestamp), "!" if button_user_ok == i[0] else "?"])
        )
        for i in items
    ]
    random.shuffle(buttons_user)

    # 管理组
    buttons_admin = [
        types.InlineKeyboardButton(text="✔", callback_data="__".join([str(member_id), str(msg_timestamp), "O"])),
        types.InlineKeyboardButton(text="❌", callback_data="__".join([str(member_id), str(msg_timestamp), "X"])),
    ]

    # 文字
    content = WELCOME_TEXT % {"title": member_name, "user_id": member_id, "icon": button_user_ok}

    return content, types.InlineKeyboardMarkup(inline_keyboard=[buttons_user, buttons_admin])


async def accepted_member(chat: types.Chat, msg: types.Message, user: types.User):
    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    try:
        await chat.restrict(
            user.id,
            permissions=types.ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
    except Exception as e:
        logger.error(f"{prefix} restrict {user.id} error {e}")
        return

    logger.info(f"{prefix} member {user.id}({manager.username(user)}) is accepted")

    title = manager.username(user)
    user_id = user.id
    content = (
        f"欢迎 [{title}](tg://user?id={user_id}) 加入群组，先请阅读群规。\n\n"
        f"Welcome [{title}](tg://user?id={user_id}). \n\n"
        "Please read the rules carefully before sending the message in the group."
    )

    try:
        photos = await user.get_profile_photos(0, 1)
        if photos.total_count == 0:
            content += (
                "\n\n请设置头像或显示头像，能够更好体现个性。\n\n"
                "Please choose your appropriate fancy profile photo and set it available in public. "
                "It would improve your experience in communicate with everyone here and knowing you faster and better."
            )
    except:
        logger.exception("get profile photos error")

    await manager.delete_message(
        chat, await msg.answer(content, parse_mode="markdown"), msg.date + timedelta(seconds=DELETED_AFTER)
    )
    await manager.lazy_session_delete(chat.id, user.id, "new_member_check")


async def check_spams_with_llm(
    members: List[Union[
        types.ChatMemberOwner,
        types.ChatMemberAdministrator,
        types.ChatMemberMember,
        types.ChatMemberRestricted,
        types.ChatMemberLeft,
        types.ChatMemberBanned,
        types.User,
    ]],
    session=None,
    additional_strings=None,
    now=None,
) -> List[Tuple[int, str]]:
    try:
        members_data = []
        for member in members:
            if hasattr(member, 'user'):
                user = member.user
            else:
                user = member
                
            member_data = {
                "id": user.id,
                "username": getattr(user, 'username', None),
                "first_name": getattr(user, 'first_name', None),
                "last_name": getattr(user, 'last_name', None),
                "fullname": user.full_name,
            }
            
            if session and hasattr(session, 'member_bio') and session.member_bio:
                member_data["bio"] = session.member_bio
                
            members_data.append(member_data)
            
        members_str = "\n".join([f"{i + 1}. {json.dumps(member)}" for i, member in enumerate(members_data)])

        prompt = "分辨出那些用户是SPAM，这些用户资料来自 Telegram，判断依据：\n"
        prompt += "1. username可能为null，不过fullname肯定有\n"
        prompt += "2. 检查bio是否包含广告或推广内容\n"
        prompt += "3. 检查用户名是否看起来像随机生成的\n"
        prompt += "4. 检查用户资料是否有可疑模式\n\n"
        prompt += f"用户数据：\n{members_str}\n\n"
        
        if additional_strings and len(additional_strings) > 0:
            prompt += f"附加信息：\n{json.dumps(additional_strings)}\n\n"
            
        prompt += '仅输出JSON结构,不要输出其他任何资料，每个用户资料内添加一个 "reason" 字段说明判断理由\n\n'
        prompt += '{ "spams": [] }\n'

        result = await generate_text(prompt, SPAM_MODEL_NAME)
        if not result:
            return []

        result = result.strip().replace("```json", "").replace("```", "")
        data = json.loads(result)
        if not data:
            return []

        spams = data.get("spams", [])
        if not spams or len(spams) == 0:
            return []

        return [(member["id"], member["reason"]) for member in spams if member.get("id") and member.get("reason")]
    except Exception as e:
        logger.error(f"check_spams_with_llm error: {e}")
        return []
