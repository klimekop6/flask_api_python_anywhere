import base64
from contextlib import contextmanager
from pathlib import Path

import cv2
import numpy as np
import requests
from flask import Flask, jsonify, request
from flask_caching import Cache
from flask_mysqlpool import MySQLPool as MySQL

import config
from email_notification import send_email
from twb_api_utils import (
    get_nearest_villages_to_the_target_sorted_by_distance,
    get_players,
    get_tribe_players_id,
    get_tribe_villages,
    get_villages,
    get_villages_per_player_id,
)

WORLD_VILLAGES_DIR = "mysite/tribalwarsbot/world_villages"
WORLD_PLAYERS_DIR = "mysite/tribalwarsbot/world_players"
WORLD_SETTINGS_DIR = "mysite/tribalwarsbot/world_settings"


app = Flask(__name__)
cache = Cache(
    app,
    config={
        "CACHE_TYPE": "FileSystemCache",
        "CACHE_DEFAULT_TIMEOUT": 3600,
        "CACHE_DIR": "mysite/tmp",
    },
)


if __name__ == "__main__":
    import MySQLdb
    import sshtunnel

    sshtunnel.SSH_TIMEOUT = 5.0
    sshtunnel.TUNNEL_TIMEOUT = 5.0

    @contextmanager
    def open_connection():
        with sshtunnel.SSHTunnelForwarder(
            ("ssh.eu.pythonanywhere.com"),
            ssh_username=config.MYSQL_USER,
            ssh_password=config.PYTHON_ANYWHERE_PASS,
            remote_bind_address=(config.MYSQL_HOST, 3306),
        ) as tunnel:
            db_connection = MySQLdb.connect(
                user=config.MYSQL_USER,
                passwd=config.MYSQL_PASS,
                host="127.0.0.1",
                port=tunnel.local_bind_port,
                db=config.MYSQL_DB,
            )
            cursor = db_connection.cursor()
            try:
                yield cursor
            finally:
                db_connection.commit()
                cursor.close()

else:
    app.config["MYSQL_HOST"] = config.MYSQL_HOST
    app.config["MYSQL_USER"] = config.MYSQL_USER
    app.config["MYSQL_PASS"] = config.MYSQL_PASS
    app.config["MYSQL_DB"] = config.MYSQL_DB
    app.config["MYSQL_POOL_SIZE"] = config.MYSQL_POOL_SIZE
    app.config["MYSQL_COLLATION"] = config.MYSQL_COLLATION

    mysql = MySQL(app)

    @contextmanager
    def open_connection():
        db_connection = mysql.connection.get_connection()
        cursor = db_connection.cursor()
        try:
            yield cursor
        finally:
            db_connection.close()


def check_token(func):
    def wrapper(*args, **kwargs):
        if not "Authorization" in request.headers:
            return "Bad request!", 400
        if request.headers["Authorization"] != config.API_TOKEN:
            return "unauthorized", 401
        return func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


# Login
@app.route("/tribalwarsbot/api/v1/login", methods=["POST"])
@check_token
def login():
    if request.method == "POST":
        data: dict = request.json
        if "user_name" not in data or "user_password" not in data:
            return "Bad request!", 400
        check_credentials = (
            f"SELECT * FROM Konta_Plemiona "
            f"WHERE user_name = %(user_name)s AND password = %(user_password)s"
        )
        with open_connection() as cursor:
            cursor.execute(
                check_credentials,
                {
                    "user_name": data["user_name"],
                    "user_password": data["user_password"],
                },
            )
            db_response = cursor.fetchone()
            if not db_response:
                return "unauthorized", 401
            user_data = {
                key[0]: value for key, value in zip(cursor.description, db_response)
            }
            user_data["active_until"] = str(user_data["active_until"])
            user_data["active_since"] = str(user_data["active_since"])
        return user_data


# Register
@app.route("/tribalwarsbot/api/v1/register", methods=["GET", "POST"])
@check_token
def register():
    if request.method == "GET":
        data = request.args.to_dict()
        if not data or ("operator" not in data and len(data) > 1):
            return "Bad request!", 400
        select = f"SELECT * FROM Konta_Plemiona "
        operator = data.pop("operator", "")
        if "and" in operator:
            select += "WHERE " + " AND ".join(
                [f"{key} = '{value}'" for key, value in data.items()]
            )
        else:
            select += "WHERE " + " OR ".join(
                [f"{key} = '{value}'" for key, value in data.items()]
            )
        with open_connection() as cursor:
            cursor.execute(select)
            if cursor.fetchone():
                return jsonify(no_exist=False)
            else:
                return jsonify(no_exist=True)

    if request.method == "POST":
        data: dict = request.json
        if not data:
            return "Bad request!", 400
        create_account = (
            f"INSERT INTO Konta_Plemiona({', '.join([str(key) for key in data])}) "
            f"""VALUES ({', '.join([f"'{value}'" for value in data.values()])})"""
        )
        with open_connection() as cursor:
            cursor.execute(create_account)
            set_default_account_values = (
                f"UPDATE Konta_Plemiona SET "
                f"active_since = DATE(NOW()), "
                f"active_until = DATE_ADD(DATE(NOW()), INTERVAL 10 DAY) "
                f"WHERE user_name = '{data['user_name']}'"
            )
            cursor.execute(set_default_account_values)

        return "Account has been created!", 201


