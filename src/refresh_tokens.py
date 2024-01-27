import logging
import shelve

from discord.ext import tasks

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
                    esi_security.update_token(tokens)
                    author_character_tokens[user][character_id] = esi_security.refresh()


    except Exception as e:
        logger.error(f"Got an unhandled exception: {e}", exc_info=True)
