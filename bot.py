import functools
import logging
import re
from datetime import datetime, timezone, timedelta, time as dt_time
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

import config
import db
import flags
import football_api
from points import calculate_points

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TZ = ZoneInfo(config.TIMEZONE)

SCORE_RE = re.compile(r"^(\d+)-(\d+)$")
REMINDER_LEAD = 3600  # seconds before kickoff to post the prediction reminder


# ── Helpers ───────────────────────────────────────────────────────────────────

def _display(user) -> str:
    return user.full_name or user.username or str(user.id)


def _team(name: str) -> str:
    f = flags.flag(name)
    return f"{f} {name}" if f else name


def _parse_utc(utc_iso: str) -> datetime:
    dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_kickoff(utc_iso: str) -> str:
    return _parse_utc(utc_iso).astimezone(TZ).strftime("%b %d, %H:%M")


async def _is_group_member(bot, user_id: int) -> bool:
    if not config.GROUP_CHAT_ID:
        return True
    if user_id in config.ADMIN_IDS:
        return True
    try:
        member = await bot.get_chat_member(config.GROUP_CHAT_ID, user_id)
        return member.status in ("creator", "administrator", "member", "restricted")
    except Exception as e:
        logger.warning("get_chat_member failed for user %d: %s", user_id, e)
        return False


def require_member(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        chat = update.effective_chat
        # Messages from the group chat itself prove membership
        from_group = config.GROUP_CHAT_ID and chat.id == config.GROUP_CHAT_ID
        if not from_group and not await _is_group_member(context.bot, user.id):
            await update.message.reply_text("This bot is private and only available to group members.")
            return
        db.upsert_user(user.id, user.username, _display(user))
        return await func(update, context)
    return wrapper


def require_admin(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in config.ADMIN_IDS:
            await update.message.reply_text("Admin only.")
            return
        return await func(update, context)
    return wrapper


# ── User commands ─────────────────────────────────────────────────────────────

@require_member
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"Welcome, {_display(user)}! You're registered.\n\n"
        "/matches — upcoming matches\n"
        "/predict <id> <home>-<away> — submit prediction\n"
        "/mypreds — your upcoming predictions\n"
        "/myresults — your past results\n"
        "/table — rankings\n"
        "/help — all commands"
    )


@require_member
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Player commands*\n"
        "/matches — next 4 upcoming matches\n"
        "/recent — last 5 results\n"
        "/allmatches — all matches including finished\n"
        "/predict <id> <score> — e.g. `/predict 3 2-1`\n"
        "/mypreds — your upcoming predictions\n"
        "/myresults — your past results and points\n"
        "/preds <id> — see everyone's predictions for a match\n"
        "/stats — your prediction accuracy breakdown\n"
        "/table — rankings (with bonus)\n"
        "/bottable — rankings without bonus points\n"
        "/avgtable — points per prediction\n"
        "/olympictable — ranked by exact → goal diff → outcome\n"
        "/alltables — show all four tables\n\n"
        "*Admin commands*\n"
        "/sync — import upcoming fixtures from football-data.org\n"
        "/addmatch <home> vs <away> <YYYY-MM-DD HH:MM> — add match manually\n"
        "/result <id> <score> — override/set result manually\n"
        "/setbonus <name or @username> <points> — set starting bonus\n"
        "/deletematch <id> — delete an unplayed match\n"
        "/users — list registered players\n"
        "/chatid — show this chat's ID (for GROUP\\_CHAT\\_ID in .env)",
        parse_mode="Markdown",
    )


@require_member
async def cmd_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    matches = db.get_upcoming_matches()
    if not matches:
        await update.message.reply_text("No upcoming matches scheduled.")
        return
    shown = matches[:4]
    remaining = len(matches) - len(shown)
    lines = ["*Next 4 Upcoming Matches:*\n"]
    for m in shown:
        lock = "🔒 Locked" if m["is_locked"] else "✅ Open"
        lines.append(f"#{m['id']}  {_team(m['home_team'])} vs {_team(m['away_team'])}\n"
                     f"   {_fmt_kickoff(m['kickoff_utc'])} — {lock}")
    if remaining:
        lines.append(f"\n_{remaining} more — use /allmatches to see all_")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@require_member
