from google.oauth2 import service_account
from googleapiclient import discovery
from collections import Counter
import os

def lines_to_counter(lines):
    items = Counter()
    for item in lines:
        if "[" in item or item == "":
            continue
        if ', ' in item:
            item = item.split(", ")[0]
        if ' x' in item:
            name, count = item.rsplit(" x", 1)
            items[name.strip()] += int(count)
        else:
            items[item.strip()] += 1
    return items


def eft_to_counter(eft):
    eft = eft.replace('\r', '')
    sections = eft.strip().split("\n\n\n")
    title_item = sections[0].split(",")[0].strip("[]")
    ship_counter = Counter()
    ship_counter[title_item] += 1
    all_counter = (
        lines_to_counter(sections[0].splitlines()) +
        lines_to_counter("\n".join(sections[1:]).splitlines()) +
        ship_counter
    )

    # Ignore FLAG fitting
    if "FLAG" in eft:
        return ship_counter, Counter()

    return ship_counter, all_counter


def fetch_requirements():
    sheet_service = get_sheet_service()
    result = sheet_service.spreadsheets().values().get(
        spreadsheetId=os.environ["SPREADSHEET_ID"],
        range=os.environ["RANGE"]
    ).execute()
    inputs = result.get('values', [])

    comp_requirements = {}
    item_counter = Counter()
    ship_counter = Counter()

    # Archetype
    other_line_count = 0
    comp_names = []
    comp_archetypes = []

    for row in inputs:
        content = row[0] if row else ""
        if "Fit" in content:
            other_line_count = 0

            # We have completed the previous comp
            if item_counter:
                # Make a unique name
                comp_name =  ", ".join([f"{key:5} x{value}" for key, value in ship_counter.items()])
                while comp_name in comp_requirements:
                    comp_name += " - copy" # VLD Style

                comp_requirements[comp_name] = item_counter
                comp_names.append(comp_name)
                item_counter = Counter()
                ship_counter = Counter()
        elif "[" in content: # Line is an eft
            other_line_count = 0
            ship_local, all_local = eft_to_counter(content)
            ship_counter += ship_local
            item_counter += all_local
        else:
            if other_line_count > 1:
                # We have a new archetype
                comp_archetypes.append(comp_names)
                comp_names = []
            else:
                other_line_count += 1

    # Store final comp
    if item_counter:
        # Make a unique name
        comp_name = ", ".join([f"{key} x{value}" if (value > 1) else key for key, value in ship_counter.items()])
        while comp_name in comp_requirements:
            comp_name += " copy"  # VLD Style

        comp_requirements[comp_name] = item_counter
        comp_names.append(comp_name)

    # Store final archetype
    comp_archetypes.append(comp_names)

    return comp_requirements, comp_archetypes


# Google Sheets setup
def get_sheet_service():
    scopes = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/drive.file",
              "https://www.googleapis.com/auth/spreadsheets"]
    credentials = service_account.Credentials.from_service_account_file("credentials.json", scopes=scopes)
    service = discovery.build('sheets', 'v4', credentials=credentials)
    return service
