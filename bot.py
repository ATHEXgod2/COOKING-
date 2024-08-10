# bot.py

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pymongo import MongoClient
from datetime import datetime, timedelta
import requests
import threading
import time

client = MongoClient(MONGO_URI)
db = client["file_sharing_bot"]
users_col = db["users"]
files_col = db["files"]
tokens_col = db["tokens"]

app = Client("file_sharing_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Function to shorten URLs using Public Earn (for generating tokens)
def shorten_link_public_earn(long_url):
    headers = {
        'Authorization': f'Bearer {PUBLIC_EARN_API_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {'url': long_url}
    response = requests.post(PUBLIC_EARN_API_URL, headers=headers, json=payload)
    
    if response.status_code == 200:
        data = response.json()
        return data.get('short_url')
    return None

# Function to generate and store token with expiry
def generate_and_store_token(user_id):
    token = "unique_generated_token"  # Replace with your token generation logic
    expiration_time = datetime.utcnow() + timedelta(hours=24)
    tokens_col.insert_one({"user_id": user_id, "token": token, "expires_at": expiration_time})
    return token

# Function to check if a token is valid and not expired
def is_token_valid(user_id, token):
    token_data = tokens_col.find_one({"user_id": user_id, "token": token})
    if token_data:
        if datetime.utcnow() < token_data["expires_at"]:
            return True
        else:
            tokens_col.delete_one({"user_id": user_id, "token": token})  # Remove expired token
    return False

# Function to check if a file should be deleted
def auto_delete_files():
    while True:
        now = datetime.utcnow()
        expiration_time = now - timedelta(hours=2)
        files_col.delete_many({"access_time": {"$lt": expiration_time}})
        time.sleep(3600)  # Sleep for 1 hour before checking again

# Force subscription check function
def is_subscribed(client, user_id):
    try:
        member = client.get_chat_member(FORCE_SUB_CHANNEL, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# Check if the user is the bot owner
def is_owner(user_id):
    return user_id in BOT_OWNER_IDS

# Start command handler with welcome message and inline keyboard
@app.on_message(filters.command("start") & filters.private)
def start(client, message):
    user_id = message.chat.id
    if not is_subscribed(client, user_id):
        ad_watch_link = shorten_link_public_earn("https://yourwebsite.com/watch_ad")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Watch Ad", url=ad_watch_link)],
            [InlineKeyboardButton("Help", callback_data="help")]
        ])
        client.send_message(
            chat_id=user_id,
            text=f"⚠️ To access the bot for 24 hours, please watch the ad:\n\n[Watch Ad]({ad_watch_link})",
            reply_markup=keyboard,
            parse_mode="markdown"
        )
        return
    
    add_user(user_id)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Store a File", callback_data="store_file")],
        [InlineKeyboardButton("Get a File", callback_data="get_file")],
        [InlineKeyboardButton("Help", callback_data="help")]
    ])
    message.reply(
        text="Welcome to the file-sharing bot! Choose an option below:",
        reply_markup=keyboard,
        parse_mode="markdown"
    )

# Handle button presses for various actions
@app.on_callback_query()
def handle_callback(client, callback_query):
    user_id = callback_query.from_user.id
    query_data = callback_query.data

    if query_data == "store_file":
        client.send_message(chat_id=user_id, text="To store a file, please send the file directly here.")
    elif query_data == "get_file":
        client.send_message(chat_id=user_id, text="To get a file, please use the command with the file ID.")
    elif query_data == "help":
        client.send_message(
            chat_id=user_id,
            text="Here’s how you can use the bot:\n\n"
                 "/store_file - Store a file (requires a token if not subscribed)\n"
                 "/get_file - Get a stored file (requires a token if not subscribed)\n"
                 "Join our [channel]({FORCE_SUB_LINK}) to skip token verification.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Channel", url=FORCE_SUB_LINK)]
            ]),
            parse_mode="markdown"
        )

# Automatically generate a token for the bot owner on non-command messages
@app.on_message(filters.private & ~filters.command)
def auto_generate_token(client, message):
    user_id = message.chat.id
    if is_owner(user_id):
        token = generate_and_store_token(user_id)
        shortened_link = shorten_link_public_earn(f"https://yourwebsite.com/verify?token={token}")
        
        if shortened_link:
            client.send_message(chat_id=user_id, text=f"Your token verification link: {shortened_link}")
        else:
            client.send_message(chat_id=user_id, text="Failed to generate a shortened link.")

# Store files (subscription bypasses token check)
@app.on_message(filters.command("store_file") & filters.private)
def store_file(client, message):
    user_id = message.chat.id
    if not is_subscribed(client, user_id):
        # Token verification for non-subscribed users
        token = message.text.split(' ', 1)[1] if len(message.text.split(' ', 1)) > 1 else None
        if not token or not is_token_valid(user_id, token):
            client.send_message(chat_id=user_id, text="⚠️ Invalid or expired token. Please watch the ad again for a new token.", parse_mode="markdown")
            return
    
    if message.document:
        file_id = message.document.file_id
        access_time = datetime.utcnow()
        files_col.insert_one({"file_id": file_id, "stored_by": user_id, "access_time": access_time})
        client.send_message(PRIVATE_CHANNEL_ID, f"New file stored: {file_id}")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Store Another File", callback_data="store_file")],
            [InlineKeyboardButton("Help", callback_data="help")]
        ])
        message.reply("File stored successfully! You can store another file or get help below:", reply_markup=keyboard)

# Send files (subscription bypasses token check)
@app.on_message(filters.command("get_file") & filters.private)
def send_file(client, message):
    user_id = message.chat.id
    if not is_subscribed(client, user_id):
        # Token verification for non-subscribed users
        token = message.text.split(' ', 1)[1] if len(message.text.split(' ', 1)) > 1 else None
        if not token or not is_token_valid(user_id, token):
            client.send_message(chat_id=user_id, text="⚠️ Invalid or expired token. Please watch the ad again for a new token.", parse_mode="markdown")
            return
    
    file_data = files_col.find_one({"stored_by": user_id})  # Modify query as needed
    if file_data:
        client.send_document(chat_id=user_id, document=file_data["file_id"])
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Get Another File", callback_data="get_file")],
            [InlineKeyboardButton("Help", callback_data="help")]
        ])
        message.reply("Here is your file! You can get another file or get help below:", reply_markup=keyboard)
    else:
        client.send_message(chat_id=user_id, text="No files found. Please store some files first.")

if __name__ == "__main__":
    # Start the auto-delete thread
    threading.Thread(target=auto_delete_files, daemon=True).start()
    app.run()
