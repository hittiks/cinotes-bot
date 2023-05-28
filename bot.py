import os
import json
import base64
import asyncio
import requests
import psycopg2

from logger import log, LogMode
from datetime import datetime
from languages import TEXTS

from aiogram import Bot as AiogramBot, Dispatcher, executor, types, exceptions as tg_exceptions
from aiogram.types.message import ContentTypes
from aiogram.types.input_file import InputFile
from aiogram.types.web_app_info import WebAppInfo
from aiogram.dispatcher.filters import BoundFilter, Text
from aiogram.types.reply_keyboard import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.types.inline_keyboard import InlineKeyboardMarkup, InlineKeyboardButton


bot = AiogramBot(os.environ["cinotes_bot_token"])
dp = Dispatcher(bot)
BOT_OWNER_ID = int(os.environ["cinotes_bot_owner_id"])
USERS_LANGS = dict()


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


async def get_lang(user_id: int):
    global USERS_LANGS
    if USERS_LANGS.get(user_id):
        return USERS_LANGS.get(user_id)
    
    res = cur_executor("SELECT language FROM users WHERE user_id=%s;", user_id)
    if isinstance(res[0], str):
        await bot.send_message(BOT_OWNER_ID, f"Не удалось получить язык юзера из-за sql-ошибки: type: '{res[0]}', text: '{res[1]}'")
        return "en"
    
    USERS_LANGS[user_id] = res[0][0]
    return res[0][0]


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
    cur.execute("CREATE TABLE IF NOT EXISTS accounts(user_id BIGINT PRIMARY KEY NOT NULL, user_type TEXT NOT NULL, jwt TEXT NOT NULL, expire_on BIGINT NOT NULL);")
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
        lang = await get_lang(message.chat.id)
        await message.answer(TEXTS[lang]["start_message"])
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

    global USERS_LANGS
    USERS_LANGS[uid] = lang

    res = cur_executor("SELECT * FROM users WHERE user_id=%s;", uid)
    if res and isinstance(res[0], tuple):
        cur_executor("UPDATE users SET language=%s WHERE user_id=%s;", lang, uid)
    else:
        cur_executor("INSERT INTO users(user_id, language) VALUES (%s, %s);", uid, lang)
        log(f"New user in database: {uid}", LogMode.OK)
        tu = cur_executor("SELECT * FROM users;")
        await bot.send_message(BOT_OWNER_ID, f"Новый пользователь в базе: {uid}\nСтало пользователей: {len(tu)}")
    
    lang = await get_lang(uid)
    await callback.message.edit_text(TEXTS[lang]["start_message"])


async def check_user_in_db(uid: int) -> bool:
    res = bool(cur_executor("SELECT user_id FROM users WHERE user_id=%s;", uid))
    if not res:
        lang = await get_lang(uid)
        await bot.send_message(uid, TEXTS[lang]["user_not_in_db_error"])
    return res


@dp.message_handler(commands=["help"])
async def help_func(message: types.Message):
    log(f"Get help by user {message.chat.id}", LogMode.INFO)

    if not await check_user_in_db(message.chat.id):
        return

    lang = await get_lang(message.chat.id)
    await message.answer(TEXTS[lang]["help_message"], parse_mode="HTML")


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

    lang = await get_lang(message.chat.id)
    await bot.send_message(message.chat.id, TEXTS[lang]["press_button_to_login"], reply_markup=ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(TEXTS[lang]["login_button_text"], web_app=WebAppInfo(url="https://hittiks.github.io/"))
            ]
        ], True
    ))


async def add_account_to_db(user_id: int, user_type: str, jwt: str, expire_on: int):
    log(f"Trying add to db account of user {user_id} with type '{user_type}' and jwt '{jwt}'", LogMode.INFO)

    res = cur_executor("SELECT user_id FROM accounts WHERE user_id=%s;", user_id)
    if res and isinstance(res[0], str):
        log(f"Get error when trying add account to db: type: '{res[0]}', text: '{res[1]}'", LogMode.ERROR)
        return False
    
    if res and isinstance(res[0], tuple):
        cur_executor("UPDATE accounts SET user_type=%s, jwt=%s, expire_on=%s WHERE user_id=%s;", user_type, jwt, expire_on, user_id)
        return True
    else:
        cur_executor("INSERT INTO accounts(user_id, user_type, jwt, expire_on) VALUES (%s, %s, %s, %s);", user_id, user_type, jwt, expire_on)
        return True


