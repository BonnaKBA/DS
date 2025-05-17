import os
import re
import asyncio
import discord
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
from discord.ext import commands
from discord import app_commands
from datetime import timedelta, datetime

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
APPLICATION_ID = os.getenv("DISCORD_APPLICATION_ID")
CHAT_BANNED_ROLE_ID = int(os.getenv("CHAT_BANNED_ROLE_ID"))
VOICE_BANNED_ROLE_ID = int(os.getenv("VOICE_BANNED_ROLE_ID"))

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents, application_id=APPLICATION_ID)

USER_FILE = "clear_users.txt"

MAX_TIMEOUT_SECONDS = 28 * 24 * 60 * 60

def log_moderation_action(
    action, moderator_id, moderator_name, user_id, user_name,
    scope, reason, amount=None, unit=None, expires_at=None
):
    try:
        connection = mysql.connector.connect(
            host=os.getenv("MYSQL_HOST"),
            port=int(os.getenv("MYSQL_PORT", 3306)),
            user=os.getenv("MYSQL_USER"),
            password=os.getenv("MYSQL_PASSWORD"),
            database=os.getenv("MYSQL_DATABASE")
        )

        cursor = connection.cursor()

        query = """
            INSERT INTO moderation_logs (
                action, moderator_id, moderator_name, user_id, user_name,
                scope, reason, amount, unit, created_at, expires_at, resolved
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(), %s, %s)
        """

        # resolved только если channel
        resolved_value = False if scope == 'channel' else None

        cursor.execute(query, (
            action, moderator_id, moderator_name, user_id, user_name,
            scope, reason, amount, unit, expires_at, resolved_value
        ))

        connection.commit()

    except Error as e:
        print(f"[MySQL] Ошибка при логировании действия: {e}")

    finally:
        if 'connection' in locals() and connection.is_connected():
            cursor.close()
            connection.close()


def is_user_allowed(user_id):
    if not os.path.exists(USER_FILE):
        return False

    with open(USER_FILE, "r") as file:
        allowed_users = file.read().splitlines()

    return str(user_id) in allowed_users

@bot.event
async def on_ready():
    print(f'{bot.user} подключён')
    await bot.tree.sync()
    print("Команды успешно синхронизированы")
    bot.loop.create_task(check_expired_locks())

@bot.tree.command(name="clear_add", description="Добавить пользователя в список разрешенных")
async def clear_add(interaction: discord.Interaction, user: discord.User):
    if interaction.user.id == interaction.guild.owner_id:
        user_id = user.id
        if os.path.exists(USER_FILE):
            with open(USER_FILE, "r") as file:
                allowed_users = file.read().splitlines()
            if str(user_id) in allowed_users:
                await interaction.response.send_message(f"Пользователь {user.mention} уже добавлен в список разрешенных.", ephemeral=True)
                return
        with open(USER_FILE, "a") as file:
            file.write(f"{user_id}\n")
        await interaction.response.send_message(f"Пользователь {user.mention} добавлен в список разрешенных.", ephemeral=True)
    else:
        await interaction.response.send_message("Только владелец сервера может добавлять пользователей.", ephemeral=True)

@bot.tree.command(name="clear_remove", description="Удалить пользователя из списка разрешенных")
async def clear_remove(interaction: discord.Interaction, user: discord.User):
    if interaction.user.id == interaction.guild.owner_id:
        user_id = user.id
        if os.path.exists(USER_FILE):
            with open(USER_FILE, "r") as file:
                allowed_users = file.read().splitlines()

            if str(user_id) in allowed_users:
                allowed_users.remove(str(user_id))
                with open(USER_FILE, "w") as file:
                    file.write("\n".join(allowed_users))
                await interaction.response.send_message(f"Пользователь {user.mention} удален из списка разрешенных.", ephemeral=True)
            else:
                await interaction.response.send_message(f"Пользователь {user.mention} не найден в списке.", ephemeral=True)
        else:
            await interaction.response.send_message("Файл с разрешенными пользователями не найден.", ephemeral=True)
    else:
        await interaction.response.send_message("Только владелец сервера может удалять пользователей.", ephemeral=True)

def get_message_declension(number):
    if number % 10 == 1 and number % 100 != 11:
        return "сообщение"
    elif 2 <= number % 10 <= 4 and not (12 <= number % 100 <= 14):
        return "сообщения"
    else:
        return "сообщений"

