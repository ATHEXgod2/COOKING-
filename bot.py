# bot.py

from pyrogram import Client, filters
from pymongo import MongoClient
from config import *
import requests

client = MongoClient(MONGO_URI)
db = client["file_sharing_bot"]
users_col = db["users"]
files_col = db["files"]

app = Client("file_sharing_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Force subscription check function
def is_subscribed(client, user_id):
    try:
        member = client.get_chat_member(FORCE_SUB_CHANNEL, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# Welcome and force subscription check
@app.on_message(filters.command("start") & filters.private)
def start(client, message):
    user_id = message.chat.id
    if not is_subscribed(client, user_id):
        client.send_message(chat_id=user_id, text=f"⚠️ Please join [our channel]({FORCE_SUB_LINK}) to use this bot.", parse_mode="markdown")
        return
    
    add_user(user_id)
    message.reply("Welcome to the file-sharing bot!")

# Store files (only for subscribed users)
@app.on_message(filters.command("store_file") & filters.private)
def store_file(client, message):
    user_id = message.chat.id
    if not is_subscribed(client, user_id):
        client.send_message(chat_id=user_id, text=f"⚠️ Please join [our channel]({FORCE_SUB_LINK}) to use this bot.", parse_mode="markdown")
        return
    
    if message.document:
        file_id = message.document.file_id
        files_col.insert_one({"file_id": file_id, "stored_by": user_id})
        client.send_message(PRIVATE_CHANNEL_ID, f"New file: {file_id}")
        message.reply("File stored successfully!")

# Send files (only for subscribed users)
@app.on_message(filters.command("get_file") & filters.private)
def send_file(client, message):
    user_id = message.chat.id
    if not is_subscribed(client, user_id):
        client.send_message(chat_id=user_id, text=f"⚠️ Please join [our channel]({FORCE_SUB_LINK}) to use this bot.", parse_mode="markdown")
        return
    
    file_data = files_col.find_one()  # Modify query as needed
    if file_data:
        client.send_document(chat_id=user_id, document=file_data["file_id"])

if __name__ == "__main__":
    app.run()
