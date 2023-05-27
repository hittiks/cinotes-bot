import os
import json
import base64
import requests
import psycopg2

from datetime import datetime
from logger import log, LogMode

from aiogram import Bot as AiogramBot, Dispatcher, executor, types
from aiogram.types.message import ContentTypes
from aiogram.types.web_app_info import WebAppInfo
from aiogram.dispatcher.filters import BoundFilter, Text
from aiogram.types.reply_keyboard import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.types.inline_keyboard import InlineKeyboardMarkup, InlineKeyboardButton


bot = AiogramBot(os.environ["cinotes_bot_token"])
dp = Dispatcher(bot)
BOT_OWNER_ID = int(os.environ["cinotes_bot_owner_id"])


class BotOwnerFilter(BoundFilter):
    key = "is_bot_owner"

    def __init__(self, is_bot_owner):
        self.is_owner = is_bot_owner

    async def check(self, message: types.Message):
        return message.chat.id == BOT_OWNER_ID


dp.filters_factory.bind(BotOwnerFilter)


class BotAdminFilter(BoundFilter):
    key = "is_bot_admin"

    def __init__(self, is_bot_admin):
        self.is_admin = is_bot_admin

    async def check(self, message: types.Message):
        res = cur_executor("SELECT user_type FROM accounts WHERE user_id=%s;", message.chat.id)
        if res and isinstance(res[0], str):
            log(f"Get error when check if user permitted to admin command: type: '{res[0]}', text: '{res[1]}'", LogMode.ERROR)
            await bot.send_message(BOT_OWNER_ID, f"Админский фильтр упал из-за sql-ошибки: type: '{res[0]}', text: '{res[1]}'")
            return False
        return res[0][0] == "admin" or message.chat.id == BOT_OWNER_ID


dp.filters_factory.bind(BotAdminFilter)


def cur_executor(command: str, *args):
    base = psycopg2.connect(
        host=os.environ["cinotes_host"],
        user=os.environ["cinotes_user"],
        password=os.environ["cinotes_password"],
        database=os.environ["cinotes_db_name"]    
    )

    base.autocommit = True
    cur = base.cursor()
    
    try:
        cur.execute(command, args)
        result = cur.fetchall()
    except Exception as e:
        return [type(e).__name__, str(e)]
    finally:
        if base:
            cur.close()
            base.close()

    return result


async def start_db():
    conn = psycopg2.connect(
        host=os.environ["cinotes_host"],
        user=os.environ["cinotes_user"],
        password=os.environ["cinotes_password"]  
    )

    conn.autocommit = True

    try:
        conn.cursor().execute(f"CREATE DATABASE {os.environ['cinotes_db_name']}")
        log("Database successfully created", LogMode.OK)
    except psycopg2.errors.DuplicateDatabase:
        pass
    conn.close()
    
    base = psycopg2.connect(
        host=os.environ["cinotes_host"],
        user=os.environ["cinotes_user"],
        password=os.environ["cinotes_password"],
        database=os.environ["cinotes_db_name"]    
    )
    base.autocommit = True
    
    if base:
        log("Database successfully connected", LogMode.OK)
        await bot.send_message(BOT_OWNER_ID, "Бот и база данных были успешно запущены")
    else:
        log("Database not connected", LogMode.ERROR)
        await bot.send_message(BOT_OWNER_ID, "Бот был запущен, а база данных нет, дальнейшие действия с бд невозможны")
        return

    cur = base.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users(user_id BIGINT PRIMARY KEY NOT NULL, language TEXT NOT NULL);")
    cur.execute("CREATE TABLE IF NOT EXISTS accounts(user_id BIGINT PRIMARY KEY NOT NULL, user_type TEXT NOT NULL, jwt TEXT NOT NULL);")
    cur.execute("CREATE TABLE IF NOT EXISTS weights(user_id BIGINT PRIMARY KEY NOT NULL, weights TEXT NOT NULL);")


    tu = cur_executor("SELECT * FROM users;")
    if len(tu) == 0 or isinstance(tu[0], tuple):
        log(f"Num of telegram users: {len(tu)}", LogMode.INFO)
    else:
        log(f"Get error in sql on start: type: '{tu[0]}', text: '{tu[1]}'", LogMode.ERROR)

    ta = cur_executor("SELECT * FROM accounts;")
    if len(ta) == 0 or isinstance(ta[0], tuple):
        log(f"Num of accounts: {len(ta)}", LogMode.INFO)
    else:
        log(f"Get error in sql on start: type: '{ta[0]}', text: '{ta[1]}'", LogMode.ERROR)


    if base:
        cur.close()
        base.close()


