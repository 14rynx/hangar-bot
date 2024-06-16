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
        return f"Item(item_id={self.item_id}, type_id={self.type_id}, subordinates={len(self.subordinates)})"

    @property
    def full_name(self):
        return f"{self.name} ({self.type_name})"

    @property
    def is_assembled_ship(self):
        return self.location_flag == "Hangar" and any(["Slot" in x.location_flag for x in self.subordinates])

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

        # Set up initial info
        character_data = preston.whoami()
        self.character_id = character_data["CharacterID"]
        self.character_name = character_data["CharacterName"]

        # Fetch all available assets
        self.items = []
        page = 1
        while True:
            result = preston.get_op('get_characters_character_id_assets', character_id=self.character_id, page=page)
            if "error" in result:
                if result["error"] == "Requested page does not exist!":
                    break
            else:
                self.items.extend([Item(**x) for x in result])
                page += 1

        # Index items by id for quick finding
        id_items = {x.item_id: x for x in self.items}

        # Build a tree of all times
        self.root_items = []
        for item in id_items.values():
            if item.location_id in id_items:
                id_items[item.location_id].add_subordinate(item)
            else:
                self.root_items.append(item)

        # Fetch the name of each container root item e.g. ship and container
        for item_data in preston.post_op(
                'post_characters_character_id_assets_names',
                path_data={"character_id": self.character_id},
                post_data=[x.item_id for x in self.root_items]
        ):
            id_items[item_data["item_id"]].name = item_data["name"].replace("&gt;", ">").replace("&lt;", "<")

        # Fetch all type names and add them to the items
        type_ids = set([x.type_id for x in self.items])
        type_id_names = {}
        for type_id in type_ids:
            response = preston.get_op('get_universe_types_type_id', type_id=type_id)
            try:
                type_id_names[response["type_id"]] = response["name"]
            except KeyError:
                pass

        for item in self.items:
            item.type_name = type_id_names.get(item.type_id, "Unknown Item")

        # Build list with ships
        self.ships = [x for x in self.root_items if x.is_assembled_ship]

    def save_requirement(self, requirement_path):
        # Generate the dictionary representation
        state = {}
        for ship in self.ships:
            # If there are multiple containers with the same name take the fullest one
            if ship.full_name not in state or ship.total_item_count > sum(state[ship.full_name].values()):
                state[ship.full_name] = dict(ship.item_counts)

        with open(requirement_path, "w") as file:
            yaml.dump(state, file, yaml.CDumper)

    def check_requirement(self, requirement_path):
        """Checks the state according to the requirements and returns any mismatches"""
        with open(requirement_path, "r") as file:
            requirements = yaml.load(file, yaml.CLoader)

        for target_name, target_contents in requirements.items():
            for ship in self.ships:
                if ship.full_name == target_name:
                    difference = Counter(target_contents) - ship.item_counts

                    out = f"{ship.full_name}:\n"
                    out += "\n".join([f"{name} missing {count}" for name, count in difference.items() if count > 0])
                    yield out

    def get_buy_list(self, requirement_path, buy_list=None):

        # Check if a previous buy list was passed, otherwise create an empty one
        buy_list = buy_list or Counter()

        with open(requirement_path, "r") as file:
            requirements = yaml.load(file, yaml.CLoader)

        for target_name, target_contents in requirements.items():
            for ship in self.ships:
                if ship.full_name == target_name:
                    difference = Counter(target_contents) - ship.item_counts
                    missing = Counter({k: max(0, v) for k, v in difference.items()})
                    buy_list += missing

        return buy_list
