import collections
import logging
import os
import secrets
from io import BytesIO, StringIO
from typing import Literal
import copy

import discord
import requests
from discord import Interaction, app_commands
from discord.ext import commands
from preston import Preston

from assets import Assets
from callback_server import callback_server
from models import initialize_database, User, Challenge, CorporationCharacter, Character
from utils import lookup, command_error_handler
from sheet import fetch_requirements

# Configure the logger
logger = logging.getLogger('discord.main')
logger.setLevel(logging.INFO)

# Figure out users for at
allowed_users = list(map(int, map(lambda x: x.strip(), os.environ["AT_USERS"].split(","))))

# Initialize the database
initialize_database()

def base_token_callback(preston):
    character_id = preston.whoami()["character_id"]
    character = Character.get(character_id=character_id)
    character.token = preston.refresh_token
    character.save()


# Setup ESI connection
base_preston = Preston(
    user_agent="Hangar organizing discord bot by larynx.austrene@gmail.com",
    client_id=os.environ["CCP_CLIENT_ID"],
    client_secret=os.environ["CCP_SECRET_KEY"],
    callback_url=os.environ["CCP_REDIRECT_URI"],
    scope="esi-assets.read_assets.v1",
    refresh_token_callback=base_token_callback,
    timeout=6,
)

def corporation_token_callback(preston):
    character_id = preston.whoami()["character_id"]
    character = CorporationCharacter.get(character_id=character_id)
    character.token = preston.refresh_token
    character.save()

corp_base_preston = Preston(
    user_agent="Hangar organizing discord bot by larynx.austrene@gmail.com",
    client_id=os.environ["CCP_CLIENT_ID"],
    client_secret=os.environ["CCP_SECRET_KEY"],
    callback_url=os.environ["CCP_REDIRECT_URI"],
    scope="esi-assets.read_corporation_assets.v1",
    refresh_token_callback=corporation_token_callback,
    timeout=6,
)

# Setup Discord
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)


async def get_author_assets(author_id: str):
    user = User.get_or_none(User.user_id == author_id)
    if user:
        for character in user.characters:
            a = Assets(base_preston.authenticate_from_token(character.token))
            await a.fetch()
            yield a

        for corporation_character in user.corporation_characters:
            try:
                a = Assets(corp_base_preston.authenticate_from_token( corporation_character.token))
                await a.fetch()
            except AssertionError:
                corporation_character.delete_instance()
            else:
                yield a

def update_requirements(user):
    if user.update_url is not None:
        response = requests.get(user.update_url, allow_redirects=True)
        user.requirements_file = response.text
        user.save()


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}", exc_info=True)
    callback_server.start(base_preston)


@bot.tree.command(name="auth", description="Sends you an ESI authorization link.")
@app_commands.describe(corporation="Authorize a character for your corporation instead of a personal one.")
@command_error_handler
async def auth(interaction: Interaction, corporation: bool = False):

    if int(interaction.user.id) not in allowed_users:
        await interaction.response.send_message("You are not allowed to use this command!", ephemeral=True)
        return

    secret_state = secrets.token_urlsafe(60)

    user, created = User.get_or_create(user_id=str(interaction.user.id))
    Challenge.delete().where(Challenge.user == user).execute()
    Challenge.create(user=user, state=secret_state)

    if corporation:
        url = f"{corp_base_preston.get_authorize_url(secret_state)}"
        await interaction.response.send_message(
            f"Use this [authentication link]({url}) to authorize a character in your corporation (must have the Accountant role).",
            ephemeral=True
        )
    else:
        url = f"{base_preston.get_authorize_url(secret_state)}"
        await interaction.response.send_message(
            f"Use this [authentication link]({url}) to authorize your personal characters.", ephemeral=True
        )