async def startup(dp):
    log("CINOTES BOT STARTED", LogMode.OK)

    await start_db()


async def shutdown(dp):
    log("CINOTES BOT STOPED", LogMode.OK)


@dp.message_handler(commands=["start"])
async def start_func(message: types.Message):
    log(f"Start pressed by user {message.chat.id}", LogMode.INFO)

    res = cur_executor("SELECT * FROM users WHERE user_id=%s;", message.chat.id)
    if res and isinstance(res[0], tuple):
        await message.answer("Привіт, я бот персональних рекомендацій для проекту Cinotes. Тисни /help для отримання інструкцій")
    else:
        await bot.send_message(message.chat.id, "Обери мову бота / Choose bot language", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton("Українська", callback_data="language_ua"),
                InlineKeyboardButton("English", callback_data="language_en")
            ]
        ]))


@dp.callback_query_handler(Text(startswith="language_"))
async def language_call(callback: types.CallbackQuery):
    await callback.answer()

    lang = callback.data.split("_")[1]
    uid = callback.message.chat.id

    res = cur_executor("SELECT * FROM users WHERE user_id=%s;", uid)
    if res and isinstance(res[0], tuple):
        cur_executor("UPDATE users SET language=%s WHERE user_id=%s;", lang, uid)
    else:
        cur_executor("INSERT INTO users(user_id, language) VALUES (%s, %s);", uid, lang)
    
    await callback.message.edit_text("Привіт, я бот персональних рекомендацій для проекту Cinotes. Тисни /help для отримання інструкцій")


async def check_user_in_db(uid: int) -> bool:
    res = bool(cur_executor("SELECT user_id FROM users WHERE user_id=%s;", uid))
    if not res:
        await bot.send_message(uid, "Виникла помилка всередині бота, відправ /start")
    return res


@dp.message_handler(commands=["help"])
async def help_func(message: types.Message):
    log(f"Get help by user {message.chat.id}", LogMode.INFO)

    if not await check_user_in_db(message.chat.id):
        return

    await message.answer("<b>Пізніше</b> <i>тут</i> <code>щось</code> буде...", parse_mode="HTML")



@dp.message_handler(commands=["language"])
async def language_func(message: types.Message):
    log(f"Get language by user {message.chat.id}", LogMode.INFO)

    if not await check_user_in_db(message.chat.id):
        return

    await bot.send_message(message.chat.id, "Обери мову бота / Choose bot language", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton("Українська", callback_data="language_ua"),
            InlineKeyboardButton("English", callback_data="language_en")
        ]
    ]))


@dp.message_handler(commands=["login"])
async def login_func(message: types.Message):
    log(f"Trying login by user {message.chat.id}", LogMode.INFO)

    if not await check_user_in_db(message.chat.id):
        return

    await bot.send_message(message.chat.id, "Просто натисни на кнопку внизу", reply_markup=ReplyKeyboardMarkup(
        [
            [
                KeyboardButton("Авторизуватися", web_app=WebAppInfo(url="https://hittiks.github.io/"))
            ]
        ], True
    ))


async def add_account_to_db(user_id: int, user_type: str, jwt: str):
    log(f"Trying add to db account of user {user_id} with type '{user_type}' and jwt '{jwt}'", LogMode.INFO)

    res = cur_executor("SELECT user_id FROM accounts WHERE user_id=%s;", user_id)
    if res and isinstance(res[0], str):
        log(f"Get error when trying add account to db: type: '{res[0]}', text: '{res[1]}'", LogMode.ERROR)
        return False
    
    if res and isinstance(res[0], tuple):
        cur_executor("UPDATE accounts SET user_type=%s, jwt=%s WHERE user_id=%s;", user_type, jwt, user_id)
        return True
    else:
        cur_executor("INSERT INTO accounts(user_id, user_type, jwt) VALUES (%s, %s, %s);", user_id, user_type, jwt)
        return True


