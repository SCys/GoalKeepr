import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any, List, Optional

import orjson as json
from loguru import logger

from ..utils import chat_completions, get_spam_models
from ..member_captcha.config import LLM_MAX_TOKENS, LLM_MODEL_TIMEOUT

@dataclass
class LLMUserEvaluation:
    id: int
    score: int
    is_spam: bool
    reason: str

def _user_fullname(user: Any) -> str:
    first = getattr(user, "first_name", None) or ""
    last = getattr(user, "last_name", None) or ""
    return f"{first} {last}".strip() or ""

async def check_spams_with_llm(
    members: List[Any],
    session=None,
    additional_strings=None,
    now=None,
    message: Optional[str] = None,
) -> List[LLMUserEvaluation]:
    """members 为具 .user 的对象或 User，兼容 Telethon。返回每个用户的评估结果列表。"""
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

            if message:
                member_data["first_message"] = message

            members_data.append(member_data)

        members_str = "\n".join([f"{i + 1}. {json.dumps(member)}" for i, member in enumerate(members_data)])

        system_prompt = (
            "你是一个专业的 Telegram 群组安全与垃圾信息（SPAM）识别专家。\n"
            "任务：分析给出的 Telegram 用户资料（用户名、昵称、Bio 简介）以及用户的发言内容 (first_message)，准确评估每个用户的垃圾/风险评分（0~100 分），识别恶意广告、黑灰产、违规引流号，并严防误杀普通正常用户。\n\n"
            "【评分标准 (0~100 分)】：\n"
            "1. 0 ~ 30 分（正常普通用户）：普通的日常打招呼、交流、技术探讨，无广告引流内容，打低分（0~30分，is_spam=false）。\n"
            "2. username 允许为 null，没有 username 绝对不是扣分项。\n"
            "3. 80 ~ 100 分（高危 SPAM，is_spam=true）：只要个人资料或发言内容 (first_message) 中存在以下确凿恶意证据，一律打高分（≥80，is_spam=true）：\n"
            "   - 招人、招募兼职、刷单、推广、代购、私聊领福利、外链、微信号/QQ/TG群等引流；\n"
            "   - 博彩/赌博/色情/代办/信用卡套现/黑产营销话术；\n"
            "   - 明显的批量黑产营销机器人特征。\n\n"
            "【输出格式】：\n"
            "请为输入的每一个用户输出评估结果，严格输出 JSON 结构：\n"
            "{\n"
            '  "evaluations": [\n'
            "    {\n"
            '      "id": <用户ID>,\n'
            '      "score": <0~100分整数>,\n'
            '      "is_spam": <true或false，score>=80为true>,\n'
            '      "reason": "<简明中文说明判定的具体依据或特征>"\n'
            "    }\n"
            "  ]\n"
            "}"
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

        eval_list: List[LLMUserEvaluation] = []
        if isinstance(data, dict):
            if "evaluations" in data and isinstance(data["evaluations"], list):
                for item in data["evaluations"]:
                    if isinstance(item, dict) and item.get("id"):
                        score = item.get("score", 0)
                        try:
                            score = int(score)
                        except (ValueError, TypeError):
                            score = 0
                        is_spam = item.get("is_spam", score >= 80)
                        reason = item.get("reason", "正常用户")
                        eval_list.append(
                            LLMUserEvaluation(
                                id=item["id"],
                                score=score,
                                is_spam=bool(is_spam),
                                reason=str(reason),
                            )
                        )
            elif "spams" in data and isinstance(data["spams"], list):
                # 兼容旧格式 spams
                spam_map = {}
                for s in data["spams"]:
                    if isinstance(s, dict) and s.get("id"):
                        score = s.get("score", 85)
                        reason = s.get("reason", "疑似SPAM")
                        spam_map[s["id"]] = (score, reason)
                for member in members_data:
                    m_id = member["id"]
                    if m_id in spam_map:
                        sc, reas = spam_map[m_id]
                        eval_list.append(
                            LLMUserEvaluation(
                                id=m_id,
                                score=sc,
                                is_spam=True,
                                reason=reas,
                            )
                        )
                    else:
                        eval_list.append(
                            LLMUserEvaluation(
                                id=m_id,
                                score=10,
                                is_spam=False,
                                reason="正常用户",
                            )
                        )

        return eval_list
    except Exception as e:
        logger.exception(f"check_spams_with_llm error: {e}")
        return []