@bot.tree.command(name="characters", description="Displays your currently authorized characters.")
@command_error_handler
async def characters(interaction: Interaction):

    if int(interaction.user.id) not in allowed_users:
        await interaction.response.send_message("You are not allowed to use this command!", ephemeral=True)
        return

    character_names = []
    user = User.get_or_none(User.user_id == str(interaction.user.id))

    if user is None:
        await interaction.response.send_message("You are not a registered user!")
        return
        
    for character in user.characters:
        char_auth = base_preston.authenticate_from_token(character.token)
        name = char_auth.whoami()['character_name']
        character_names.append(f"- {name}")

    for corp_character in user.corporation_characters:
        char_auth = corp_base_preston.authenticate_from_token(corp_character.token)
        char_name = char_auth.whoami()['character_name']
        corp_name = char_auth.get_op("get_corporations_corporation_id",
                                     corporation_id=corp_character.corporation_id).get("name")
        character_names.append(f"- {corp_name} (via {char_name})")

    if character_names:
        await interaction.response.send_message(
            f"You have the following character(s) authenticated:\n" + "\n".join(character_names), ephemeral=True
        )
    else:
        await interaction.response.send_message("You have no authorized characters.", ephemeral=True)


@bot.tree.command(name="revoke", description="Revoke ESI access to characters or corporations.")
@app_commands.describe(
    entity_type="Type of entity to revoke, character hangar, corporation hangar or all hangars.",
    entity_name="Name of the character or corporation or empty to remove all"
)
@command_error_handler
async def revoke(
        interaction: Interaction,
        entity_type: Literal["character", "corporation", "all"],
        entity_name: str | None = None
):

    if int(interaction.user.id) not in allowed_users:
        await interaction.response.send_message("You are not allowed to use this command!", ephemeral=True)
        return

    try:
        user = User.get(User.user_id == str(interaction.user.id))

        if entity_type == "character":
            if entity_name is None:
                user_characters = Character.select().where(Character.user == user)
                if user_characters:
                    for character in user_characters:
                        character.delete_instance()
                if len(user_characters) == 0:
                    await interaction.response.send_message(
                        f"You did not have any characters linked with their personal hangars"
                    )
                else:
                    await interaction.response.send_message(
                        f"Successfully removed {len(user_characters)} characters linked with their personal hangars."
                    )

            else:
                character_id = await lookup(base_preston, entity_name, return_type="characters")
                character = user.characters.select().where(Character.character_id == character_id).first()
                if character:
                    character.delete_instance()
                    await interaction.response.send_message(f"Successfully removed {entity_name}.")
                else:
                    await interaction.response.send_message(f"You have no character linked named {entity_name}.")

        elif entity_type == "corporation":
            if entity_name is None:
                user_corp_characters = CorporationCharacter.select().where(CorporationCharacter.user == user)
                if user_corp_characters:
                    for corp_character in user_corp_characters:
                        corp_character.delete_instance()

                await interaction.response.send_message(
                    f"Successfully revoked access to all your character corporation scopes."
                )

            else:
                corp_id = await lookup(base_preston, entity_name, return_type="corporations")
                corp_characters = user.corporation_characters.select().where(
                    CorporationCharacter.corporation_id == corp_id)

                for corp_character in corp_characters:
                    corp_character.delete_instance()

                if len(corp_characters) == 0:
                    await interaction.response.send_message(
                        f"You did not have any characters linking corporation {entity_name}."
                    )
                else:
                    await interaction.response.send_message(
                        f"Successfully removed {len(corp_characters)} characters linked corporation {entity_name}."
                    )

        else:
            user_characters = Character.select().where(Character.user == user)
            if user_characters:
                for character in user_characters:
                    character.delete_instance()

            user_corp_characters = CorporationCharacter.select().where(CorporationCharacter.user == user)
            if user_corp_characters:
                for corp_character in user_corp_characters:
                    corp_character.delete_instance()

            user.delete_instance()
            await interaction.response.send_message("Successfully revoked access to all your characters.")


    except User.DoesNotExist:
        await  interaction.response.send_message(f"You did not have any authorized characters in the first place.")
    except ValueError:
        await  interaction.response.send_message(f"Args `{entity_name}` could not be parsed or looked up.")


###############################################################################
# Extra Commands for AT Hangar-Checking

async def get_all_assets():
    for user in User.select():
        for character in user.characters:
            a = Assets(base_preston.authenticate_from_token(character.token))
            await a.fetch()
            yield a

        for corporation_character in user.corporation_characters:
            try:
                a = Assets(corp_base_preston.authenticate_from_token( corporation_character.token))
                await a.fetch()
            except AssertionError:
                corporation_character.delete_instance()
            else:
                yield a

