import os
import discord
from dotenv import load_dotenv
from discord.ext import commands

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
APPLICATION_ID = os.getenv("DISCORD_APPLICATION_ID")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents, application_id=APPLICATION_ID)

USER_FILE = "users.txt"

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

bot.run(TOKEN)
