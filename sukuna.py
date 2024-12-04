import pyrogram
import time
import asyncio
import json
import tgcrypto
import os
import aiohttp
import parso
import requests
import openai
import pathlib
from pathlib import Path
import glob
import pytz
import re
from collections import deque
import logging
from pyrogram.errors import RPCError
import random
from random import choice
from random import choices
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler, Updater
from datetime import datetime, timedelta
from pyrogram.enums import ChatMemberStatus
from googletrans import Translator, LANGUAGES
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from pyrogram import Client

# Load environment variables from the .env file
load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
API_TOKEN = os.getenv("API_TOKEN")


# Initialize the Pyrogram client
app = Client("my_bot", api_id=(API_ID), api_hash=API_HASH, bot_token=API_TOKEN)

GEMINI_API_TOKEN = "AIzaSyDdBvqeAkLkOBK53JGenbunDh8Gy4RjwMI"  # Replace with your actual API token
# Gemini API endpoint
GEMINI_API_URL = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_TOKEN}'

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory storage
user_hp = {}
user_points = {}
user_cooldowns = {}
user_barrier_status = {}
user_protect_status={}
reverse_cooldowns={}
medical_cooldowns={}
counter_cooldowns = {}
hospital_cooldowns = {}  # New cooldown dictionary for users with 0 HP


# Dictionary to store warnings for each user in each chat
user_warnings = {}  # {chat_id: {user_id: warn_count}}

# Global storage for rankings
group_rankings = {}

# Scheduler for resetting rankings at midnight IST
scheduler = BackgroundScheduler()
scheduler.start()

# Constants
TOTAL_HP = 500  # Total health points for users
COOLDOWN_CURSE = timedelta(minutes=10)  # 10 minutes cooldown for curse
BARRIER_COOLDOWN = timedelta(hours=3)  # Barrier cooldown
RESET_COOLDOWN = timedelta(minutes=30)  # Reset cooldown
COUNTER_COOLDOWN = timedelta(minutes=10)  # Cooldown for COUNTER action
HOSPITAL_COOLDOWN = timedelta(hours=25)
PROTECT_COOLDOWN= timedelta(minutes=45)
REVERSE_COOLDOWN= timedelta(minutes=8)
MEDICAL_COOLDOWN= timedelta(hours=20)
COOLDOWN_SOUL = timedelta(minutes=8)

# File paths
user_data_file = "user_data.json"
domain_folder = "DOMAIN"
cursed_folder = "CURSED"
counter_folder = "COUNTER"
started_folder = "STARTED"
bankai_folder= "BANKAI"
reverse_folder= "REVERSE"
soul_folder="SOUL"


# Folder paths
STAR_FOLDERS = {
    1: pathlib.Path("1STAR"),
    2: pathlib.Path("2STAR"),
    3: pathlib.Path("3STAR"),
    4: pathlib.Path("4STAR"),
    5: pathlib.Path("5STAR")
}

# Cooldown and user data
WEB_COOLDOWN = 30 * 60  # 30 minutes in seconds

CHARACTER_BASE_DIR = "characters"  # Base directory for star folders
WEB_COOLDOWN = 30 * 60  # 30 minutes in seconds
user_data = {}  # To store user information like cooldowns and captured characters

# Initialize team dictionaries
team_scores = {
    "team_sun": {
        "players": deque(),  # Queue to handle turn rotation
        "score": 0
    },
    "team_moon": {
        "players": deque(),
        "score": 0
    }
}

# Dictionary to hold user points per chat
chat_user_points = {}  # {chat_id: {user_id: points}}

# Dictionary to store Sukuna mode states
sukuna_mode = {}

def get_all_image_files(folder_path):
    return [
        str(file)
        for file in folder_path.glob("*")
        if file.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]
    ]


# Utility functions
def get_random_image(folder):
    """Return a random image path from the specified folder."""
    images = [f for f in os.listdir(folder) if f.endswith('.jpg')]
    if images:
        return os.path.join(folder, random.choice(images))
    return None

