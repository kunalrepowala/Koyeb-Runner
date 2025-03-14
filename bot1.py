import nest_asyncio
nest_asyncio.apply()

import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# Bot configuration
BOT_TOKEN = "7498922436:AAFpr3j3RuzDrLaxmaEMBXvjfuLq1KzUtV8"
ADMIN_ID = 6773787379

# Global list of websites and a dictionary to store status info
websites = ["https://google.com"]
website_status = {}  # {website: {"last_status": str, "last_open": datetime, "next_open": datetime}}

# Conversation state for adding website
WAITING_FOR_URL = 1

async def check_websites(session: aiohttp.ClientSession):
    """
    Background task: Every 10 seconds, attempts to open each website in the list.
    Updates website_status with the HTTP status or error message.
    """
    global websites, website_status
    while True:
        now = datetime.now()
        for site in websites:
            try:
                async with session.get(site) as response:
                    status_code = response.status
                    website_status[site] = {
                        "last_status": f"HTTP {status_code}",
                        "last_open": now,
                        "next_open": now + timedelta(seconds=10),
                    }
            except Exception as e:
                website_status[site] = {
                    "last_status": f"Error: {str(e)}",
                    "last_open": now,
                    "next_open": now + timedelta(seconds=10),
                }
        await asyncio.sleep(10)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /status command: Replies with the status of each website.
    Only responds if the sender is the admin.
    """
    if update.effective_user.id != ADMIN_ID:
        return
    msg = "Website status:\n"
    for site, stat in website_status.items():
        last_status = stat.get("last_status", "N/A")
        last_open = stat.get("last_open")
        next_open = stat.get("next_open")
        last_open_str = last_open.strftime("%Y-%m-%d %H:%M:%S") if last_open else "N/A"
        next_open_str = next_open.strftime("%Y-%m-%d %H:%M:%S") if next_open else "N/A"
        msg += (f"{site}:\n"
                f"   Last Status: {last_status}\n"
                f"   Last Open: {last_open_str}\n"
                f"   Next Open: {next_open_str}\n")
    await update.message.reply_text(msg)

async def website(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /website command: Shows current websites with an inline button to add a new website.
    Only responds if the sender is the admin.
    """
    if update.effective_user.id != ADMIN_ID:
        return
    keyboard = [[InlineKeyboardButton("Add Website", callback_data="add_website")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "Current websites:\n" + "\n".join(websites)
    await update.message.reply_text(text, reply_markup=reply_markup)

async def add_website_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Callback for the "Add Website" inline button.
    Prompts the admin to send the website link.
    """
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Please send the website link you want to add:")
    return WAITING_FOR_URL

async def add_website_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Receives the website link from the admin and adds it to the websites list.
    """
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    url = update.message.text.strip()
    if url not in websites:
        websites.append(url)
        await update.message.reply_text(f"Website {url} added successfully!")
    else:
        await update.message.reply_text(f"Website {url} is already in the list.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Cancels the add website conversation.
    """
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

async def delete_website(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /delete command: Deletes the specified website from the list.
    The admin should send the command as /delete {website_url}.
    Then, the bot resends the updated website list.
    """
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /delete {website_url}")
        return
    # Extract the website URL (all arguments combined)
    url = " ".join(context.args).strip()
    if url in websites:
        websites.remove(url)
        # Remove status record if exists
        website_status.pop(url, None)
        await update.message.reply_text(f"Website {url} removed successfully!")
    else:
        await update.message.reply_text(f"Website {url} not found in the list.")
    
    # Resend the updated website list
    keyboard = [[InlineKeyboardButton("Add Website", callback_data="add_website")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "Current websites:\n" + "\n".join(websites)
    await update.message.reply_text(text, reply_markup=reply_markup)

async def main():
    # Set up logging
    logging.basicConfig(level=logging.INFO)
    
    # Build the application
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Conversation handler for adding a website
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_website_callback, pattern="^add_website$")],
        states={
            WAITING_FOR_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_website_url)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Register command and conversation handlers
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("website", website))
    application.add_handler(CommandHandler("delete", delete_website))

    # Create an aiohttp session and start the background task
    session = aiohttp.ClientSession()
    asyncio.create_task(check_websites(session))

    # Start the bot
    await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
