import os
import json
import asyncio
import random
import shutil
import discord
from datetime import datetime, date, timedelta
from discord import app_commands, ui
from discord.ext import commands, tasks
from dotenv import load_dotenv
from typing import Optional

# ================= CONFIGURATION & CONSTANTS =================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DATA_FILE = "referee_data.json"
BACKUP_FILE = "backup_referee_data.json"
LOG_CHANNEL_ID = 1470795305657172256 

BFL_CLUBS = [
    "Rentford FC", "Silverthorn", "Amsterdam FC", "Billericay FC", "Spen Valley",
    "Copenhagen FC", "Darvel FC", "Southend United", "Croydon FC", "Manchester FC",
    "Luqmania FC", "Seattle FC", "Sheffield United", "Birmingham FC", "Highfield FC",
    "Rangers FC", "Everton FC", "AFC Milan", "Oakford FC", "Tallaght Rovers",
    "IFK Goteborg", "AS Roma", "Juventus", "Brondby IF", "Crusaders FC",
    "Richmond FC", "Elgin City FC", "Seelo United FC", "Celtic FC", "AFC Wimbledon",
    "Torquay United", "Crystal Palace", "Wolverhampton", "Platinis Viikos", "Hashtag City",
    "RZD Zelitex", "Wesham County", "Husavik Huskies", "Leipzig FC", "KR Moscow"
]

DAYS_OF_THE_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# ================= DATABASE ENGINE =================

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"referees": {}, "config": {"id_counter": 1}, "history": []}
    try:
        with open(DATA_FILE, "r") as file:
            data = json.load(file)
            if "history" not in data: data["history"] = []
            return data
    except Exception as e:
        print(f"Error loading JSON: {e}")
        return {"referees": {}, "config": {"id_counter": 1}, "history": []}

def save_data(data):
    try:
        if os.path.exists(DATA_FILE):
            shutil.copy2(DATA_FILE, BACKUP_FILE)
        with open(DATA_FILE, "w") as file:
            json.dump(data, file, indent=4)
    except Exception as e:
        print(f"Error saving JSON: {e}")

async def send_log(bot, title, description, color=discord.Color.blue()):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        embed = discord.Embed(title=f"📋 BFL LOG: {title}", description=description, color=color)
        embed.timestamp = datetime.now()
        await channel.send(embed=embed)

# ================= REGISTRATION UI =================

class DaySelectionView(ui.View):
    def __init__(self, user_id, user_name, selected_clubs, category, is_update=False):
        super().__init__(timeout=None)
        self.user_id, self.user_name, self.selected_clubs = str(user_id), user_name, selected_clubs
        self.category, self.is_update = category, is_update
        self.day_select = ui.Select(
            placeholder="Choose your working days...", min_values=1, max_values=7, 
            options=[discord.SelectOption(label=d) for d in DAYS_OF_THE_WEEK]
        )
        self.day_select.callback = self.generic_callback
        self.add_item(self.day_select)

    async def generic_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

    @ui.button(label="Finish Registration", style=discord.ButtonStyle.success)
    async def save(self, interaction: discord.Interaction, button: ui.Button):
        data = load_data()
        days = self.day_select.values
        if self.is_update:
            data["referees"][self.user_id]["availability"] = days
            save_data(data)
            await interaction.response.send_message("✅ Availability updated in the database.", ephemeral=True)
        else:
            ref_id = f"BFL-{str(data['config']['id_counter']).zfill(3)}"
            data["referees"][self.user_id] = {
                "referee_id": ref_id, "name": self.user_name, "strikes": 0, "matches_completed": 0, 
                "category": self.category, "joined_at": str(date.today()), "clubs": self.selected_clubs, 
                "availability": days, "suspended": False, "ratings": []
            }
            data["config"]["id_counter"] += 1
            save_data(data)
            await interaction.response.send_message(f"✅ Contract Signed! Your ID is **{ref_id}**.", ephemeral=True)