# Function to format remaining time
def format_remaining_time(cooldown_end_time):
    remaining_time = cooldown_end_time - datetime.now()
    minutes, seconds = divmod(remaining_time.seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"

def is_on_cooldown(user_id, command):
    """Check if the user is on cooldown for a specific command."""
    cooldowns = user_cooldowns.get(user_id, {})
    if isinstance(cooldowns, dict):  # Ensure cooldowns is a dictionary
        command_cooldown = cooldowns.get(command, None)
        if command_cooldown is not None and datetime.now().timestamp() < command_cooldown:
            return True
    return False




def activate_barrier(user_id):
    if user_id not in user_barrier_status:
        user_barrier_status[user_id] = {"barrier_active": False, "last_barrier_use": None}
    
    user_barrier_status[user_id]["barrier_active"] = True
    user_barrier_status[user_id]["last_barrier_use"] = datetime.now()



def set_hospital_cooldown(user_id):
    hospital_cooldowns[user_id] = (datetime.now() + HOSPITAL_COOLDOWN).timestamp()

def is_in_hospital(user_id):
    if user_id in hospital_cooldowns:
        cooldown_end = datetime.fromtimestamp(hospital_cooldowns[user_id])
        if datetime.now() < cooldown_end:
            return True, cooldown_end
    return False, None


def set_cooldown(user_id, command, duration):
    if user_id not in user_cooldowns:
        user_cooldowns[user_id] = {}  # Initialize as a dictionary
    user_cooldowns[user_id][command] = (datetime.now() + duration).timestamp()



# Get remaining cooldown time
def get_cooldown_remaining_time(user_id, command):
    cooldown_end = user_cooldowns.get(user_id, {}).get(command, None)
    if cooldown_end:
        remaining_time = cooldown_end - datetime.now()
        if remaining_time.total_seconds() > 0:
            return remaining_time
    return None


def set_counter_cooldown(user_id):
    counter_cooldowns[user_id] = (datetime.now() + COUNTER_COOLDOWN).timestamp()

def is_on_counter_cooldown(user_id):
    if user_id in counter_cooldowns:
        cooldown_end = datetime.fromtimestamp(counter_cooldowns[user_id])
        if datetime.now() < cooldown_end:
            return True
    return False


# Protect (formerly Barrier) activation logic
def activate_protect(user_id):
    if user_id not in user_protect_status:
        user_protect_status[user_id] = {"protect_active": False, "last_protect_use": None}
    
    user_protect_status[user_id]["protect_active"] = True
    user_protect_status[user_id]["last_protect_use"] = datetime.now()

# Medical cooldown management
def set_medical_cooldown(user_id):
    medical_cooldowns[user_id] = (datetime.now() + MEDICAL_COOLDOWN).timestamp()

def is_in_medical_cooldown(user_id):
    if user_id in medical_cooldowns:
        cooldown_end = datetime.fromtimestamp(medical_cooldowns[user_id])
        if datetime.now() < cooldown_end:
            return True, cooldown_end
    return False, None

# General cooldown management for commands
def set_cooldown(user_id, command, duration):
    if user_id not in user_cooldowns:
        user_cooldowns[user_id] = {}  # Initialize as a dictionary
    user_cooldowns[user_id][command] = (datetime.now() + duration).timestamp()

# Get remaining cooldown time for a command
def get_cooldown_remaining_time(user_id, command):
    cooldown_end = user_cooldowns.get(user_id, {}).get(command, None)
    if cooldown_end:
        remaining_time = cooldown_end - datetime.now()
        if remaining_time.total_seconds() > 0:
            return remaining_time
    return None

# Reverse cooldown management
def set_reverse_cooldown(user_id):
    reverse_cooldowns[user_id] = (datetime.now() + COUNTER_COOLDOWN).timestamp()

def is_on_reverse_cooldown(user_id):
    if user_id in reverse_cooldowns:
        cooldown_end = datetime.fromtimestamp(reverse_cooldowns[user_id])
        if datetime.now() < cooldown_end:
            return True
    return False


# Function to load JSON data
def load_json_data(file_path, default_data=None):
    """Load JSON data from a file or return default data if the file is missing or empty."""
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        with open(file_path, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                print(f"Error: JSON file {file_path} is corrupted. Initializing empty data.")
                return default_data if default_data is not None else {}
    return default_data if default_data is not None else {}

# Function to save JSON data
def save_json_data(file_path, data):
    """Save JSON data to a file."""
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)

# Load data from JSON files
def load_data():
    global user_data
    user_data = load_json_data(user_data_file, default_data={})

# Get a random image from the specified folder
def get_random_image(folder):
    """Get a random image from the specified folder."""
    images = [f for f in os.listdir(folder) if f.endswith('.jpg')]
    return os.path.join(folder, random.choice(images)) if images else None

def initialize_user_data(user_id):
    if user_id not in user_hp:
        user_hp[user_id] = TOTAL_HP
    if user_id not in user_points:
        user_points[user_id] = 0
    if user_id not in user_cooldowns:
        user_cooldowns[user_id] = {}  # Initialize as an empty dictionary
    if user_id not in user_barrier_status:
        user_barrier_status[user_id] = {"barrier_active": False, "barrier_lift_time": None, "last_barrier_use": None}



# Check if a user is an admin in the group
async def is_admin(client, chat_id, user_id):
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except Exception as e:
        print(f"Error checking admin status: {e}")
        return False


# Start a 26-hour cooldown
def start_26_hour_cooldown(user_id):
    user_cooldowns[user_id] = datetime.now() + timedelta(hours=26)  # 26 hours


def reset_rankings():
    global group_rankings
    if not group_rankings:
        return
    
    # Sort rankings
    sorted_rankings = sorted(group_rankings.items(), key=lambda x: x[1], reverse=True)
    
    # Top 2 users
    top_users = sorted_rankings[:3]
    announcement = ["🎖️ **Daily Rankings** 🎖️\n"]
    
    for rank, (user_id, stars) in enumerate(top_users, start=1):
        try:
            user = app.get_users(user_id)  # Fetch user details
            user_mention = f"[{user.first_name}](tg://user?id={user_id})"  # Clickable mention
        except:
            user_mention = f"User {user_id}"  # Fallback if user info can't be fetched
        announcement.append(f"{rank}. {user_mention} - **{stars} Stars**")

    announcement.append("\n⭐ Rankings have been reset. Start earning stars again!")
    
    # Send announcement
    app.send_message("@DemonSlayerGC", "\n".join(announcement))
    
    # Reset rankings
    group_rankings = {}

    # Reset user stores
    for user_id in user_data.keys():
        user_data[user_id]["store"] = []  # Clear the character list
        user_data[user_id]["reset"] = True  # Mark reset flag for /home

# Schedule the reset at 12:00 AM IST daily
scheduler.add_job(reset_rankings, trigger="cron", hour=00, minute=00)  # 18:30 UTC = 12:00 AM IST


def get_random_mp4(folder_path):
    """Get a random .mp4 file from a given folder."""
    mp4_files = [f for f in os.listdir(folder_path) if f.endswith('.mp4')]
    if not mp4_files:
        return None
    return os.path.join(folder_path, random.choice(mp4_files))

def reset_team_scores():
    """Reset scores and clear players for both teams."""
    team_scores["team1"]["score"] = 0
    team_scores["team2"]["score"] = 0
    team_scores["team1"]["players"].clear()
    team_scores["team2"]["players"].clear()
    team_scores["team1"]["current_turn"] = 0
    team_scores["team2"]["current_turn"] = 0

# Load data at startup
load_data()







# List of random texts for the caption
random_texts = [
    "Where are the people?! The women?! What a wonderful age this is! Women and children are spawning like maggots! Marvelous! It'll be a massacre!",
    "You Want Praise Now?!",
    "A system that isn't based purely on strength is boring if you ask me. When I make this kid's body mine, you'll be the first one I kill.",
    "Did you think a measly one or two fingers would grant you the right to order me around?",
    "I'll show you what real jujutsu is.",
    "You dare touch my soul? Since we shared a laugh at the brat's expense, I'll only allow it once. There won't be a second time.",
    "Know your place, you fool.",
    "Stand proud. You are strong."
]
@app.on_message(filters.command("start"))
async def start(client, message):
    # Get a random .mp4 file from the folder
    video_path = get_random_mp4(started_folder)
    
    # Check if a video file was found
    if not video_path:
        await message.reply_text("Error: No .mp4 files found in the STARTED folder.")
        return

    # Select a random text for the caption
    caption = random.choice(random_texts)
    
    # Send the .mp4 file with a random caption
    await message.reply_video(
        video=video_path,
        caption=caption
    )




@app.on_message(filters.command("arise") & filters.chat("@DemonSlayerGC"))
async def arise(client, message):
    global group_rankings
    user_id = message.from_user.id
    user_mention = f"[{message.from_user.first_name}](tg://user?id={user_id})"

    # Check cooldown for the web command, which will be about 30 minutes
    last_used = user_data.get(user_id, {}).get("last_web", 0)
    if time.time() - last_used < WEB_COOLDOWN:
        remaining_time = WEB_COOLDOWN - (time.time() - last_used)
        await message.reply_text(
            f"⏳ {user_mention}, you need to wait {int(remaining_time // 60)} minutes and {int(remaining_time % 60)} seconds to use /arise again."
        )
        return

    # Define star folder and emoji mapping
    star_probabilities = [20, 20, 30, 20, 10]
    star_level = random.choices(range(1, 6), weights=star_probabilities, k=1)[0]
    star_folder = STAR_FOLDERS[star_level]
    star_emojis = {
        1: "🟢",  # Green Emoji
        2: "🔵",  # Blue Emoji
        3: "⚫",  # Black Emoji
        4: "🟣",  # Purple Emoji
        5: "🟡",  # Golden Emoji
    }
    emoji = star_emojis.get(star_level, "⭐")  # Default to star emoji

    # Select random character
    if not os.listdir(star_folder):
        await message.reply_text(f"No characters available in the {star_level} Star folder.")
        return

    character_file = random.choice(os.listdir(star_folder))
    character_name = os.path.splitext(character_file)[0]

    # Store character
    user_store = user_data.setdefault(user_id, {}).setdefault("store", [])
    user_store.append((character_name, star_level))
    user_data[user_id]["last_web"] = time.time()

    # Update rankings
    group_rankings[user_id] = group_rankings.get(user_id, 0) + star_level

    # Send character
    character_path = os.path.join(star_folder, character_file)
    with open(character_path, "rb") as character_image:
        await message.reply_photo(
            character_image,
            caption=(
                f"🎉 Congratulations {user_mention}!\n\n"
                f"{emoji} You managed to arise {emoji}\n**{character_name}** ({star_level} Star)!"
            )
        )

@app.on_message(filters.command("home"))
async def home(client, message):
    user_id = message.from_user.id
    user_mention = f"[{message.from_user.first_name}](tg://user?id={user_id})"

    # Get user characters
    user_store = user_data.get(user_id, {}).get("store", [])
    if not user_store:
        await message.reply_text(
            f"🏠 {user_mention}, your home is empty. Use /arise to build characters!"
        )
        return

    # Define emoji mapping
    star_emojis = {
        1: "🟢",  # Green Emoji
        2: "🔵",  # Blue Emoji
        3: "⚫",  # Black Emoji
        4: "🟣",  # Purple Emoji
        5: "🟡",  # Golden Emoji
    }

    # Display characters and total stars
    total_stars = sum(star for _, star in user_store)
    response = [f"🏠 {user_mention}, here are your characters:\n"]
    for idx, (character_name, star_level) in enumerate(user_store, start=1):
        emoji = star_emojis.get(star_level, "⭐")  # Default to star emoji
        response.append(f"{idx}. {emoji} {character_name} ({star_level} Star)")

    response.append(f"\n✨ Total Stars: {total_stars}")
    await message.reply_text("\n".join(response))



@app.on_message(filters.command("ranks") & filters.chat("@DemonSlayerGC"))
async def ranks(client, message):
    global group_rankings
    user_id = message.from_user.id

    if not group_rankings:
        await message.reply_text("📜 Rankings are empty. Be the first to start earning stars with /arise!")
        return

    # Sort rankings by star count in descending order
    sorted_rankings = sorted(group_rankings.items(), key=lambda x: x[1], reverse=True)
    response = ["📜 **Current Rankings** 📜\n"]

    # Initialize rank categories with emojis
    categories = {
    "Z+ Rank 🏆": (1, 3),         # Trophy Emoji
    "SSS+ Rank 🔥": (4, 7),      # Fire Emoji
    "SS Rank 🌟": (8, 12),       # Star Emoji
    "S Rank 💎": (13, 16),       # Gem Emoji
    "A Rank 🥇": (17, 20),       # Gold Medal Emoji
    "B Rank 🥈": (21, 24),       # Silver Medal Emoji
    "C Rank 🥉": (25, 28),       # Bronze Medal Emoji
    "D Rank ⚙️": (29, 30),       # Gear Emoji
    "Newbie Rank 🌱": (31, float("inf")),  # Seedling Emoji
}

    # Group users into ranks
    for category, (start, end) in categories.items():
        rank_group = [
            (rank, uid, stars)
            for rank, (uid, stars) in enumerate(sorted_rankings, start=1)
            if start <= rank <= end
        ]
        if rank_group:
            response.append(f"**{category}**")
            for rank, uid, stars in rank_group:
                try:
                    user = await client.get_users(uid)
                    user_name = user.first_name
                except:
                    user_name = f"User {uid}"
                response.append(f"{rank}. {user_name} - **{stars} Stars**")
            response.append("")  # Add spacing between categories

    # Find and append the current user's rank
    user_rank = next((rank for rank, (uid, _) in enumerate(sorted_rankings, start=1) if uid == user_id), None)
    if user_rank:
        user_stars = group_rankings.get(user_id, 0)
        user_mention = f"[{message.from_user.first_name}](tg://user?id={user_id})"
        response.append(
            f"\n🧑‍🎓 {user_mention}, you are ranked **#{user_rank}** with **{user_stars} Stars**."
        )

    # Send the response message
    await message.reply_text("\n".join(response))



# /warn command - Admins only
@app.on_message(filters.command("warn") & filters.group)
async def warn_user(client, message: Message):
    if not message.reply_to_message:
        await message.reply_text("Reply to someone so that I can curse them!")
        return

    chat_id = message.chat.id
    user_id = message.reply_to_message.from_user.id
    user_status = await client.get_chat_member(chat_id, user_id)
    admin_status = await client.get_chat_member(chat_id, message.from_user.id)

    # Check if the command issuer is an admin
    if admin_status.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        await message.reply_text("Admins have power to use my Techniques!")
        return

    # Check if the target user is an admin
    if user_status.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        await message.reply_text("They hold higher authorities to match my power. I cannot use techniques on Admin.")
        return

    # Increment the user's warn count
    if chat_id not in user_warnings:
        user_warnings[chat_id] = {}

    user_warnings[chat_id][user_id] = user_warnings[chat_id].get(user_id, 0) + 1

    # Notify the user and chat
    warn_count = user_warnings[chat_id][user_id]
    if warn_count >= 3:
        await client.ban_chat_member(chat_id, user_id)
        await message.reply_text(f"{message.reply_to_message.from_user.mention()} DOMIAN EXPANSION: SHRINE! User...\n\n IS BANNED.")
    else:
        await message.reply_text(f"{message.reply_to_message.from_user.mention()} has been attacked with my Cursed Energy! \n\nThey now have {warn_count} warning(s).")

# /rmwarn command - Admins only
@app.on_message(filters.command("rmwarn") & filters.group)
async def remove_warn(client, message: Message):
    if not message.reply_to_message:
        await message.reply_text("If you won't specify the target or opponent how can I use my powers?")
        return

    chat_id = message.chat.id
    user_id = message.reply_to_message.from_user.id
    user_status = await client.get_chat_member(chat_id, user_id)
    admin_status = await client.get_chat_member(chat_id, message.from_user.id)

    # Check if the command issuer is an admin
    if admin_status.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        await message.reply_text("Only Grade lvl: SSS Rank can remove the Warns.")
        return

    # Check if the target user is an admin
    if user_status.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        await message.reply_text("They are out of my domain as they're admins.")
        return

    # Remove the user's warnings if they have any
    if chat_id in user_warnings and user_id in user_warnings[chat_id]:
        del user_warnings[chat_id][user_id]
        await message.reply_text(f"All my warns are removed from {message.reply_to_message.from_user.mention()}.")
    else:
        await message.reply_text("This user doesn't have any warnings from me. Check properly!")




@app.on_message(filters.command("barrier"))
async def barrier_command(client, message):
    user_id = message.from_user.id
    initialize_user_data(user_id)

    # Check if the user is under cooldown
    if user_id in user_cooldowns and user_cooldowns[user_id] is not None and datetime.now().timestamp() < user_cooldowns[user_id]:
        remaining_time = int(user_cooldowns[user_id] - datetime.now().timestamp())
        hours, seconds = divmod(remaining_time, 3600)
        minutes, seconds = divmod(seconds, 60)
        await message.reply_text(
            f"{message.from_user.first_name}, you are still under cooldown. You can use the **Barrier** command again in {hours} hour(s), {minutes} minute(s), and {seconds} second(s)."
        )
        return

    # Ensure user data is initialized in user_barrier_status
    if user_id not in user_barrier_status:
        user_barrier_status[user_id] = {"barrier_active": False, "barrier_lift_time": None, "last_barrier_use": None}

    # Activate Barrier for the user
    user_barrier_status[user_id]["barrier_active"] = True
    user_barrier_status[user_id]["last_barrier_use"] = datetime.now()
    await message.reply_text("Barrier activated! You are now protected from curses.")

    # Set the cooldown for 3 hours
    user_cooldowns[user_id] = (datetime.now() + BARRIER_COOLDOWN).timestamp()







@app.on_message(filters.command("domain"))
async def domain_command(client, message):
    user_id = message.from_user.id
    now = datetime.now()
    initialize_user_data(user_id)

    # Check if the user has an active barrier
    barrier_active = user_barrier_status.get(user_id, {}).get("barrier_active", False)
    if not barrier_active:
        await message.reply_text("No active barrier to lift.")
        return

    # Lift the barrier immediately
    user_barrier_status[user_id]["barrier_active"] = False
    user_barrier_status[user_id]["barrier_lift_time"] = None
    user_barrier_status[user_id]["last_barrier_use"] = now
    await message.reply_text("Barrier has been lifted early!")

    # Reset the cooldown for the Barrier command to 30 minutes
    user_cooldowns[user_id] = (now + RESET_COOLDOWN).timestamp()

    remaining_time = int(user_cooldowns[user_id] - now.timestamp())
    hours, seconds = divmod(remaining_time, 3600)
    minutes, seconds = divmod(seconds, 60)
    await message.reply_text(
        f"You cannot use the **Barrier** command again for {hours} hour(s), {minutes} minute(s), and {seconds} second(s)."
    )










def create_health_bar(current_hp):
    full_blocks = int(current_hp / TOTAL_HP * 20)
    empty_blocks = 20 - full_blocks
    return f"[{'█' * full_blocks}{'░' * empty_blocks}] {current_hp}/{TOTAL_HP} HP"

def initialize_user_data(user_id):
    if user_id not in user_hp:
        user_hp[user_id] = TOTAL_HP

@app.on_message(filters.command(["health", "hp"]))
async def show_health(client, message):
    user_id = message.from_user.id
    initialize_user_data(user_id)
    hp_bar = create_health_bar(user_hp[user_id])
    await message.reply_text(f"Your Health: {hp_bar}")




@app.on_message(filters.command("curse"))
async def curse_command(client, message):
    user_id = message.from_user.id
    target_user_id = None
    
    # Check if the command was a reply to a message
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user

        # Check if the target is a bot
        if target_user.is_bot:
            await message.reply_text("**KNOW YOUR PLACE, FOOL!** \nReply to other user, rather then stealing points from a Bot.")
            return

    else:
        await message.reply_text("Reply to a user's message to target them with a curse.")
        return
    
    # Initialize user data for the attacker
    initialize_user_data(user_id)

    # Check if the user is currently in the hospital
    in_hospital, cooldown_end = is_in_hospital(user_id)
    if in_hospital:
        remaining_time = int(cooldown_end.timestamp() - datetime.now().timestamp())
        hours, seconds = divmod(remaining_time, 3600)
        minutes, seconds = divmod(seconds, 60)
        await message.reply_text(
            f"You have been taken down, you are at Hospital recovering.\n\nTime needed - {hours} hour(s), {minutes} minute(s), and {seconds} second(s)."
        )
        return

    # Check if the user is currently on cooldown due to a COUNTER action
    if is_on_counter_cooldown(user_id):
        remaining_time = int(counter_cooldowns[user_id] - datetime.now().timestamp())
        hours, seconds = divmod(remaining_time, 3600)
        minutes, seconds = divmod(seconds, 60)
        await message.reply_text(
            f"Your **Cursed Technique was COUNTERED**. You can use it back under {hours} hour(s), {minutes} minute(s), and {seconds} second(s)."
        )
        return

    # Check if the user issuing the command has an active barrier
    if user_id in user_barrier_status and user_barrier_status[user_id].get("barrier_active", False):
        await message.reply_text(f"You are currently protected by a Barrier and cannot use the **Curse** command.")
        return

    # Check if the command was a reply to another user's message
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
    else:
        await message.reply_text("Reply to a user's message to target them with a curse.")
        return

    # Initialize target user data
    initialize_user_data(target_user_id)

    # Check if the target user has an active barrier
    if user_barrier_status.get(target_user_id, {}).get("barrier_active", False):
        await message.reply_text(f"{message.reply_to_message.from_user.first_name} is protected by a Barrier. You cannot curse them.")
        return

    # Fetch target user details
    target_user = message.reply_to_message.from_user
    if not target_user:
        await message.reply_text("Target user not found.")
        return

    target_user_id = target_user.id
    target_user_name = target_user.first_name

    # Ensure user HP is initialized
    if target_user_id not in user_hp:
        user_hp[target_user_id] = TOTAL_HP

    if user_id not in user_hp:
        user_hp[user_id] = TOTAL_HP

    # If user's HP is 0, set the hospital cooldown
    if user_hp[user_id] <= 0:
        set_hospital_cooldown(user_id)
        await message.reply_text("You have been taken down and are being sent to the hospital for recovery.")
        return

    # Random selection for action (DOMAIN, CURSED, COUNTER)
    random_choice = random.choices(
        ["DOMAIN", "CURSED", "COUNTER"], 
        [0.1, 0.8, 0.1]
    )[0]

    if random_choice == "DOMAIN":
        image_path = get_random_image(domain_folder)
        user_hp[target_user_id] -= 80
        user_points[user_id] = user_points.get(user_id, 0) + 5
        action_message = f"**DOMAIN EXPANSION** by [{message.from_user.first_name}](tg://user?id={user_id}) to [{target_user_name}](tg://user?id={target_user_id}). \n -80 Health is Vanished!!"
        # Remove Barrier if target user had it
        if target_user_id in user_barrier_status:
            user_barrier_status[target_user_id]["barrier_active"] = False

    elif random_choice == "CURSED":
        image_path = get_random_image(cursed_folder)
        user_hp[target_user_id] -= 10
        user_points[user_id] = user_points.get(user_id, 0) + 1
        action_message = f"**CURSED ATTACK** by [{message.from_user.first_name}](tg://user?id={user_id}) to [{target_user_name}](tg://user?id={target_user_id}). \n -10 Health is Vanished!!"

    else:  # COUNTER
        image_path = get_random_image(counter_folder)
        user_hp[user_id] += 5
        user_points[user_id] = user_points.get(user_id, 0) - 3
        action_message = f"**COUNTERED** [{message.from_user.first_name}](tg://user?id={user_id}) from [{target_user_name}](tg://user?id={target_user_id}). \n +5 Health is REPLENISHED!!"
        
        # Set cooldown for COUNTER action
        set_counter_cooldown(user_id)

    # Ensure HP is within bounds
    user_hp[target_user_id] = max(0, user_hp[target_user_id])
    user_hp[user_id] = min(TOTAL_HP, user_hp[user_id])

    # If target user's HP reaches 0, they go on a 26-hour cooldown
    if user_hp[target_user_id] == 0:
        start_26_hour_cooldown(target_user_id)
        await message.reply_text(
            f"[{target_user_name}](tg://user?id={target_user_id}) has been taken down successfully!!"
        )
        return

    # Create health bars for both users
    target_hp_bar = create_health_bar(user_hp[target_user_id])
    user_hp_bar = create_health_bar(user_hp[user_id])

    # Send the image and action message
    if image_path:
        await message.reply_photo(
            photo=image_path,
            caption=f"{action_message}\n\nTarget's Health: {target_hp_bar}\n\nYour Health: {user_hp_bar}"
        )
    else:
        await message.reply_text(action_message)









@app.on_message(filters.command("jujutsu"))
async def show_rankings(client, message):
    sorted_users = sorted(user_points.items(), key=lambda x: x[1], reverse=True)

    if not sorted_users:
        await message.reply_text("No rankings available. Start earning Cursed Energy!")
        return

    # Show current rankings
    ranking_message = "**Jujutsu Rankings based on your Curse Energy**\n\n"
    for idx, (user_id, points) in enumerate(sorted_users, 1):
        try:
            user = await client.get_users(user_id)
            user_name = user.mention()  # Use mention to notify user
            ranking_message += f"{idx}. {user_name} - {points} **Cursed Energy**\n"
        except Exception as e:
            print(f"Error retrieving user info: {e}")
            ranking_message += f"{idx}. User with ID {user_id} - {points} **Cursed Energy**\n"

    await message.reply_text(ranking_message)

@app.on_message(filters.command("grade"))
async def show_top_5(client, message):

    sorted_users = sorted(user_points.items(), key=lambda x: x[1], reverse=True)

    if not sorted_users:
        await message.reply_text("No rankings available. Start earning Cursed Energy!")
        return

    # Show top 5 rankings
    top_5_message = "**Top 5 Rankings based on your Curse Energy**\n\n"
    for idx, (user_id, points) in enumerate(sorted_users[:5], 1):
        try:
            user = await client.get_users(user_id)
            user_name = user.mention()  # Use mention to notify user
            top_5_message += f"{idx}. {user_name} - {points} **Cursed Energy**\n"
        except Exception as e:
            print(f"Error retrieving user info: {e}")
            top_5_message += f"{idx}. User with ID {user_id} - {points} **Cursed Energy**\n"

    await message.reply_text(top_5_message)

# Scheduler setup
scheduler = AsyncIOScheduler()

async def send_daily_top_3_winners():
    for chat_id, user_points in chat_user_points.items():
        sorted_users = sorted(user_points.items(), key=lambda x: x[1], reverse=True)
        
        if len(sorted_users) < 3:
            continue

        top_3_message = "**Congratulations to the Top 3 Winners for Today!**\n\n"
        for idx, (user_id, points) in enumerate(sorted_users[:3], 1):
            try:
                user = await app.get_users(user_id)
                user_name = user.mention()
                top_3_message += f"{idx}. {user_name} - {points} **Cursed Energy**\n"
            except Exception as e:
                print(f"Error retrieving user info: {e}")
                top_3_message += f"{idx}. User with ID {user_id} - {points} **Cursed Energy**\n"
        
        await app.send_message(chat_id, top_3_message)

def reset_rankings():
    global chat_user_points
    chat_user_points = {}  # Reset rankings for all chats
    print("Rankings have been reset.")

def schedule_daily_tasks():
    tz = pytz.timezone('Asia/Kolkata')
    scheduler.add_job(send_daily_top_3_winners, 'cron', hour=0, minute=0, timezone=tz)
    scheduler.add_job(reset_rankings, 'cron', hour=0, minute=0, timezone=tz)
    scheduler.start()









# Helper to check if a user is admin
async def is_admin(client, chat_id, user_id):
    member = await client.get_chat_member(chat_id, user_id)
    return member.status in ["administrator", "creator"]

# BAN command
@app.on_message(filters.command("ban") & filters.group)
async def ban_command(client, message):
    chat_id = message.chat.id
    target_user = message.reply_to_message.from_user if message.reply_to_message else None
    admin_user = message.from_user

    # Check if command user is admin
    if not await is_admin(client, chat_id, admin_user.id):
        await message.reply_text("Know your place, Fool!")
        return

    # If no one is replied to
    if not target_user:
        await message.reply_text("Show me who dared to get out from my Domain.")
        return

    # Prevent banning admins
    if await is_admin(client, chat_id, target_user.id):
        if target_user.is_bot:
            await message.reply_text("Don't go this low.")
        else:
            await message.reply_text("They are my Teammates. I won't curse them.")
        return

    # Create inline buttons
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("DOMAIN EXPANSION", callback_data=f"ban_{target_user.id}_domain_{admin_user.id}")],
        [InlineKeyboardButton("REVERSAL", callback_data=f"ban_{target_user.id}_reversal_{admin_user.id}")]
    ])

    await message.reply_text("Choose the action for the user:", reply_markup=keyboard)

