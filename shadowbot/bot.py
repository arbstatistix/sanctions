import asyncio
import json
import logging
import platform
import re
import sys
import time
import unicodedata
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import telegram.error
from openai import (
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    BadRequestError,
    RateLimitError,
)
from telegram import Message, Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from config import settings
from response_policies import ResponsePolicy, choose_response_policy


# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────

today_str = datetime.today().strftime("%Y-%m-%d")
log_dir = Path("logs") / today_str
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / f"{settings.bot_username}.log"

log_handlers = [
    logging.StreamHandler(sys.stdout),
    RotatingFileHandler(
        log_file,
        maxBytes=getattr(settings, "max_log_file_bytes", 10 * 1024 * 1024),
        backupCount=getattr(settings, "log_backup_count", 3),
        encoding="utf-8",
    ),
]

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=getattr(logging, str(settings.log_level).upper(), logging.INFO),
    handlers=log_handlers,
)
logger = logging.getLogger(settings.bot_username)
logger.warning("intense error logging warning")
logger.error("intense error logging warning")


# ──────────────────────────────────────────────────────────────────────────────
# OpenAI client
# ──────────────────────────────────────────────────────────────────────────────

client = AsyncOpenAI(
    api_key=settings.moonshot_api_key,
    base_url=settings.moonshot_base_url,
)


# ──────────────────────────────────────────────────────────────────────────────
# Constants / limits
# ──────────────────────────────────────────────────────────────────────────────

MAX_SESSION_MESSAGES = 12  # 6 user/assistant turns
MAX_SESSIONS = getattr(settings, "max_sessions", 1024)
MAX_ACTIVE_SESSION_MAPPINGS = getattr(settings, "max_active_session_mappings", 4096)
MAX_BOT_MESSAGE_BINDINGS = getattr(settings, "max_bound_bot_messages", 8192)
SESSION_TTL_SECONDS = getattr(settings, "session_ttl_seconds", 6 * 60 * 60)
MAX_CONCURRENT_REQUESTS = getattr(settings, "max_concurrent_requests", 8)
MAX_TOOL_ROUNDS = max(0, int(getattr(settings, "max_tool_rounds", 1)))


def _build_aliases() -> tuple[str, ...]:
    aliases: set[str] = {
        str(settings.bot_username).strip().lower().lstrip("/"),
        "zentrixbot",
    }
    for alias in getattr(settings, "command_aliases", []) or []:
        alias_str = str(alias).strip().lower().lstrip("/")
        if alias_str:
            aliases.add(alias_str)
    return tuple(sorted(aliases))


BOT_COMMAND_ALIASES = _build_aliases()
COMMAND_RE = re.compile(
    rf"^/(?P<command>{'|'.join(re.escape(a) for a in BOT_COMMAND_ALIASES)})"
    rf"(?:@\w+)?(?:\s+(?P<payload>.*))?$",
    re.IGNORECASE | re.DOTALL,
)


# ──────────────────────────────────────────────────────────────────────────────
# In-memory state
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class SessionState:
    history: deque[dict[str, str]] = field(
        default_factory=lambda: deque(maxlen=MAX_SESSION_MESSAGES)
    )
    last_access: float = field(default_factory=time.monotonic)


_sessions: OrderedDict[str, SessionState] = OrderedDict()
_active_session_by_user: OrderedDict[tuple[int, int], str] = OrderedDict()
_bot_message_to_session: OrderedDict[tuple[int, int], str] = OrderedDict()
_docs_cache: dict[str, dict[str, Any]] = {}

_state_lock = asyncio.Lock()
_folder_cache_lock = asyncio.Lock()
_request_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)


# ──────────────────────────────────────────────────────────────────────────────
# Session / cache utilities
# ──────────────────────────────────────────────────────────────────────────────

def _make_session_id(chat_id: int, user_id: int) -> str:
    return f"{chat_id}:{user_id}:{time.time_ns()}"


def _trim_ordered_dict(od: OrderedDict, max_size: int) -> None:
    while len(od) > max_size:
        od.popitem(last=False)


