import collections
import logging
import os
import secrets

import discord
import requests
from discord.ext import commands
from preston import Preston

from assets import Assets
from callback_server import callback_server
from models import initialize_database, User, Challenge

# Configure the logger
logger = logging.getLogger('discord.refresh')
logger.setLevel(logging.INFO)

# Initialize the database
initialize_database()

# Setup ESI connection
base_preston = Preston(
    user_agent="Hangar organizing discord bot by larynx.austrene@gmail.com",
    client_id=os.environ["CCP_CLIENT_ID"],
    client_secret=os.environ["CCP_SECRET_KEY"],
    callback_url=os.environ["CCP_REDIRECT_URI"],
    scope="esi-assets.read_assets.v1",
)

# Setup Discord
intent = discord.Intents.default()
intent.messages = True
intent.message_content = True
bot = commands.Bot(command_prefix='!', intents=intent)


def with_refresh(preston_instance, refresh_token: str):
    new_kwargs = dict(preston_instance._kwargs)
    new_kwargs["refresh_token"] = refresh_token
    new_kwargs["access_token"] = None
    return Preston(**new_kwargs)


def get_author_ps(author_id: int):
    user = User.get_or_none(User.user_id == str(author_id))
    if user:
        for character in user.characters:
            yield with_refresh(base_preston, character.token)


def get_author_assets(author_id: int):
    for p in get_author_ps(author_id=author_id):
        yield Assets(p)


async def send_large_message(ctx, message, max_chars=2000):
    while len(message) > 0:
        if len(message) <= max_chars:
            await ctx.send(message)
            break

        last_newline_index = message.rfind('\n', 0, max_chars)

        if last_newline_index == -1:
            await ctx.send(message[:max_chars])
            message = message[max_chars:]
        else:
            await ctx.send(message[:last_newline_index])
            message = message[last_newline_index + 1:]


@bot.event
async def on_ready():
    callback_server.start(base_preston)


@bot.command()
async def state(ctx):
    """Returns the current state of all your ships in yaml format. (Useful for first setting things up)"""
    logger.info(f"{ctx.author.name} used !state")

    await ctx.send("Fetching assets...")
    files_to_send = []
    for assets in get_author_assets(ctx.author.id):
        assets.save_requirement(f"data/states/{assets.character_name}.yaml")
        with open(f"data/states/{assets.character_name}.yaml", "rb") as file:
            files_to_send.append(discord.File(file, filename=f"{assets.character_name}.yaml"))

    if files_to_send:
        await ctx.send("Here are your current ship states.", files=files_to_send)
    else:
        await ctx.send("You have no authorized characters!")


@bot.command()
async def check(ctx):
    """Returns a bullet point list of what ships are missing things."""
    logger.info(f"{ctx.author.name} used !check")

    try:
        await ctx.send("Fetching assets...")
        has_characters = False
        has_errors = False
        message = ""
        for assets in get_author_assets(ctx.author.id):
            has_characters = True
            name = f"**{assets.character_name}:**\n"
            for ship_error_message in assets.check_requirement(f"data/reqs/{ctx.author.id}.yaml"):
                has_errors = True

                if len(message) + len(ship_error_message) + len(name) > 1990:
                    await ctx.send(message)
                    message = ""

                if len(name) > 0:
                    message += name
                    name = ""

                message += f"{ship_error_message}\n"

        if has_characters:
            if has_errors:
                await ctx.send(message)
            else:
                await ctx.send("**No State Errors found!**")
        else:
            await ctx.send("You have no authorized characters!")

    except FileNotFoundError:
        await ctx.send("You have not set a requirements file, use the !set command and upload one!")


@bot.command()
async def buy(ctx):
    """Returns a multibuy of all the things missing in your ships."""
    logger.info(f"{ctx.author.name} used !buy")

    try:
        await ctx.send("Fetching assets...")
        buy_list = collections.Counter()
        has_characters = False
        for assets in get_author_assets(ctx.author.id):
            buy_list = assets.get_buy_list(f"data/reqs/{ctx.author.id}.yaml", buy_list=buy_list)
            has_characters = True

        buy_list_body = "\n".join([f"{item} {amount}" for item, amount in buy_list.items()])
        if buy_list_body:
            await send_large_message(ctx, f"**Buy List:**\n```{buy_list_body}```")
        else:
            if has_characters:
                await ctx.send("**Nothing to buy!**")
            else:
                await ctx.send("You have no authorized characters!")
    except FileNotFoundError:
        await ctx.send("You have not set a requirements file, use the !set command and upload one!")


@bot.command()
async def set(ctx, attachment: discord.Attachment):
    """Sets your current requirement file to the one attached to this command."""
    logger.info(f"{ctx.author.name} used !set")

    if attachment:
        response = requests.get(attachment.url, allow_redirects=True)
        with open(f"data/reqs/{ctx.author.id}.yaml", 'wb') as file:
            file.write(response.content)
        await ctx.send("Set new requirements file!")
    else:
        await ctx.send("You forgot to attach a new requirement file!")


@bot.command()
async def get(ctx):
    """Returns your current requirements."""
    logger.info(f"{ctx.author.name} used !get")

    with open(f"data/reqs/{ctx.author.id}.yaml", "rb") as file:
        requirements = discord.File(file, filename=f"requirements.yaml")
    await ctx.send("Here is your current requirement file.", file=requirements)


@bot.command()
async def auth(ctx):
    """Sends you an authorization link for a character."""
    logger.info(f"{ctx.author.name} used !auth")

    secret_state = secrets.token_urlsafe(60)

    user, created = User.get_or_create(user_id=str(ctx.author.id))
    Challenge.delete().where(Challenge.user == user).execute()
    Challenge.create(user=user, state=secret_state)

    full_link = f"{base_preston.get_authorize_url()}&state={secret_state}"
    await ctx.author.send(f"Use this [authentication link]({full_link}) to authorize your characters.")


@bot.command()
async def characters(ctx):
    """Displays your currently authorized characters."""
    logger.info(f"{ctx.author.name} used !characters")

    character_names = []
    for p in get_author_ps(ctx.author.id):
        character_names.append(p.whoami()["CharacterName"])

    if character_names:
        character_names_body = "\n".join(character_names)
        await ctx.send(f"You have the following character(s) authenticated:\n{character_names_body}")
    else:
        await ctx.send("You have no authorized characters!")


@bot.command()
async def revoke(ctx):
    """Revokes ESI access from all your characters."""
    logger.info(f"{ctx.author.name} used !revoke")
    await ctx.send("Currently not implemented!")


if __name__ == "__main__":
    bot.run(os.environ["DISCORD_TOKEN"])
