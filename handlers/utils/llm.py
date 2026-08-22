import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any, List, Optional
import re

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

# 严格结构化输出规范（JSON Schema），锁定模型只按此结构返回
SPAM_EVAL_JSON_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "spam_evaluations",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "evaluations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer", "description": "Telegram user ID"},
                            "score": {"type": "integer", "description": "Spam score 0-100"},
                            "is_spam": {"type": "boolean", "description": "True if score >= 80, else False"},
                            "reason": {"type": "string", "description": "Concise reason in Chinese"},
                        },
                        "required": ["id", "score", "is_spam", "reason"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["evaluations"],
            "additionalProperties": False,
        },
    },
}

def _extract_and_parse_json(raw: Any) -> Optional[dict]:
    """强鲁棒性 JSON 提取与解析器：支持纯字符串、数组片段、Markdown代码块等。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        parts = []
        for part in raw:
            if isinstance(part, dict):
                if "text" in part:
                    parts.append(str(part["text"]))
                elif "content" in part:
                    parts.append(str(part["content"]))
            elif isinstance(part, str):
                parts.append(part)
        raw = "".join(parts)
    elif not isinstance(raw, str):
        raw = str(raw)

    raw = raw.strip()
    if not raw:
        return None

    # 1. 优先直接解析
    try:
        return json.loads(raw)
    except Exception:
        pass

    # 2. 剥离 Markdown 代码块（如 ```json ... ```）
    if "```" in raw:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
        if m:
            clean_code = m.group(1).strip()
            try:
                return json.loads(clean_code)
            except Exception:
                pass

    # 3. 提取最外层大括号 { ... }
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except Exception:
            pass

    return None

async def check_spams_with_llm(
    members: List[Any],
    session=None,
    additional_strings=None,
    now=None,
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

            members_data.append(member_data)

        members_str = "\n".join([f"{i + 1}. {json.dumps(member)}" for i, member in enumerate(members_data)])

        system_prompt = (
            "你是一个专业的 Telegram 群组安全与垃圾信息（SPAM）识别专家。\n"
            "任务：分析给出的 Telegram 用户资料（用户名、昵称、Bio 简介），准确评估每个用户的垃圾/风险评分（0~100 分），识别恶意广告、黑灰产、违规引流号，并严防误杀普通正常用户。\n\n"
            "【评分标准 (0~100 分)】：\n"
            "1. 0 ~ 30 分（正常普通用户）：普通英文/中文昵称（例如包含 Deep, OP, Man, Bot, AI, Pro 等常见字母或词汇），只要没有实际违规引流内容，一律打低分（0~30分，is_spam=false）。\n"
            "2. username 允许为 null，没有 username 绝对不是扣分项。\n"
            "3. 80 ~ 100 分（高危 SPAM，is_spam=true）：只有存在确凿恶意证据时才打高分，如：\n"
            "   - Bio 或昵称包含明确的引流广告（如微信号/QQ号/联系方式/Telegram群链接/外链等）；\n"
            "   - 包含博彩/赌博/色情/代开发票/办证/信用卡套现/兼职刷单/暴富等黑产特征词或话术；\n"
            "   - 明显的批量营销黑产机器人账号。\n\n"
            "【输出格式要求】：\n"
            "必须输出标准的 JSON 对象，包含 evaluations 数组，严禁输出任何额外说明文本。"
        )

        if additional_strings and len(additional_strings) > 0:
            system_prompt += f"\n\n附加信息：\n{json.dumps(additional_strings)}\n"

        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": members_str}]

        result = None
        for model in get_spam_models():
            model_started = monotonic()
            # 优先尝试 strict json_schema，若代理不支持则回退 json_object
            for fmt in (SPAM_EVAL_JSON_SCHEMA, {"type": "json_object"}):
                try:
                    result = await asyncio.wait_for(
                        chat_completions(
                            messages,
                            model,
                            max_tokens=LLM_MAX_TOKENS,
                            temperature=0.0,
                            response_format=fmt,
                        ),
                        timeout=LLM_MODEL_TIMEOUT,
                    )
                    if result:
                        break
                except asyncio.TimeoutError as e:
                    logger.error(
                        f"check_spams_with_llm timeout for model {model} "
                        f"after {monotonic() - model_started:.2f}s: {e}"
                    )
                    break
                except Exception as e:
                    logger.debug(f"check_spams_with_llm format {fmt.get('type')} error on {model}: {e}")
                    continue

            if result:
                logger.info(
                    f"check_spams_with_llm model {model} returned "
                    f"in {monotonic() - model_started:.2f}s"
                )
                break

        if not result:
            return []

        data = _extract_and_parse_json(result)
        if not data:
            logger.error(f"Failed to parse LLM response as JSON: {str(result)[:300]}")
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
