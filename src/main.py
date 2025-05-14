import collections
import logging
import os
import secrets
from io import BytesIO, StringIO
from typing import Literal

import discord
import requests
from discord import Interaction, app_commands
from discord.ext import commands
from preston import Preston

from assets import Assets
from callback_server import callback_server
from models import initialize_database, User, Challenge, CorporationCharacter, Character
from utils import lookup, command_error_handler

# Configure the logger
logger = logging.getLogger('discord.main')
logger.setLevel(logging.INFO)

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
intent = discord.Intents.default()
intent.messages = True
intent.message_content = True
bot = commands.Bot(command_prefix='!', intents=intent)


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


@bot.tree.command(name="state", description="Returns current ship state in YAML format.")
@command_error_handler
async def state(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    files_to_send = []

    async for assets in get_author_assets(interaction.user.id):
        filename = f"{assets.corporation_name if assets.is_corporation else assets.character_name}.yaml"
        yaml_text = assets.save_requirement()
        file = discord.File(StringIO(yaml_text), filename=filename)
        files_to_send.append(file)

    if files_to_send:
        await interaction.followup.send("Here are your current ship states.", files=files_to_send, ephemeral=True)
    else:
        await interaction.followup.send("You have no authorized characters!", ephemeral=True)


@bot.tree.command(name="check", description="Returns list of ships missing required items.")
@command_error_handler
async def check(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)

    user = User.get_or_none(User.user_id == str(interaction.user.id))

    if user is None:
        await interaction.response.send_message("You are not a registered user!")
        return

    update_requirements(user)

    if user.requirements_file is None:
        await interaction.response.send_message("You have not set a requirements file, use the !set command and upload one!")
        return

    has_characters = False
    has_errors = False
    message = ""

    async for assets in get_author_assets(str(interaction.user.id)):
        has_characters = True
        name = f"\n## {assets.corporation_name if assets.is_corporation else assets.character_name}:\n"
        user = User.get_or_none(User.user_id == str(interaction.user.id))

        if user and user.requirements_file:
            for ship_error_message in assets.check_requirement(user.requirements_file):
                has_errors = True
                if len(message) + len(ship_error_message) + len(name) > 1990:
                    await interaction.followup.send(message)
                    message = ""
                if name:
                    message += name
                    name = ""
                message += f"{ship_error_message}\n"
        else:
            await interaction.followup.send(
                "You have not set a requirements file. Use `/set` and upload one!", ephemeral=True
            )

    if not has_characters:
        await  interaction.followup.send("You have no authorized characters!", ephemeral=True)
        return


    if has_errors:
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.followup.send("**No State Errors found!**", ephemeral=True)



@bot.tree.command(name="buy", description="Returns a multibuy of missing items in your ships.")
@command_error_handler
async def buy(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    buy_list = collections.Counter()
    has_characters = False

    user = User.get_or_none(User.user_id == str(interaction.user.id))
    if user is None:
        await interaction.followup.send("You are not a registered user!")
        return

    update_requirements(user)

    if user.requirements_file is None:
        await interaction.followup.send("You have not set a requirements file, use the !set command and upload one!")
        return

    async for assets in get_author_assets(interaction.user.id):
        has_characters = True
        user = User.get_or_none(User.user_id == str(interaction.user.id))
        if user and user.requirements_file:
            buy_list = assets.get_buy_list(user.requirements_file, buy_list=buy_list)
        else:
            await interaction.followup.send(
                "You have not set a requirements file. Use `/set` and upload one!", ephemeral=True
            )

    if not has_characters:
        await interaction.followup.send("You have no authorized characters!", ephemeral=True)
        return

    buy_list_body = "\n".join(f"{item} {amount}" for item, amount in buy_list.items())
    
    if buy_list_body:
        await interaction.followup.send(f"**Buy List:**\n```{buy_list_body}```", ephemeral=True)
    else:
        await interaction.followup.send(
            "**Nothing to buy!**", ephemeral=True
        )


@bot.tree.command(name="set", description="Set your requirement file.")
@app_commands.describe(attachment="Your requirements.yaml file")
@command_error_handler
async def set(interaction: Interaction, attachment: discord.Attachment):
    await interaction.response.defer(ephemeral=True)

    if not attachment:
        await interaction.followup.send("You forgot to attach a new requirement file!")
        return

    response = requests.get(attachment.url)
    content = response.content.decode("utf-8")
    user = User.get_or_none(user_id=str(interaction.user.id))
    if user is None:
        await interaction.followup.send("You currently have no linked characters, so having requirements makes no sense.")
        return

    if user.update_url:
        await interaction.followup.send("Setting a requirements file doesn't make sense as you have an update-url. Unset that first.")
        return

    user.requirements_file = content
    user.save()
    await interaction.followup.send("Set new requirements file!", ephemeral=True)


@bot.tree.command(name="get", description="Download your current requirement file.")
@command_error_handler
async def get(interaction: Interaction):
    user = User.get_or_none(User.user_id == str(interaction.user.id))

    if user is None:
        await interaction.response.send_message("You are not a registered user!")
        return

    update_requirements(user)

    if user.requirements_file is None:
        await interaction.response.send_message("You have not set a requirements file, use the !set command and upload one!")
        return

    requirements = discord.File(
        fp=BytesIO(user.requirements_file.encode('utf-8')),
        filename="requirements.yaml"
    )
    await interaction.response.send_message("Here is your current requirement file.", file=requirements, ephemeral=True)


@bot.tree.command(name="auth", description="Sends you an ESI authorization link.")
@app_commands.describe(corporation="Authorize a character for your corporation instead of a personal one.")
@command_error_handler
async def auth(interaction: Interaction, corporation: bool = False):
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


@bot.tree.command(name="url", description="Add an URL to get requirements from.")
@command_error_handler
async def url(interaction: Interaction, url: str | None = None):
    """Set an url from which to update your requirements file before other actions."""
    # Upsert the user's requirements file into the database
    user = User.get_or_none(user_id=str(interaction.user.id))
    if user:
        user.update_url = url
        user.save()
        await interaction.response.send_message("Set new update url!")
    else:
        await interaction.response.send_message("You currently have no linked characters, so having an update url makes no sense.")


if __name__ == "__main__":
    bot.run(os.environ["DISCORD_TOKEN"])
