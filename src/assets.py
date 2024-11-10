import asyncio
from collections import Counter

import yaml


class Item:
    def __init__(self, item_id, is_singleton, location_flag, location_id, location_type, quantity, type_id, **kwargs):
        self.item_id = item_id
        self.is_singleton = is_singleton
        self.location_flag = location_flag
        self.location_id = location_id
        self.location_type = location_type
        self.quantity = quantity
        self.type_id = type_id
        self.subordinates = []
        self.name = ""
        self.type_name = ""

    def add_subordinate(self, subordinate):
        self.subordinates.append(subordinate)

    def __repr__(self):
        ret = f"Item(item_id={self.item_id}, type_id={self.type_id}"
        if self.name != "":
            ret += f", name={self.name}"
        if self.type_name != "":
            ret += f", type_name={self.type_name}"
        ret += ")"
        return ret

    @property
    def full_name(self):
        return f"{self.name} ({self.type_name})"

    @property
    def is_assembled_ship(self):
        return any(["Slot" in x.location_flag for x in self.subordinates])

    @property
    def is_top_level_container(self):
        # Top level container in hangar
        if self.location_flag == "Hangar" and self.location_type == "station":
            return True

        # Container in Corp Hangar
        if "CorpSAG" in self.location_flag:
            return True

        return False

    @property
    def item_counts(self):
        counter = Counter()

        for subordinate in self.subordinates:
            counter += Counter({subordinate.type_name: subordinate.quantity})
            counter += subordinate.item_counts

        return counter

    @property
    def total_item_count(self):
        return sum(self.item_counts.values())


class Assets:
    def __init__(self, preston):

        self.preston = preston

        # Set up initial info
        character_data = preston.whoami()
        self.character_id = character_data["CharacterID"]
        self.character_name = character_data["CharacterName"]
        self.is_corporation = character_data["Scopes"] == "esi-assets.read_corporation_assets.v1"

        if self.is_corporation:
            self.corporation_id = preston.get_op(
                'get_characters_character_id',
                character_id=self.character_id
            ).get("corporation_id")

            self.corporation_name = preston.get_op(
                'get_corporations_corporation_id',
                corporation_id=self.corporation_id
            ).get("name")

        self.items = []
        self.root_items = []
        self.items_of_interesst = []
        self.corp_hangars = []

    async def fetch(self):
        # Fetch all available assets
        page = 1
        while True:
            if self.is_corporation:
                result = self.preston.get_op('get_corporations_corporation_id_assets', corporation_id=self.corporation_id,
                                        page=page)
            else:
                result = self.preston.get_op('get_characters_character_id_assets', character_id=self.character_id, page=page)
            if "error" in result:
                if "Requested page does not exist!" in result["error"]:
                    break
                elif result["error"] == "Character does not have required role(s)":
                    raise AssertionError(result["error"])
            else:
                self.items.extend([Item(**x) for x in result])
                page += 1

            # Allow other things to catch up
            await asyncio.sleep(0.2)

        # Index items by id for quick finding
        id_items = {x.item_id: x for x in self.items}

        # Build a tree of all times
        for item in id_items.values():
            if item.location_id in id_items:
                id_items[item.location_id].add_subordinate(item)
            else:
                self.root_items.append(item)

        # Build list with ships
        self.items_of_interesst = [x for x in self.items if x.is_assembled_ship or x.is_top_level_container]

        # Fetch the name of each container root item e.g. ship and container
        if self.is_corporation:
            result = self.preston.post_op(
                'post_corporations_corporation_id_assets_names',
                path_data={"corporation_id": self.corporation_id},
                post_data=[x.item_id for x in self.items_of_interesst]
            )
        else:
            result = self.preston.post_op(
                'post_characters_character_id_assets_names',
                path_data={"character_id": self.character_id},
                post_data=[x.item_id for x in self.items_of_interesst]
            )

        try:
            for item_data in result:
                id_items[item_data["item_id"]].name = item_data["name"].replace("&gt;", ">").replace("&lt;", "<")
        except TypeError:
            pass

        # Fetch all type names and add them to the items
        type_ids = set([x.type_id for x in self.items])
        type_id_names = {}
        for type_id in type_ids:
            response = self.preston.get_op('get_universe_types_type_id', type_id=type_id)
            try:
                type_id_names[response["type_id"]] = response["name"]
            except KeyError:
                pass

        for item in self.items:
            item.type_name = type_id_names.get(item.type_id, "Unknown Item")

    def save_requirement(self):
        """Generates and returns the requirements as a YAML string."""
        state = {}
        for ship in self.items_of_interesst:
            # If there are multiple containers with the same name take the fullest one
            if ship.full_name not in state or ship.total_item_count > sum(state[ship.full_name].values()):
                state[ship.full_name] = dict(ship.item_counts)

        return yaml.dump(state, Dumper=yaml.CDumper)

    def check_requirement(self, yaml_text):
        """Checks the state according to the requirements and returns any mismatches."""
        requirements = yaml.load(yaml_text, Loader=yaml.CLoader)

        for target_name, target_contents in requirements.items():
            for ship in self.items_of_interesst:
                if ship.full_name == target_name:
                    difference = Counter(target_contents) - ship.item_counts

                    out = f"### {ship.full_name}:"
                    has_missing = False
                    for name, count in difference.items():
                        if count > 0:
                            has_missing = True
                            out += f"\n- Missing {count}x {name}"

                    if has_missing:
                        yield out

    def get_buy_list(self, yaml_text, buy_list=None):
        """Generates a buy list based on the requirements in the provided YAML text."""

        # Check if a previous buy list was passed, otherwise create an empty one
        buy_list = buy_list or Counter()

        requirements = yaml.load(yaml_text, Loader=yaml.CLoader)

        for target_name, target_contents in requirements.items():
            for ship in self.items_of_interesst:
                if ship.full_name == target_name:
                    difference = Counter(target_contents) - ship.item_counts
                    missing = Counter({k: max(0, v) for k, v in difference.items()})
                    buy_list += missing

        return buy_list
