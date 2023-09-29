import os
import secrets
import shelve
import sys
import threading
from io import BytesIO

import discord
import requests
from waitress import serve

from assets import Assets

# Fix for Mutable Mapping collection being moved
if sys.version_info.major == 3 and sys.version_info.minor >= 10:
    import collections

    setattr(collections, "MutableMapping", collections.abc.MutableMapping)
    setattr(collections, "Mapping", collections.abc.Mapping)

from esipy import EsiApp
from esipy import EsiClient
from esipy import EsiSecurity

from flask import Flask
from flask import request

# Setup Server
flask_app = Flask(__name__)

# Setup ESI
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

# Setup Discord
discord_intent = discord.Intents.default()
discord_intent.messages = True
discord_intent.message_content = True
discord_client = discord.Client(intents=discord_intent)

# Setup temporary storage
state_author = {}


# Server Functionality
@flask_app.route("/")
def hello_world():
    return "<p>Hangar Script Callback Server</p>"


@flask_app.route('/callback/')
def callback():
    # get the code from the login process
    code = request.args.get('code')
    state = request.args.get('state')

    try:
        author_id = str(state_author[state])
    except KeyError:
        return 'Authentication failed: State Missmatch', 403

    tokens = esi_security.auth(code)

    character_data = esi_security.verify()
    character_id = character_data["sub"].split(':')[-1]
    character_name = character_data["name"]

    # Store tokens under author
    with shelve.open('../data/tokens', writeback=True) as author_character_tokens:
        if author_id not in author_character_tokens:
            author_character_tokens[author_id] = {character_id: tokens}
        else:
            author_character_tokens[author_id][character_id] = tokens

    return f"<p>Sucessfully authentiated {character_name}!</p>"


# Discord Functionality
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


async def send_maybe_file(send_object, text):
    if len(text) < 2000:
        await send_object.send(text)
    else:
        await send_object.send("Message to big, sending file instead.", file=discord.File(BytesIO(text), "message.md"))


@discord_client.event
async def on_ready():
    print(f'We have logged in as {discord_client.user}')


@discord_client.event
async def on_message(message):
    if message.author == discord_client.user:  # It is our own message
        return

    if message.content.startswith("!auth"):
        state = secrets.token_urlsafe(30)
        state_author[state] = message.author.id
        uri = esi_security.get_auth_uri(state=state, scopes=['esi-assets.read_assets.v1'])
        await message.author.send(
            f"Use this [authentication link]({uri}) to authorize your characters."
        )

    if message.content.startswith("!state"):
        files_to_send = []
        for assets in get_author_assets(str(message.author.id)):
            assets.save_state(f"data/states/{assets.character_name}.yaml")
            with open(f"data/states/{assets.character_name}.yaml", "rb") as file:
                files_to_send.append(discord.File(file, filename=f"{assets.character_name}.yaml"))

        if files_to_send:
            await message.channel.send("Here are your current Ships", files=files_to_send)
        else:
            await message.channel.send("You have no authorized characters!")

    if message.content.startswith("!check"):
        try:
            state_errors = []
            has_characters = False
            for assets in get_author_assets(str(message.author.id)):
                state_error_body = assets.check_state(f"data/reqs/{message.author.id}.yaml")
                if state_error_body:
                    state_errors.append(f"**{assets.character_name}:**\n{state_error_body}")
                has_characters = True

            state_errors_body = "\n\n".join(state_errors)
            if state_errors_body:
                await send_maybe_file(message.channel, f"**State Errors:**\n{state_errors_body}")
            else:
                if has_characters:
                    await message.channel.send("**No State Errors found!**")
                else:
                    await message.channel.send("You have no authorized characters!")
        except FileNotFoundError:
            await message.channel.send("You have not set a requirements file, use the !set command and upload one!")

    if message.content.startswith("!buy"):
        try:
            buy_list = collections.defaultdict(int)
            has_characters = False
            for assets in get_author_assets(str(message.author.id)):
                buy_list = assets.get_buy_list(f"data/reqs/{message.author.id}.yaml", buy_list=buy_list)
                has_characters = True

            buy_list_body = "\n".join([f"{item} {amount}" for item, amount in buy_list.items()])
            if buy_list_body:
                await send_maybe_file(message.channel, f"**Buy List:**\n```{buy_list_body}```")
            else:
                if has_characters:
                    await message.channel.send("**Nothing to buy!**")
                else:
                    await message.channel.send("You have no authorized characters!")
        except FileNotFoundError:
            await message.channel.send("You have not set a requirements file, use the !set command and upload one!")

    if message.content.startswith("!set"):
        try:
            if message.attachments[0].url:
                response = requests.get(message.attachments[0].url, allow_redirects=True)
                with open(f"data/reqs/{message.author.id}.yaml", 'wb') as file:
                    file.write(response.content)
            await message.channel.send("Set new requirements file!")
        except (KeyError, IndexError):
            await message.channel.send("You forgot to attach a new requirement file!")

    if message.content.startswith("!characters"):
        author_id = str(message.author.id)
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
            await message.channel.send(f"You have the following character(s) authenticated:\n{character_names_body}")
        else:
            await message.channel.send("You have no authorized characters!")

    if message.content.startswith("!revoke"):
        author_id = str(message.author.id)
        with shelve.open('../data/tokens', writeback=True) as author_character_tokens:
            for character_id, tokens in author_character_tokens[author_id].items():
                esi_security.update_token(tokens)
                esi_security.refresh()
                esi_security.revoke()

            author_character_tokens[author_id] = {}

        await message.channel.send("Revoked all characters(') API access!\n")


if __name__ == "__main__":
    threading.Thread(target=lambda: serve(flask_app, port=80)).start()
    discord_client.run(os.environ["DISCORD_TOKEN"])
