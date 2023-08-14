import asyncio
from collections import defaultdict

import yaml
from tqdm.asyncio import tqdm_asyncio

from esi.endpoints import get_item_name, get_names, get_assets


class Assets:
    def __init__(self, character_id, access_token, character=True):

        self.character_id = character_id
        self.access_token = access_token
        if character:
            self.assets = asyncio.run(get_assets(character_id, access_token))
        else:
            raise NotImplementedError
        self.groups = asyncio.run(self.generate_groups())
        self.types = asyncio.run(self.generate_types())
        self.names = self.generate_names()

    @staticmethod
    async def _group_helper(asset, containers):
        asset_name = await get_item_name(asset["type_id"])
        if asset["location_flag"] == "Cargo" or asset["location_flag"] == "DroneBay":
            if asset["location_id"] not in containers:
                containers[asset["location_id"]] = defaultdict(int)
            containers[asset["location_id"]][asset_name] += asset.get("quantity", 1)

    #  Sum Assets Grouped by Container (Ship)
    async def generate_groups(self):
        containers = {}
        tasks = [self._group_helper(asset, containers) for asset in self.assets]
        await tqdm_asyncio.gather(*tasks)
        return containers

    @staticmethod
    async def _type_helper(i, t):
        return i, await get_item_name(t)

    async def generate_types(self):
        """Returns a id: type dictionary for all containers"""
        tasks = []
        for asset in self.assets:
            if asset["item_id"] in self.groups.keys():
                tasks.append(self._type_helper(asset["item_id"], asset["type_id"]))

        return {i: t for i, t in await tqdm_asyncio.gather(*tasks)}

    def generate_names(self):
        """Returns a id: given_name dictionary for all containers"""
        container_names = {}
        for item_data in asyncio.run(get_names(list(self.groups), self.character_id, self.access_token)):
            name = item_data["name"]
            name = name.replace("&gt;", ">")
            name = name.replace("&lt;", "<")

            container_names.update({item_data["item_id"]: name})
        return container_names

    @property
    def state(self):
        # Generate the dictionary representation
        state = {}
        for container_item_id, items in self.groups.items():
            shipname = f"{self.names[container_item_id]} ({self.types[container_item_id]}):"

            contents = {}
            for item, amount in sorted(items.items(), key=lambda x: x[0]):
                contents.update({item: amount})

            if shipname not in state:
                state.update({shipname: contents})
            elif sum(items.values()) > sum(state[shipname].values()):
                state.update({shipname: contents})

        return state

    def check_state(self, requirement_path):
        """Checks the state according to the requirements and returns any mismatches"""
        with open(requirement_path, "r") as file:
            required = yaml.load(file, yaml.CLoader)
            for container_item_id, actual in self.groups.items():
                shipname = f"{self.names[container_item_id]} ({self.types[container_item_id]}):"

                output = ""

                if shipname in required:
                    for item, amount in required[shipname].items():
                        if not item in actual:
                            output += f" - {item} is completely missing ({amount} units)\n"
                        elif actual[item] < amount:
                            output += f" - {item} is missing {amount - actual[item]} units\n"

                if output != "":
                    print(f"{shipname}:\n{output}")

    def get_buy_list(self, requirement_path, buy_list=None):

        if buy_list is None:
            buy_list = defaultdict(int)
        """Checks the state according to the requirements and returns any mismatches"""
        with open(requirement_path, "r") as file:
            required = yaml.load(file, yaml.CLoader)
            for container_item_id, actual in self.groups.items():
                shipname = f"{self.names[container_item_id]} ({self.types[container_item_id]}):"

                if shipname in required:
                    for item, amount in required[shipname].items():
                        if not item in actual:
                            buy_list[item] += amount
                        elif actual[item] < amount:
                            buy_list[item] += amount - actual[item]
        return buy_list

    @staticmethod
    def print_buy_list(buy_list):
        for item, amount in buy_list.items():
            print(f"{item} {amount}")

    def filter_state(self, shipname):
        """Checks the state and returns the current one for a specific shipname.
        Usefull for incremental additions to the requirements"""
        for ship, data in self.state.items():
            if shipname in ship:
                print(yaml.dump({ship: data}))

    def save_state(self, requirement_path):
        with open(requirement_path, "w") as file:
            yaml.dump(self.state, file, yaml.CDumper)
