FROM python:3.11-slim

WORKDIR /discord_app

COPY discord_app/ .
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "bot.py"]