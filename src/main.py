import copy
import logging
import os
import secrets
from collections import Counter

import discord
from discord.ext import commands
from google.oauth2 import service_account
from googleapiclient import discovery
from preston import Preston

from assets import Assets
from callback_server import callback_server
from models import initialize_database, User, Challenge

logger = logging.getLogger('discord.main')
logger.setLevel(logging.INFO)




# Google Sheets setup
def get_sheet_service():
    scopes = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/drive.file",
              "https://www.googleapis.com/auth/spreadsheets"]
    credentials = service_account.Credentials.from_service_account_file("credentials.json", scopes=scopes)
    service = discovery.build('sheets', 'v4', credentials=credentials)
    return service


def lines_to_counter(lines):
    items = Counter()
    for item in lines:
        if "[" in item or item == "":
            continue
        if ', ' in item:
            item = item.split(", ")[0]
        if ' x' in item:
            name, count = item.rsplit(" x", 1)
            items[name.strip()] += int(count)
        else:
            items[item.strip()] += 1
    return items


def eft_to_counter(eft):


    eft = eft.replace('\r', '')
    sections = eft.strip().split("\n\n\n")
    title_item = sections[0].split(",")[0].strip("[]")
    ship_counter = Counter()
    ship_counter[title_item] += 1
    all_counter = lines_to_counter(sections[0].splitlines()) + lines_to_counter(
        "\n".join(sections[1:]).splitlines()) + ship_counter

    # Ignore FLAG fitting
    if "FLAG" in eft:
        return ship_counter, Counter()

    return ship_counter, all_counter


def fetch_requirements():
    sheet_service = get_sheet_service()
    result = sheet_service.spreadsheets().values().get(spreadsheetId=os.environ["SPREADSHEET_ID"], range=os.environ["RANGE"]).execute()
    inputs = result.get('values', [])

    comp_requirements = []
    all_counter = Counter()
    ship_counter = Counter()
    for row in inputs:
        eft = row[0] if row else ""
        if "Fit" in eft:
            if all_counter:
                comp_requirements.append((ship_counter, all_counter))
            all_counter = Counter()
            ship_counter = Counter()
        elif "[" in eft:
            ship_local, all_local = eft_to_counter(eft)
            ship_counter += ship_local
            all_counter += all_local

    return comp_requirements


# Configure the logger
logger = logging.getLogger('discord.main')
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

