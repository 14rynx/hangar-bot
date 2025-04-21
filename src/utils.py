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


def with_refresh(preston_instance, refresh_token: str):
    new_kwargs = dict(preston_instance._kwargs)
    new_kwargs["refresh_token"] = refresh_token
    new_kwargs["access_token"] = None
    return Preston(**new_kwargs)


def command_error_handler(func):
    """Decorator for handling bot command logging and exceptions."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        interaction, *arguments = args
        logger.info(f"{interaction.user.name} used !{func.__name__} {arguments} {kwargs}")

        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in !{func.__name__} command: {e}", exc_info=True)

    return wrapper