def _purge_expired_sessions_locked() -> None:
    now = time.monotonic()
    expired_session_ids = [
        session_id
        for session_id, state in _sessions.items()
        if now - state.last_access > SESSION_TTL_SECONDS
    ]
    if not expired_session_ids:
        return

    expired_set = set(expired_session_ids)
    for session_id in expired_session_ids:
        _sessions.pop(session_id, None)

    for key, session_id in list(_active_session_by_user.items()):
        if session_id in expired_set:
            _active_session_by_user.pop(key, None)

    for key, session_id in list(_bot_message_to_session.items()):
        if session_id in expired_set:
            _bot_message_to_session.pop(key, None)


def _start_new_session_locked(chat_id: int, user_id: int) -> str:
    _purge_expired_sessions_locked()

    session_id = _make_session_id(chat_id, user_id)
    _sessions[session_id] = SessionState()
    _active_session_by_user[(chat_id, user_id)] = session_id

    _sessions.move_to_end(session_id)
    _active_session_by_user.move_to_end((chat_id, user_id))

    _trim_ordered_dict(_sessions, MAX_SESSIONS)
    _trim_ordered_dict(_active_session_by_user, MAX_ACTIVE_SESSION_MAPPINGS)

    return session_id


async def start_new_session(chat_id: int, user_id: int) -> str:
    async with _state_lock:
        return _start_new_session_locked(chat_id, user_id)


async def get_or_create_session(chat_id: int, user_id: int) -> str:
    async with _state_lock:
        _purge_expired_sessions_locked()

        key = (chat_id, user_id)
        session_id = _active_session_by_user.get(key)

        if session_id is None or session_id not in _sessions:
            return _start_new_session_locked(chat_id, user_id)

        state = _sessions[session_id]
        state.last_access = time.monotonic()
        _sessions.move_to_end(session_id)
        _active_session_by_user.move_to_end(key)
        return session_id


async def get_session_history(session_id: str) -> list[dict[str, str]]:
    async with _state_lock:
        state = _sessions.get(session_id)
        if state is None:
            return []

        state.last_access = time.monotonic()
        _sessions.move_to_end(session_id)
        return list(state.history)


async def append_session_turn(session_id: str, user_query: str, answer: str) -> None:
    async with _state_lock:
        state = _sessions.get(session_id)
        if state is None:
            return

        state.history.append({"role": "user", "content": user_query})
        state.history.append({"role": "assistant", "content": answer})
        state.last_access = time.monotonic()
        _sessions.move_to_end(session_id)


async def bind_bot_messages_to_session(
    chat_id: int,
    session_id: str,
    sent_messages: list[Message],
) -> None:
    if not sent_messages:
        return

    async with _state_lock:
        for sent in sent_messages:
            _bot_message_to_session[(chat_id, sent.message_id)] = session_id
            _bot_message_to_session.move_to_end((chat_id, sent.message_id))
        _trim_ordered_dict(_bot_message_to_session, MAX_BOT_MESSAGE_BINDINGS)


async def get_bound_session_for_message(chat_id: int, message_id: int) -> str | None:
    async with _state_lock:
        session_id = _bot_message_to_session.get((chat_id, message_id))
        if session_id is not None:
            _bot_message_to_session.move_to_end((chat_id, message_id))
        return session_id


# ──────────────────────────────────────────────────────────────────────────────
# Text sanitization / chunking
# ──────────────────────────────────────────────────────────────────────────────

def strip_markdown_emphasis(text: str) -> str:
    text = re.sub(r"\*\*\s*(.*?)\s*\*\*", r"\1", text)
    text = re.sub(r"__\s*(.*?)\s*__", r"\1", text)
    text = re.sub(r"`\s*([^`]*?)\s*`", r"\1", text)
    text = re.sub(r"(?<!\*)\*\s*([^\n*].*?[^\n*]?)\s*\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_\s*([^\n_].*?[^\n_]?)\s*_(?!_)", r"\1", text)
    return text


