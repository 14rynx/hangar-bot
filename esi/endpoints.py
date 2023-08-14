import json
import ssl
from json import JSONDecodeError

import aiohttp
import certifi
from aiocache import cached

ssl_context = ssl.create_default_context(cafile=certifi.where())


@cached()
async def get_assets(character_id, access_token):
    headers = {
        "Authorization": "Bearer {}".format(access_token)
    }

    assets = []
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        for page in range(100000):
            async with session.get(f"https://esi.evetech.net/latest/characters/{character_id}/assets/?page={page}",
                                   headers=headers) as response:
                if response.status == 200:
                    batch = await response.json(content_type=None)
                    assets.extend(batch)
                    if len(batch) < 1000:
                        return assets


@cached()
async def get_names(asset_ids, character_id, access_token):
    headers = {
        "Authorization": "Bearer {}".format(access_token)
    }

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        async with session.post(f"https://esi.evetech.net/latest/characters/{character_id}/assets/names/",
                                headers=headers,
                                data=json.dumps(asset_ids)) as response:
            if response.status == 200:
                return await response.json(content_type=None)
            else:
                print(await response.text())


@cached()
async def get_item_name(item_id):
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        try:
            async with session.get(f"https://esi.evetech.net/latest/universe/types/{item_id}/") as response:
                if response.status == 200:
                    return (await response.json(content_type=None))["name"]
        except (JSONDecodeError, KeyError) as e:
            print(f"Error: {e}")

        return f"Could not load item {item_id}"