async def cmd_recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["*Last 5 Results:*\n"]
    found = False

    if config.FOOTBALL_API_KEY:
        try:
            api_matches = await football_api.fetch_recent_finished(
                config.FOOTBALL_API_KEY, config.COMPETITION_CODE
            )
            api_matches.sort(key=lambda m: m["utcDate"], reverse=True)
            for m in api_matches[:5]:
                home = football_api.team_name(m["homeTeam"])
                away = football_api.team_name(m["awayTeam"])
                score = (m.get("score") or {}).get("fullTime") or {}
                h, a = score.get("home", "?"), score.get("away", "?")
                db_match = db.get_match_by_api_id(m["id"])
                id_str = f"#{db_match['id']}  " if db_match else ""
                lines.append(
                    f"{id_str}{_team(home)} *{h}–{a}* {_team(away)}\n"
                    f"   _{_fmt_kickoff(m['utcDate'])}_"
                )
                found = True
        except Exception as e:
            logger.warning("API error in /recent: %s", e)

    if not found:
        for m in db.get_recent_finished():
            lines.append(
                f"#{m['id']}  {_team(m['home_team'])} *{m['home_score']}–{m['away_score']}* {_team(m['away_team'])}\n"
                f"   _{_fmt_kickoff(m['kickoff_utc'])}_"
            )
            found = True

    if not found:
        await update.message.reply_text("No finished matches yet.")
        return

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@require_member
async def cmd_allmatches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_allmatches_page(update.message.chat_id, offset=0, context=context)