def sanitize_for_telegram(text: str) -> str:
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    for ch in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"):
        text = text.replace(ch, "")

    text = "".join(
        ch for ch in text
        if ch in ("\n", "\t") or unicodedata.category(ch)[0] != "C"
    )

    # Preserve heading markers, bullets, and separators because they are part of
    # the output templates the bot is expected to emit.
    text = re.sub(r"```(?:[a-zA-Z0-9_+\-]+)?\n", "", text)
    text = text.replace("```", "")
    text = strip_markdown_emphasis(text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r"\1: \2", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))

    return text.strip()


def split_text(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]

    parts: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for line in text.splitlines(keepends=True):
        line_len = len(line)

        if current_len + line_len <= max_len:
            current_lines.append(line)
            current_len += line_len
            continue

        if current_lines:
            parts.append("".join(current_lines).strip())
            current_lines = []
            current_len = 0

        while len(line) > max_len:
            parts.append(line[:max_len].strip())
            line = line[max_len:]

        if line:
            current_lines.append(line)
            current_len = len(line)

    if current_lines:
        parts.append("".join(current_lines).strip())

    return [part for part in parts if part]


async def safe_reply(message: Message, text: str) -> list[Message]:
    cleaned = sanitize_for_telegram(text) or "(empty response)"
    chunks = split_text(cleaned, settings.max_telegram_message_len)
    sent_messages: list[Message] = []

    for index, chunk in enumerate(chunks, start=1):
        try:
            sent = await message.reply_text(chunk)
            sent_messages.append(sent)
            logger.debug(
                "Sent chunk %d/%d | chat_id=%s | len=%d | message_id=%s",
                index,
                len(chunks),
                message.chat_id,
                len(chunk),
                sent.message_id,
            )
        except telegram.error.TelegramError as exc:
            logger.error(
                "Failed sending chunk %d/%d to chat_id=%s: %s",
                index,
                len(chunks),
                message.chat_id,
                exc,
            )
            if index == 1:
                raise

    return sent_messages


async def typing_indicator(bot, chat_id: int, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except telegram.error.TelegramError as exc:
            logger.warning("Typing indicator failed for chat_id=%s: %s", chat_id, exc)

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=settings.typing_interval_seconds,
            )
        except asyncio.TimeoutError:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# Folder context
# ──────────────────────────────────────────────────────────────────────────────

def should_skip_dir(path: Path) -> bool:
    return any(part in settings.ignored_dirs for part in path.parts)


def read_local_folder(folder_path: str, max_chars: int) -> str:
    folder = Path(folder_path)

    if not folder.exists() or not folder.is_dir():
        logger.warning("Local docs path is invalid: %s", folder_path)
        return "Local folder not found or is not a directory."

    chunks: list[str] = []
    total_chars = 0
    files_scanned = 0
    files_failed = 0

    files = sorted(
        (
            path for path in folder.rglob("*")
            if path.is_file()
            and path.suffix.lower() in settings.allowed_suffixes
            and not should_skip_dir(path)
        ),
        key=lambda path: str(path).lower(),
    )

    per_file_char_budget = int(settings.max_file_snippet_chars)

    for file_path in files:
        rel_path = file_path.relative_to(folder)
        files_scanned += 1

        try:
            with file_path.open("r", encoding="utf-8", errors="replace") as f:
                prefix = f.read(per_file_char_budget + 1)
        except OSError as exc:
            files_failed += 1
            logger.warning("Failed to read file %s: %s", rel_path, exc)
            block = f"\n--- FILE: {rel_path} ---\n[Could not read file: {exc}]\n"
        else:
            prefix = prefix.strip()
            if not prefix:
                continue

            truncated = len(prefix) > per_file_char_budget
            snippet = prefix[:per_file_char_budget]
            if truncated:
                snippet += "\n...[truncated]"

            block = f"\n--- FILE: {rel_path} ---\n{snippet}\n"

        if total_chars + len(block) > max_chars:
            logger.info(
                "Context budget reached after %d files (%d chars)",
                files_scanned,
                total_chars,
            )
            break

        chunks.append(block)
        total_chars += len(block)

    logger.info(
        "Folder scan complete | path=%s | scanned=%d | failed=%d | chars=%d",
        folder_path,
        files_scanned,
        files_failed,
        total_chars,
    )

    if not chunks:
        return "No readable files found in the folder."

    return "".join(chunks).strip()