@dp.message_handler(content_types="web_app_data")
async def handle_web_app_data_func(message :types.Message):
    log(f"Get web app data '{message.web_app_data}' from user {message.chat.id}", LogMode.INFO)

    if not await check_user_in_db(message.chat.id):
        return

    lang = await get_lang(message.chat.id)
    temp = await message.answer(TEXTS[lang]["trying_login"])

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
            await temp.edit_text(TEXTS[lang]["wrong_email"])
            return
        elif response.status_code == 403 and "wrong password" in response.text:
            log("Wrong password", LogMode.WARNING)
            await temp.edit_text(TEXTS[lang]["wrong_password"])
            return
        else:
            await temp.edit_text(TEXTS[lang]["unknown_server_error"])
            log(f"Get unknown error: status code: {response.status_code}, response text: '{response.text.strip()}'", LogMode.ERROR)
            return

    try:
        jwt: str = response.json()["jwt"]
        log(f"JWT: '{jwt}'", LogMode.OK)
        await temp.edit_text(TEXTS[lang]["success_login"])
        parts = jwt.split(".")

        data_str = base64.b64decode(parts[1] + "=" * (4-(len(parts[1]) % 4))).decode("utf-8")
        data = json.loads(data_str)
        dt = datetime.fromtimestamp(data["exp"])

        await message.answer(TEXTS[lang]["jwt_expire_on"].format(dt=dt), reply_markup=ReplyKeyboardRemove())

        user_type = data["userType"]

        if user_type == "basic":
            log(f"Account of user {message.chat.id} is basic so he don't accessed to recomendations", LogMode.INFO)
            await message.answer(TEXTS[lang]["user_is_basic"])

        if user_type == "admin":
            await add_account_to_db(message.chat.id, user_type, jwt, int(data["exp"]))
            await message.answer(TEXTS[lang]["user_is_admin"])

        if user_type == "premium":
            await add_account_to_db(message.chat.id, user_type, jwt, int(data["exp"]))
            await message.answer(TEXTS[lang]["user_is_premium"])

    except Exception as e:
        log(f"Get error when parse jwt: error type: '{type(e).__name__}', error args: '{e.args}'", LogMode.ERROR)
        await temp.edit_text(TEXTS[lang]["unknown_bot_error"])


@dp.message_handler(is_bot_admin=True, commands=["admin"])
async def admin_func(message: types.Message):
    log(f"Get admin by user {message.chat.id}", LogMode.INFO)

    if not await check_user_in_db(message.chat.id):
        return

    lang = await get_lang(message.chat.id)
    await message.answer(TEXTS[lang]["admin_message"])


@dp.message_handler(is_bot_owner=True, commands=["stop"])
async def stop_func(message: types.Message):
    log("Trying stop bot", LogMode.INFO)

    try:
        await message.delete()
    except tg_exceptions.MessageToDeleteNotFound:
        pass
    else:
        await bot.send_message(BOT_OWNER_ID, "Выход...")
        await asyncio.sleep(3)

        dp.stop_polling()
        await dp.storage.close()
        await dp.storage.wait_closed()
        session = await dp.bot.get_session()
        await session.close()

        for _ in range(10):
            try:
                asyncio.get_running_loop().stop()
                asyncio.get_running_loop().close()
            except RuntimeError:
                await asyncio.sleep(1)
            else:
                break

        await shutdown(dp)
        exit(5)


@dp.message_handler(is_bot_owner=True, commands=["sqlexecute"])
async def sqlexecute_func(message: types.Message):
    log("Trying execute sql query", LogMode.INFO)

    try:
        query = message.text.split("/sqlexecute ", maxsplit=1)[1]
    except (IndexError, ValueError):
        await message.reply("Требуется параметр в виде строки")
        return

    result = cur_executor(query)
    if result == ['ProgrammingError', 'no results to fetch'] or not result:
        await message.reply("Запрос не вернул никаких данных")
    elif result[0] and result[0] == "UniqueViolation":
        await message.reply("Такие данные уже есть в бд")
    elif result[0] and isinstance(result[0], str):
        await message.reply(f"Произошла ошибка во время выполнения запроса:\nТип: '{result[0]}'\nТекст: '{result[1]}'")
    else:
        with open("tempfile.txt", "w") as f:
            f.write(str(result))
        
        mess = await message.reply_document(InputFile("tempfile.txt"), caption="Результат выполнения запроса в файле")
        while True:
            if mess:
                os.remove("tempfile.txt")
                break
            asyncio.sleep(1)


@dp.message_handler(content_types=['text'])
async def text_handler(message: types.Message):
    log(f"Get unknown text '{message.text}' from user {message.chat.id}", LogMode.INFO)
    
    lang = await get_lang(message.chat.id)
    await message.answer(TEXTS[lang]["get_unknown_text_message"])


@dp.message_handler(content_types=ContentTypes.all())
async def other_handler(message: types.Message):
    log(f"Get illegal type of message from user {message.chat.id}", LogMode.INFO)
    
    lang = await get_lang(message.chat.id)
    await message.answer(TEXTS[lang]["get_unknown_type_of_message"])


if __name__ == "__main__":
    executor.start_polling(dp, on_startup=startup, on_shutdown=shutdown)
