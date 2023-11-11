import _gdbm
import os
import secrets
import shelve
import sys
import threading
from io import BytesIO

import discord
import requests
from discord.ext import commands

from assets import Assets
from server import callback_server

# Fix for Mutable Mapping collection being moved
if sys.version_info.major == 3 and sys.version_info.minor >= 10:
    import collections

    setattr(collections, "MutableMapping", collections.abc.MutableMapping)
    setattr(collections, "Mapping", collections.abc.Mapping)

from esipy import EsiApp
from esipy import EsiClient
from esipy import EsiSecurity
from esipy.exceptions import APIException

esi_app = EsiApp().get_latest_swagger
esi_security = EsiSecurity(
    redirect_uri=os.environ["CCP_REDIRECT_URI"],
    client_id=os.environ["CCP_CLIENT_ID"],
    secret_key=os.environ["CCP_SECRET_KEY"],
    headers={'User-Agent': 'Hangar organizing discord bot by larynx.austrene@gmail.com'},
)

esi_client = EsiClient(
    retry_requests=True,
    headers={'User-Agent': 'Hangar organizing discord bot by larynx.austrene@gmail.com'},
    security=esi_security
)

intent = discord.Intents.default()
intent.messages = True
intent.message_content = True
bot = commands.Bot(command_prefix='!', intents=intent)


def get_author_assets(author_id: str):
    with shelve.open('../data/tokens', writeback=True) as author_character_tokens:
        for character_id, tokens in author_character_tokens[author_id].items():
            esi_security.update_token(tokens)
            tokens = esi_security.refresh()
            author_character_tokens[author_id][character_id] = tokens

            character_data = esi_security.verify()
            character_id = character_data["sub"].split(':')[-1]
            character_name = character_data["name"]

            assets = Assets(character_id, esi_app, esi_client, character_name=character_name)
            yield assets


async def send_large_message(send_object, text):
    if len(text) < 2000:
        await send_object.send(text)
    else:
        await send_object.send("Message to big, sending file instead.", file=discord.File(BytesIO(text), "message.md"))


@bot.command()
async def auth(ctx):
    try:
        secret_state = secrets.token_urlsafe(30)
        with shelve.open('../data/challenges', writeback=True) as challenges:
            challenges[secret_state] = ctx.author.id
        uri = esi_security.get_auth_uri(state=secret_state, scopes=['esi-assets.read_assets.v1'])
        await ctx.author.send(f"Use this [authentication link]({uri}) to authorize your characters.")
    except _gdbm.error:
        await ctx.send("Currently busy with another command!")


@bot.command()
async def state(ctx):
    try:
        files_to_send = []
        for assets in get_author_assets(str(ctx.author.id)):
            assets.save_state(f"data/states/{assets.character_name}.yaml")
            with open(f"data/states/{assets.character_name}.yaml", "rb") as file:
                files_to_send.append(discord.File(file, filename=f"{assets.character_name}.yaml"))

        if files_to_send:
            await ctx.send("Here are your current Ships", files=files_to_send)
        else:
            await ctx.send("You have no authorized characters!")
    except APIException:
        await ctx.send("Authorization ran out!")
    except _gdbm.error:
        await ctx.send("Currently busy with another command!")


@bot.command()
async def check(ctx):
    try:
        state_errors = []
        has_characters = False
        for assets in get_author_assets(str(ctx.author.id)):
            state_error_body = assets.check_state(f"data/reqs/{ctx.author.id}.yaml")
            if state_error_body:
                state_errors.append(f"**{assets.character_name}:**\n{state_error_body}")
            has_characters = True

        state_errors_body = "\n\n".join(state_errors)
        if state_errors_body:
            await send_large_message(ctx, f"**State Errors:**\n{state_errors_body}")
        else:
            if has_characters:
                await ctx.send("**No State Errors found!**")
            else:
                await ctx.send("You have no authorized characters!")
    except FileNotFoundError:
        await ctx.send("You have not set a requirements file, use the !set command and upload one!")
    except APIException:
        await ctx.send("Authorization ran out!")
    except _gdbm.error:
        await ctx.send("Currently busy with another command!")


@bot.command()
async def buy(ctx):
    try:
        buy_list = collections.defaultdict(int)
        has_characters = False
        for assets in get_author_assets(str(ctx.author.id)):
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
    except APIException:
        await ctx.send("Authorization ran out!")
    except _gdbm.error:
        await ctx.send("Currently busy with another command!")


@bot.command()
async def set(ctx):
    try:
        if ctx.attachments[0].url:
            response = requests.get(ctx.attachments[0].url, allow_redirects=True)
            with open(f"data/reqs/{ctx.author.id}.yaml", 'wb') as file:
                file.write(response.content)
        await ctx.send("Set new requirements file!")
    except (KeyError, IndexError):
        await ctx.send("You forgot to attach a new requirement file!")
    except _gdbm.error:
        await ctx.send("Currently busy with another command!")


@bot.command()
async def characters(ctx):
    try:
        author_id = str(ctx.author.id)
        character_names = []
        with shelve.open('../data/tokens', writeback=True) as author_character_tokens:
            for character_id, tokens in author_character_tokens[author_id].items():
                esi_security.update_token(tokens)
                tokens = esi_security.refresh()
                author_character_tokens[author_id][character_id] = tokens

                character_data = esi_security.verify()
                character_names.append(character_data["name"])

        if character_names:
            character_names_body = "\n".join(character_names)
            await ctx.send(f"You have the following character(s) authenticated:\n{character_names_body}")
        else:
            await ctx.send("You have no authorized characters!")
    except APIException:
        await ctx.send("Authorization ran out!")
    except _gdbm.error:
        await ctx.send("Currently busy with another command!")


@bot.command()
async def revoke(ctx):
    try:
        author_id = str(ctx.author.id)
        with shelve.open('../data/tokens', writeback=True) as author_character_tokens:
            for character_id, tokens in author_character_tokens[author_id].items():
                try:
                    esi_security.update_token(tokens)
                    esi_security.refresh()
                    esi_security.revoke()
                except APIException:
                    pass

            author_character_tokens[author_id] = {}

        await ctx.send("Revoked all characters(') API access!\n")
    except _gdbm.error:
        await ctx.send("Currently busy with another command!")


if __name__ == "__main__":
    callback_server = threading.Thread(target=lambda: callback_server(esi_security))
    callback_server.start()
    bot.run(os.environ["DISCORD_TOKEN"])