async def _send_allmatches_page(chat_id: int, offset: int, context: ContextTypes.DEFAULT_TYPE):
    matches = db.get_all_matches()
    if not matches:
        await context.bot.send_message(chat_id, "No matches yet.")
        return

    all_lines = []
    for m in matches:
        if m["is_finished"]:
            all_lines.append(
                f"✅ #{m['id']}  {_team(m['home_team'])} *{m['home_score']}–{m['away_score']}* {_team(m['away_team'])}"
                f"  _{_fmt_kickoff(m['kickoff_utc'])}_"
            )
        else:
            lock = "🔒" if m["is_locked"] else "📋"
            all_lines.append(
                f"{lock} #{m['id']}  {_team(m['home_team'])} vs {_team(m['away_team'])}"
                f"  _{_fmt_kickoff(m['kickoff_utc'])}_"
            )

    header = "*All Matches:*\n" if offset == 0 else f"*...continued ({offset + 1}–)*\n"
    page_lines = [header]
    char_count = len(header)
    end_idx = offset

    for i, line in enumerate(all_lines[offset:], start=offset):
        if char_count + len(line) + 1 > 3800:
            break
        page_lines.append(line)
        char_count += len(line) + 1
        end_idx = i + 1

    has_more = end_idx < len(all_lines)
    keyboard = (
        InlineKeyboardMarkup([[InlineKeyboardButton("Show more →", callback_data=f"allmatches:{end_idx}")]])
        if has_more else None
    )

    await context.bot.send_message(
        chat_id,
        "\n".join(page_lines),
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def _allmatches_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    offset = int(query.data.split(":")[1])
    await _send_allmatches_page(query.message.chat_id, offset=offset, context=context)


@require_member
async def cmd_predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    if len(args) < 2 or not SCORE_RE.match(args[1]):
        await update.message.reply_text(
            "Usage: /predict <match\\_id> <home>-<away> [winner]\n"
            "Example: `/predict 3 2-1`\n"
            "For draws: `/predict 3 1-1 1` (1=home wins, 2=away wins)",
            parse_mode="Markdown",
        )
        return

    match_id = int(args[0])
    pred_home, pred_away = map(int, args[1].split("-"))
    
    pred_winner = None
    if len(args) == 3:
        if args[2] not in ("1", "2"):
            await update.message.reply_text("Winner must be 1 (home) or 2 (away).")
            return
        pred_winner = int(args[2])

    match = db.get_match(match_id)
    if not match:
        await update.message.reply_text(f"Match #{match_id} not found.")
        return
    if match["is_locked"]:
        await update.message.reply_text("Predictions are closed for this match.")
        return

    db_user = db.get_user(user.id)
    db.upsert_prediction(db_user["id"], match_id, pred_home, pred_away, pred_winner)
    
    winner_str = ""
    if pred_winner == 1:
        winner_str = f" — {match['home_team']} to advance"
    elif pred_winner == 2:
        winner_str = f" — {match['away_team']} to advance"
    
    await update.message.reply_text(
        f"Saved: {_team(match['home_team'])} *{pred_home}–{pred_away}* {_team(match['away_team'])}{winner_str}",
        parse_mode="Markdown",
    )



def _pred_line(p):
    pred_str = f"{p['home_score']}-{p['away_score']}"
    if p["is_finished"] and p["actual_home"] is not None:
        pts = p["points"] if p["points"] is not None else 0
        suffix = f"→ {p['actual_home']}-{p['actual_away']}  *{pts} pts*"
    elif p["is_locked"]:
        suffix = "🔒 locked"
    else:
        suffix = "✅ open"
    return (
        f"#{p['match_id']} {_team(p['home_team'])} vs {_team(p['away_team'])}"
        f" ({_fmt_kickoff(p['kickoff_utc'])})\n"
        f"   Pred: *{pred_str}*  {suffix}"
    )


@require_member
async def cmd_mypreds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = db.get_user(user.id)
    preds = db.get_user_predictions(db_user["id"])
    upcoming = [p for p in preds if not p["is_finished"]]

    if not upcoming:
        await update.message.reply_text("You have no upcoming predictions.")
        return

    lines = ["*Your Predictions:*\n"] + [_pred_line(p) for p in upcoming]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@require_member
async def cmd_myresults(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = db.get_user(user.id)
    preds = db.get_user_predictions(db_user["id"])
    finished = [p for p in preds if p["is_finished"]]

    if not finished:
        await update.message.reply_text("No finished predictions yet.")
        return

    shown = finished[-4:][::-1]
    remaining = len(finished) - 4

    lines = ["*Your Results:*\n"] + [_pred_line(p) for p in shown]

    keyboard = None
    if remaining > 0:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"Show {min(remaining, 4)} more", callback_data=f"myresults:{user.id}:4")
        ]])

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)


async def _myresults_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, uid, offset_str = query.data.split(":")
    offset = int(offset_str)

    db_user = db.get_user(int(uid))
    if not db_user:
        return
    preds = db.get_user_predictions(db_user["id"])
    finished = [p for p in preds if p["is_finished"]]

    shown = finished[-(offset + 4):-offset if offset else None][::-1]
    remaining = len(finished) - offset - 4

    lines = [f"*Your Results (older):*\n"] + [_pred_line(p) for p in shown]

    keyboard = None
    if remaining > 0:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"Show {min(remaining, 4)} more", callback_data=f"myresults:{uid}:{offset + 4}")
        ]])

    await query.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)


@require_member
async def cmd_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rankings = db.get_rankings()
    if not rankings:
        await update.message.reply_text("No players registered yet.")
        return

    medals = ["🥇", "🥈", "🥉"]
    lines = ["*🏆 World Cup Rankings:*\n"]
    for i, r in enumerate(rankings):
        badge = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{badge} {r['display_name']} — *{r['total_points']} pts*")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@require_member
async def cmd_bottable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rankings = db.get_bot_rankings()
    if not rankings:
        await update.message.reply_text("No players registered yet.")
        return

    medals = ["🥇", "🥈", "🥉"]
    lines = ["*🤖 Bot Table (no bonus):*\n"]
    for i, r in enumerate(rankings):
        badge = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{badge} {r['display_name']} — *{r['earned_points']} pts*")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@require_member
