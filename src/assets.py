from collections import defaultdict

import yaml


def good_location(location_flag):
    return location_flag == "Cargo" or \
        location_flag == "DroneBay" or \
        "HiSlot" in location_flag or \
        "MedSlot" in location_flag or \
        "LoSlot" in location_flag or \
        "RigSlot" in location_flag or \
        "SubSystemSlot" in location_flag


class Assets:
    def __init__(self, character_id, esi_app, esi_client, character_name=""):
        self.character_id = character_id
        self.character_name = character_name

        # Fetch assets
        self.assets = []
        op = esi_app.op['get_characters_character_id_assets'](character_id=character_id)
        head_result = esi_client.head(op)

        if head_result.status == 200:
            npages = head_result.header['X-Pages'][0]
            ops = [esi_app.op['get_characters_character_id_assets'](character_id=character_id, page=page)
                   for page in range(1, npages + 1)]
            results = esi_client.multi_request(ops)
            for request, result in results:
                self.assets.extend(result.data)

        # Group Assets by Container
        containers = defaultdict(lambda: defaultdict(int))
        for asset in self.assets:
            if good_location(asset["location_flag"]):
                containers[asset["location_id"]][asset["type_id"]] += asset.get("quantity", 1)

        # Get the name of each container
        op = esi_app.op['post_characters_character_id_assets_names'](character_id=character_id,
                                                                     item_ids=list(containers))
        result = esi_client.request(op)

        container_names = {}
        for item_data in result.data:
            name = item_data["name"]
            name = name.replace("&gt;", ">")
            name = name.replace("&lt;", "<")
            container_names[item_data["item_id"]] = name

        # Get the type_id for each container
        container_type_ids = {}
        for asset in self.assets:
            if asset["item_id"] in containers.keys():
                container_type_ids[asset["item_id"]] = asset["type_id"]

        # Get the type_name of each item and container
        ops = [esi_app.op['get_universe_types_type_id'](type_id=asset["type_id"]) for asset in self.assets]
        results = esi_client.multi_request(ops)

        item_type_names = {}
        for request, result in results:
            item_type_names[result.data["type_id"]] = result.data["name"]

        # Finally rebuild containers with names
        self.named_containers = defaultdict(lambda: defaultdict(int))
        for container_item_id, contents in containers.items():
            container_name = f"{container_names[container_item_id]} ({item_type_names[container_type_ids[container_item_id]]}):"
            for item_id, quantity in contents.items():
                item_name = item_type_names[item_id]
                self.named_containers[container_name][item_name] = quantity

    @property
    def state(self):
        # Generate the dictionary representation
        state = {}
        for container_name, contents in self.named_containers.items():

            # Sort contents
            sorted_contents = {}
            for item_name, amount in sorted(contents.items(), key=lambda x: x[0]):
                sorted_contents[item_name] = amount

            # If there are multiple containers with the same name take the fullest one
            if container_name not in state or sum(contents.values()) > sum(state[container_name].values()):
                state[container_name] = sorted_contents

        return state

    def check_state(self, requirement_path):
        output = []
        """Checks the state according to the requirements and returns any mismatches"""
        with open(requirement_path, "r") as file:
            container_requirements = yaml.load(file, yaml.CLoader)

        for container_name, container_contents in self.named_containers.items():
            container_output = []
            if container_name in container_requirements:
                for required_item_name, required_item_amount in container_requirements[container_name].items():
                    if not required_item_name in container_contents:
                        container_output.append(
                            f"- {required_item_name} is completely missing ({required_item_amount} units)")
                    elif container_contents[required_item_name] < required_item_amount:
                        container_output.append(
                            f"- {required_item_name} is missing {required_item_amount - container_contents[required_item_name]} units")

            if container_output:
                container_body = "\n".join(container_output)
                output.append(f"{container_name.strip(':')}:\n{container_body}")

        return "\n".join(output)

    def get_buy_list(self, requirement_path, buy_list=None, replenish_from_others=False):

        # Check if a previous buy list was passed, otherwise create an empty one
        if buy_list is None:
            buy_list = defaultdict(int)

        with open(requirement_path, "r") as file:
            container_requirements = yaml.load(file, yaml.CLoader)

        for container_name, container_contents in self.named_containers.items():
            if container_name in container_requirements:
                for required_item_name, required_item_amount in container_requirements[container_name].items():
                    if replenish_from_others or required_item_amount > container_contents.get(required_item_name, 0):
                        buy_list[required_item_name] += required_item_amount - container_contents.get(
                            required_item_name, 0)

        if replenish_from_others:
            buy_list = {k: v for k, v in buy_list if v > 0}

        return buy_list

    def filter_state(self, ship_name):
        """Checks the state and returns the current one for a specific shipname.
        Usefull for incremental additions to the requirements"""
        for container_name, container_contents in self.state.items():
            if ship_name in container_name:
                print(yaml.dump({container_name: container_contents}))

    def save_state(self, requirement_path):
        with open(requirement_path, "w") as file:
            yaml.dump(self.state, file, yaml.CDumper)