class ClubSelectionView(ui.View):
    def __init__(self, user_id, user_name, category=None, is_update=False):
        super().__init__(timeout=None)
        self.user_id, self.user_name, self.category, self.is_update = str(user_id), user_name, category, is_update
        self.s1 = ui.Select(placeholder="BFL Clubs (Group 1)", min_values=0, max_values=5, options=[discord.SelectOption(label=c) for c in BFL_CLUBS[:20]])
        self.s2 = ui.Select(placeholder="BFL Clubs (Group 2)", min_values=0, max_values=5, options=[discord.SelectOption(label=c) for c in BFL_CLUBS[20:]])
        self.s1.callback = self.s2.callback = self.generic_callback
        self.add_item(self.s1); self.add_item(self.s2)

    async def generic_callback(self, interaction: discord.Interaction): await interaction.response.defer(ephemeral=True)

    @ui.button(label="Proceed to Days", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: ui.Button):
        clubs = list(set(self.s1.values + self.s2.values))
        await interaction.response.send_message("Step 3: Select your available days.", view=DaySelectionView(self.user_id, self.user_name, clubs, self.category, self.is_update), ephemeral=True)

# ================= MATCH ASSIGNMENT UI =================

class MatchAcceptanceView(ui.View):
    def __init__(self, bot, referee_id, home, away, m_type, time, stadium, admin_interaction, attempted):
        super().__init__(timeout=3600)
        self.bot, self.ref_id, self.home, self.away = bot, str(referee_id), home, away
        self.m_type, self.time, self.stadium, self.admin_int, self.attempted = m_type, time, stadium, admin_interaction, attempted

    @ui.button(label="ACCEPT MATCH", style=discord.ButtonStyle.green, emoji="⚽")
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        data = load_data()
        if self.ref_id in data["referees"]:
            data["referees"][self.ref_id]["matches_completed"] += 1
            match_data = {"fixture": f"{self.home} vs {self.away}", "time": self.time, "stadium": self.stadium, "type": self.m_type, "date": str(date.today())}
            data["referees"][self.ref_id]["current_match"] = match_data
            data["history"].append({"ref_id": self.ref_id, "ref_name": data["referees"][self.ref_id]["name"], **match_data})
            save_data(data)
            await interaction.response.edit_message(content=f"✅ You have accepted: **{self.home} vs {self.away}**", view=None)
            await self.admin_int.followup.send(f"🏟️ Referee <@{self.ref_id}> confirmed for **{self.home} vs {self.away}**")

    @ui.button(label="DECLINE MATCH", style=discord.ButtonStyle.red, emoji="✖️")
    async def decline(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(content="❌ You declined the match.", view=None)
        self.attempted.append(self.ref_id)
        await search_and_assign(self.bot, self.admin_int, self.home, self.away, self.m_type, self.time, self.stadium, self.attempted)

# ================= OPERATIONS ENGINE =================

async def search_and_assign(bot, interaction, home, away, m_type, time, stadium, attempted):
    data = load_data(); day = datetime.now().strftime("%A") 
    eligible = [uid for uid, info in data["referees"].items() if uid not in attempted 
                and day in info["availability"] and not info.get("suspended", False)
                and not (info.get("loa_until") and datetime.now() < datetime.fromisoformat(info["loa_until"]))
                and not (m_type == "Cup (Category A)" and info["category"] != "Category A")
                and home not in info["clubs"] and away not in info["clubs"]]

    if not eligible: return await interaction.followup.send("❌ No available referees found for this criteria.")
    ref_uid = random.choice(eligible)
    try:
        user = await bot.fetch_user(int(ref_uid))
        view = MatchAcceptanceView(bot, ref_uid, home, away, m_type, time, stadium, interaction, attempted)
        embed = discord.Embed(title="🚨 URGENT: Match Assignment", color=discord.Color.gold())
        embed.add_field(name="Fixture", value=f"**{home} vs {away}**", inline=False)
        embed.add_field(name="Kick-off", value=time, inline=True)
        embed.add_field(name="Stadium", value=stadium, inline=True)
        embed.add_field(name="Competition", value=m_type, inline=False)
        await user.send(embed=embed, view=view)
        await interaction.followup.send(f"⏳ Request sent to <@{ref_uid}>. Waiting for response...")
    except Exception:
        attempted.append(ref_uid); await search_and_assign(bot, interaction, home, away, m_type, time, stadium, attempted)

# ================= BOT CLASS =================

class BFLBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default(); intents.members = True
        super().__init__(command_prefix="!", intents=intents)
    async def setup_hook(self): await self.tree.sync()

bot = BFLBot()

# ================= ADMIN COMMANDS =================

@bot.tree.command(name="broadcast", description="Send a DM to ALL registered referees")
@app_commands.checks.has_role("BFL Admin")
async def broadcast(interaction: discord.Interaction, message: str):
    await interaction.response.defer(ephemeral=True)
    data = load_data(); count = 0; failed = 0
    
    embed = discord.Embed(title="📢 BFL Official Announcement", description=message, color=discord.Color.blue())
    embed.set_footer(text=f"Sent by {interaction.user.display_name}")
    embed.timestamp = datetime.now()

    for uid in data["referees"].keys():
        try:
            user = await bot.fetch_user(int(uid))
            await user.send(embed=embed)
            count += 1
            await asyncio.sleep(0.5) # Prevent rate limiting
        except:
            failed += 1
    
    await interaction.followup.send(f"✅ Broadcast complete. Sent: {count} | Failed: {failed}")
    await send_log(bot, "BROADCAST SENT", f"Admin: {interaction.user.mention}\nMessage: {message}\nSuccess: {count}\nFailed: {failed}")

@bot.tree.command(name="add_referee", description="Invite a new member!")
@app_commands.choices(category=[app_commands.Choice(name=f"Category {x}", value=f"Category {x}") for x in ["A", "B", "C"]])
@app_commands.checks.has_role("BFL Admin")
async def add_referee(interaction: discord.Interaction, user: discord.Member, category: str):
    class StartContract(ui.View):
        @ui.button(label="BEGIN CONTRACT", style=discord.ButtonStyle.green)
        async def begin(self, i, b): await i.response.send_message("Step 2: Selecting Restricted Clubs", view=ClubSelectionView(user.id, user.display_name, category), ephemeral=True)
    await user.send(f"👋 Hello! You have been invited to join the BFL as a **{category}** Referee. Please begin your registration:", view=StartContract())
    await interaction.response.send_message(f"✅ Contract invitation sent to {user.mention}.", ephemeral=True)

@bot.tree.command(name="assign_match", description="Search for an available referee and send them a match request")
@app_commands.choices(match_type=[app_commands.Choice(name=x, value=x) for x in ["Cup (Category A)", "Category A", "Category B", "Category C"]])
@app_commands.checks.has_role("BFL Admin")
async def assign_match(interaction: discord.Interaction, home_team: str, away_team: str, match_type: str, time: str, stadium: str):
    await interaction.response.defer(); await search_and_assign(bot, interaction, home_team, away_team, match_type, time, stadium, [])

@bot.tree.command(name="suspend", description="Suspend a referee (stops match assignments)")
@app_commands.checks.has_role("BFL Admin")
async def suspend(interaction: discord.Interaction, member: discord.Member, reason: str):
    data = load_data(); uid = str(member.id)
    if uid in data["referees"]:
        data["referees"][uid]["suspended"] = True; save_data(data)
        await interaction.response.send_message(f"🔴 Referee {member.mention} has been suspended.")
        await send_log(bot, "SUSPENSION", f"Ref: {member.mention}\nReason: {reason}", discord.Color.red())

@bot.tree.command(name="unsuspend", description="Lift a suspension from a referee")
@app_commands.checks.has_role("BFL Admin")
async def unsuspend(interaction: discord.Interaction, member: discord.Member):
    data = load_data(); uid = str(member.id)
    if uid in data["referees"]:
        data["referees"][uid]["suspended"] = False; save_data(data)
        await interaction.response.send_message(f"🟢 Referee {member.mention} is now active.")
        await send_log(bot, "REACTIVATION", f"Ref: {member.mention}", discord.Color.green())

# ================= PUBLIC & STATS COMMANDS =================

@bot.tree.command(name="stats", description="View profile, ratings, and availability")
async def stats(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    data = load_data(); target = member or interaction.user; uid = str(target.id)
    ref = data["referees"].get(uid)
    if not ref: return await interaction.response.send_message("❌ User not found in BFL database.", ephemeral=True)
    
    avg = sum(r["stars"] for r in ref.get("ratings", [])) / len(ref.get("ratings", [1])) if ref.get("ratings") else 0
    status = "🔴 SUSPENDED" if ref.get("suspended") else "🟢 ACTIVE"
    if ref.get("loa_until") and datetime.now() < datetime.fromisoformat(ref["loa_until"]): status = "⛺ ON LEAVE"

    embed = discord.Embed(title=f"BFL Referee Profile: {ref['name']}", color=discord.Color.blue())
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="Category", value=ref["category"]).add_field(name="Rating", value=f"{avg:.1f}⭐").add_field(name="Matches", value=ref["matches_completed"])
    embed.add_field(name="Strikes", value=f"{ref['strikes']}/3").add_field(name="Status", value=status).add_field(name="Ref ID", value=f"`{ref['referee_id']}`")
    embed.add_field(name="🚫 Club Restrictions", value=f"```{', '.join(ref['clubs']) or 'None'}```", inline=False)
    embed.add_field(name="📅 Working Days", value=f"```{', '.join(ref['availability'])}```", inline=False)
    
    if ref.get("ratings"):
        last = ref["ratings"][-1]; embed.add_field(name="💬 Latest Peer Feedback", value=f"**{last['stars']}⭐**: \"{last['comment']}\"", inline=False)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="leaderboard", description="Global rankings")