class ConfirmClearView(discord.ui.View):
    def __init__(self, interaction, amount):
        super().__init__(timeout=30)
        self.interaction = interaction
        self.amount = amount

    @discord.ui.button(label="Да", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message("Вы не инициировали эту команду.", ephemeral=True)
            return
        await interaction.response.defer()
    
        deleted_messages = await self.interaction.channel.purge(limit=self.amount)
        declension = get_message_declension(len(deleted_messages))
    
        if len(deleted_messages) == 0:
            content = "В данном канале нет сообщений."
        else:
            content = f"Все {len(deleted_messages)} {declension} в данном канале удалены."
        await interaction.edit_original_response(content=content, view=None)
    
    @discord.ui.button(label="Нет", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message("Вы не инициировали эту команду.", ephemeral=True)
            return

        await interaction.response.edit_message(content="Удаление отменено.", view=None)

@bot.tree.command(name="clear", description="Удалить сообщения в канале")
async def clear(interaction: discord.Interaction, amount: int = 10000):
    if amount <= 0:
        await interaction.response.send_message("Количество сообщений для удаления должно быть больше 0.", ephemeral=True)
        return

    if interaction.user.id == interaction.guild.owner_id or is_user_allowed(interaction.user.id):
        if amount == 10000:
            await interaction.response.defer(ephemeral=True)
            channel_link = f"<#{interaction.channel.id}>"
            await interaction.followup.send(
                content=f"Вы уверены, что хотите удалить все сообщения в {channel_link}?",
                view=ConfirmClearView(interaction, amount),
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        deleted_messages = await interaction.channel.purge(limit=amount)
        count = len(deleted_messages)
        if count == 0:
            await interaction.followup.send("В данном канале нет сообщений.", ephemeral=True)
        else:
            declension = get_message_declension(count)
            await interaction.followup.send(f"Последние {count} {declension} в данном канале удалены.", ephemeral=True)
    else:
        await interaction.response.send_message("У вас нет прав для использования этой команды.", ephemeral=True)

@bot.tree.command(name="clear_show", description="Показать добавленных пользователей")
async def clear_show(interaction: discord.Interaction):
    if os.path.exists(USER_FILE):
        with open(USER_FILE, "r") as file:
            allowed_users = file.read().splitlines()

        if allowed_users:
            user_mentions = []
            for user_id in allowed_users:
                user_mentions.append(f"<@{user_id}>")
            user_list = "\n".join(user_mentions)
            await interaction.response.send_message(f"Список добавленных пользователей:\n{user_list}", ephemeral=True)
        else:
            await interaction.response.send_message("Список разрешенных пользователей пуст.", ephemeral=True)
    else:
        await interaction.response.send_message("Файл с разрешенными пользователями не найден.", ephemeral=True)

def parse_duration(duration: str) -> int:
    """Преобразует строку (например, '10m', '2h') в секунды"""
    match = re.fullmatch(r"(\d+)([smhd])", duration)
    if not match:
        return None
    value, unit = match.groups()
    value = int(value)
    if unit == "s":
        return value
    if unit == "m":
        return value * 60
    if unit == "h":
        return value * 3600
    if unit == "d":
        return value * 86400
    return None

UNITS = {
    "seconds": 1,
    "minutes": 60,
    "hours": 3600,
    "days": 86400
}

def get_time_unit(unit: str, amount: int) -> str:
    suffixes = {
        "seconds": ["секунду", "секунды", "секунд"],
        "minutes": ["минуту", "минуты", "минут"],
        "hours": ["час", "часа", "часов"],
        "days": ["день", "дня", "дней"]
}
    forms = suffixes.get(unit, [unit, unit, unit])
    if 11 <= amount % 100 <= 14:
        return forms[2]
    elif amount % 10 == 1:
        return forms[0]
    elif 2 <= amount % 10 <= 4:
        return forms[1]
    return forms[2]


@app_commands.describe(
    user="Кого ограничить",
    scope="Канал — только в этом канале, Сервер — на всём сервере",
    amount="Время блокировки",
    unit="Единица времени (секунды, минуты, часы, дни)",
    reason="Причина ограничения"
)
@app_commands.choices(
    unit=[
        app_commands.Choice(name="секунды", value="seconds"),
        app_commands.Choice(name="минуты", value="minutes"),
        app_commands.Choice(name="часы", value="hours"),
        app_commands.Choice(name="дни", value="days")
    ]
)
@app_commands.choices(
    scope=[
        app_commands.Choice(name="Сервер", value="server"),
        app_commands.Choice(name="Канал", value="channel"),
    ]
)
@app_commands.checks.has_permissions(administrator=True)
@bot.tree.command(name="lock", description="Ограничить пользователя")
async def lock(
    interaction: discord.Interaction,
    user: discord.Member,
    scope: str,
    reason: str,
    amount: int = None,
    unit: app_commands.Choice[str] = None
):
    await interaction.response.defer(ephemeral=True)

    if user.guild_permissions.administrator:
        await interaction.followup.send("❌ Нельзя ограничить администратора.", ephemeral=True)
        return

    if user.top_role >= interaction.guild.me.top_role:
        await interaction.followup.send("❌ У пользователя роль выше или равна роли бота. Ограничение невозможно.", ephemeral=True)
        return

    if (amount is None and unit is not None) or (amount is not None and unit is None):
        await interaction.followup.send(
            "⚠️ Укажите и `amount`, и `unit` вместе, либо не указывайте вовсе для максимальной блокировки.",
            ephemeral=True
        )
        return
    
    if scope == "channel":
        if await asyncio.to_thread(has_scope_lock, user.id, "server"):
            await interaction.followup.send(
                f"❌ У пользователя {user.mention} уже есть активная блокировка `server`.",
                ephemeral=True
            )
            return
        if await asyncio.to_thread(has_scope_lock, user.id, "channel"):
            await interaction.followup.send(
                f"❌ У пользователя {user.mention} уже есть активная блокировка `channel`.",
                ephemeral=True
            )
            return
    
    elif scope == "server":
        if await asyncio.to_thread(has_scope_lock, user.id, "server"):
            await interaction.followup.send(
                f"❌ У пользователя {user.mention} уже есть активная блокировка `server`.",
                ephemeral=True
            )
            return
    
    if amount == 0:
        await interaction.followup.send("⚠️ Значение времени не может быть равно 0.", ephemeral=True)
        return

    if scope == "channel":
        chat_banned_role = interaction.guild.get_role(CHAT_BANNED_ROLE_ID)
        if not chat_banned_role:
            await interaction.followup.send("❌ Не найдена роль chat banned.", ephemeral=True)
            return

        await user.add_roles(chat_banned_role, reason=reason)

        await interaction.followup.send(
            f"🔒 {user.mention} теперь не может писать в этом канале.\n**Причина:** {reason}",
            ephemeral=True
        )

        expires_at = None
        if amount and unit:
            seconds = amount * UNITS[unit.value]
            expires_at = datetime.utcnow() + timedelta(seconds=seconds)

        await asyncio.to_thread(
            log_moderation_action,
            action="lock",
            moderator_id=interaction.user.id,
            moderator_name=str(interaction.user),
            user_id=user.id,
            user_name=str(user),
            scope=scope,
            reason=reason,
            amount=amount,
            unit=unit.value if unit else None,
            expires_at=expires_at
        )

        return

    elif scope == "server":
        if amount and unit:
            if unit.value not in UNITS:
                await interaction.followup.send("❌ Неверно указана единица времени.", ephemeral=True)
                return
    
            seconds = amount * UNITS[unit.value]
            if seconds > MAX_TIMEOUT_SECONDS:
                await interaction.followup.send("❌ Максимальное время таймаута — 28 дней.", ephemeral=True)
                return
    
            until = discord.utils.utcnow() + timedelta(seconds=seconds)
            unit_str = get_time_unit(unit.value, amount)
            duration_text = f"на {amount} {unit_str}"
    
            # ✅ добавляем expires_at
            expires_at = datetime.utcnow() + timedelta(seconds=seconds)
        else:
            until = discord.utils.utcnow() + timedelta(days=28)
            duration_text = "максимально (28 дней макс)"
    
            # ✅ для максимального времени блокировки можно не задавать expires_at (None)
            expires_at = None
    
        try:
            await user.timeout(until, reason=reason)
    
            await interaction.followup.send(
                f"🔒 {user.mention} ограничен {duration_text}.\n**Причина:** {reason}",
                ephemeral=True
            )
    
            await asyncio.to_thread(
                log_moderation_action,
                action="lock",
                moderator_id=interaction.user.id,
                moderator_name=str(interaction.user),
                user_id=user.id,
                user_name=str(user),
                scope=scope,
                reason=reason,
                amount=amount,
                unit=unit.value if unit else None,
                expires_at=expires_at  # ✅ сохраняем дату окончания
            )
    
        except discord.Forbidden:
            await interaction.followup.send("❌ Нет прав ограничить этого пользователя.", ephemeral=True)
    
def has_scope_lock(user_id: int, scope: str) -> bool:
    try:
        connection = mysql.connector.connect(
            host=os.getenv("MYSQL_HOST"),
            port=int(os.getenv("MYSQL_PORT", 3306)),
            user=os.getenv("MYSQL_USER"),
            password=os.getenv("MYSQL_PASSWORD"),
            database=os.getenv("MYSQL_DATABASE")
        )

        cursor = connection.cursor()
        query = """
            SELECT COUNT(*) FROM moderation_logs
            WHERE user_id = %s AND scope = %s AND action = 'lock'
            AND (
                (scope = 'channel' AND resolved = FALSE)
                OR (scope = 'server' AND (expires_at IS NULL OR expires_at > UTC_TIMESTAMP()))
            )
        """
        cursor.execute(query, (user_id, scope))
        count = cursor.fetchone()[0]
        return count > 0

    except Error as e:
        print(f"[MySQL] Ошибка при проверке блокировки: {e}")
        return False

    finally:
        if 'connection' in locals() and connection.is_connected():
            cursor.close()
            connection.close()

@app_commands.describe(
    user="Кого разблокировать",
    scope="Где снять ограничение: канал или сервер",
    reason="Причина разблокировки"
)
@app_commands.choices(
    scope=[
        app_commands.Choice(name="Сервер", value="server"),
        app_commands.Choice(name="Канал", value="channel"),
    ]
)
@app_commands.checks.has_permissions(administrator=True)
@bot.tree.command(name="unlock", description="Снять ограничение на отправку сообщений у пользователя")
async def unlock(
    interaction: discord.Interaction,
    user: discord.Member,
    scope: app_commands.Choice[str],
    reason: str
):
    await interaction.response.defer(ephemeral=True)

    if user.guild_permissions.administrator:
        await interaction.followup.send("❌ У администратора нет ограничений.", ephemeral=True)
        return

    if user.top_role >= interaction.guild.me.top_role:
        await interaction.followup.send("❌ У пользователя роль выше или равна роли бота. Снятие невозможно.", ephemeral=True)
        return
    
    if not await asyncio.to_thread(has_scope_lock, user.id, scope.value):
        await interaction.followup.send(
            f"✅ У пользователя {user.mention} нет активной блокировки в области `{scope.value}`.",
            ephemeral=True
        )
        return

    if scope.value == "channel":
        chat_banned_role = interaction.guild.get_role(CHAT_BANNED_ROLE_ID)
        if not chat_banned_role:
            await interaction.followup.send("❌ Роль chat banned не найдена.", ephemeral=True)
            return

        if chat_banned_role in user.roles:
            await user.remove_roles(chat_banned_role, reason=reason)
            await interaction.followup.send(
                f"🔓 {user.mention} разблокирован в этом канале.\n**Причина:** {reason}",
                ephemeral=True
            )

            await asyncio.to_thread(
                log_moderation_action,
                action="unlock",
                moderator_id=interaction.user.id,
                moderator_name=str(interaction.user),
                user_id=user.id,
                user_name=str(user),
                scope=scope.value,
                reason=reason
            )

        else:
            await interaction.followup.send(
                f"{user.mention} не был заблокирован в канале.",
                ephemeral=True
            )

    elif scope.value == "server":
        try:
            await user.timeout(None, reason=reason)
            await interaction.followup.send(
                f"🔓 {user.mention} разблокирован на сервере.\n**Причина:** {reason}",
                ephemeral=True
            )

            await asyncio.to_thread(
                log_moderation_action,
                action="unlock",
                moderator_id=interaction.user.id,
                moderator_name=str(interaction.user),
                user_id=user.id,
                user_name=str(user),
                scope=scope.value,
                reason=reason
            )
    
        except discord.Forbidden:
            await interaction.followup.send("❌ Нет прав разблокировать пользователя.", ephemeral=True)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message(
            "❌ У вас нет прав администратора для использования данной команды.",
            ephemeral=True
        )

async def check_expired_locks():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            connection = mysql.connector.connect(
                host=os.getenv("MYSQL_HOST"),
                port=int(os.getenv("MYSQL_PORT", 3306)),
                user=os.getenv("MYSQL_USER"),
                password=os.getenv("MYSQL_PASSWORD"),
                database=os.getenv("MYSQL_DATABASE")
            )
            cursor = connection.cursor(dictionary=True)

            query = """
                SELECT * FROM moderation_logs
                WHERE action = 'lock'
                AND scope = 'channel'
                AND resolved = FALSE
                AND expires_at IS NOT NULL
                AND expires_at <= UTC_TIMESTAMP()
            """
            cursor.execute(query)
            expired_locks = cursor.fetchall()

            for lock in expired_locks:
                guild = bot.get_guild(int(os.getenv("GUILD_ID")))
                if not guild:
                    continue

                member = guild.get_member(lock["user_id"])
                if not member:
                    continue

                role = guild.get_role(CHAT_BANNED_ROLE_ID)
                if role and role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Автоматическая разблокировка")
                    except Exception as e:
                        print(f"[AutoUnlock] Не удалось снять роль: {e}")

                update_query = """
                    UPDATE moderation_logs SET resolved = TRUE
                    WHERE id = %s
                """
                cursor.execute(update_query, (lock["id"],))
                connection.commit()
                print(f"[AutoUnlock] Разблокирован {member} в области {lock['scope']}")

        except Error as e:
            print(f"[MySQL] Ошибка при проверке истекших блокировок: {e}")

        finally:
            if 'connection' in locals() and connection.is_connected():
                cursor.close()
                connection.close()

        await asyncio.sleep(60)  # Проверка каждую минуту

bot.run(TOKEN)