async def get_cached_folder_context(folder_path: str) -> str:
    now = time.time()
    cache_key = str(Path(folder_path).resolve(strict=False))
    cached = _docs_cache.get(cache_key)

    if cached and now < cached["expires_at"]:
        return cached["value"]

    async with _folder_cache_lock:
        cached = _docs_cache.get(cache_key)
        now = time.time()

        if cached and now < cached["expires_at"]:
            return cached["value"]

        logger.info("Folder context cache miss: %s", cache_key)
        context = await asyncio.to_thread(
            read_local_folder,
            folder_path,
            settings.max_context_chars,
        )

        _docs_cache[cache_key] = {
            "value": context,
            "expires_at": now + settings.doc_cache_ttl_seconds,
        }
        return context


# ──────────────────────────────────────────────────────────────────────────────
# Prompt construction
# ──────────────────────────────────────────────────────────────────────────────

def build_base_system_prompt() -> str:
    return (
        f"You are {settings.bot_name} in a Telegram group. "
        "You are the operating brain for an end-to-end AI marketing app that helps brands plan, create, launch, analyze, and improve marketing. "
        "Act like a combined marketing strategist, growth operator, brand systems lead, and marketing ops architect. "
        "Be concise, rigorous, commercially grounded, and implementation-first. "
        "Do not give fluffy advice. Do not give generic copy unless explicitly asked. "
        "Optimize for business outcomes: revenue, pipeline, CAC efficiency, conversion, retention, velocity, and brand consistency. "
        "Always anchor answers to the operating variables that matter: objective, audience, offer, positioning, funnel stage, channel, creative angle, CTA, budget, constraints, measurement, and decision criteria. "
        "If key context is missing, ask only for the minimum missing variables that would materially change the answer. Otherwise state assumptions explicitly and proceed. "
        "Default to first-principles reasoning. Surface hidden assumptions, bottlenecks, failure modes, edge cases, second-order effects, and tradeoffs. "
        "Prefer systems over one-off tactics: reusable workflows, templates, taxonomies, briefs, checklists, prompts, schemas, dashboards, and automations. "
        "For strategy requests, produce: diagnosis, strategic options, recommendation, execution sequence, risks, and KPIs. "
        "For campaign requests, produce: target segment, insight, positioning, message hierarchy, channel plan, asset list, timeline, experiment plan, and success metrics. "
        "For content requests, stay on-brand, respect style constraints, adapt to channel and funnel stage, and explain the job each asset performs. "
        "For analytics requests, separate facts, assumptions, and hypotheses. Define baselines, instrumentation, attribution caveats, experiment design, and decision thresholds. "
        "For product or workflow requests, think in terms of entities, states, permissions, approvals, handoffs, integrations, and feedback loops. "
        "When recommending tactics, explain why they should work, what signal they improve, what could break, and how to validate quickly. "
        "Use local folder context when relevant and sufficient. "
        "If local context is weak, stale, or insufficient, use web search for current platform facts, channel changes, competitive context, or regulations. "
        "Never hallucinate APIs, integrations, files, sources, benchmarks, customer data, or campaign results. "
        "Do not present guesses as facts. "
        "When a response policy is selected, you must follow that policy exactly. "
        "Return only the answer, with no hidden reasoning, no tool traces, and no web search process details."
    )


def build_llm_messages(
    user_query: str,
    folder_context: str,
    history: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], ResponsePolicy]:
    policy = choose_response_policy(user_query)

    system_content = "\n\n".join([
        build_base_system_prompt(),
        f"Selected response policy: {policy.name}",
        policy.instructions,
    ])

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_content},
    ]

    for example_user, example_assistant in policy.examples:
        messages.append({"role": "user", "content": example_user})
        messages.append({"role": "assistant", "content": example_assistant})

    if history:
        messages.extend(history)

    messages.append({
        "role": "user",
        "content": f"""
User question:
{user_query}

Local folder context:
{folder_context}

Execution rules:
- Use folder context when relevant and sufficient.
- If folder context is weak, stale, or insufficient, use web search.
- Follow the selected response policy exactly.
- Distinguish facts from inference internally, but return only the final answer.
- Do not expose chain-of-thought, reasoning traces, or tool call details.
- Do not mention web search unless directly necessary for the answer.
- For code, give production-grade fixes.
""".strip(),
    })

    return messages, policy