@app_commands.choices(sort_by=[app_commands.Choice(name="Highest Rated", value="rating"), app_commands.Choice(name="Most Matches", value="matches")])
async def leaderboard(interaction: discord.Interaction, sort_by: str):
    data = load_data(); ref_list = []
    for uid, info in data["referees"].items():
        avg = sum(r["stars"] for r in info.get("ratings", [])) / len(info.get("ratings", [1])) if info.get("ratings") else 0.0
        ref_list.append({"name": info["name"], "rating": avg, "matches": info["matches_completed"]})
    
    sorted_data = sorted(ref_list, key=lambda x: x[sort_by], reverse=True)[:10]
    embed = discord.Embed(title=f"🏆 BFL Leaderboard: {sort_by.capitalize()}", color=discord.Color.gold())
    for i, r in enumerate(sorted_data, 1):
        score = f"{r['rating']:.1f}⭐" if sort_by == "rating" else f"{r['matches']} games"
        embed.add_field(name=f"#{i} {r['name']}", value=score, inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="match_history", description="View the last 15 matches recorded")
async def match_history(interaction: discord.Interaction):
    data = load_data(); hist = data["history"][-15:]; hist.reverse()
    if not hist: return await interaction.response.send_message("History is empty.")
    embed = discord.Embed(title="📜 BFL Match History (Last 15)", color=discord.Color.dark_grey())
    for m in hist:
        embed.add_field(name=f"📅 {m['date']} | {m['fixture']}", value=f"Ref: {m['ref_name']} | Competition: {m['type']}", inline=False)
    await interaction.response.send_message(embed=embed)

