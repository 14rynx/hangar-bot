import logging

from aiohttp import web
from discord.ext import tasks
from preston import Preston

from models import User, Character, Challenge, CorporationCharacter

# Configure the logger
logger = logging.getLogger('callback')
logger.setLevel(logging.INFO)


@tasks.loop()
async def callback_server(preston: Preston):
    routes = web.RouteTableDef()

    @routes.get('/')
    async def hello(request):
        return web.Response(text="Hangar Script Callback Server")

    @routes.get('/callback/')
    async def callback(request):
        # Get the code and state from the login process
        code = request.query.get('code')
        state = request.query.get('state')

        # Verify the state and get the user ID
        challenge = Challenge.get_or_none(Challenge.state == state)
        if not challenge:
            logger.warning("Failed to verify challenge")
            return web.Response(text="Authentication failed: State mismatch", status=403)

        # Authenticate using the code
        try:
            auth = preston.authenticate(code)
        except Exception as e:
            logger.error(e)
            logger.warning("Failed to verify token")
            return web.Response(text="Authentication failed!", status=403)

        # Get character data
        character_data = auth.whoami()
        character_id = character_data["character_id"]
        character_name = character_data["character_name"]
        scopes = character_data["scopes"]

        # Create / Update user and store refresh_token
        user, user_created = User.get_or_create(user_id=challenge.user.user_id)

        if scopes == "esi-assets.read_corporation_assets.v1":

            corporation_id = preston.get_op('get_characters_character_id', character_id=character_id).get(
                "corporation_id")

            corporation_character, created = CorporationCharacter.get_or_create(
                character_id=character_id, user=user,
                defaults={"corporation_id": corporation_id, "token": auth.refresh_token}
            )
            corporation_character.corporation_id = corporation_id
            corporation_character.token = auth.refresh_token
            corporation_character.save()

        elif scopes == "esi-assets.read_assets.v1":
            character, created = Character.get_or_create(
                character_id=character_id, user=user,
                defaults={"token": auth.refresh_token}
            )
            character.token = auth.refresh_token
            character.save()

        else:
            return web.Response(text=f"Invalid scope for {character_name}!", status=400)

        logger.info(f"Added character {character_id}")
        if created:
            return web.Response(text=f"Successfully authenticated {character_name}!")
        else:
            return web.Response(text=f"Successfully re-authenticated {character_name}!")

    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, port=80)
    await site.start()
