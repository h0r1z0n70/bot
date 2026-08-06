import os
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

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


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
    username="reciever",
    webhook="webhook",
)
async def generate(interaction: discord.Interaction, username: str, webhook: str):
    # Defer so we have time to hit the API
    await interaction.response.defer(ephemeral=True)

    if "discord.com/api/webhooks/" not in webhook:
        await interaction.followup.send(
            "not valid webhook", ephemeral=True
        )
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{PROTECTOR_URL}/api/v3/token/register",
                json={"webhook_url": webhook, "username": username},
                headers={"x-admin-secret": ADMIN_SECRET},
            )
    except httpx.RequestError as e:
        await interaction.followup.send(f"failed go ask a dev: `{e}`", ephemeral=True)
        return

    if resp.status_code != 200:
        await interaction.followup.send(
            f"worked `{resp.status_code}`: {resp.text[:200]}", ephemeral=True
        )
        return

    data = resp.json()
    token = data.get("token", "unknown")

    # Build the config block
    config_block = f'token = "{token}"'

    embed = discord.Embed(
        title="generated",
        description="**this is shown only once!**",
        color=0x57F287,
    )
    embed.add_field(name="username", value=f"`{username}`", inline=True)
    embed.add_field(name="config", value=f"```lua\n{config_block}\n```", inline=False)
    embed.set_footer(text="Horizon Scripts | Best Script Serivces")

    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="revoke", description="Revoke a Horizon Protector token")
@app_commands.describe(token="The horizon$scripts-... token to revoke")
async def revoke(interaction: discord.Interaction, token: str):
    await interaction.response.defer(ephemeral=True)

    if not token.startswith("horizon$scripts-"):
        await interaction.followup.send("not valid token", ephemeral=True)
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{PROTECTOR_URL}/api/v3/token/revoke",
                json={"token": token},
                headers={"x-admin-secret": ADMIN_SECRET},
            )
    except httpx.RequestError as e:
        await interaction.followup.send(f"failed ask dev `{e}`", ephemeral=True)
        return

    if resp.status_code == 200:
        await interaction.followup.send("revoked", ephemeral=True)
    else:
        await interaction.followup.send(
            f"failed `{resp.status_code}` — {resp.text[:200]}", ephemeral=True
        )


bot.run(BOT_TOKEN)
