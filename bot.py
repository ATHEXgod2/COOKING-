import os
import datetime
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler

# Configuration (using environment variables)
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
MONGO_URI = os.getenv("MONGO_URI")
PRIVATE_CHANNEL_ID = int(os.getenv("PRIVATE_CHANNEL_ID"))
FORCE_SUB_CHANNEL_ID = os.getenv("FORCE_SUB_CHANNEL_ID")
PORT = int(os.getenv("PORT", 8080))  # Default to 8080 if PORT is not set

# MongoDB setup
client = MongoClient(MONGO_URI)
db = client['telegram_bot']
files = db['files']
users = db['users']  # For storing user tokens and subscription status

# Shorten URL function
def shorten_url(url):
    # Implement your URL shortening logic here (using an API like bit.ly, tinyurl, etc.)
    return url  # Placeholder, replace with actual shortened URL

# Force subscription check
def check_subscription(user_id):
    member = context.bot.get_chat_member(FORCE_SUB_CHANNEL_ID, user_id)
    return member.status in ['member', 'administrator', 'creator']

# Handle the /start command
def start(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    
    if not check_subscription(user_id):
        keyboard = [
            [InlineKeyboardButton("🔔 Subscribe to Channel", url=f"https://t.me/{FORCE_SUB_CHANNEL_ID[1:]}")],
            [InlineKeyboardButton("✅ I Subscribed", callback_data='subscribed')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(
            "👋 Welcome to the bot! To continue, please subscribe to our channel.",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        update.message.reply_text(
            "🎉 Great! You're already subscribed. Please enter your token to access the bot features.",
            parse_mode=ParseMode.MARKDOWN
        )

# Handle callback queries (button presses)
def button(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    
    if query.data == 'subscribed':
        if check_subscription(user_id):
            query.edit_message_text(
                text="✅ Subscription confirmed! Please enter your token to continue.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            query.edit_message_text(
                text="🚫 It seems you're not subscribed yet. Please subscribe to the channel first.",
                parse_mode=ParseMode.MARKDOWN
            )

# Handle token verification
def verify_token(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    token = update.message.text.strip()
    
    # Assume token verification logic here (check if the token is valid and not expired)
    is_valid_token = True  # Placeholder, replace with actual token validation logic
    
    if is_valid_token:
        users.update_one({'user_id': user_id}, {'$set': {'access_until': datetime.datetime.now() + datetime.timedelta(hours=24)}}, upsert=True)
        update.message.reply_text(
            "🎫 Token verified! You now have access to all bot features for the next 24 hours.",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        update.message.reply_text(
            "❌ Invalid token. Please try again or contact support.",
            parse_mode=ParseMode.MARKDOWN
        )

# Check if user has valid access
def has_access(user_id):
    user = users.find_one({'user_id': user_id})
    if user and user.get('access_until') and user['access_until'] > datetime.datetime.now():
        return True
    return False

# Handle file uploads and generate persistent links
def handle_message(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    
    if not has_access(user_id):
        update.message.reply_text(
            "🔑 Please verify your token first to access this feature.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if user_id == OWNER_ID:
        if update.message.document or update.message.photo:
            file = update.message.document or update.message.photo[-1]
            file_id = file.file_id
            file_info = context.bot.get_file(file_id)
            
            # Generate a shortened link
            link = shorten_url(file_info.file_path)
            
            # Save the file in the private channel and get the message ID
            sent_message = context.bot.send_document(PRIVATE_CHANNEL_ID, file_id)
            message_id = sent_message.message_id
            
            # Save file data with the original file ID in MongoDB
            save_file({
                'owner_id': OWNER_ID,
                'file_id': file_id,
                'message_id': message_id,
                'link': link,
                'expires_in': datetime.datetime.now() + datetime.timedelta(hours=2)
            })

            # Reply with the generated link
            update.message.reply_text(
                f"📎 Your file link: {link}",
                parse_mode=ParseMode.MARKDOWN
            )
    else:
        update.message.reply_text(
            "🚫 You don't have permission to create links.",
            parse_mode=ParseMode.MARKDOWN
        )

# Save file data to MongoDB
def save_file(file_data):
    files.insert_one(file_data)

# Function to serve files with protection
def serve_file(update: Update, context: CallbackContext):
    file_link = update.message.text
    
    user_id = update.message.from_user.id
    
    if not has_access(user_id):
        update.message.reply_text(
            "🔑 Please verify your token first to access this file.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    file_data = files.find_one({'link': file_link})
    
    if file_data:
        current_time = datetime.datetime.now()
        if current_time > file_data['expires_in']:
            # File expired, re-fetch from the private channel
            try:
                context.bot.send_document(
                    update.message.chat_id, 
                    file_data['file_id'], 
                    protect_content=True
                )
                # Re-set expiration time
                files.update_one(
                    {'_id': file_data['_id']},
                    {'$set': {'expires_in': datetime.datetime.now() + datetime.timedelta(hours=2)}}
                )
            except Exception as e:
                update.message.reply_text(
                    "⚠️ Failed to retrieve the file. Please contact the owner.",
                    parse_mode=ParseMode.MARKDOWN
                )
                print(f"Error fetching file: {e}")
        else:
            # File still valid, serve it directly
            context.bot.send_document(
                update.message.chat_id, 
                file_data['file_id'], 
                protect_content=True
            )
    else:
        update.message.reply_text(
            "❌ Invalid link or the file no longer exists.",
            parse_mode=ParseMode.MARKDOWN
        )

# Cleanup job to delete files after 2 hours
def clean_up_files(context: CallbackContext):
    current_time = datetime.datetime.now()
    expired_files = files.find({'expires_in': {'$lt': current_time}})
    
    for file in expired_files:
        try:
            # Attempt to delete the file from the bot's storage (but not from the private channel)
            context.bot.delete_message(PRIVATE_CHANNEL_ID, file['message_id'])
        except Exception as e:
            print(f"Failed to delete file: {e}")
        
        # Update the file record to remove the current file ID
        files.update_one({'_id': file['_id']}, {'$unset': {'file_id': ''}})

    print(f"Cleaned up {expired_files.count()} expired files at {current_time}")

# Broadcast function for the owner to send messages to all users
def broadcast(update: Update, context: CallbackContext):
    if update.message.from_user.id == OWNER_ID:
        message = update.message.text.split(' ', 1)[1]
        user_ids = users.distinct('user_id')
        for user_id in user_ids:
            try:
                context.bot.send_message(chat_id=user_id, text=message)
            except Exception as e:
                print(f"Failed to send message to {user_id}: {e}")

# Main function to start the bot
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, serve_file))
    dp.add_handler(MessageHandler(Filters.document | Filters.photo, handle_message))
    dp.add_handler(CommandHandler("broadcast", broadcast))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, verify_token))

    # Schedule cleanup job to delete files every hour
    job_queue = updater.job_queue
    job_queue.run_repeating(clean_up_files, interval=3600, first=0)

    # Start the bot
    updater.start_polling(port=PORT)
    updater.idle
