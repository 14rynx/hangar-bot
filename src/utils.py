import logging

from preston import Preston

logger = logging.getLogger("discord.main.utils")
import functools


async def lookup(preston, string, return_type):
    """Tries to find an ID related to the input.

    Parameters
    ----------
    string : str
        The character / corporation / alliance name
    return_type : str
        what kind of id should be tried to match
        can be characters, corporations and alliances

    Raises
    ------
    ValueError if the name can't be resolved
    """
    try:
        return int(string)
    except ValueError:
        try:
            result = preston.post_op(
                'post_universe_ids',
                path_data={},
                post_data=[string]
            )
            return int(max(result[return_type], key=lambda x: x["id"])["id"])
        except (ValueError, KeyError):
            raise ValueError("Could not parse that character!")


def command_error_handler(func):
    """Decorator for handling bot command logging and exceptions."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        interaction, *arguments = args
        logger.info(f"{interaction.user.name} used /{func.__name__} {arguments} {kwargs}")

        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in /{func.__name__} command: {e}", exc_info=True)

    return wrapper


async def send_large_followup(interaction, message, max_chars=1994, delimiter='\n', **kwargs):
    """
    Safely sends a message longer than Discord's character limit by splitting it
    while preserving code block integrity.

    Parameters:
        interaction (discord.Interaction): The interaction to reply to.
        message (str): The message to send (potentially long).
        max_chars (int): Max allowed characters per message (default: 1994 for safety).
        delimiter (str): Preferred splitting character (default: newline).
        **kwargs: Extra arguments forwarded to followup.send (like ephemeral=True).
    """
    open_code_block = False

    while len(message) > 0:
        if len(message) <= max_chars:
            if open_code_block:
                message = f"```{message}"
            await interaction.followup.send(message, **kwargs)
            break

        # Find last delimiter within limit
        last_delim_index = message.rfind(delimiter, 0, max_chars)
        if last_delim_index == -1:
            part = message[:max_chars]
            message = message[max_chars:]
        else:
            part = message[:last_delim_index]
            message = message[last_delim_index + 1:]

        # Handle code blocks
        code_block_count = part.count("```")
        if open_code_block:
            part = f"```{part}"
        if code_block_count % 2 == 1:
            open_code_block = not open_code_block
        if open_code_block:
            part = f"{part}```"

        await interaction.followup.send(part, **kwargs)