# Logout
@app.route("/tribalwarsbot/api/v1/logout", methods=["PATCH"])
@check_token
def logout():
    if request.method == "PATCH":
        data: dict = request.json
        if "user_name" not in data:
            return "Bad request!", 400
        with open_connection() as cursor:
            cursor.execute(
                f"UPDATE Konta_Plemiona SET "
                f"currently_running=0, "
                f"last_logged = NOW() "
                f"WHERE user_name='{data['user_name']}'"
            )
        return "", 204


# Status
@app.route("/tribalwarsbot/api/v1/status", methods=["PATCH"])
@check_token
def status():
    if request.method == "PATCH":
        data: dict = request.json
        if "captcha_counter" in data:
            sql_str = (
                f"UPDATE Konta_Plemiona "
                f"SET currently_running=1, captcha_solved=captcha_solved + {data['captcha_counter']}, last_logged = NOW() "
                f"WHERE user_name='{data['user_name']}'"
            )
        else:
            sql_str = (
                f"UPDATE Konta_Plemiona SET currently_running=1, last_logged = NOW() "
                f"WHERE user_name='{data['user_name']}'"
            )
        with open_connection() as cursor:
            cursor.execute(sql_str)

        return "", 204


# User
@app.route("/tribalwarsbot/api/v1/user", methods=["GET", "PATCH"])
@check_token
def user():
    if request.method == "GET":
        data = request.args.to_dict()
        if not data or ("operator" not in data and len(data) > 1):
            return "Bad request!", 400
        select = f"SELECT * FROM Konta_Plemiona "
        operator = data.pop("operator", "")
        if "and" in operator:
            select += "WHERE " + " AND ".join(
                [f"{key} = '{value}'" for key, value in data.items()]
            )
        else:
            select += "WHERE " + " OR ".join(
                [f"{key} = '{value}'" for key, value in data.items()]
            )
        with open_connection() as cursor:
            cursor.execute(select)
            db_response = cursor.fetchone()
            if not db_response:
                return "There is no such user", 400
            user_data = {
                key[0]: value for key, value in zip(cursor.description, db_response)
            }
            user_data["active_until"] = str(user_data["active_until"])
            user_data["active_since"] = str(user_data["active_since"])
        return user_data

    if request.method == "PATCH":
        data: dict = request.json
        if not data:
            return "Bad request!", 400
        update_account = (
            f"UPDATE Konta_Plemiona SET "
            f"""{', '.join([f"{column}={value}" for column, value in data.items()])} """
        )
        # If no args than make update for all
        if not request.args:
            with open_connection() as cursor:
                cursor.execute(update_account)
            return "", 204

        # Filter using sql WHERE
        data: dict = request.args.to_dict()
        if "operator" not in data and len(data) > 1:
            return "Bad request!", 400
        operator = data.pop("operator", "")
        if "and" in operator:
            update_account += "WHERE " + " AND ".join(
                [f"{key} = '{value}'" for key, value in data.items()]
            )
        else:
            update_account += "WHERE " + " OR ".join(
                [f"{key} = '{value}'" for key, value in data.items()]
            )
        with open_connection() as cursor:
            cursor.execute(update_account)

        return "", 204


# Bonus
@app.route("/tribalwarsbot/api/v1/bonus", methods=["PATCH"])
@check_token
def bonus():
    if request.method == "PATCH":
        data: dict = request.json
        if "user_name" not in data or "invited_by" not in data:
            return "Bad request!", 400

        active_until_less_than_current_date = (
            f"UPDATE Konta_Plemiona "
            f"SET active_until = IF(active_until < DATE(NOW()), DATE_ADD(DATE(NOW()), INTERVAL 1 DAY), DATE_ADD(active_until, INTERVAL 1 DAY)) "
            f"WHERE user_name = '{data['invited_by']}'"
        )
        set_email_bonus_add_status = (
            f"UPDATE Konta_Plemiona "
            f"SET bonus_email = 1 "
            f"WHERE user_name = '{data['user_name']}'"
        )

        with open_connection() as cursor:
            cursor.execute(active_until_less_than_current_date)
            cursor.execute(set_email_bonus_add_status)

        return "", 204


