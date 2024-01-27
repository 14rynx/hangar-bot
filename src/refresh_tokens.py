import logging
import shelve
import sys

# Fix for Mutable Mapping collection being moved
if sys.version_info.major == 3 and sys.version_info.minor >= 10:
    import collections

    setattr(collections, "MutableMapping", collections.abc.MutableMapping)
    setattr(collections, "Mapping", collections.abc.Mapping)

from discord.ext import tasks
from esipy.exceptions import APIException

# Configure the logger
logger = logging.getLogger('discord.refresh')
logger.setLevel(logging.INFO)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)


@tasks.loop(hours=49)
async def refresh_tokens(esi_security):
    """Periodically fetch structure state apu from ESI"""

    logger.info("refreshing_tokens")

    try:
        with shelve.open('../data/tokens', writeback=True) as author_character_tokens:
            for user, characters in author_character_tokens.items():
                for character_id, tokens in characters.items():
                    try:
                        esi_security.update_token(tokens)
                        author_character_tokens[user][character_id] = esi_security.refresh()
                    except APIException:
                        # Tokens are already expired somehow -> let the user fix it
                        pass


    except Exception as e:
        logger.error(f"Got an unhandled exception: {e}", exc_info=True)