corp_base_preston = Preston(
    user_agent="Hangar organizing discord bot by larynx.austrene@gmail.com",
    client_id=os.environ["CCP_CLIENT_ID"],
    client_secret=os.environ["CCP_SECRET_KEY"],
    callback_url=os.environ["CCP_REDIRECT_URI"],
    scope="esi-assets.read_corporation_assets.v1",
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


async def get_author_assets(author_id: int):
    user = User.get_or_none(User.user_id == str(author_id))
    if user:
        for character in user.characters:
            a = Assets(with_refresh(base_preston, character.token))
            await a.fetch()
            yield a
        for corporation_character in user.corporation_characters:
            try:
                a = Assets(with_refresh(corp_base_preston, corporation_character.token))
                await a.fetch()
            except AssertionError:
                corporation_character.delete_instance()
            else:
                yield a


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
async def satisfaction(ctx):
    """Check how many times each requirement set is fully satisfied by your assets."""
    logger.info(f"{ctx.author.name} used !satisfaction")
    if int(ctx.author.id) not in [242164531151765505, 131845161645899777]:
        await ctx.send("You are not allowed to use this command!")
        return

    await ctx.send("Fetching assets and requirements...")

    comp_requirements = fetch_requirements()
    satisfaction_counts = Counter()

    async for assets in get_author_assets(ctx.author.id):
        user_items = assets.item_counts()

        for ship_counter, item_counter in comp_requirements:

            requirement_name = ", ".join([f"{key} x{value}" for key, value in ship_counter.items()])

            comp_items = copy.copy(user_items)
            satisfaction_counts[requirement_name] = 0

            while True:
                # If the intersection is smaller than the requirement we stop
                intersection = comp_items & item_counter
                if intersection.total() != item_counter.total():
                    break

                # Remove items that are no longer there, this might delete values of 0!
                comp_items -= item_counter
                satisfaction_counts[requirement_name] += 1

    if comp_requirements:
        message = "**Satisfaction Counts:**\n"
        for i, (requirement_name, count) in enumerate(satisfaction_counts.items()):
            message += f"- Comp {i} x{count} (Ships: {requirement_name})\n"
    else:
        message = "No requirements provided!"

    await send_large_message(ctx, message)



@bot.command()
async def missing(ctx):
    """Check what is missing for each requirement set to be satisfied one more time."""
    logger.info(f"{ctx.author.name} used !missing")
    if int(ctx.author.id) not in [242164531151765505, 131845161645899777]:
        await ctx.send("You are not allowed to use this command!")
        return

    await ctx.send("Fetching assets and requirements...")

    comp_requirements = fetch_requirements()

    async for assets in get_author_assets(ctx.author.id):
        user_items = assets.item_counts()

        # Process each requirement set
        for i, (ship_counter, item_counter) in enumerate(comp_requirements):

            comp_items = copy.copy(user_items)
            satisfaction_count = 0

            while True:
                # If the intersection is smaller than the requirement we stop
                intersection = comp_items & item_counter
                if intersection.total() != item_counter.total():
                    missing_items = item_counter - intersection
                    break

                # Remove items that are no longer there, this might delete values of 0!
                comp_items -= item_counter
                satisfaction_count += 1

            # Prepare the message
            requirement_name = ", ".join([f"{key} x{value}" for key, value in ship_counter.items()])

            if satisfaction_count > 0:
                message = f"**Comp {i} is satisfied {satisfaction_count} times (Ships: {requirement_name})**\n"
                message += f"To satisfy it one more time, you need:\n```"

            else:
                message = f"**Comp {i} is not satisfied yet (Ships: {requirement_name})**\n"
                message += f"Missing the following items:\n```"

            for item, count in missing_items.items():
                message += f"{item} x{count}\n"
            message += "```"

            # Send the message for each requirement
            await send_large_message(ctx, message)

    if not comp_requirements:
        await ctx.send("No requirements provided.")


@bot.command()
async def auth(ctx, corporation=False):
    """Sends you an authorization link for a character.
    :corporation: Set true if you want to authorize for your corporation"""
    logger.info(f"{ctx.author.name} used !auth")

    secret_state = secrets.token_urlsafe(60)

    user, created = User.get_or_create(user_id=str(ctx.author.id))
    Challenge.delete().where(Challenge.user == user).execute()
    Challenge.create(user=user, state=secret_state)

    if corporation:
        full_link = f"{corp_base_preston.get_authorize_url()}&state={secret_state}"
        await ctx.author.send(
            f"Use this [authentication link]({full_link}) to authorize a character in your corporation "
            f"with the required role (Accountant).")
    else:
        full_link = f"{base_preston.get_authorize_url()}&state={secret_state}"
        await ctx.author.send(f"Use this [authentication link]({full_link}) to authorize your characters.")


@bot.command()
async def characters(ctx):
    """Displays your currently authorized characters."""
    logger.info(f"{ctx.author.name} used !characters")

    character_names = []
    user = User.get_or_none(User.user_id == str(ctx.author.id))
    if user:
        for character in user.characters:
            char_auth = with_refresh(base_preston, character.token)
            character_name = char_auth.whoami()['CharacterName']
            character_names.append(f"- {character_name}")

        for corporation_character in user.corporation_characters:
            char_auth = with_refresh(corp_base_preston, corporation_character.token)
            character_name = char_auth.whoami()['CharacterName']
            corporation_name = char_auth.get_op("get_corporations_corporation_id",
                                                corporation_id=corporation_character.corporation_id).get("name")
            character_names.append(f"- {corporation_name} (via {character_name})")

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
