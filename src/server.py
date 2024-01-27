import logging
import shelve

from flask import Flask
from flask import request
from waitress import serve

# Configure the logger
logger = logging.getLogger('callback')
logger.setLevel(logging.INFO)


def callback_server(esi_security):
    flask_app = Flask("Hanger Callback Server")

    @flask_app.route("/")
    def hello_world():
        return "<p>Hangar Script Callback Server</p>"

    @flask_app.route('/callback/')
    def callback():
        # get the code from the login process
        code = request.args.get('code')
        secret_state = request.args.get('state')

        try:
            with shelve.open('../data/challenges', writeback=True) as challenges:
                author_id = str(challenges[secret_state])
        except KeyError:
            return 'Authentication failed: State Missmatch', 403

        tokens = esi_security.auth(code)

        character_data = esi_security.verify()
        character_id = character_data["sub"].split(':')[-1]
        character_name = character_data["name"]

        # Store tokens under author
        with shelve.open('../data/tokens', writeback=True) as author_character_tokens:
            if author_id not in author_character_tokens:
                author_character_tokens[author_id] = {character_id: tokens}
            else:
                author_character_tokens[author_id][character_id] = tokens

        return f"<p>Sucessfully authentiated {character_name}!</p>"

    serve(flask_app, port=80)