# UNBAN command
@app.on_message(filters.command("unban") & filters.group)
async def unban_command(client, message):
    chat_id = message.chat.id
    target_user = message.reply_to_message.from_user if message.reply_to_message else None
    admin_user = message.from_user

    # Check if command user is admin
    if not await is_admin(client, chat_id, admin_user.id):
        await message.reply_text("Know your place, Fool!")
        return

    # If no one is replied to
    if not target_user:
        await message.reply_text("I will give that person one more chance so show me where he is.")
        return

    # Prevent unbanning admins or bot admins
    if await is_admin(client, chat_id, target_user.id):
        if target_user.is_bot:
            await message.reply_text("Don't go this low.")
        else:
            await message.reply_text("They are my Teammates. I won't curse them.")
        return

    try:
        # Unban the user
        await client.unban_chat_member(chat_id, target_user.id)
        await message.reply_text(f"{target_user.first_name} has been unbanned.")
    except RPCError as e:
        await message.reply_text(f"Failed to unban user: {e}")

# Handle button presses for BAN command
@app.on_callback_query()
async def handle_callback_query(client, callback_query):
    data = callback_query.data.split('_')
    chat_id = callback_query.message.chat.id
    user_id = int(data[1])
    action = data[2]
    admin_id = int(data[3])

    # Ensure only the admin who initiated can press the button
    if callback_query.from_user.id != admin_id:
        await callback_query.answer("It is not your place to come in.", show_alert=True)
        return

    # Perform action and remove the buttons
    if action == "domain":
        try:
            await client.ban_chat_member(chat_id, user_id)
            await callback_query.message.edit_text("User has been banned.")
        except RPCError as e:
            await callback_query.message.edit_text(f"Failed to ban user: {e}")

    elif action == "reversal":
        await callback_query.message.edit_text("Ban action reversed. User is safe from ban.")

    # Acknowledge the callback and remove the buttons
    await callback_query.answer()

