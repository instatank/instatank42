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

## 7. Connect DayOS (the second brain) — optional, do this after step 5 works

This gives the agent read access to everything you log in DayOS — journals,
activity blocks, notes, project sessions, learning entries, trends. It syncs
automatically every 2 hours (plus a full refresh daily), and you can force a
refresh anytime by messaging the bot `/sync`.

You need one thing: the **Firebase service-account key** for the DayOS
project (a small JSON file that acts as a server-side password to your
DayOS database — the same kind of key DayOS itself uses on Vercel).

1. Go to https://console.firebase.google.com → open your DayOS project →
   ⚙️ **Project settings** → **Service accounts** tab → click
   **Generate new private key**. A `.json` file downloads.
2. Copy it to the server. On your own computer, run (replace the IP and the
   filename with yours):

```
scp ~/Downloads/your-downloaded-key.json root@203.0.113.42:/opt/instatank-agent/.firebase-sa.json
```
*Copies the key file from your computer onto the server.*

3. On the server, lock it down and point the bot at it:

```
chown agent:agent /opt/instatank-agent/.firebase-sa.json && chmod 600 /opt/instatank-agent/.firebase-sa.json
```
*Makes the key readable only by the bot's own user account.*

```
nano /opt/instatank-agent/.env
```
Add this line (it's already in the file if you copied `.env.example`):

```
FIREBASE_SERVICE_ACCOUNT_FILE=/opt/instatank-agent/.firebase-sa.json
```

4. Restart the bot and turn on the auto-sync:

```
systemctl restart telegram-agent && systemctl start dayos-sync.timer
```
*Restarts the bot so it sees the new key, and turns on the every-2-hours auto-sync.*

Then in Telegram send **`/sync full`** — that pulls your whole DayOS history
into the agent's memory (a few seconds) and replies with what it fetched.

> Why through Telegram? Running the sync script by hand with `sudo` does NOT
> load the settings in `.env` (only systemd and the bot itself do), so a
> manual `python dayos_sync.py` just prints "not configured" and quits.
> If you ever want a manual server-side run, use
> `systemctl start dayos-sync.service` and check it with
> `journalctl -u dayos-sync --no-pager -n 15`.

5. Test it: ask the bot something like *"what did I do yesterday?"* or
   *"how was my week?"* — it should answer from your real DayOS data.
   `/sync` in Telegram forces a refresh; `/sync full` re-pulls everything.

**Notes:**
- The agent only **reads** DayOS data. It never writes to your DayOS
  database, so it cannot corrupt or duplicate anything there.
- The key file is a secret. It never goes in git (`.gitignore` covers it),
  only on the server.
- Voice notes sync as their titles (the audio itself isn't transcribed —
  you already use a separate transcription tool).

## 8. Teach the agent your playbook — optional, 5 minutes

This gives the agent your written working rules — the `playbook/` folder in
the time-tracker repo (PLAYBOOK, NORTH_STAR, CURRICULUM, the SOPs) plus the
LEARNINGS ledger — so it can quote your own rules back at you and knows the
technique-of-the-week. It refreshes on the same 2-hour timer as DayOS, and
`/sync` refreshes it on demand.

1. First make sure the server has the latest bot code (step 6 has the
   update commands).

2. GitHub needs to let the server read the time-tracker repo. Create a
   **fine-grained personal access token**: on github.com click your avatar →
   **Settings** → **Developer settings** (bottom of the left menu) →
   **Fine-grained tokens** → **Generate new token**. Set:
   - **Repository access:** "Only select repositories" → pick
     `instatank/time-tracker` only.
   - **Permissions → Repository permissions → Contents: Read-only.**
     Leave everything else on "No access".
   - Expiration: 1 year is fine.

   Copy the token (starts with `github_pat_`) — you see it only once.

3. On the server, open the settings file and add the playbook lines:

```
nano /opt/instatank-agent/.env
```

Add (or fill in, if you copied the newer `.env.example`):

```
PLAYBOOK_REPO_URL=https://github.com/instatank/time-tracker.git
PLAYBOOK_REPO_TOKEN=github_pat_paste-yours-here
```

4. Restart the bot so it picks up the new settings:

```
systemctl restart telegram-agent
```

Then in Telegram send **`/sync`** — the reply should include a line like
*"Playbook: commit a1b2c3d, 10 docs."* (Don't run the sync script by hand
with `sudo` — it won't see `.env`; see the note in step 7.)

5. Test it: ask the bot *"what's my rule about bundled fixes?"* or *"what's
   this week's technique?"* — it should quote the actual playbook.

**Notes:**
- The token can read that one repo and nothing else, and can't write
  anywhere. It lives only in `.env` on the server, never in git.
- If the sync ever says "SYNC FAILED", the bot will also warn you itself the
  next time you ask a playbook question — run `/sync` after fixing.

## 9. Feed it WhatsApp conversations — optional, 2 minutes per chat

No server setup at all for this one — if the bot is running, it already works.

1. On your phone, open WhatsApp → the chat you want the agent to know →
   tap the name at the top → **Export chat** → **Without media**.
2. Share the exported file (`.txt`, or the `.zip` iPhones make) straight to
   your bot on Telegram, like sending any file.
3. The bot replies with what it detected — which chat, how many messages,
   what date range — and two buttons. Press **Add to brain** (or **Discard**
   if it's not what you meant to send). Nothing is saved until you press it.
4. Test it: *"what did we agree with <name> about <topic>?"*

**Notes:**
- This is a **snapshot**, not a live link — the agent only knows the chat up
  to the moment you exported it (it tells you the coverage date when it
  answers). Re-export the same chat any time to refresh; the new export
  replaces the old one automatically.
- Exports include the other person's messages too — be choosy about which
  chats you feed in.
- Media (photos/voice notes) is never ingested; export *without* media.

## 9b. Feed it YouTube videos — optional, 30 seconds per video

No setup for this one either — if the bot is running, it already works.

1. In the YouTube app, on a video worth keeping: **Share → Telegram → your
   bot**. (Any message containing a YouTube link works — you can add a
   comment around the link and it's saved as your note on the video.)
2. The bot fetches the video's title and transcript and shows you what it
   found, with two buttons. Press **Add to brain** — nothing is saved until
   you press it. Sending the same link again later replaces the entry.
3. If it says it **couldn't fetch the transcript** (YouTube sometimes blocks
   requests from servers — expected now and then, maybe always; we find out
   in practice), you get two fallback buttons:
   - **"I'll paste the transcript"** — on the video's page press **⋯ → Show
     transcript**, select it all, copy, and paste it as your next message.
     Saved as the real transcript.
   - **"I'll paste a summary"** — get a summary from Gemini's summarize
     button (or write two lines yourself) and paste that. Saved clearly
     marked as a summary, not a transcript.
4. **Several at once:** paste multiple YouTube links in one message — the
   bot fetches them all and gives you a single "Add N to brain" button
   instead of one per video.
5. Test it: *"what was that video about <topic> I sent you?"*

**Notes:**
- Only videos you deliberately send are saved — the agent never sees your
  watch history.
- Transcript fetching is free (no API key, no per-video cost).

### The hands-off way: log links in DayOS

You can skip Telegram entirely: **paste a YouTube link into a learning
entry in DayOS** (the learning sessions page). Once a day (6:30am, and on
every `/sync`), the agent scans your learning log for YouTube links and
saves any new video's transcript automatically — no buttons, no
notifications. Logging the link in your own learning log *is* the
confirmation (your call, 2026-07-16).

- The daily 6:30am scan needs its timer installed once: re-run
  `deploy/setup_vps.sh` (the same re-run that installs the Friday digest
  timer). Until then, `/sync` runs the scan just as well.
- `/sync` shows what the scan found each time; so does
  `sudo -u agent venv/bin/python youtube_autofetch.py --status` on the server.
- If a video's transcript can't be fetched, the scan retries it on the next
  two runs, then gives up on that one (visible in `/sync`) — share that link
  to the bot directly to use the paste buttons instead.

## 10. The Friday + monthly syntheses — automatic, nothing to configure

Once steps 4–7 are done, every **Friday at 6pm IST** the agent writes a short
synthesis of your week (numbers vs last week, patterns, open loops, one
suggestion) and sends it to you on Telegram by itself. And on the **5th of
every month at 6pm IST** it writes the month's story from its own weekly
syntheses (trajectory, patterns-of-patterns, biggest open loop) and refreshes
its standing list of themes that keep recurring across months. Together they
cost about 10¢ a month and count against the same daily budget cap as
everything else. (The monthly timer installs with a `setup_vps.sh` re-run,
same as the others.)

- Want one right now? Send **`/digest`** (this week) or **`/digest month`**
  (last month + themes) to the bot.
- Ask *"what did you make of my week?"*, *"how did June go?"*, or *"what are
  my patterns?"* later — the agent re-reads its own past syntheses and themes.
- If a scheduled run fails, the agent messages you the error itself (and
  skips politely if the day's budget cap is already spent).

## 10b. Back up your brain + finally see your data — optional, 5 minutes

Everything the agent remembers lives as plain files on this server. Some of it
(the DayOS mirror, the playbook) can always be rebuilt — but the **WhatsApp
exports, YouTube transcripts, and anything you pasted in** exist *only* here. If
this server ever dies, they're gone. This step copies your whole brain to a
**private GitHub repo every night** — which also means you can finally **open
the repo and read your brain's files** (on GitHub, or by cloning it into an
Obsidian vault).

**One-time setup:**

1. Create a **private** repo on GitHub called `2ndbrain` (Settings will already
   have one if a Claude Code session set it up for you — reuse it).
2. Make a **fine-grained token** with **Contents: Read and write** on *only*
   that repo: GitHub → Settings → Developer settings → Fine-grained tokens.
3. Open the settings file:

```
nano /opt/instatank-agent/.env
```

Add these two lines and fill in the token. (They're pre-filled **only** on a
server set up from scratch with the current `.env.example` — an already-running
server won't have them yet, so if you don't see them, just paste them in at the
bottom of the file. That's normal, not a mistake.)

```
BACKUP_REPO_URL=https://github.com/instatank/2ndbrain.git
BACKUP_REPO_TOKEN=paste-your-fine-grained-token-here
```

4. Save (Ctrl+O, Enter, Ctrl+X). Install the nightly timer and run the first
   backup now to check it works:

```
cd /opt/instatank-agent && git pull && bash deploy/setup_vps.sh https://github.com/instatank/instatank42.git
systemctl start memory-backup.service
```

Then open your `2ndbrain` repo on GitHub — you should see a new `memory/`
folder with everything in it. After that it backs itself up every night at
3:30am IST, only committing when something actually changed.

**Notes:**
- Always run it through `systemctl start memory-backup.service` (not a bare
  `python …` with `sudo`) so it loads `.env`. See what happened with
  `journalctl -u memory-backup.service --no-pager -n 40`.
- The token is scrubbed from every log and never written into the repo on disk.
- **About secrets in your data:** the app's own keys live in `.env` and the
  Firebase key file, *outside* the backed-up folder. But if you ever saved an
  API key or token inside a DayOS note, the backup **automatically blanks it out
  of the copy it pushes** (your DayOS data is left untouched) — so keys never
  reach the repo. A free-text **password** typed into a note has no recognizable
  shape and can't be auto-caught, so keep real passwords out of DayOS (use a
  password manager) and delete any you've already stored there.
- **Reading it in Obsidian:** clone the repo (`git clone …/2ndbrain.git`) and
  open the folder as a vault. Treat it as **read-only** — the server rewrites
  `memory/` every night, so anything you *write* belongs in DayOS or a separate
  vault folder, not inside the mirrored `memory/`.
- If a nightly backup ever fails, the agent messages you the reason on Telegram.

## 11. Troubleshooting

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

**DayOS data seems stale or `/sync` fails:**

```
journalctl -u dayos-sync -n 30
```
*Shows the last sync attempts and their error messages.*

```
sudo -u agent /opt/instatank-agent/venv/bin/python /opt/instatank-agent/dayos_sync.py --status
```
*Prints when the last successful sync ran and what it pulled.*

Common causes: the key file path in `.env` is wrong, the key was generated
in a different Firebase project than DayOS, or the file permissions block
the `agent` user (fix with the `chown`/`chmod` line from step 7.3).

**Still stuck?** Watch the live log (`journalctl -u telegram-agent -f`)
while you message the bot — whatever it prints when your message arrives is
the clue.
