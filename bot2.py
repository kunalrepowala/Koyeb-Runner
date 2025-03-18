import asyncio
import nest_asyncio
import uuid
import logging
from pymongo import MongoClient
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    MessageHandler,
    InlineQueryHandler,
    CommandHandler,
    filters,
    ContextTypes,
)

# Allow nested asyncio loops
nest_asyncio.apply()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# --- MongoDB Setup ---
mongo_url = "mongodb+srv://kunalrepowalaa1:wEkoUJ8S92X7Qwyx@cluster0.hdm9d.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
mongo_client = MongoClient(mongo_url)
mongo_db = mongo_client['Cluster0']
invite_links_collection = mongo_db['invite_links']

# Global in-memory dictionary (for quick access) – we'll update MongoDB when posting.
invite_links = {}

ADMIN_ID = 6773787379
bot_token = "8157877774:AAFK7qpFm6GeaunPzpilZD7vuz5N-j3bFjA"  # replace with your token

# --- Helper: URL validation ---
def is_valid_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://") or url.startswith("tg://")

# --- Helper: Split text into chunks (if needed) ---
def split_text(text, chunk_size=4096):
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

# --- Keyboard builders ---
def build_editing_keyboard(session):
    session_id = session["session_id"]
    keyboard = []
    for i, row in enumerate(session["inline_buttons"]):
        row_buttons = [InlineKeyboardButton(text=btn["text"], url=btn["url"]) for btn in row]
        row_buttons.append(InlineKeyboardButton(text="+", callback_data=f"session:{session_id}:add_to_row:{i}"))
        keyboard.append(row_buttons)
    keyboard.append([InlineKeyboardButton(text="+", callback_data=f"session:{session_id}:new_row")])
    if session["inline_buttons"]:
        keyboard.append([InlineKeyboardButton(text="Done ✅", callback_data=f"session:{session_id}:done")])
    return InlineKeyboardMarkup(keyboard)

def build_final_keyboard(session):
    keyboard = []
    for row in session["inline_buttons"]:
        row_buttons = [InlineKeyboardButton(text=btn["text"], url=btn["url"]) for btn in row]
        keyboard.append(row_buttons)
    return InlineKeyboardMarkup(keyboard)

def build_post_share_keyboard(session):
    session_id = session["session_id"]
    share_btn = InlineKeyboardButton(
        text="Share",
        switch_inline_query=f"share_{session_id}"
    )
    post_btn = InlineKeyboardButton(
        text="Post To Group/Channel",
        callback_data=f"session:{session_id}:post"
    )
    return InlineKeyboardMarkup([[share_btn], [post_btn]])

def build_yes_no_keyboard(session, dest):
    session_id = session["session_id"]
    keyboard = [[
        InlineKeyboardButton(text="Yes", callback_data=f"session:{session_id}:post_confirm:yes:{dest}"),
        InlineKeyboardButton(text="No", callback_data=f"session:{session_id}:post_confirm:no")
    ]]
    return InlineKeyboardMarkup(keyboard)