# Satisfaction command
@bot.tree.command(name="satisfaction", description="Check how many times each requirement set is fully satisfied by your assets.")
@command_error_handler
async def satisfaction(interaction: Interaction):
    logger.info(f"{interaction.user.name} used /satisfaction")

    if int(interaction.user.id) not in allowed_users:
        await interaction.response.send_message("You are not allowed to use this command!", ephemeral=True)
        return

    await interaction.response.defer()

    await interaction.followup.send("Fetching assets and requirements...")

    comp_requirements = fetch_requirements()
    satisfaction_counts = collections.Counter()

    async for assets in get_all_assets():
        user_items = assets.item_counts()

        for ship_counter, item_counter in comp_requirements:
            requirement_name = ", ".join([f"{key} x{value}" for key, value in ship_counter.items()])
            comp_items = copy.copy(user_items)
            satisfaction_counts[requirement_name] = 0

            while True:
                intersection = comp_items & item_counter
                if intersection.total() != item_counter.total():
                    break
                comp_items -= item_counter
                satisfaction_counts[requirement_name] += 1

    if comp_requirements:
        message = "**Satisfaction Counts:**\n"
        for i, (requirement_name, count) in enumerate(satisfaction_counts.items()):
            message += f"- Comp {i} x{count} (Ships: {requirement_name})\n"
    else:
        message = "No requirements provided!"

    await interaction.followup.send(message)


@bot.tree.command(name="missing", description="Check what is missing for each requirement set to be satisfied one more time.")
@command_error_handler
async def missing(interaction: Interaction):
    logger.info(f"{interaction.user.name} used /missing")

    if int(interaction.user.id) not in allowed_users:
        await interaction.response.send_message("You are not allowed to use this command!", ephemeral=True)
        return

    await interaction.response.defer()
    await interaction.followup.send("Fetching assets and requirements...")

    comp_requirements = fetch_requirements()

    async for assets in get_all_assets():
        user_items = assets.item_counts()

        for i, (ship_counter, item_counter) in enumerate(comp_requirements):
            comp_items = copy.copy(user_items)
            satisfaction_count = 0

            while True:
                intersection = comp_items & item_counter
                if intersection.total() != item_counter.total():
                    missing_items = item_counter - intersection
                    break
                comp_items -= item_counter
                satisfaction_count += 1

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

            await interaction.followup.send(message)

    if not comp_requirements:
        await interaction.followup.send("No requirements provided.")


@bot.tree.command(name="all", description="Check what is missing for each requirement set to be satisfied one more time.")
@command_error_handler
async def all(interaction: Interaction):
    logger.info(f"{interaction.user.name} used /all")

    if int(interaction.user.id) not in allowed_users:
        await interaction.response.send_message("You are not allowed to use this command!", ephemeral=True)
        return

    await interaction.response.defer()
    await interaction.followup.send("Fetching assets and requirements...")

    comp_requirements = fetch_requirements()
    all_missing_items = collections.Counter()

    async for assets in get_all_assets():
        user_items = assets.item_counts()

        for i, (ship_counter, item_counter) in enumerate(comp_requirements):
            comp_items = copy.copy(user_items)
            satisfaction_count = 0

            while True:
                intersection = comp_items & item_counter
                if intersection.total() != item_counter.total():
                    missing_items = item_counter - intersection
                    break
                comp_items -= item_counter
                satisfaction_count += 1

            requirement_name = ", ".join([f"{key} x{value}" for key, value in ship_counter.items()])

            if satisfaction_count > 0:
                message = f"**Comp {i} is satisfied {satisfaction_count} times (Ships: {requirement_name})**\n"
            else:
                all_missing_items = all_missing_items | missing_items
                message = f"**Comp {i} is not satisfied yet (Ships: {requirement_name})**\n"

            await interaction.followup.send(message)

        message = f"**Total missing items to run everything once**\n```"
        for item, count in all_missing_items.items():
            message += f"{item} x{count}\n"
        message += "```"

        await interaction.followup.send(message)

    if not comp_requirements:
        await interaction.followup.send("No requirements provided.")



if __name__ == "__main__":
    bot.run(os.environ["DISCORD_TOKEN"])
