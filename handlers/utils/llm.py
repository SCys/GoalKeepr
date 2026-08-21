import asyncio
from time import monotonic
from typing import Any, List, Tuple

import orjson as json
from loguru import logger

from ..utils import chat_completions, get_spam_models
from ..member_captcha.config import LLM_MAX_TOKENS, LLM_MODEL_TIMEOUT


def _user_fullname(user: Any) -> str:
    first = getattr(user, "first_name", None) or ""
    last = getattr(user, "last_name", None) or ""
    return f"{first} {last}".strip() or ""


async def check_spams_with_llm(
    members: List[Any],
    session=None,
    additional_strings=None,
    now=None,
) -> List[Tuple[int, str]]:
    """members 为具 .user 的对象或 User，兼容 Telethon。"""
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
                "fullname": _user_fullname(user),
            }

            if session and hasattr(session, "member_bio") and session.member_bio:
                member_data["bio"] = session.member_bio

            members_data.append(member_data)

        members_str = "\n".join([f"{i + 1}. {json.dumps(member)}" for i, member in enumerate(members_data)])

        system_prompt = (
            "你是一个专业的 Telegram 群组安全与垃圾信息（SPAM）识别专家。\n"
            "任务：分析给出的 Telegram 用户资料（用户名、昵称、Bio 简介），准确识别出恶意广告、黑灰产、违规引流号，并严防误杀普通正常用户。\n\n"
            "【判定依据与评分标准 (0~100 分)】：\n"
            "1. 严禁误杀：普通英文/中文昵称（例如包含 Deep, OP, Man, Bot, AI, Pro 等常见字母或词汇），只要没有实际违规引流内容，一律视为正常用户（score < 50，不要加入 spams）。\n"
            "2. username 允许为 null，没有 username 绝对不是扣分项。\n"
            "3. 只有存在以下确凿恶意特征时，才判定为 SPAM（打分 score ≥ 80）：\n"
            "   - Bio 或昵称包含明确的引流广告（如微信号/QQ号/联系方式/Telegram群链接/外链等）；\n"
            "   - 包含博彩/赌博/色情/代开发票/办证/信用卡套现/兼职刷单/暴富等黑产特征词或话术；\n"
            "   - 明显的批量营销机器人账号。\n\n"
            "【输出格式】：\n"
            "仅输出 JSON 格式，不要包含任何多余文字：\n"
            "{\n"
            '  "spams": [\n'
            "    {\n"
            '      "id": <用户ID>,\n'
            '      "score": <80~100的分数>,\n'
            '      "reason": "<简明中文说明判定的具体违规理由>"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "如果所有用户均为正常用户，则输出：{\"spams\": []}"
        )

        if additional_strings and len(additional_strings) > 0:
            system_prompt += f"\n\n附加信息：\n{json.dumps(additional_strings)}\n"

        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": members_str}]

        result = None
        for model in get_spam_models():
            model_started = monotonic()
            try:
                result = await asyncio.wait_for(
                    chat_completions(
                        messages,
                        model,
                        max_tokens=LLM_MAX_TOKENS,
                        temperature=0.1,
                        response_format={"type": "json_object"},
                    ),
                    timeout=LLM_MODEL_TIMEOUT,
                )
            except asyncio.TimeoutError as e:
                logger.error(
                    f"check_spams_with_llm timeout for model {model} "
                    f"after {monotonic() - model_started:.2f}s: {e}"
                )
                continue

            except ValueError as e:
                logger.error(f"check_spams_with_llm error: {e}")
                continue

            except Exception as e:
                logger.exception(f"check_spams_with_llm error: {e}")
                continue

            if not result:
                continue

            logger.info(
                f"check_spams_with_llm model {model} returned "
                f"in {monotonic() - model_started:.2f}s"
            )

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

        valid_spams = []
        for member in spams:
            if not isinstance(member, dict):
                continue
            m_id = member.get("id")
            reason = member.get("reason")
            score = member.get("score", 80)
            if m_id and reason and isinstance(score, (int, float)) and score >= 80:
                valid_spams.append((m_id, f"[{score}分] {reason}"))
        return valid_spams
    except Exception as e:
        logger.exception(f"check_spams_with_llm error: {e}")
        return []