# Premium
@app.route("/tribalwarsbot/api/v1/premium", methods=["PATCH"])
@check_token
def premium():
    if request.method == "PATCH":
        data: dict = request.json
        if "user_name" not in data or "months" not in data:
            return "Bad request!", 400

        add_premium = (
            f"UPDATE Konta_Plemiona "
            f"SET active_until = IF("
            f"  active_until < DATE(NOW()), "
            f"  DATE_ADD(DATE(NOW()), INTERVAL {data['months']} MONTH), "
            f"  DATE_ADD(active_until, INTERVAL {data['months']} MONTH)"
            f") "
            f"WHERE user_name = '{data['user_name']}'"
        )
        get_bonus_add = (
            f"SELECT bonus_add FROM Konta_Plemiona "
            f"WHERE user_name = '{data['user_name']}'"
        )
        get_email_and_acc_expiration_date = (
            f"SELECT email, active_until FROM Konta_Plemiona "
            f"WHERE user_name = '{data['user_name']}'"
        )
        with open_connection() as cursor:
            cursor.execute(add_premium)
            cursor.execute(get_bonus_add)
            if cursor.fetchone()[0] == 0:
                set_bonus_add = (
                    f"UPDATE Konta_Plemiona "
                    f"SET bonus_add=1 "
                    f"WHERE user_name = '{data['user_name']}';"
                )
                cursor.execute(set_bonus_add)
                add_bonus_to_invited_by = (
                    f"UPDATE Konta_Plemiona "
                    f"SET active_until=IF("
                    f"  active_until < DATE(NOW()), "
                    f"  DATE_ADD(DATE(NOW()), INTERVAL 14 DAY), "
                    f"  DATE_ADD(active_until, INTERVAL 14 DAY)"
                    f") "
                    f"WHERE user_name = (SELECT inv FROM (SELECT invited_by AS inv FROM Konta_Plemiona WHERE user_name = '{data['user_name']}') as tmp );"
                )
                cursor.execute(add_bonus_to_invited_by)
            cursor.execute(get_email_and_acc_expiration_date)
            email, active_until = cursor.fetchone()

        send_email(
            target=email,
            subject="Potwierdzenie otrzymania zapłaty",
            body=(
                f"Dzięki za skorzystanie z moich usług.\n\n"
                f"Mam nadzieję, że aplikacja spełni wszystkie Twoje oczekiwania.\n\n"
                f"Twoje konto pozostanie aktywne do {active_until}\n\n"
                f"W razie jakichkolwiek problemów proszę o kontakt na adres k.spec@tuta.io\n\n"
                f"Udanego bocenia! :-)"
            ),
        )

        return f"{active_until}"


# Logging
@app.route("/tribalwarsbot/api/v1/log", methods=["POST"])
@check_token
def save_log():
    if "app_version" in request.json:
        app_version = request.json["app_version"]
        Path(f"logs//{app_version}").mkdir(exist_ok=True)
        with open(f"logs//{app_version}//{request.json['owner']}.txt", "a") as file:
            file.write(f"{request.json['message']}\n")
    else:
        with open(f"logs//{request.json['owner']}.txt", "a") as file:
            file.write(f"{request.json['message']}\n")
    return "", 204


# World settings file
@app.route("/tribalwarsbot/api/v1/world/<path:path>", methods=["POST"])
@check_token
def world_settings(path):
    if request.method == "POST":
        with open(f"{WORLD_SETTINGS_DIR}//{path}.xml", "w") as file:
            file.write(request.get_data(cache=False, as_text=True))
        return "Ok", 200
    else:
        return "Bad request method", 400


@app.route("/tribalwarsbot/api/v1/villages", methods=["GET"])
@check_token
def player_villages():
    if request.method == "GET":
        data = request.args.to_dict()
        server_world = data["server_world"]

        if cache.has(server_world):
            if "player_id" in data:
                return jsonify(cache.get(server_world)[data["player_id"]])
            return cache.get(server_world)

        if "server_url" in data:
            response = requests.get(f"{data['server_url']}/map/village.txt")
            if response.ok:
                with open(f"{WORLD_VILLAGES_DIR}//{server_world}.txt", "w") as file:
                    file.write(response.text)
            villages = {}
            for line in response.text.splitlines(keepends=False):
                _, _, x, y, player_id, _, _ = line.split(",")
                if player_id in villages:
                    villages[player_id].append(f"{x}|{y}")
                else:
                    villages[player_id] = [f"{x}|{y}"]
            cache.set(server_world, villages)

            if "player_id" in data:
                return jsonify(villages[data["player_id"]])
            return villages

        return "Bad request arguments", 422
    else:
        return "Bad request method", 400


