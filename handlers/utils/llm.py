import asyncio
from datetime import timedelta
from typing import List, Tuple, Union
from urllib import response

import orjson as json
from aiogram import types
from loguru import logger

from ..utils import chat_completions

SPAM_MODELS = ["gemini-flash-lite", "gemma3"]


async def check_spams_with_llm(
    members: List[
        Union[
            types.ChatMemberOwner,
            types.ChatMemberAdministrator,
            types.ChatMemberMember,
            types.ChatMemberRestricted,
            types.ChatMemberLeft,
            types.ChatMemberBanned,
            types.User,
        ]
    ],
    session=None,
    additional_strings=None,
    now=None,
) -> List[Tuple[int, str]]:
    try:
        members_data = []
        for member in members:
            if hasattr(member, "user"):
                user = member.user
            else:
                user = member

            member_data = {
                "id": user.id,
                "username": getattr(user, "username", None),
                "first_name": getattr(user, "first_name", None),
                "last_name": getattr(user, "last_name", None),
                "fullname": user.full_name,
            }

            if session and hasattr(session, "member_bio") and session.member_bio:
                member_data["bio"] = session.member_bio

            members_data.append(member_data)

        members_str = "\n".join([f"{i + 1}. {json.dumps(member)}" for i, member in enumerate(members_data)])

        system_prompt = "分辨出那些用户是SPAM，这些用户资料来自 Telegram，判断依据：\n"
        system_prompt += "1. username可能为null，为空也不减分\n"
        system_prompt += "2. 检查bio是否包含广告或推广内容\n"
        system_prompt += "3. 检查用户名是否看起来像随机生成的\n"
        system_prompt += "4. 检查用户资料是否有可疑模式\n\n"
        system_prompt += "\n 输出格式："

        if additional_strings and len(additional_strings) > 0:
            system_prompt += f"附加信息：\n{json.dumps(additional_strings)}\n\n"

        system_prompt += '仅输出JSON结构,不要输出其他任何资料，每个用户资料内添加一个 "reason" 字段说明判断理由\n\n'
        system_prompt += '{ "spams": [] }'

        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": members_str}]

        result = None
        for model in SPAM_MODELS:
            try:
                result = await asyncio.wait_for(
                    chat_completions(
                        messages,
                        model,
                        max_tokens=1024,
                        temperature=0.5,
                        response_format={"type": "json_object"},
                    ),
                    timeout=7,
                )
            except ValueError as e:
                logger.error(f"check_spams_with_llm error: {e}")
                continue

            except Exception as e:
                logger.exception(f"check_spams_with_llm error: {e}")
                continue

            if not result:
                continue

            result = result.strip().replace("```json", "").replace("```", "")

            if result:
                break

        if not result:
            return []

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