def assistant_message_to_dict(message: Any) -> dict[str, Any]:
    model_extra = getattr(message, "model_extra", {}) or {}

    reasoning_content = (
        getattr(message, "reasoning_content", None)
        or model_extra.get("reasoning_content")
        or " "
    )

    data: dict[str, Any] = {
        "role": "assistant",
        "content": getattr(message, "content", None) or "",
        "reasoning_content": reasoning_content,
    }

    if getattr(message, "tool_calls", None):
        data["tool_calls"] = [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ]

    return data


def search_impl(arguments: dict[str, Any]) -> Any:
    return arguments


# ──────────────────────────────────────────────────────────────────────────────
# LLM calling
# ──────────────────────────────────────────────────────────────────────────────

async def _call_llm_with_retry(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> Any:
    last_exc: Exception | None = None

    for attempt in range(1, settings.max_llm_retries + 1):
        try:
            t0 = time.monotonic()
            completion = await client.chat.completions.create(
                model=settings.model_name,
                messages=messages,
                tools=tools,
                max_tokens=settings.max_tokens,
            )
            elapsed = time.monotonic() - t0

            choice = completion.choices[0]
            usage = completion.usage

            logger.info(
                "LLM response | attempt=%d | model=%s | finish_reason=%s | tool_calls=%d | "
                "duration=%.2fs | prompt_tokens=%s | completion_tokens=%s | total_tokens=%s",
                attempt,
                settings.model_name,
                choice.finish_reason,
                len(choice.message.tool_calls or []),
                elapsed,
                getattr(usage, "prompt_tokens", "?"),
                getattr(usage, "completion_tokens", "?"),
                getattr(usage, "total_tokens", "?"),
            )
            return completion

        except BadRequestError:
            raise

        except RateLimitError as exc:
            last_exc = exc
            wait = min(8.0, float(settings.retry_backoff_base) ** attempt)
            logger.warning(
                "Rate limited | attempt=%d/%d | sleeping=%.2fs | error=%s",
                attempt,
                settings.max_llm_retries,
                wait,
                exc,
            )
            await asyncio.sleep(wait)

        except APITimeoutError as exc:
            last_exc = exc
            wait = min(8.0, float(settings.retry_backoff_base) ** attempt)
            logger.warning(
                "API timeout | attempt=%d/%d | sleeping=%.2fs | error=%s",
                attempt,
                settings.max_llm_retries,
                wait,
                exc,
            )
            await asyncio.sleep(wait)

        except APIError as exc:
            status_code = getattr(exc, "status_code", 0)
            if status_code >= 500:
                last_exc = exc
                wait = min(8.0, float(settings.retry_backoff_base) ** attempt)
                logger.warning(
                    "Server error | status=%s | attempt=%d/%d | sleeping=%.2fs | error=%s",
                    status_code,
                    attempt,
                    settings.max_llm_retries,
                    wait,
                    exc,
                )
                await asyncio.sleep(wait)
            else:
                raise

    logger.error("LLM call failed after %d attempts", settings.max_llm_retries)
    raise last_exc if last_exc is not None else RuntimeError("LLM call failed unexpectedly")


async def ask_llm(
    user_query: str,
    folder_context: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    messages, policy = build_llm_messages(
        user_query=user_query,
        folder_context=folder_context,
        history=history,
    )

    logger.info("Selected response policy: %s", policy.name)

    tools = [
        {
            "type": "builtin_function",
            "function": {"name": "$web_search"},
        }
    ]

    for tool_round in range(MAX_TOOL_ROUNDS + 1):
        completion = await _call_llm_with_retry(messages, tools)
        message = completion.choices[0].message
        tool_calls = list(getattr(message, "tool_calls", None) or [])

        if not tool_calls:
            return (message.content or "").strip()

        if tool_round >= MAX_TOOL_ROUNDS:
            raise RuntimeError("Exceeded maximum allowed tool rounds")

        tool_outputs: list[dict[str, Any]] = []
        for tc in tool_calls:
            raw_args = tc.function.arguments or "{}"
            try:
                args = json.loads(raw_args)
                if not isinstance(args, dict):
                    raise ValueError("Tool arguments must decode to a JSON object")
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning(
                    "Invalid tool arguments | tool=%s | error=%s | raw=%r",
                    tc.function.name,
                    exc,
                    raw_args[:500],
                )
                args = {}

            result = search_impl(args)
            tool_outputs.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.function.name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

        messages.append(assistant_message_to_dict(message))
        messages.extend(tool_outputs)

    raise RuntimeError("LLM tool loop terminated unexpectedly")


# ──────────────────────────────────────────────────────────────────────────────
# Update routing
# ──────────────────────────────────────────────────────────────────────────────

def _is_reply_to_this_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.message is None or update.message.reply_to_message is None:
        return False

    reply_to = update.message.reply_to_message
    if reply_to.from_user is None or not reply_to.from_user.is_bot:
        return False

    replied_username = (reply_to.from_user.username or "").strip().lower()
    bot_id = getattr(context.bot, "id", None)

    return (
        replied_username in BOT_COMMAND_ALIASES
        or (bot_id is not None and reply_to.from_user.id == bot_id)
    )


async def process_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    question: str,
    session_id: str,
) -> None:
    if update.message is None:
        return

    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id if user else 0
    username = user.username if user else "unknown"

    logger.info(
        "Incoming query | user_id=%s | username=%s | chat_id=%s | session_id=%s | query_len=%d | query=%.120s",
        user_id,
        username,
        chat_id,
        session_id,
        len(question),
        question,
    )

    stop_event = asyncio.Event()
    typing_task = asyncio.create_task(typing_indicator(context.bot, chat_id, stop_event))

    t0 = time.monotonic()
    try:
        async with _request_semaphore:
            folder_context_task = asyncio.create_task(
                get_cached_folder_context(settings.local_docs_path)
            )
            history_task = asyncio.create_task(get_session_history(session_id))

            folder_context, history = await asyncio.gather(
                folder_context_task,
                history_task,
            )

            answer = await ask_llm(question, folder_context, history)

            await append_session_turn(session_id, question, answer)

            sent_messages = await safe_reply(update.message, answer)
            await bind_bot_messages_to_session(chat_id, session_id, sent_messages)

        elapsed = time.monotonic() - t0
        logger.info(
            "Request complete | user_id=%s | chat_id=%s | session_id=%s | duration=%.2fs | answer_len=%d",
            user_id,
            chat_id,
            session_id,
            elapsed,
            len(answer),
        )

    except (BadRequestError, APIError) as exc:
        elapsed = time.monotonic() - t0
        logger.error(
            "LLM error | user_id=%s | chat_id=%s | duration=%.2fs | type=%s | error=%s",
            user_id,
            chat_id,
            elapsed,
            type(exc).__name__,
            exc,
        )
        await update.message.reply_text(
            f"AI service error: {type(exc).__name__}. Please try again shortly."
        )

    except telegram.error.TelegramError as exc:
        elapsed = time.monotonic() - t0
        logger.error(
            "Telegram error | user_id=%s | chat_id=%s | duration=%.2fs | type=%s | error=%s",
            user_id,
            chat_id,
            elapsed,
            type(exc).__name__,
            exc,
        )
        try:
            await update.message.reply_text(
                "Failed to send the full response. Please try again."
            )
        except Exception:
            logger.exception("Could not send Telegram error reply to chat_id=%s", chat_id)

    except Exception:
        elapsed = time.monotonic() - t0
        logger.exception(
            "Unexpected error | user_id=%s | chat_id=%s | duration=%.2fs",
            user_id,
            chat_id,
            elapsed,
        )
        try:
            await update.message.reply_text("Unexpected error. Please try again.")
        except Exception:
            logger.exception("Could not send generic error reply to chat_id=%s", chat_id)

    finally:
        stop_event.set()
        await typing_task


async def handle_command_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    raw_text: str,
) -> None:
    if update.message is None:
        return

    match = COMMAND_RE.match(raw_text.strip())
    if not match:
        return

    payload = (match.group("payload") or "").strip()

    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id if user else 0

    if not payload:
        alias_list = ", ".join(f"/{alias}" for alias in BOT_COMMAND_ALIASES)
        await update.message.reply_text(
            "Usage:\n"
            f"{alias_list} new <your question>\n"
            f"{alias_list} <follow-up question>"
        )
        return

    lowered = payload.lower()
    is_new_chat = lowered == "new" or lowered.startswith("new ")

    if is_new_chat:
        session_id = await start_new_session(chat_id, user_id)
        question = payload[3:].strip()

        if not question:
            sent = await update.message.reply_text(
                "Started a new chat. Send your next message or reply to this one."
            )
            await bind_bot_messages_to_session(chat_id, session_id, [sent])
            return
    else:
        session_id = await get_or_create_session(chat_id, user_id)
        question = payload

    await process_query(update, context, question, session_id)


