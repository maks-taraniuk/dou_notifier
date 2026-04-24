# DOU RSS Notifier

Small Docker container that watches the DOU Android vacancies RSS feed and sends new vacancies to Telegram.

Default feed:

```text
https://jobs.dou.ua/vacancies/feeds/?descr=1&category=Android
```

## Setup

1. Create Telegram bot with `@BotFather`.
2. Send any message to the bot.
3. Open this URL in a browser, replacing `<YOUR_TOKEN>`:

```text
https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
```

4. Open `.env` and fill in:

```dotenv
TELEGRAM_BOT_TOKEN=123456:your-token
TELEGRAM_CHAT_ID=123456789
```

5. Start the notifier:

```bash
docker compose up -d --build
```

Logs:

```bash
docker compose logs -f
```

Stop:

```bash
docker compose down
```

## Portainer on Synology

Recommended path: put this project into a private Git repository, without committing `.env`.

Files that should be in the repo:

```text
app/rss_notifier.py
Dockerfile
docker-compose.yml
.env.example
README.md
```

In Portainer:

1. Go to `Stacks`.
2. Click `Add stack`.
3. Choose `Repository`.
4. Set repository URL, branch, and compose path: `docker-compose.yml`.
5. Add these environment variables in Portainer:

```dotenv
RSS_URL=https://jobs.dou.ua/vacancies/feeds/?descr=1&category=Android
POLL_INTERVAL_SECONDS=300
FIRST_RUN_SEND_EXISTING=false
MAX_ITEMS_PER_POLL=20
MAX_SUMMARY_CHARS=1200
LOG_LEVEL=INFO
TELEGRAM_BOT_TOKEN=your-real-token
TELEGRAM_CHAT_ID=370838943
```

6. Deploy the stack.
7. Open stack logs and check for `Watching RSS feed`.

No inbound port is needed. The container only makes outgoing requests to DOU RSS and Telegram API.

## Run Without Docker

This script has no external Python dependencies, so it can also run directly:

```bash
python3 app/rss_notifier.py
```

For a one-time check:

```bash
RUN_ONCE=true STATE_FILE=./data/seen.json python3 app/rss_notifier.py
```

## First Run Behavior

By default, the first run saves existing RSS vacancies without sending them. After that it sends only new vacancies.

To send current vacancies too, set:

```dotenv
FIRST_RUN_SEND_EXISTING=true
```

## Useful Settings

```dotenv
RSS_URL=https://jobs.dou.ua/vacancies/feeds/?descr=1&category=Android
POLL_INTERVAL_SECONDS=300
MAX_ITEMS_PER_POLL=20
MAX_SUMMARY_CHARS=1200
```

State is stored in the Docker volume `dou-rss-data`, so restarting the container will not resend old vacancies.
