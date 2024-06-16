import logging
import shelve

from aiohttp import web
from discord.ext import tasks
from preston import preston

# Configure the logger
logger = logging.getLogger('callback')
logger.setLevel(logging.INFO)


@tasks.loop()
async def callback_server(preston: preston.Preston):
    routes = web.RouteTableDef()

    @routes.get('/')
    async def hello(request):
        return web.Response(text="Hangar Script Callback Server<")

    @routes.get('/callback/')
    async def callback(request):
        # get the code from the login process
        code = request.query.get('code')
        state = request.query.get('state')

        try:
            with shelve.open('../data/challenges', writeback=True) as challenges:
                author_id = str(challenges[state])
        except KeyError:
            logger.warning(f"failed to verify challenge")
            return web.Response(text="Authentication failed: State Missmatch", status=403)

        try:
            auth = preston.authenticate(code)
        except Exception as e:
            logger.error(e)
            logger.warning(f"failed to verify token")
            return web.Response(text="Authentication failed!", status=403)

        character_data = auth.whoami()
        logger.info(f"authenticated user data : {character_data}")

        character_id = character_data["CharacterID"]

        # Store tokens under author
        with shelve.open('../data/tokens', writeback=True) as author_character_tokens:
            if author_id not in author_character_tokens:
                author_character_tokens[author_id] = {character_id: auth.refresh_token}
            else:
                author_character_tokens[author_id][character_id] = auth.refresh_token

        logger.info(f"Added character {character_id}")

        character_name = character_data["CharacterName"]

        return web.Response(text=f"Sucessfully authentiated {character_name}!")

    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, port=80)
    await site.start()