async def cmd_avgtable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rankings = db.get_avg_rankings()
    if not rankings:
        await update.message.reply_text("No players registered yet.")
        return

    medals = ["🥇", "🥈", "🥉"]
    lines = ["*📈 Avg Bot Table (pts per prediction):*\n"]
    for i, r in enumerate(rankings):
        badge = medals[i] if i < 3 else f"{i + 1}."
        avg = round(r["avg_points"], 2)
        lines.append(
            f"{badge} {r['display_name']} — *{avg} pts/pred*"
            f"  _({r['earned_points']} pts, {r['graded']} preds)_"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@require_member
async def cmd_olympictable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rankings = db.get_olympic_rankings()
    if not rankings:
        await update.message.reply_text("No players registered yet.")
        return

    medals = ["🥇", "🥈", "🥉"]
    lines = ["*🏅 Olympic Table:*\n_(sorted by exact → goal diff → outcome)_\n"]
    for i, r in enumerate(rankings):
        badge = medals[i] if i < 3 else f"{i + 1}."
        lines.append(
            f"{badge} {r['display_name']} — "
            f"🎯{r['exact']}  ✅{r['correct_gd']}  👍{r['correct_outcome']}"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@require_member
async def cmd_alltables(update: Update, context: ContextTypes.DEFAULT_TYPE):
    medals = ["🥇", "🥈", "🥉"]

    def _badge(i):
        return medals[i] if i < 3 else f"{i + 1}."

    sections = []

    r1 = db.get_rankings()
    if r1:
        lines = ["*🏆 World Cup Rankings (with bonus):*\n"]
        for i, r in enumerate(r1):
            lines.append(f"{_badge(i)} {r['display_name']} — *{r['total_points']} pts*")
        sections.append("\n".join(lines))

    r2 = db.get_bot_rankings()
    if r2:
        lines = ["*🤖 Bot Table (no bonus):*\n"]
        for i, r in enumerate(r2):
            lines.append(f"{_badge(i)} {r['display_name']} — *{r['earned_points']} pts*")
        sections.append("\n".join(lines))

    r3 = db.get_avg_rankings()
    if r3:
        lines = ["*📈 Avg Bot Table (pts per prediction):*\n"]
        for i, r in enumerate(r3):
            avg = round(r["avg_points"], 2)
            lines.append(
                f"{_badge(i)} {r['display_name']} — *{avg} pts/pred*"
                f"  _({r['earned_points']} pts, {r['graded']} preds)_"
            )
        sections.append("\n".join(lines))

    r4 = db.get_olympic_rankings()
    if r4:
        lines = ["*🏅 Olympic Table:*\n_(sorted by exact → goal diff → outcome)_\n"]
        for i, r in enumerate(r4):
            lines.append(
                f"{_badge(i)} {r['display_name']} — "
                f"🎯{r['exact']}  ✅{r['correct_gd']}  👍{r['correct_outcome']}"
            )
        sections.append("\n".join(lines))

    if not sections:
        await update.message.reply_text("No players registered yet.")
        return

    for section in sections:
        await update.message.reply_text(section, parse_mode="Markdown")


@require_member
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = db.get_user(user.id)
    stats = db.get_user_stats(db_user["id"])
    rankings = db.get_rankings()
    bonus = next((r["bonus_points"] for r in rankings if r["display_name"] == db_user["display_name"]), 0)

    graded = stats["graded"] or 0
    exact = stats["exact"] or 0
    correct_gd = stats["correct_gd"] or 0
    correct_outcome = stats["correct_outcome"] or 0
    miss = stats["miss"] or 0
    earned = stats["earned_points"] or 0

    lines = [
        f"📊 *Stats — {_display(user)}*\n",
        f"Predictions graded: *{graded}*",
        f"🎯 Exact score (10 pts): *{exact}*",
        f"✅ Correct + GD (7 pts): *{correct_gd}*",
        f"👍 Correct outcome (5 pts): *{correct_outcome}*",
        f"❌ Miss (0 pts): *{miss}*\n",
        f"Points from games: *{earned}*",
        f"Bonus points: *{bonus}*",
        f"Total: *{earned + bonus} pts*",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── Admin commands ────────────────────────────────────────────────────────────

@require_admin
async def cmd_addmatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    m = re.match(
        r"^(.+?)\s+vs\s+(.+?)\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})$",
        text,
        re.IGNORECASE,
    )
    if not m:
        await update.message.reply_text(
            "Usage: `/addmatch <home> vs <away> YYYY-MM-DD HH:MM`\n"
            f"Time is in {config.TIMEZONE}.\n"
            "Example: `/addmatch Brazil vs Argentina 2026-06-18 20:00`",
            parse_mode="Markdown",
        )
        return

    home, away, time_str = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
    local_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    utc_dt = local_dt.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)

    if utc_dt <= now:
        await update.message.reply_text("Kickoff time must be in the future.")
        return

    match_id = db.add_match(home, away, utc_dt.isoformat())

    delay = (utc_dt - now).total_seconds()
    context.job_queue.run_once(
        _lock_match_job,
        when=delay,
        name=f"lock_{match_id}",
        data=match_id,
    )
    reminder_delay = delay - REMINDER_LEAD
    if reminder_delay > 0:
        context.job_queue.run_once(
            _reminder_job,
            when=reminder_delay,
            name=f"reminder_{match_id}",
            data=match_id,
        )

    await update.message.reply_text(
        f"Match #{match_id} added: *{home} vs {away}*\n{_fmt_kickoff(utc_dt.isoformat())}",
        parse_mode="Markdown",
    )


@require_admin
async def cmd_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 2 or not SCORE_RE.match(args[1]):
        await update.message.reply_text(
            "Usage: `/result <match_id> <home>-<away>`\nExample: `/result 3 2-1`",
            parse_mode="Markdown",
        )
        return

    match_id = int(args[0])
    actual_home, actual_away = map(int, args[1].split("-"))

    match = db.get_match(match_id)
    if not match:
        await update.message.reply_text(f"Match #{match_id} not found.")
        return

    db.set_result(match_id, actual_home, actual_away)

    preds = db.get_match_predictions(match_id)
    award_lines = []
    for p in preds:
        pts = calculate_points(p["home_score"], p["away_score"], actual_home, actual_away)
        db.award_points(match_id, p["user_id"], pts)
        award_lines.append(f"• {p['display_name']}: {p['home_score']}-{p['away_score']} → *{pts} pts*")

    summary = "\n".join(award_lines) if award_lines else "_No predictions for this match._"
    await update.message.reply_text(
        f"Result: {_team(match['home_team'])} *{actual_home}–{actual_away}* {_team(match['away_team'])}\n\n"
        f"*Points awarded:*\n{summary}",
        parse_mode="Markdown",
    )


@require_admin
async def cmd_setbonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: `/setbonus <name or @username> <points>`", parse_mode="Markdown")
        return

    try:
        points = int(args[-1])
    except ValueError:
        await update.message.reply_text("Points must be a whole number.")
        return

    identifier = " ".join(args[:-1])
    if db.set_bonus_points(identifier, points):
        await update.message.reply_text(f"Bonus for *{identifier}* set to *{points} pts*.", parse_mode="Markdown")
    else:
        await update.message.reply_text(
            f"User `{identifier}` not found. They need to /start the bot first.",
            parse_mode="Markdown",
        )


@require_member
async def cmd_preds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /preds <match_id>")
        return

    match_id = int(context.args[0])
    match = db.get_match(match_id)
    if not match:
        await update.message.reply_text(f"Match #{match_id} not found.")
        return

    preds = db.get_match_predictions(match_id)
    if not preds:
        await update.message.reply_text("No predictions for this match yet.")
        return

    lines = [f"*Predictions — {_team(match['home_team'])} vs {_team(match['away_team'])}:*\n"]
    for p in preds:
        pts_str = f"  ({p['points']} pts)" if p["points"] is not None else ""
        lines.append(f"• {p['display_name']}: *{p['home_score']}-{p['away_score']}*{pts_str}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@require_admin
async def cmd_deletematch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /deletematch <match_id>")
        return

    match_id = int(context.args[0])
    if db.delete_match(match_id):
        for job in context.job_queue.get_jobs_by_name(f"lock_{match_id}"):
            job.schedule_removal()
        await update.message.reply_text(f"Match #{match_id} deleted.")
    else:
        await update.message.reply_text(f"Match #{match_id} not found or already finished.")


@require_admin
async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = db.list_users()
    if not users:
        await update.message.reply_text("No registered players yet.")
        return
    lines = ["*Registered Players:*\n"]
    for u in users:
        uname = f" (@{u['username']})" if u["username"] else ""
        lines.append(f"• {u['display_name']}{uname} — bonus: {u['bonus_points']} pts")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
@require_admin
async def cmd_removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /removeuser <name or @username>")
        return
    identifier = " ".join(context.args)
    if db.delete_user(identifier):
        await update.message.reply_text(f"✅ User '{identifier}' removed.")
    else:
        await update.message.reply_text(f"❌ User '{identifier}' not found.")

@require_admin
async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.message.reply_text(
        f"Chat ID: `{chat.id}`\nType: {chat.type}\n\nPaste this as GROUP\\_CHAT\\_ID in your .env",
        parse_mode="Markdown",
    )


@require_admin
async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not config.FOOTBALL_API_KEY:
        await update.message.reply_text(
            "FOOTBALL\\_API\\_KEY is not set in .env\\.\n"
            "Get a free key at football\\-data\\.org and add it\\.",
            parse_mode="MarkdownV2",
        )
        return

    await update.message.reply_text(
        f"Syncing {config.COMPETITION_CODE} fixtures from football-data.org…"
    )

    try:
        api_matches = await football_api.fetch_scheduled(
            config.FOOTBALL_API_KEY, config.COMPETITION_CODE
        )
    except Exception as e:
        await update.message.reply_text(f"API error: {e}")
        return

    added = 0
    skipped_tbd = 0
    now = datetime.now(timezone.utc)
    for m in api_matches:
        api_id = m["id"]
        if db.get_match_by_api_id(api_id):
            continue

        home = football_api.team_name(m["homeTeam"])
        away = football_api.team_name(m["awayTeam"])

        if home == "TBD" or away == "TBD":
            skipped_tbd += 1
            continue

        kickoff_utc = m["utcDate"].replace("Z", "+00:00")
        kickoff_dt = _parse_utc(kickoff_utc)

        match_id = db.add_match(home, away, kickoff_utc, api_match_id=api_id)

        if kickoff_dt > now:
            delay = (kickoff_dt - now).total_seconds()
            context.job_queue.run_once(
                _lock_match_job,
                when=delay,
                name=f"lock_{match_id}",
                data=match_id,
            )
            reminder_delay = delay - REMINDER_LEAD
            if reminder_delay > 0:
                context.job_queue.run_once(
                    _reminder_job,
                    when=reminder_delay,
                    name=f"reminder_{match_id}",
                    data=match_id,
                )

        added += 1

    already = len(api_matches) - added - skipped_tbd
    note = f"\n_{skipped_tbd} knockout slots skipped (TBD teams — re-run /sync later)_" if skipped_tbd else ""
    await update.message.reply_text(
        f"Done. Added *{added}* new match(es), {already} already in DB.{note}",
        parse_mode="Markdown",
    )


# ── Scheduler ─────────────────────────────────────────────────────────────────

async def _lock_match_job(context: ContextTypes.DEFAULT_TYPE):
    match_id = context.job.data
    db.lock_match(match_id)
    match = db.get_match(match_id)
    if not match:
        return

    logger.info("Match #%d (%s vs %s) locked for predictions.", match_id,
                match["home_team"], match["away_team"])

    if not config.GROUP_CHAT_ID:
        return

    preds = db.get_match_predictions(match_id)
    if preds:
        pred_lines = "\n".join(f"• {p['display_name']}: *{p['home_score']}-{p['away_score']}*" for p in preds)
    else:
        pred_lines = "_No predictions submitted._"

    text = (
        f"⚽ Kick off! {_team(match['home_team'])} vs {_team(match['away_team'])}\n\n"
        f"*Predictions:*\n{pred_lines}"
    )

    try:
        await context.bot.send_message(config.GROUP_CHAT_ID, text, parse_mode="Markdown")
    except Exception as e:
        logger.warning("Failed to post kick-off predictions to group: %s", e)


async def _reminder_job(context: ContextTypes.DEFAULT_TYPE):
    match_id = context.job.data
    match = db.get_match(match_id)
    if not match or match["is_locked"] or match["is_finished"]:
        return
    if not config.GROUP_CHAT_ID:
        return

    all_users = db.list_users()
    predicted_ids = {p["user_id"] for p in db.get_match_predictions(match_id)}
    missing = [u for u in all_users if u["id"] not in predicted_ids]

    header = f"⏰ 1 hour to kick off: {_team(match['home_team'])} vs {_team(match['away_team'])}"
    if not missing:
        text = f"{header}\n\nEveryone has predicted! ✅"
    else:
        tags = ", ".join(f"@{u['username']}" if u["username"] else u["display_name"] for u in missing)
        text = f"{header}\n\nStill waiting on: {tags}"

    try:
        await context.bot.send_message(config.GROUP_CHAT_ID, text)
    except Exception as e:
        logger.warning("Failed to post reminder to group: %s", e)


async def _daily_digest_job(context: ContextTypes.DEFAULT_TYPE):
    if not config.GROUP_CHAT_ID:
        return

    now_local = datetime.now(TZ)
    day_start = now_local.replace(hour=12, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    matches = db.get_matches_between(
        day_start.astimezone(timezone.utc).isoformat(),
        day_end.astimezone(timezone.utc).isoformat(),
    )
    if not matches:
        return

    lines = ["📅 *Today's Matches:*\n"]
    for m in matches:
        if m["is_finished"]:
            lines.append(
                f"✅ {_team(m['home_team'])} *{m['home_score']}–{m['away_score']}* {_team(m['away_team'])}"
                f"  _{_fmt_kickoff(m['kickoff_utc'])}_"
            )
        else:
            lock = "🔒" if m["is_locked"] else "📋"
            lines.append(
                f"{lock} #{m['id']}  {_team(m['home_team'])} vs {_team(m['away_team'])}"
                f"  _{_fmt_kickoff(m['kickoff_utc'])}_"
            )

    try:
        await context.bot.send_message(config.GROUP_CHAT_ID, "\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        logger.warning("Failed to post daily digest: %s", e)


async def _check_results_job(context: ContextTypes.DEFAULT_TYPE):
    """Polls the API for finished matches and auto-awards points."""
    if not config.FOOTBALL_API_KEY:
        return

    try:
        finished = await football_api.fetch_recent_finished(
            config.FOOTBALL_API_KEY, config.COMPETITION_CODE
        )
    except Exception as e:
        logger.warning("Result checker API error: %s", e)
        return

    for m in finished:
        our_match = db.get_match_by_api_id(m["id"])
        if not our_match or our_match["is_finished"]:
            continue

        score = (m.get("score") or {}).get("fullTime") or {}
        actual_home = score.get("home")
        actual_away = score.get("away")
        if actual_home is None or actual_away is None:
            continue

        match_id = our_match["id"]
        db.set_result(match_id, actual_home, actual_away)

        preds = db.get_match_predictions(match_id)
        award_lines = []
        for p in preds:
            pts = calculate_points(p["home_score"], p["away_score"], actual_home, actual_away)
            db.award_points(match_id, p["user_id"], pts)
            award_lines.append(
                f"• {p['display_name']}: {p['home_score']}-{p['away_score']} → *{pts} pts*"
            )

        summary = "\n".join(award_lines) if award_lines else "_No predictions for this match._"
        text = (
            f"⚽ Full time: {_team(our_match['home_team'])} *{actual_home}–{actual_away}* {_team(our_match['away_team'])}\n\n"
            f"*Points awarded:*\n{summary}"
        )

        logger.info("Auto-result: match #%d set to %d-%d", match_id, actual_home, actual_away)

        if config.GROUP_CHAT_ID:
            try:
                await context.bot.send_message(
                    config.GROUP_CHAT_ID, text, parse_mode="Markdown"
                )
            except Exception as e:
                logger.warning("Failed to post result to group: %s", e)


async def _post_init(app: Application) -> None:
    """Reschedule lock/reminder jobs and start result checker and daily digest on startup."""
    pending = db.get_pending_locks()
    now = datetime.now(timezone.utc)
    for m in pending:
        kickoff = _parse_utc(m["kickoff_utc"])
        delay = max(1.0, (kickoff - now).total_seconds())
        app.job_queue.run_once(
            _lock_match_job,
            when=delay,
            name=f"lock_{m['id']}",
            data=m["id"],
        )
        reminder_delay = (kickoff - now).total_seconds() - REMINDER_LEAD
        if reminder_delay > 0:
            app.job_queue.run_once(
                _reminder_job,
                when=reminder_delay,
                name=f"reminder_{m['id']}",
                data=m["id"],
            )
        logger.info("Rescheduled lock for match #%d in %.0fs", m["id"], delay)

    if config.FOOTBALL_API_KEY:
        app.job_queue.run_repeating(
            _check_results_job,
            interval=config.RESULT_CHECK_INTERVAL,
            first=10,
            name="result_checker",
        )
        logger.info(
            "Result checker active — polling every %ds", config.RESULT_CHECK_INTERVAL
        )

    app.job_queue.run_daily(
        _daily_digest_job,
        time=dt_time(12, 0, tzinfo=TZ),
        name="daily_digest",
    )
    logger.info("Daily digest scheduled at 12:00 %s", config.TIMEZONE)


# ── Entry point ───────────────────────────────────────────────────────────────

async def auto_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and not user.is_bot:
        if await _is_group_member(context.bot, user.id):
            db.upsert_user(user.id, user.username, _display(user))


def main():
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")
    if not config.ADMIN_IDS:
        raise RuntimeError("ADMIN_IDS is not set. Add your Telegram user ID to .env.")

    db.init_db()

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )

    # Player commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("matches", cmd_matches))
    app.add_handler(CommandHandler("recent", cmd_recent))
    app.add_handler(CommandHandler("allmatches", cmd_allmatches))
    app.add_handler(CallbackQueryHandler(_allmatches_callback, pattern=r"^allmatches:\d+$"))
    app.add_handler(CommandHandler("predict", cmd_predict))
    app.add_handler(CommandHandler("mypreds", cmd_mypreds))
    app.add_handler(CommandHandler("myresults", cmd_myresults))
    app.add_handler(CallbackQueryHandler(_myresults_callback, pattern=r"^myresults:\d+:\d+$"))
    app.add_handler(CommandHandler("table", cmd_table))
    app.add_handler(CommandHandler("bottable", cmd_bottable))
    app.add_handler(CommandHandler("avgtable", cmd_avgtable))
    app.add_handler(CommandHandler("olympictable", cmd_olympictable))
    app.add_handler(CommandHandler("alltables", cmd_alltables))
    app.add_handler(CommandHandler("stats", cmd_stats))

    # Admin commands
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("addmatch", cmd_addmatch))
    app.add_handler(CommandHandler("result", cmd_result))
    app.add_handler(CommandHandler("setbonus", cmd_setbonus))
    app.add_handler(CommandHandler("preds", cmd_preds))
    app.add_handler(CommandHandler("deletematch", cmd_deletematch))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("removeuser", cmd_removeuser))
    app.add_handler(CommandHandler("chatid", cmd_chatid))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, auto_register))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