async def handle_reply_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message is None or not update.message.text:
        return

    if not _is_reply_to_this_bot(update, context):
        return

    question = update.message.text.strip()
    if not question:
        return

    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id if user else 0

    reply_to = update.message.reply_to_message
    assert reply_to is not None

    session_id = await get_bound_session_for_message(chat_id, reply_to.message_id)
    if session_id is None:
        session_id = await get_or_create_session(chat_id, user_id)

    await process_query(update, context, question, session_id)


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or not update.message.text:
        return

    raw_text = update.message.text.strip()

    if COMMAND_RE.match(raw_text):
        await handle_command_message(update, context, raw_text)
        return

    if update.message.reply_to_message is not None:
        await handle_reply_message(update, context)
        return


# ──────────────────────────────────────────────────────────────────────────────
# App lifecycle
# ──────────────────────────────────────────────────────────────────────────────

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(
        "Unhandled exception in update %s: %s",
        update,
        context.error,
        exc_info=context.error,
    )


def log_startup_info() -> None:
    logger.info("─── %s Startup ───", settings.bot_name)
    logger.info("Python %s on %s", sys.version.split()[0], platform.system())
    logger.info("Model: %s | Base URL: %s", settings.model_name, settings.moonshot_base_url)
    logger.info("Max tokens: %d | Max context chars: %d", settings.max_tokens, settings.max_context_chars)
    logger.info("Local docs path: %s", settings.local_docs_path)
    logger.info("Telegram max message len: %d", settings.max_telegram_message_len)
    logger.info("Doc cache TTL: %ss | Session TTL: %ss", settings.doc_cache_ttl_seconds, SESSION_TTL_SECONDS)
    logger.info("LLM retries: %d | Max tool rounds: %d", settings.max_llm_retries, MAX_TOOL_ROUNDS)
    logger.info("Concurrency limit: %d", MAX_CONCURRENT_REQUESTS)
    logger.info("Accepted command aliases: %s", ", ".join(f"/{a}" for a in BOT_COMMAND_ALIASES))
    logger.info("─────────────────────────")


async def post_init(app) -> None:
    try:
        me = await app.bot.get_me()
        logger.info("Telegram bot connected as @%s (id=%s)", me.username, me.id)
        if me.username and me.username.lower() not in BOT_COMMAND_ALIASES:
            logger.warning(
                "Actual Telegram username @%s is not in accepted aliases. "
                "Add it to settings.command_aliases if needed.",
                me.username,
            )
    except Exception:
        logger.exception("Failed to fetch bot identity during post_init")


def main() -> None:
    try:
        log_startup_info()

        app = (
            ApplicationBuilder()
            .token(settings.telegram_bot_token)
            .post_init(post_init)
            .build()
        )

        app.add_handler(MessageHandler(filters.TEXT, text_router))
        app.add_error_handler(global_error_handler)

        logger.info("%s is running...", settings.bot_username)
        app.run_polling(
            drop_pending_updates=getattr(settings, "drop_pending_updates", False)
        )

    except Exception:
        logger.exception("Fatal error during %s execution", settings.bot_name)
        sys.exit(1)


if __name__ == "__main__":
    main()
