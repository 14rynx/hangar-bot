import base64
import hashlib
import json
import secrets
import urllib

import requests

from esi.jwt import validate_eve_jwt

CLIENT_ID = "6207baec2588400f9366a461b903fc61"


def print_auth_url(client_id, code_challenge=None):
    """Prints the URL to redirect users to.

    Args:
        client_id: The client ID of an EVE SSO application
        code_challenge: A PKCE code challenge
    """

    base_auth_url = "https://login.eveonline.com/v2/oauth/authorize/"
    params = {
        "response_type": "code",
        "redirect_uri": "https://localhost/callback/",
        "client_id": client_id,
        "scope": "esi-assets.read_assets.v1",
        "state": "unique-state"
    }

    if code_challenge:
        params.update({
            "code_challenge": code_challenge,
            "code_challenge_method": "S256"
        })

    string_params = urllib.parse.urlencode(params)

    print(f"Open the following link in your browser:\n {base_auth_url}?{string_params}")


def send_token_request(form_values):
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Host": "login.eveonline.com",
    }

    res = requests.post(
        "https://login.eveonline.com/v2/oauth/token",
        data=form_values,
        headers=headers,
    )

    res.raise_for_status()

    return res


def generate_token():
    # Generate the PKCE code challenge
    random = base64.urlsafe_b64encode(secrets.token_bytes(32))
    m = hashlib.sha256()
    m.update(random)
    d = m.digest()
    code_challenge = base64.urlsafe_b64encode(d).decode().replace("=", "")

    print_auth_url(CLIENT_ID, code_challenge=code_challenge)

    auth_code = input("Copy the \"code\" query parameter and enter it here: ")

    code_verifier = random

    form_values = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": auth_code,
        "code_verifier": code_verifier
    }

    sso_response = send_token_request(form_values)

    if sso_response.status_code == 200:
        data = sso_response.json()

        jwt_data = validate_eve_jwt(data["access_token"])
        character_id = jwt_data["sub"].split(":")[2]

        return character_id, data["access_token"], data["refresh_token"]


def renew_token(refresh_token):
    form_values = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Host": "login.eveonline.com",
    }

    sso_response = requests.post(
        "https://login.eveonline.com/v2/oauth/token",
        data=form_values,
        headers=headers,
    )
    if sso_response.status_code == 200:
        data = sso_response.json()

        jwt_data = validate_eve_jwt(data["access_token"])
        character_id = jwt_data["sub"].split(":")[2]

        return character_id, data["access_token"], data["refresh_token"]


def load_token(token_file):
    try:
        with open(token_file, "r") as file:
            data = json.load(file)
        character_id, access_token, refresh_token = renew_token(data["refresh_token"])
    except FileNotFoundError:
        character_id, access_token, refresh_token = generate_token()

    data = {
        "refresh_token": refresh_token,
        "access_token": access_token
    }
    with open(token_file, "w") as file:
        json.dump(data, file)

    return character_id, access_token