@app.route("/tribalwarsbot/api/v2/villages", methods=["GET"])
@check_token
def player_villages_v2():
    if request.method == "GET":
        data = request.args.to_dict()
        server_world = data["server_world"]

        # cache keys
        villages_key = f"{server_world}_v"
        villages_per_player_id_key = f"{server_world}_vpp"
        players_key = f"{server_world}_players"

        single_village = True if data.get("villages", "") == "1" else False
        support_other = True if data.get("no_other_support", "0") == "0" else False
        target = data.get("target", "")
        tribe_id = data.get("tribe_id", "0")

        if not cache.has(villages_key):
            response = requests.get(f"{data['server_url']}/map/village.txt")
            if response.ok:
                parsed_villages: list[str] = response.text.splitlines(keepends=False)
                with open(f"{WORLD_VILLAGES_DIR}//{server_world}.txt", "w") as file:
                    file.write(response.text)
            else:
                with open(f"{WORLD_VILLAGES_DIR}//{server_world}.txt") as file:
                    parsed_villages: list[str] = file.readlines()

            cache.set(villages_key, get_villages(parsed_villages))
            cache.set(
                villages_per_player_id_key, get_villages_per_player_id(parsed_villages)
            )

        if single_village and not support_other and not cache.has(players_key):
            response = requests.get(f"{data['server_url']}/map/player.txt")
            if response.ok:
                parsed_players = response.text.splitlines(keepends=False)
                with open(f"{WORLD_PLAYERS_DIR}//{server_world}.txt", "w") as file:
                    file.write(response.text)
            else:
                with open(f"{WORLD_PLAYERS_DIR}//{server_world}.txt") as file:
                    parsed_players: list[str] = file.readlines()
            cache.set(players_key, get_players(parsed_players))

        if single_village:
            if support_other:
                return jsonify(
                    get_nearest_villages_to_the_target_sorted_by_distance(
                        target, villages=cache.get(villages_key)
                    )
                )
            else:
                return jsonify(
                    get_nearest_villages_to_the_target_sorted_by_distance(
                        target,
                        villages=get_tribe_villages(
                            get_tribe_players_id(tribe_id, cache.get(players_key)),
                            cache.get(villages_per_player_id_key),
                        ),
                    )
                )
        else:
            if "player_id" in data:
                return jsonify(
                    get_nearest_villages_to_the_target_sorted_by_distance(
                        target, cache.get(villages_per_player_id_key)[data["player_id"]]
                    )
                )
            return cache.get(villages_per_player_id_key)
    else:
        return "Bad request method", 400


# World villages file
@app.route("/tribalwarsbot/api/v1/villages/<path:path>", methods=["POST"])
@check_token
def world_villages(path):
    if request.method == "POST":
        with open(f"{WORLD_VILLAGES_DIR}//{path}.txt", "w") as file:
            file.write(request.get_data(cache=False, as_text=True))
        return "Ok", 200
    else:
        return "Bad request method", 400


@app.route("/tribalwarsbot/api/v1/api_key/<string:key>", methods=["GET"])
@check_token
def get_api_key(key):
    if request.method == "GET":
        if key == "two_captcha":
            return config.TWO_CAPTCHA_API_KEY, 200
        return "There is no such key", 404
    else:
        return "Bad request method", 400


@app.route("/tribalwarsbot/api/v1/concat_images", methods=["POST"])
@check_token
def concat_images():
    images: dict = request.json

    def get_cv2_image(image: str):
        image = base64.b64decode(image.encode())
        nparr = np.frombuffer(image, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if image.shape != (128, 128, 3):
            image = cv2.resize(image, (128, 128))
        return image

    cv2_images = tuple(get_cv2_image(image) for image in images)

    horizontly_joined_image = tuple(
        cv2.hconcat(cv2_images[n : n + 3]) for n in range(0, 9, 3)
    )
    verticly_joined_images = cv2.vconcat(horizontly_joined_image)
    hcaptcha_image = base64.b64encode(
        cv2.imencode(".jpg", verticly_joined_images)[1]
    ).decode()
    return jsonify(hcaptcha_image)


if __name__ == "__main__":
    app.run(debug=True, port=8000, host="127.0.0.1")
