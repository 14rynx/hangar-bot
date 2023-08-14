# Hangar

A simple script to check if there are any differences in between your ships cargohold 
and their intended state (drugs missing, no capboosters etc.). Some programming knowledge required.

## Setup

To start, have a look at `template_script.py`. 
This script connects to ESI, then gets your assets and writes the cargoholds to a yaml file.
It then checks against the same yaml file and reports any differences (obviously there will be none).

In order to make the ESI part work, you need to create an application at [https://developers.eveonline.com/](https://developers.eveonline.com/)
with callback `https://localhost/callback/` and permission for `esi-assets.read_assets.v1`. Then add your client ID at the top of the template script.

Based of of that yaml file, you can now create a second yaml file that is how you want things to be. Thenpass it to the the `check_state` function.
Now you will see what is missing!

## Multicharacter

Finally you can also print a multibuy as shown below. For multiple characters you can add to the multibuy as following:
```python
buy_list = character_1.get_buy_list("states/all.yaml")
buy_list = character_2.get_buy_list("states/all.yaml", buy_list=buy_list)
...

