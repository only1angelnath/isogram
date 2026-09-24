"""
bot.py — Telegram bot entrypoint.

Thin client of the Isogram FastAPI (docs/ARCHITECTURE.md §2.6) — no direct
Postgres access, no query logic duplicated from api/. Each handler:
  1. parses the command's args (commands.py, pure)
  2. calls the API (api_client.py, network only)
  3. formats the reply (commands.py, pure)

Commands (docs/PRD.md §4): /score <project>, /gas top10, /tvl

Run:
    python bot.py
Requires TELEGRAM_BOT_TOKEN and ISOGRAM_API_BASE_URL (see .env.example).
"""

import logging
import os
from typing import Optional

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

from api_client import ApiError, get_api_base_url, get_gas_top, get_score, get_tvl, get_tvl_top
from commands import (
    format_api_error,
    format_gas_leaderboard_reply,
    format_score_reply,
    format_tvl_leaderboard_reply,
    format_tvl_reply,
    parse_leaderboard_limit,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /score <project-id>")
        return
    project_id = context.args[0].lower()

    async with httpx.AsyncClient(base_url=get_api_base_url()) as client:
        try:
            data = await get_score(client, project_id)
        except ApiError as exc:
            logger.warning("API error in /score: %s", exc)
            await update.message.reply_text(format_api_error())
            return

    await update.message.reply_markdown(format_score_reply(data, project_id))


async def gas_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    limit = parse_leaderboard_limit(context.args or [])

    async with httpx.AsyncClient(base_url=get_api_base_url()) as client:
        try:
            entries = await get_gas_top(client, limit)
        except ApiError as exc:
            logger.warning("API error in /gas: %s", exc)
            await update.message.reply_text(format_api_error())
            return

    await update.message.reply_markdown(format_gas_leaderboard_reply(entries))


async def tvl_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with httpx.AsyncClient(base_url=get_api_base_url()) as client:
        try:
            if context.args:
                project_id = context.args[0].lower()
                data = await get_tvl(client, project_id)
                reply = format_tvl_reply(data, project_id)
            else:
                limit = parse_leaderboard_limit([])
                entries = await get_tvl_top(client, limit)
                reply = format_tvl_leaderboard_reply(entries)
        except ApiError as exc:
            logger.warning("API error in /tvl: %s", exc)
            await update.message.reply_text(format_api_error())
            return

    await update.message.reply_markdown(reply)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Isogram — the data truth layer for Arc.\n\n"
        "/score <project> — Arc Native Score for a project\n"
        "/gas top10 — top projects by USDC gas paid (7d)\n"
        "/tvl — top projects by TVL, or /tvl <project> for one"
    )


def build_application() -> Application:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN must be set (see .env.example).")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("score", score_command))
    app.add_handler(CommandHandler("gas", gas_command))
    app.add_handler(CommandHandler("tvl", tvl_command))
    return app


def get_webhook_base_url() -> Optional[str]:
    """
    Render sets RENDER_EXTERNAL_URL automatically on every web service — no
    manual config needed there. WEBHOOK_BASE_URL is a manual override for
    any other host. Returns None for local dev, which is the polling-mode
    signal (see run()) — nothing to configure locally, it just works.
    """
    return os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("WEBHOOK_BASE_URL")


def run(application: Application) -> None:
    """
    Free-tier background workers no longer exist on Render/Railway — only
    free web services, which idle down and wake on an incoming HTTP request.
    Long-polling (run_polling) needs a persistent process, so it doesn't fit
    that shape; webhooks do, since Telegram just POSTs to us whenever a
    message arrives; that POST is what wakes an idled free web service back
    up. Locally (no webhook base URL configured), fall back to polling,
    which is simpler for development and doesn't need a public URL at all.
    """
    webhook_base_url = get_webhook_base_url()
    token = os.environ["TELEGRAM_BOT_TOKEN"]

    if webhook_base_url:
        port = int(os.environ.get("PORT", "10000"))
        # The bot token doubles as an unguessable URL path — anyone who
        # doesn't know the token can't POST fake updates to this endpoint.
        webhook_url = f"{webhook_base_url.rstrip('/')}/{token}"
        logger.info("Isogram bot starting (webhook mode) at %s", webhook_url)
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=token,
            webhook_url=webhook_url,
        )
    else:
        logger.info("Isogram bot starting (polling mode, local dev)...")
        application.run_polling()


if __name__ == "__main__":
    run(build_application())