# Handle BAN and UNBAN in DM: Show error message since it's not valid
@app.on_message(filters.command(["ban", "unban"]) & filters.private)
async def invalid_command_in_dm(client, message):
    await message.reply_text("These commands only work in groups, not in direct messages!")







# Join Team Sun
@app.on_message(filters.command("joinSun"))
async def join_sun_command(client, message):
    user_id = message.from_user.id

    # Check if the user is already in a team
    if user_id in team_scores["team_sun"]["players"] or user_id in team_scores["team_moon"]["players"]:
        await message.reply_text("You are already part of a team.")
        return

    # Ensure only 2 players can join Team Sun
    if len(team_scores["team_sun"]["players"]) >= 2:
        await message.reply_text("Team Sun already has 2 players.")
        return

    # Add the user to Team Sun
    team_scores["team_sun"]["players"].append(user_id)
    await message.reply_text(f"{message.from_user.mention} has joined Team Sun!")

# Join Team Moon
@app.on_message(filters.command("joinMoon"))
async def join_moon_command(client, message):
    user_id = message.from_user.id

    # Check if the user is already in a team
    if user_id in team_scores["team_sun"]["players"] or user_id in team_scores["team_moon"]["players"]:
        await message.reply_text("You are already part of a team.")
        return

    # Ensure only 2 players can join Team Moon
    if len(team_scores["team_moon"]["players"]) >= 2:
        await message.reply_text("Team Moon already has 2 players.")
        return

    # Add the user to Team Moon
    team_scores["team_moon"]["players"].append(user_id)
    await message.reply_text(f"{message.from_user.mention} has joined Team Moon!")


