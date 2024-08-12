import os
import datetime
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Load environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
OWNER_ID = int(os.getenv("OWNER_ID"))
MONGO_URI = os.getenv("MONGO_URI")
PRIVATE_CHANNEL_ID = int(os.getenv("PRIVATE_CHANNEL_ID"))
FORCE_SUB_CHANNEL_ID = int(os.getenv("FORCE_SUB_CHANNEL_ID"))
PORT = int(os.getenv("PORT", 8080))  # Default to 8080 if PORT is not set

# Initialize Pyrogram Client
app = Client("bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

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
async def check_subscription(user_id):
    member = await app.get_chat_member(FORCE_SUB_CHANNEL_ID, user_id)
    return member.status in ['member', 'administrator', 'creator']

@app.on_message(filters.command("start"))
async def start(client, message):
    user_id = message.from_user.id
    
    if not await check_subscription(user_id):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔔 Subscribe to Channel", url=f"https://t.me/{FORCE_SUB_CHANNEL_ID}")],
            [InlineKeyboardButton("✅ I Subscribed", callback_data='subscribed')]
        ])
        await message.reply(
            "👋 Welcome to the bot! To continue, please subscribe to our channel.",
            reply_markup=keyboard
        )
    else:
        await message.reply("🎉 Great! You're already subscribed. Please enter your token to access the bot features.")

@app.on_callback_query()
async def button(client, callback_query):
    user_id = callback_query.from_user.id
    
    if callback_query.data == 'subscribed':
        if await check_subscription(user_id):
            await callback_query.message.edit(
                text="✅ Subscription confirmed! Please enter your token to continue."
            )
        else:
            await callback_query.message.edit(
                text="🚫 It seems you're not subscribed yet. Please subscribe to the channel first."
            )

@app.on_message(filters.text & ~filters.command)
async def verify_token(client, message):
    user_id = message.from_user.id
    token = message.text.strip()
    
    # Assume token verification logic here (check if the token is valid and not expired)
    is_valid_token = True  # Placeholder, replace with actual token validation logic
    
    if is_valid_token:
        users.update_one({'user_id': user_id}, {'$set': {'access_until': datetime.datetime.now() + datetime.timedelta(hours=24)}}, upsert=True)
        await message.reply("🎫 Token verified! You now have access to all bot features for the next 24 hours.")
    else:
        await message.reply("❌ Invalid token. Please try again or contact support.")

# Check if user has valid access
def has_access(user_id):
    user = users.find_one({'user_id': user_id})
    return user and user.get('access_until') and user['access_until'] > datetime.datetime.now()

@app.on_message(filters.document | filters.photo)
async def handle_message(client, message):
    user_id = message.from_user.id
    
    if not has_access(user_id):
        await message.reply("🔑 Please verify your token first to access this feature.")
        return
    
    if user_id == OWNER_ID:
        if message.document or message.photo:
            file = message.document or message.photo[-1]
            file_id = file.file_id
            file_info = await client.get_file(file_id)
            
            # Generate a shortened link
            link = shorten_url(file_info.file_path)
            
            # Save the file in the private channel and get the message ID
            sent_message = await client.send_document(PRIVATE_CHANNEL_ID, file_id)
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
            await message.reply(f"📎 Your file link: {link}")
    else:
        await message.reply("🚫 You don't have permission to create links.")

# Save file data to MongoDB
def save_file(file_data):
    files.insert_one(file_data)

# Serve files with protection
@app.on_message(filters.text & ~filters.command)
async def serve_file(client, message):
    file_link = message.text
    user_id = message.from_user.id
    
    if not has_access(user_id):
        await message.reply("🔑 Please verify your token first to access this file.")
        return
    
    file_data = files.find_one({'link': file_link})
    
    if file_data:
        current_time = datetime.datetime.now()
        if current_time > file_data['expires_in']:
            # File expired, re-fetch from the private channel
            try:
                await client.send_document(
                    message.chat.id, 
                    file_data['file_id'], 
                    protect_content=True
                )
                # Re-set expiration time
                files.update_one(
                    {'_id': file_data['_id']},
                    {'$set': {'expires_in': datetime.datetime.now() + datetime.timedelta(hours=2)}}
                )
            except Exception as e:
                await message.reply("⚠️ Failed to retrieve the file. Please contact the owner.")
                print(f"Error fetching file: {e}")
        else:
            # File still valid, serve it directly
            await client.send_document(
                message.chat.id, 
                file_data['file_id'], 
                protect_content=True
            )
    else:
        await message.reply("❌ Invalid link or the file no longer exists.")

# Cleanup job to delete files after 2 hours
async def clean_up_files():
    current_time = datetime.datetime.now()
    expired_files = files.find({'expires_in': {'$lt': current_time}})
    
    for file in expired_files:
        try:
            await app.delete_messages(PRIVATE_CHANNEL_ID, file['message_id'])
        except Exception as e:
            print(f"Failed to delete file: {e}")
        
        # Update the file record to remove the current file ID
        files.update_one({'_id': file['_id']}, {'$unset': {'file_id': ''}})

    print(f"Cleaned up {expired_files.count()} expired files at {current_time}")

# Broadcast function for the owner to send messages to all users
@app.on_message(filters.command("broadcast") & filters.user(OWNER_ID))
async def broadcast(client, message):
    if len(message.command) > 1:
        broadcast_message = message.text.split(' ', 1)[1]
        user_ids = users.distinct('user_id')
        for user_id in user_ids:
            try:
                await client.send_message(chat_id=user_id, text=broadcast_message)
            except Exception as e:
                print(f"Failed to send message to {user_id}: {e}")

# Main function to start the bot
if __name__ == "__main__":
    scheduler = AsyncIOScheduler()
    scheduler.add_job(clean_up_files, "interval", hours=1)
    scheduler.start()

    app.run()
