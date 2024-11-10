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


async def send_large_message(ctx, message, max_chars=2000):
    while len(message) > 0:
        if len(message) <= max_chars:
            await ctx.send(message)
            break

        last_newline_index = message.rfind('\n', 0, max_chars)

        if last_newline_index == -1:
            await ctx.send(message[:max_chars])
            message = message[max_chars:]
        else:
            await ctx.send(message[:last_newline_index])
            message = message[last_newline_index + 1:]
