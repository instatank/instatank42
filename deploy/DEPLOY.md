# Deploying the Telegram Bot — Step by Step

This guide walks you through putting the bot on its own small server so it
runs 24/7, even when your computer is off. No prior server experience needed.
Total time: about 20–30 minutes.

You will need three secret values before you start:

| Value | What it is | Where to get it |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | The bot's password for Telegram | From @BotFather in Telegram (create a bot, it gives you a token) |
| `ANTHROPIC_API_KEY` | Key that lets the bot use Claude | https://console.anthropic.com → API Keys |
| `TELEGRAM_ALLOWED_USER_ID` | Your personal Telegram user ID (a number), so only you can use the bot | Message @userinfobot in Telegram, it replies with your ID |

Keep these somewhere handy (a notes app is fine for now) — you'll paste them
in during step 4.

---

## 1. Create a server on Hetzner

1. Go to https://www.hetzner.com/cloud and create an account (email +
   password, then verify your email; they may ask for ID or a small payment
   verification — that's normal).
2. In the Hetzner Cloud Console, click **New Project**, give it any name.
3. Inside the project, click **Add Server** and choose:
   - **Location:** anything close to you (e.g. Falkenstein or Helsinki).
   - **Image:** Ubuntu 24.04.
   - **Type:** the smallest **shared vCPU** option, e.g. **CX22**
     (2 vCPU / 4 GB RAM). This bot is tiny — the smallest tier is plenty.
     Pricing changes over time, so confirm at checkout; as of 2026 it's
     roughly €4–5/month.
   - **SSH key:** if you already have one, add it. If you don't know what
     that is, skip it — Hetzner will email you a root password instead.
4. Click **Create & Buy Now**. After about a minute the server appears with
   an **IP address** (four numbers like `203.0.113.42`). Copy it — you'll
   use it in the next step.

---

## ⚡ Fast path: let a helper script do steps 2–6

If you'd rather not type the commands below by hand, there's a helper script
you run **once on your own computer** (not on the server). It connects to your
new server and does steps 2 through 6 for you — installs everything, saves your
secret keys, and starts the bot.

**You'll need:** your server's IP address (from step 1) and the three secret
values from the table at the top of this file.

**On a Mac (or Linux):** open **Terminal** and run these two lines:

```
curl -fsSL https://raw.githubusercontent.com/instatank/instatank42/HEAD/deploy/deploy_from_laptop.sh -o deploy_bot.sh
bash deploy_bot.sh
```

**On Windows:** open **PowerShell** and run these two lines:

```
curl.exe -fsSL https://raw.githubusercontent.com/instatank/instatank42/HEAD/deploy/deploy_from_laptop.ps1 -o deploy_bot.ps1
powershell -ExecutionPolicy Bypass -File deploy_bot.ps1
```

The script asks you to paste four things (your server's IP + the three
secrets), then asks for the server's **root password** (the one Hetzner
emailed you) once, to connect. It prints the bot's status at the end — when it
shows a green **active (running)**, open Telegram and message your bot.

*(Downloading and typing your root password only happens on your own computer.
Your secret keys go straight to your server over the encrypted connection; the
script doesn't store or send them anywhere else.)*

Prefer to do it yourself step by step, or did the script hit an error? The
manual steps 2–6 below do exactly the same thing, one command at a time.

---

## 2. Connect to your server

Open a terminal on your own computer:

- **Mac:** open the app called **Terminal**.
- **Windows:** open **PowerShell** (it has `ssh` built in).

Then run (replace the numbers with YOUR server's IP address):

```
ssh root@203.0.113.42
```
*This opens a remote command line on your new server, logged in as the administrator ("root").*

- If you skipped the SSH key, it will ask for the password Hetzner emailed
  you (and may make you set a new one).
- If it asks `Are you sure you want to continue connecting?`, type `yes`
  and press Enter — that's normal the first time.

Everything from here on is typed **on the server** (in that ssh window).

## 3. Run the setup script

Run these two commands:

```
apt-get update && apt-get install -y git
```
*Installs git, the tool used to download the code.*

```
git clone https://github.com/instatank/instatank42.git /tmp/instatank42 && bash /tmp/instatank42/deploy/setup_vps.sh https://github.com/instatank/instatank42.git
```
*Downloads the code and runs the setup script, which installs everything the bot needs and sets it up to start automatically.*

> **If the repository is private**, git will ask for a username and password.
> Use your GitHub username, and for the password paste a **personal access
> token** (not your real password): create one at
> https://github.com/settings/tokens → "Fine-grained tokens" → give it
> read-only access to just this repository. Keep the token in your notes —
> you'll need it again when updating.

The script takes a couple of minutes. At the end it prints a big boxed
message telling you to add your secret keys — that's the next step.

(It's safe to run this script again later; it just updates things.)

## 4. Add your secret keys

```
nano /opt/instatank-agent/.env
```
*Opens the bot's settings file in a simple text editor.*

You'll see three lines. Paste your values directly after each `=` sign, with
no spaces and no quotes:

```
TELEGRAM_BOT_TOKEN=123456:ABC-your-token-here
ANTHROPIC_API_KEY=sk-ant-your-key-here
TELEGRAM_ALLOWED_USER_ID=123456789
```

Then save and exit nano:

- Press **Ctrl+O**, then **Enter** — *saves the file.*
- Press **Ctrl+X** — *closes the editor.*

## 5. Start the bot and check it's alive

```
systemctl start telegram-agent
```
*Starts the bot.*

```
systemctl status telegram-agent
```
*Shows whether the bot is running — look for the green word "active (running)". Press `q` to leave this screen.*

```
journalctl -u telegram-agent -f
```
*Shows the bot's live log output — useful to watch it react when you message it. Press Ctrl+C to stop watching (the bot keeps running).*

Now open Telegram and send your bot a message. It should reply!

The bot restarts itself automatically if it crashes, and starts on its own
if the server ever reboots. You can close the ssh window — the bot keeps
running.

## 6. Updating the bot later

When the code changes and you want the new version, ssh into the server
(step 2) and either:

**Option A — re-run the setup script (easiest):**

```
bash /opt/instatank-agent/deploy/setup_vps.sh https://github.com/instatank/instatank42.git
```
*Pulls the latest code, updates dependencies, and restarts the bot.*

**Option B — quick manual update:**

```
cd /opt/instatank-agent && git pull && systemctl restart telegram-agent
```
*Downloads the latest code and restarts the bot.*

## 7. Troubleshooting

**The service won't start / status shows "failed":**

```
journalctl -u telegram-agent -n 50
```
*Shows the last 50 lines of the bot's log — the error message is usually near the bottom.*
Common causes: a typo in the `.env` file, or a missing value. Fix with
`nano /opt/instatank-agent/.env`, then `systemctl restart telegram-agent`.

**The bot is running but doesn't reply in Telegram:**
Almost always one of the three values in `/opt/instatank-agent/.env`:

- `TELEGRAM_BOT_TOKEN` — wrong or incomplete token (copy it again from
  @BotFather, it should contain a colon `:`).
- `ANTHROPIC_API_KEY` — wrong key, or no credit on the Anthropic account.
- `TELEGRAM_ALLOWED_USER_ID` — must be YOUR numeric ID (from @userinfobot);
  if it's someone else's ID or wrong, the bot ignores you on purpose.

After editing the file, always restart:

```
systemctl restart telegram-agent
```
*Restarts the bot so it picks up your changes.*

**Still stuck?** Watch the live log (`journalctl -u telegram-agent -f`)
while you message the bot — whatever it prints when your message arrives is
the clue.
