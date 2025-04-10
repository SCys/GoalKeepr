from typing import List, Tuple, Union
from urllib import response

from aiogram import types
from loguru import logger
import orjson as json

from ..utils import chat_completions

# SPAM_MODEL_NAME = "gemini-2.0-flash-lite-001"
SPAM_MODEL_NAME = "grok-3-mini-fast"

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
        prompt += "1. username可能为null，为空也不减分\n"
        prompt += "2. 检查bio是否包含广告或推广内容\n"
        prompt += "3. 检查用户名是否看起来像随机生成的\n"
        prompt += "4. 检查用户资料是否有可疑模式\n\n"
        prompt += f"用户数据：\n{members_str}\n\n"
        
        if additional_strings and len(additional_strings) > 0:
            prompt += f"附加信息：\n{json.dumps(additional_strings)}\n\n"
            
        prompt += '仅输出JSON结构,不要输出其他任何资料，每个用户资料内添加一个 "reason" 字段说明判断理由\n\n'
        prompt += '{ "spams": [] }'

        result = await chat_completions(prompt, SPAM_MODEL_NAME,   max_tokens=1024, temperature=0.5, response_format={
            "type": "json_object",
        })
        if not result:
            return []
        
        
        result = result.strip().replace("```json", "").replace("```", "")
        try:
            data = json.loads(result)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {result[:200]}... Error: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error parsing LLM response: {e}")
            return []

        if not data:
            logger.warning("Empty data received from LLM response")
            return []

        spams = data.get("spams", [])
        if not spams or len(spams) == 0:
            return []

        return [(member["id"], member["reason"]) for member in spams if member.get("id") and member.get("reason")]
    except Exception as e:
        logger.exception(f"check_spams_with_llm error: {e}")
        return []
