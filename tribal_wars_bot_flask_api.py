# A very simple Flask Hello World app for you to get started with...

from flask import Flask, request, jsonify

from flask_mysqlpool import MySQLPool as MySQL

from contextlib import contextmanager
import config


app = Flask(__name__)


if __name__ == "__main__":
    import sshtunnel
    import MySQLdb

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
            f"WHERE user_name = '{data['user_name']}' AND password = '{data['user_password']}'"
        )
        with open_connection() as cursor:
            cursor.execute(check_credentials)
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
        if "user_name" not in data or "captcha_counter" not in data:
            return "Bad request!", 400
        with open_connection() as cursor:
            cursor.execute(
                f"UPDATE Konta_Plemiona SET "
                f"currently_running=0, "
                f"captcha_solved=captcha_solved + {data['captcha_counter']}, "
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
            f"""{', '.join([f"{column}='{value}'" for column, value in data.items()])} """
        )
        # If no args than make update for all
        if not request.args:
            with open_connection() as cursor:
                cursor.execute(update_account)
            return "", 204

        # Filter using sql WHERE clouse
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

        return "", 204


@app.route("/tribalwarsbot/api/v1/log", methods=["POST"])
@check_token
def save_log_v2():
    with open(f"logs//{request.json['owner']}.txt", "a") as file:
        file.write(f"{request.json['message']}\n")
    return "", 204


@app.route("/log", methods=["POST"])
@check_token
def save_log_v1():
    with open(f"logs//{request.json['owner']}.txt", "a") as file:
        file.write(f"{request.json['message']}\n")
    return "", 204


if __name__ == "__main__":
    app.run(debug=True, port=8000, host="127.0.0.1")