# Serve Command
@app.on_message(filters.command("serve"))
async def serve_command(client, message):
    # Ensure both teams have exactly 2 players each
    if len(team_scores["team_sun"]["players"]) != 2 or len(team_scores["team_moon"]["players"]) != 2:
        await message.reply_text("Both teams must have exactly 2 players each to start the game. Please join teams.")
        return

    # Get current player and team info
    user_id = message.from_user.id
    if user_id in team_scores["team_sun"]["players"]:
        team_id = "team_sun"
        opponent_team_id = "team_moon"
    elif user_id in team_scores["team_moon"]["players"]:
        team_id = "team_moon"
        opponent_team_id = "team_sun"
    else:
        await message.reply_text("You are not part of any team. Join a team first.")
        return

    # Check if it is the user's turn
    current_turn_player = team_scores[team_id]["players"][0]  # Check the first player in queue
    if user_id != current_turn_player:
        await message.reply_text("It's not your turn yet.")
        return

    # Select a random action (BLOCK, SMASH, ACE)
    category_choice = random.choices(
        ["BLOCK", "SMASH", "ACE"],
        weights=[0.25, 0.25, 0.50],
        k=1
    )[0]

    # Process the result based on category
    if category_choice == "BLOCK":
        team_scores[opponent_team_id]["score"] += 1
        feedback = f"{message.from_user.mention} was blocked! Opponent team gains +1 point."
    elif category_choice == "SMASH":
        team_scores[team_id]["score"] += 1
        feedback = f"{message.from_user.mention} smashed! Your team gains +1 point."
    else:  # ACE
        feedback = "The ball is in the air... 🏐✨"

    # Check if either team won
    if team_scores[team_id]["score"] >= 9:
        await message.reply_text(f"🎉 **Team Sun wins!** Congratulations!")
        reset_team_scores()
        return
    elif team_scores[opponent_team_id]["score"] >= 9:
        await message.reply_text(f"🎉 **Team Moon wins!** Congratulations!")
        reset_team_scores()
        return

    # Send feedback message
    await message.reply_text(feedback)

    # Rotate turns: move current player to the end of the queue for the team
    team_scores[team_id]["players"].rotate(-1)
    team_scores[opponent_team_id]["players"].rotate(-1)  # Rotate both teams for turn-based gameplay

