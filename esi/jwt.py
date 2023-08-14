import requests
from jose import jwt

SSO_META_DATA_URL = "https://login.eveonline.com/.well-known/oauth-authorization-server"
JWK_ALGORITHM = "RS256"
JWK_ISSUERS = ("login.eveonline.com", "https://login.eveonline.com")
JWK_AUDIENCE = "EVE Online"


def validate_eve_jwt(token: str) -> dict:
    """Validate a JWT access token retrieved from the EVE SSO.

    Args:
        token: A JWT access token originating from the EVE SSO
    Returns:
        The contents of the validated JWT access token if there are no errors
    """
    # fetch JWKs URL from meta data endpoint
    res = requests.get(SSO_META_DATA_URL)
    res.raise_for_status()
    data = res.json()
    try:
        jwks_uri = data["jwks_uri"]
    except KeyError:
        raise RuntimeError(
            f"Invalid data received from the SSO meta data endpoint: {data}"
        ) from None

    # fetch JWKs from endpoint
    res = requests.get(jwks_uri)
    res.raise_for_status()
    data = res.json()
    try:
        jwk_sets = data["keys"]
    except KeyError:
        raise RuntimeError(
            f"Invalid data received from the the jwks endpoint: {data}"
        ) from None

    # pick the JWK with the requested alogorithm
    jwk_set = [item for item in jwk_sets if item["alg"] == JWK_ALGORITHM].pop()

    # try to decode the token and validate it against expected values
    # will raise JWT exceptions if decoding fails or expected values do not match
    contents = jwt.decode(
        token=token,
        key=jwk_set,
        algorithms=jwk_set["alg"],
        issuer=JWK_ISSUERS,
        audience=JWK_AUDIENCE,
    )
    return contents