@dp.message_handler(content_types="web_app_data")
async def handle_web_app_data_func(message :types.Message):
    log(f"Get web app data '{message.web_app_data}' from user {message.chat.id}", LogMode.INFO)

    if not await check_user_in_db(message.chat.id):
        return

    temp = await message.answer("Намагаюсь авторизуватися...")

    login, password = message.web_app_data["data"].split("\n")
    log(f"Username: '{login}', password: '{password}'", LogMode.INFO)
    
    data = {
        "email": login,
        "password": password
    }

    response = requests.post("http://cinotes-alb-1929580936.eu-central-1.elb.amazonaws.com/auth/signin", json=data)

    if response.status_code != 200:
        if response.status_code == 404 and "no user with such email" in response.text:
            log("Wrong email", LogMode.WARNING)
            await temp.edit_text("Виникла помилка: вказано неправильну пошту")
            return
        elif response.status_code == 403 and "wrong password" in response.text:
            log("Wrong password", LogMode.WARNING)
            await temp.edit_text("Виникла помилка: вказано неправильний пароль")
            return
        else:
            await temp.edit_text("Виникла невідома помилка")
            log(f"Get unknown error: status code: {response.status_code}, response text: '{response.text.strip()}'", LogMode.ERROR)
            return

    try:
        jwt: str = response.json()["jwt"]
        log(f"JWT: '{jwt}'", LogMode.OK)
        await temp.edit_text("Успішно авторизований!")
        parts = jwt.split(".")

        data_str = base64.b64decode(parts[1] + "=" * (4-(len(parts[1]) % 4))).decode("utf-8")
        data = json.loads(data_str)
        dt = datetime.fromtimestamp(data["exp"])

        await message.answer(f"Токен авторизації дійсний до: {dt}", reply_markup=ReplyKeyboardRemove())

        user_type = data["userType"]

        if user_type == "basic":
            log(f"Account of user {message.chat.id} is basic so he don't accessed to recomendations", LogMode.INFO)
            await message.answer("Тобі недоступна система рекомендацій. Щоб отримати доступ, придбай віп-підписку на сайті або у додатку")

        if user_type == "admin":
            await add_account_to_db(message.chat.id, user_type, jwt)
            await message.answer("Твій акаунт розпізнано як адміністративний. Тобі будуть доступні деякі додаткові функції, детальніше: /admin")

        if user_type == "premium":
            await add_account_to_db(message.chat.id, user_type, jwt)
            await message.answer("Бота успішно підключено!")

    except Exception as e:
        log(f"Get error when parse jwt: error type: '{type(e).__name__}', error args: '{e.args}'", LogMode.ERROR)
        await temp.edit_text("Виникла невідома помилка")


@dp.message_handler(is_bot_admin=True, commands=["admin"])
async def admin_func(message: types.Message):
    log(f"Get admin by user {message.chat.id}", LogMode.INFO)

    if not await check_user_in_db(message.chat.id):
        return

    await message.answer("Тут буде інформація про додаткові можливості адміністраторів")


@dp.message_handler(content_types=['text'])
async def text_handler(message: types.Message):
    log(f"Get unknown text '{message.text}' from user {message.chat.id}", LogMode.INFO)
    await message.answer("Я не розумію тебе. Відправ /start або /help")


@dp.message_handler(content_types=ContentTypes.all())
async def other_handler(message: types.Message):
    log(f"Get illegal type of message from user {message.chat.id}", LogMode.INFO)
    await message.answer("Я приймаю лише текстові повідомлення. Для отримання інструкцій натисни /help")


if __name__ == "__main__":
    executor.start_polling(dp, on_startup=startup, on_shutdown=shutdown)