# Reset function
def reset_team_scores():
    global team_scores
    team_scores = {
        "team_sun": {"players": deque(), "score": 0},
        "team_moon": {"players": deque(), "score": 0}
    }


@app.on_message(filters.command("points"))
async def points_command(client, message):
    """Display the current scores of each team."""
    team1_score = team_scores["team1"]["score"]
    team2_score = team_scores["team2"]["score"]

    team1_players = [await client.get_users(player) for player in team_scores["team1"]["players"]]
    team2_players = [await client.get_users(player) for player in team_scores["team2"]["players"]]

    team1_mentions = " and ".join([player.mention for player in team1_players])
    team2_mentions = " and ".join([player.mention for player in team2_players])

    score_text = (f"**Current Score:**\n\n"
                  f"☀️ Team 1 (Sun) - {team1_mentions}: **{team1_score} points**\n"
                  f"🌙 Team 2 (Moon) - {team2_mentions}: **{team2_score} points**")

    await message.reply_text(score_text)



async def get_sukuna_response(prompt):
    headers = {
        "Content-Type": "application/json",
    }
    data = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(GEMINI_API_URL, headers=headers, json=data) as response:
            result = await response.json()
            
            # Debugging: print the entire response to see its structure
            print(result)
            
            # Extract the response text from the API
            try:
                return result['candidates'][0]['content']['parts'][0]['text']
            except (KeyError, IndexError) as e:
                return "I couldn't understand that, try asking something else."