# --- Handlers ---
async def start_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private":
        return
    if not update.message:
        return
    message = update.message
    chat_id = message.chat.id

    if message.forward_date:
        text = message.text if message.text is not None else (message.caption if message.caption is not None else "")
        is_media = (message.text is None)
        extracted_buttons = []
        if message.reply_markup and message.reply_markup.inline_keyboard:
            for row in message.reply_markup.inline_keyboard:
                new_row = []
                for btn in row:
                    if btn.url:
                        new_row.append({"text": btn.text, "url": btn.url})
                if new_row:
                    extracted_buttons.append(new_row)
        session_id = str(message.message_id) + "_" + str(uuid.uuid4().hex[:6])
        session = {
            "session_id": session_id,
            "chat_id": chat_id,
            "text": text,
            "inline_buttons": extracted_buttons,
            "awaiting_button_info": False,
            "target_row": None,
            "last_message_id": None,
            "is_media": is_media,
            "original_message_id": message.message_id,
            "final_message_id": None,
            "awaiting_post": False,
            "post_channel": None,
        }
    else:
        text = message.text if message.text is not None else (message.caption if message.caption is not None else "")
        is_media = (message.text is None)
        session_id = str(message.message_id) + "_" + str(uuid.uuid4().hex[:6])
        session = {
            "session_id": session_id,
            "chat_id": chat_id,
            "text": text,
            "inline_buttons": [],
            "awaiting_button_info": False,
            "target_row": None,
            "last_message_id": None,
            "is_media": is_media,
            "original_message_id": message.message_id,
            "final_message_id": None,
            "awaiting_post": False,
            "post_channel": None,
        }
    if "sessions" not in context.user_data:
        context.user_data["sessions"] = {}
    context.user_data["sessions"][session_id] = session

    keyboard = build_editing_keyboard(session)
    sent = await context.bot.copy_message(
        chat_id=chat_id,
        from_chat_id=chat_id,
        message_id=message.message_id,
        reply_markup=keyboard
    )
    session["last_message_id"] = sent.message_id

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private":
        return
    query = update.callback_query
    await query.answer()
    data = query.data.split(":")
    if len(data) < 3 or data[0] != "session":
        return
    session_id = data[1]
    action = data[2]
    sessions = context.user_data.get("sessions", {})
    session = sessions.get(session_id)
    if not session:
        await query.edit_message_text("Session not found.")
        return

    if action in ["add_to_row", "new_row"]:
        if action == "add_to_row":
            if len(data) < 4:
                return
            try:
                row_index = int(data[3])
            except ValueError:
                return
            session["awaiting_button_info"] = True
            session["target_row"] = row_index
        else:
            session["awaiting_button_info"] = True
            session["target_row"] = len(session["inline_buttons"])
        context.user_data["awaiting_session_id"] = session_id
        await context.bot.send_message(
            chat_id=session["chat_id"],
            text="Please send button info in format: <label> <URL>"
        )
    elif action == "done":
        if not session["inline_buttons"]:
            await context.bot.send_message(chat_id=session["chat_id"], text="No URL buttons created yet.")
            return
        final_keyboard = build_final_keyboard(session)
        sent = await context.bot.copy_message(
            chat_id=session["chat_id"],
            from_chat_id=session["chat_id"],
            message_id=session["original_message_id"],
            reply_markup=final_keyboard
        )
        session["final_message_id"] = sent.message_id
        extra_keyboard = build_post_share_keyboard(session)
        await context.bot.send_message(
            chat_id=session["chat_id"],
            text="You can share it or post it to a group/channel.",
            reply_markup=extra_keyboard
        )
    elif action == "post":
        session["awaiting_post"] = True
        context.user_data["awaiting_post_session_id"] = session_id
        await context.bot.send_message(
            chat_id=session["chat_id"],
            text="Please send the channel/group ID or forward a message from that channel/group."
        )
    elif action == "post_confirm":
        if len(data) < 4:
            return
        decision = data[3]
        if decision == "yes":
            if len(data) < 5:
                return
            dest = data[4]
            try:
                await context.bot.copy_message(
                    chat_id=int(dest),
                    from_chat_id=session["chat_id"],
                    message_id=session["original_message_id"],
                    reply_markup=build_final_keyboard(session)
                )
                await context.bot.send_message(
                    chat_id=session["chat_id"],
                    text="Message posted successfully!"
                )
                # Create an invite link for the destination channel/group.
                new_invite = await context.bot.create_chat_invite_link(chat_id=int(dest))
                chat_info = await context.bot.get_chat(chat_id=int(dest))
                title = chat_info.title if chat_info.title else "Unknown Title"
                # Update MongoDB with the invite link.
                invite_links_collection.update_one(
                    {"channel_id": int(dest)},
                    {"$set": {"title": title, "invite_link": new_invite.invite_link}},
                    upsert=True
                )
                # Also update the global in-memory dictionary.
                invite_links[int(dest)] = (title, new_invite.invite_link)
            except Exception as e:
                await context.bot.send_message(
                    chat_id=session["chat_id"],
                    text=f"Failed to post message: {e}"
                )
            if session_id in sessions:
                del sessions[session_id]
        elif decision == "no":
            await context.bot.send_message(
                chat_id=session["chat_id"],
                text="Posting cancelled."
            )
            if session_id in sessions:
                del sessions[session_id]