# ================= PEER REVIEW & LOA =================

@bot.tree.command(name="rate_referee", description="Submit feedback for a colleague")
@app_commands.choices(stars=[app_commands.Choice(name=f"{i} ⭐", value=i) for i in range(1, 6)])
async def rate_referee(interaction: discord.Interaction, colleague: discord.Member, stars: int, comment: str):
    data = load_data(); uid = str(colleague.id); auth = str(interaction.user.id)
    if auth == uid or uid not in data["referees"]: return await interaction.response.send_message("❌ Error: Invalid target.", ephemeral=True)
    
    data["referees"][uid].setdefault("ratings", []).append({"from": auth, "from_name": interaction.user.display_name, "stars": stars, "comment": comment, "date": str(date.today())})
    save_data(data)
    
    await interaction.response.send_message("✅ Peer review submitted. The board has been notified.", ephemeral=True)
    await send_log(bot, "PEER REVIEW (Investigation Log)", f"**Target:** {colleague.mention}\n**Author:** {interaction.user.mention}\n**Grade:** {stars}⭐\n**Feedback:** {comment}", discord.Color.orange())

@bot.tree.command(name="loa", description="Request leave of absence (max 15 days)")
async def loa(interaction: discord.Interaction, days: int, reason: str):
    data = load_data(); uid = str(interaction.user.id); ref = data["referees"].get(uid)
    if not ref: return await interaction.response.send_message("Not registered.", ephemeral=True)
    if days > 15:
        await interaction.response.send_message("⚠️ Requests over 15 days require manual board approval. Log sent.", ephemeral=True)
        await send_log(bot, "LONG LOA REQUEST", f"Ref: <@{uid}>\nDays: {days}\nReason: {reason}", discord.Color.purple())
    else:
        ref["loa_until"] = (datetime.now() + timedelta(days=days)).isoformat(); save_data(data)
        await interaction.response.send_message(f"✅ LOA granted for {days} days.", ephemeral=True)

# ================= MAINTENANCE =================

@bot.tree.command(name="reset_database", description="⚠️ IRREVERSIBLE: Clear all referee and history data")
@app_commands.checks.has_role("BFL Admin")
async def reset_database(interaction: discord.Interaction):
    save_data({"referees": {}, "config": {"id_counter": 1}, "history": []}); await interaction.response.send_message("🚨 DATABASE WIPED.")

@bot.event
async def on_ready():
    print(f"BFL v5.0 Operational. Logged in as {bot.user}")

if TOKEN: bot.run(TOKEN)