@app.on_message(filters.text)
async def handle_message(client, message):
    user_id = message.from_user.id
    
    # Handle SUKUNA ON and SUKUNA OFF commands
    if message.text.lower() == 'sukuna on':
        sukuna_mode[user_id] = 'ON'
        await message.reply_text("Sukuna mode is now ON. Face me if you dare.")
        return  # Exit the function to avoid further processing

    elif message.text.lower() == 'sukuna off':
        sukuna_mode[user_id] = 'OFF'
        await message.reply_text("Sukuna mode is now OFF. I will not respond with my true form.")
        return  # Exit the function to avoid further processing

    # If Sukuna mode is OFF, do not generate a Sukuna response
    if sukuna_mode.get(user_id, 'OFF') == 'OFF':
        # Simply do nothing or respond with a default message
        # Example: await message.reply_text("Sukuna mode is OFF. No responses will be given.")
        return  # Do nothing

    # Process message with Sukuna's response if Sukuna mode is ON
    if sukuna_mode.get(user_id, 'OFF') == 'ON':
        try:
            prompt = message.text
            sukuna_response = await get_sukuna_response(prompt)
            await message.reply_text(sukuna_response)
        except Exception as e:
            await message.reply_text(f"An error occurred: {e}")



if __name__ == "__main__":
    schedule_daily_tasks()
    app.run()
