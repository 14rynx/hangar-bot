import collections
import copy
import logging
import os
import secrets
from collections import Counter
from typing import Literal, Optional

import discord
import requests
from discord import Interaction, app_commands
from discord.ext import commands
from preston import Preston

from assets import Assets
from callback_server import callback_server
from models import initialize_database, User, Challenge, CorporationCharacter, Character
from sheet import fetch_requirements
from utils import lookup, command_error_handler, send_large_followup

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
    total_items = collections.Counter()

    for user in User.select():
        for character in user.characters:
            a = Assets(base_preston.authenticate_from_token(character.token))
            await a.fetch()
            total_items += a.item_counts()

        for corporation_character in user.corporation_characters:
            try:
                a = Assets(corp_base_preston.authenticate_from_token(corporation_character.token))
                await a.fetch()
            except AssertionError:
                corporation_character.delete_instance()
            else:
                total_items += a.item_counts()

    return total_items


def calc_total_requirements(comp_requirements: Counter):
    """Figure out max set requirement for all comps"""
    total = Counter()
    for r in comp_requirements.values():
        total = r | total
    return total


def calc_archetype_requirements(comp_requirements: Counter, comp_archetypes: list[list[str]]):
    """ Figure out archetype requirement per comp"""
    comp_archetype_requirements = {}
    for a in comp_archetypes:
        rx = Counter()
        for c in a:
            rx = rx | comp_requirements[c]
        # Split loop is important
        for c in a:
            comp_archetype_requirements[c] = rx

    return comp_archetype_requirements


def req_runs(
        total_items: Counter,
        requirement: Counter
):
    """Returns how many times we have a requirement and what is missing"""
    spare_items = copy.copy(total_items)
    satisfaction_count = 0

    while True:
        intersection = spare_items & total_items
        if intersection.total() != total_items.total():
            missing_items = total_items - intersection
            return missing_items, satisfaction_count
        spare_items -= requirement
        satisfaction_count += 1


def req_after_req_runs(
        total_items: Counter,
        second_req: Counter,
        first_repeated_req: Counter
):
    """Returns how many times we can repeat req1 before req2 does not work anymore."""
    spare_items = copy.copy(total_items)
    satisfaction_count = 0

    iter_requirement = Counter(
        {item: max(second_req[item], first_repeated_req.get(item, 0)) for item in second_req})

    while True:
        intersection = spare_items & total_items
        if intersection.total() != total_items.total():
            missing_items = total_items - intersection
            return missing_items, satisfaction_count - 1
        spare_items -= iter_requirement
        satisfaction_count += 1


def buy_list(items: Counter):
    message = f"```"
    for item, count in items.items():
        message += f"{item} x{count}\n"
    message += "```"
    return message


@bot.tree.command(name="all", description="Display items required to run any comp one time")
@command_error_handler
async def all(interaction: Interaction):
    logger.info(f"{interaction.user.name} used /all")

    if int(interaction.user.id) not in allowed_users:
        await interaction.response.send_message("You are not allowed to use this command!", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    total_items = await get_all_assets()
    comp_requirements, _ = fetch_requirements()
    total_requirements = calc_total_requirements(comp_requirements)

    missing_items, satisfaction_count = req_runs(total_items, total_requirements)
    message = f"We can run any comp {satisfaction_count} times.\n+1 means buying\n"
    message += buy_list(missing_items)

    message += f"If we want to buy a full set\n"
    message += buy_list(total_requirements)

    await send_large_followup(interaction, message, ephemeral=True)


@bot.tree.command(name="comps", description="Break down per comp what we have")
@app_commands.describe(
    selected_comp_name="Only display items for that comp id"
)
@command_error_handler
async def comps(interaction: Interaction, selected_comp_name: Optional[str] = None):
    logger.info(f"{interaction.user.name} used /comps")

    if int(interaction.user.id) not in allowed_users:
        await interaction.response.send_message("You are not allowed to use this command!", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    total_items = await get_all_assets()
    comp_requirements, comp_archetypes = fetch_requirements()
    total_requirements = calc_total_requirements(comp_requirements)
    comp_archetype_requirements = calc_archetype_requirements(comp_archetypes, comp_archetypes)

    for comp_name, comp_requirement in comp_requirements.items():
        if selected_comp_name is not None:
            if comp_name != selected_comp_name:
                continue

        archetype_id = -1
        for i, a in enumerate(comp_archetypes):
            if comp_name in a:
                archetype_id = i

        message = f"**Comp `{comp_name}`** (A {archetype_id})\n"

        missing_items, satisfaction_count = req_runs(total_items, comp_requirement)
        message += f"- Can be run standalone {satisfaction_count} times.\n"
        if selected_comp_name is not None:
            message += "  +1 means buying\n"
            message += buy_list(missing_items)

        missing_items, satisfaction_count = req_after_req_runs(total_items, comp_requirement, total_requirements)
        message += f"- We can run any other comp {satisfaction_count} times befoe running this comp once.\n"
        if selected_comp_name is not None:
            message += "  +1 means buying\n"
            message += buy_list(missing_items)

        missing_items, satisfaction_count = req_after_req_runs(total_items, comp_requirement,
                                                               comp_archetype_requirements[comp_name])
        message += f"- We can run a comp in this archetype {satisfaction_count} times befoe running this comp once.\n"
        if selected_comp_name is not None:
            message += "  +1 means buying\n"
            message += buy_list(missing_items)

        if selected_comp_name is not None:
            message += f"- Standalone +1 means buying\n"
            message += buy_list(comp_requirement)

        await send_large_followup(interaction, message, ephemeral=True)


@bot.tree.command(name="comps", description="Break down per arcehtype what we have")
@app_commands.describe(
    only_archetype="Display details for this archetype",
)
@command_error_handler
async def archetypes(interaction: Interaction, only_archetype: Optional[int] = None):
    if int(interaction.user.id) not in allowed_users:
        await interaction.response.send_message("You are not allowed to use this command!", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    total_items = await get_all_assets()
    comp_requirements, comp_archetypes = fetch_requirements()
    total_requirements = calc_total_requirements(comp_requirements)
    comp_archetype_requirements = calc_archetype_requirements(comp_archetypes, comp_archetypes)

    for i, arch_comps in comp_archetypes.items():
        if only_archetype is not None:
            if only_archetype != i:
                continue

        message = f"**Archetype {i}**\n"

        message += f"- Comps:\n"
        for comp_name in arch_comps:
            message += f" - {comp_name}\n"

        missing_items, satisfaction_count = req_runs(total_items, comp_archetype_requirements[arch_comps[0]])
        message += f"- Can be run standalone {satisfaction_count} times.\n"
        if only_archetype is not None:
            message += "  +1 means buying\n"
            message += buy_list(missing_items)

        missing_items, satisfaction_count = req_after_req_runs(total_items, comp_archetype_requirements[arch_comps[0]],
                                                               total_requirements)
        message += f"- We can run any other comp {satisfaction_count} times befoe running this arechetype once.\n"
        if only_archetype is not None:
            message += "  +1 means buying\n"
            message += buy_list(missing_items)

        if only_archetype is not None:
            message += f"- Standalone +1 means buying\n"
            message += buy_list(comp_archetype_requirements[arch_comps[0]])

        await send_large_followup(interaction, message, ephemeral=True)


if __name__ == "__main__":
    bot.run(os.environ["DISCORD_TOKEN"])
