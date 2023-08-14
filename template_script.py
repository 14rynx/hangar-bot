from esi.oauth import load_token
from assets import Assets

CLIENT_ID = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

# If the token does not exist it will be created and you have to log in to eve
character_id, access_token = load_token("tokens/my_token.json")

# Fetch the assets from ESI
my_assets = Assets(character_id, access_token)

# Save cargoholds to file
my_assets.save_state("states/my_state.yaml")

# Check what changed
my_assets.check_state("states/my_second_state.yaml")

# Print a Multibuy what is missing
Assets.print_buy_list(my_assets.get_buy_list("states/all.yaml"))