async def button_info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private":
        return
    if not update.message:
        return
    # Post destination flow.
    if "awaiting_post_session_id" in context.user_data:
        session_id = context.user_data["awaiting_post_session_id"]
        sessions = context.user_data.get("sessions", {})
        session = sessions.get(session_id)
        if not session:
            context.user_data.pop("awaiting_post_session_id", None)
            return
        dest = None
        if update.message.forward_from_chat:
            dest = update.message.forward_from_chat.id
        elif update.message.text:
            dest = update.message.text.strip()
        else:
            await update.message.reply_text("Invalid input for channel/group ID.")
            return
        try:
            dest = int(dest)
        except ValueError:
            await update.message.reply_text("Invalid channel/group ID. It should be numeric.")
            return
        try:
            member = await context.bot.get_chat_member(chat_id=dest, user_id=update.effective_user.id)
            if member.status not in ["administrator", "creator"]:
                await update.message.reply_text("You are not an admin in that channel/group.")
                context.user_data.pop("awaiting_post_session_id", None)
                session["awaiting_post"] = False
                return
        except Exception as e:
            await update.message.reply_text(f"Error checking admin status: {e}")
            context.user_data.pop("awaiting_post_session_id", None)
            session["awaiting_post"] = False
            return
        yes_no_keyboard = build_yes_no_keyboard(session, dest)
        await update.message.reply_text(
            f"Do you want to post the final message to channel/group {dest}?",
            reply_markup=yes_no_keyboard,
            reply_to_message_id=session["final_message_id"]
        )
        context.user_data.pop("awaiting_post_session_id", None)
        return

    # Button info for adding URL.
    if "awaiting_session_id" in context.user_data:
        session_id = context.user_data["awaiting_session_id"]
        sessions = context.user_data.get("sessions", {})
        session = sessions.get(session_id)
        if not session:
            context.user_data.pop("awaiting_session_id", None)
            return
        text = update.message.text.strip()
        parts = text.rsplit(" ", 1)
        if len(parts) < 2:
            await update.message.reply_text("Invalid format. Please send in format: <label> <URL>")
            return
        label, url = parts[0], parts[1]
        if not is_valid_url(url):
            await update.message.reply_text("Invalid URL. It must start with http://, https:// or tg://")
            return
        target_row = session["target_row"]
        if target_row == len(session["inline_buttons"]):
            session["inline_buttons"].append([{"text": label, "url": url}])
        else:
            session["inline_buttons"][target_row].append({"text": label, "url": url})
        session["awaiting_button_info"] = False
        session["target_row"] = None
        context.user_data.pop("awaiting_session_id", None)
        keyboard = build_editing_keyboard(session)
        sent = await context.bot.copy_message(
            chat_id=session["chat_id"],
            from_chat_id=session["chat_id"],
            message_id=session["original_message_id"],
            reply_markup=keyboard
        )
        session["last_message_id"] = sent.message_id
        await update.message.reply_text("Button added! Use the '+' buttons to add more or 'Done ✅' to finalize.")
    else:
        await start_message(update, context)

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.inline_query.query
    if not query.startswith("share_"):
        return
    session_id = query[6:]
    sessions = context.user_data.get("sessions", {})
    session = sessions.get(session_id)
    if not session:
        return
    result_id = uuid.uuid4().hex
    final_keyboard = build_final_keyboard(session)
    result = InlineQueryResultArticle(
        id=result_id,
        title="Share Final Message",
        input_message_content=InputTextMessageContent(session["text"] if session["text"] else "No text content"),
        description="Tap to share the final post.",
        reply_markup=final_keyboard
    )
    await update.inline_query.answer([result], cache_time=0)

async def invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("You are not authorized to use this command.")
        return
    cursor = invite_links_collection.find()
    msg = ""
    for doc in cursor:
        msg += f"Channel/Group: {doc.get('title', 'Unknown')} (ID: {doc.get('channel_id')})\nInvite Link: {doc.get('invite_link')}\n\n"
    if not msg:
        await update.message.reply_text("No invite links have been created yet.")
        return
    chunks = split_text(msg)
    for chunk in chunks:
        await update.message.reply_text(chunk)

async def main():
    application = (
        ApplicationBuilder()
        .token(bot_token)
        .concurrent_updates(True)
        .build()
    )
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, button_info_handler))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(InlineQueryHandler(inline_query_handler))
    application.add_handler(CommandHandler("invite", invite_command))
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logging.error("Exception while handling an update:", exc_info=context.error)
    application.add_error_handler(error_handler)
    await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
