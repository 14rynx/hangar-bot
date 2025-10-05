import io
import logging
from collections import Counter

import discord

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


async def send_large_followup(interaction, message, max_chars=1994, delimiter='\n', files=None, **kwargs):
    """
    Safely sends a message longer than Discord's character limit by splitting it
    while preserving code block integrity.

    Parameters:
        interaction (discord.Interaction): The interaction to reply to.
        message (str): The message to send (potentially long).
        max_chars (int): Max allowed characters per message (default: 1994 for safety).
        delimiter (str): Preferred splitting character (default: newline).
        files (list): List of files to send.
        **kwargs: Extra arguments forwarded to followup.send (like ephemeral=True).
    """
    open_code_block = False

    while len(message) > 0:
        is_last = len(message) <= max_chars

        if is_last:
            part = message
            message = ""
        else:
            last_delim_index = message.rfind(delimiter, 0, max_chars)
            if last_delim_index == -1:
                part = message[:max_chars]
                message = message[max_chars:]
            else:
                part = message[:last_delim_index]
                message = message[last_delim_index + 1:]

        # Handle code block integrity
        code_block_count = part.count("```")
        if open_code_block:
            part = f"```{part}"
        if code_block_count % 2 == 1:
            open_code_block = not open_code_block
        if open_code_block:
            part = f"{part}```"

        # Only attach files to the final message
        if is_last:
            await interaction.followup.send(part, files=files, **kwargs)
        else:
            await interaction.followup.send(part, **kwargs)



def create_buy_list_file(items: Counter, name: str = "buy_list") -> discord.File:
    """
    Creates an in-memory text file containing the buy list.

    Parameters:
        items (Counter): Item name → quantity mapping.
        name (str): File name prefix.

    Returns:
        discord.File: The attachment ready to send.
    """
    content = ""
    for item, count in items.items():
        content += f"{item} x{count}\n"

    # Create in-memory file
    file_obj = io.BytesIO(content.encode())
    return discord.File(file_obj, filename=f"{name}.txt")
