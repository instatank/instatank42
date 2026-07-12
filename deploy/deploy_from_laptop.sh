#!/usr/bin/env bash
#
# deploy_from_laptop.sh — one-command deploy for the Telegram bot.
#
# Run this ONCE on your OWN computer (Mac or Linux), AFTER you've created the
# Hetzner server (step 1 of deploy/DEPLOY.md). It connects to the server and
# performs steps 2–6 for you: installs everything, saves your secret keys, and
# starts the bot.
#
#   bash deploy_from_laptop.sh
#
# It will ask you to paste four things (your server's IP + three secret keys),
# then ask for the server's root password once to connect. Your secrets are
# sent straight to your server over the encrypted SSH connection — they are not
# stored anywhere else.
#
set -euo pipefail

REPO_URL="https://github.com/instatank/instatank42.git"

# --- Helper: prompt until the user gives a non-empty value -------------------
prompt_required() {
    # $1 = prompt text, $2 = name of variable to store the answer in
    local _value=""
    while [[ -z "${_value}" ]]; do
        read -r -p "$1" _value || true
        if [[ -z "${_value}" ]]; then
            echo "  (this can't be empty — please paste the value and press Enter)"
        fi
    done
    printf -v "$2" '%s' "${_value}"
}

echo "=================================================================="
echo "  Telegram bot — one-command deploy"
echo "=================================================================="
echo
echo "This runs on YOUR computer and sets up your Hetzner server for you."
echo "Have these ready (see the table at the top of DEPLOY.md):"
echo "  - your server's IP address (from Hetzner)"
echo "  - your Telegram bot token   (from @BotFather)"
echo "  - your Anthropic API key    (from console.anthropic.com)"
echo "  - your Telegram user ID      (a number, from @userinfobot)"
echo

prompt_required "Server IP address (e.g. 203.0.113.42): " SERVER_IP
prompt_required "Telegram bot token: "                    TG_TOKEN
prompt_required "Anthropic API key: "                     ANTHROPIC_KEY
prompt_required "Your Telegram user ID (a number): "      TG_USER_ID

# --- Light sanity checks (warnings only, never block) ------------------------
if [[ "${TG_TOKEN}" != *:* ]]; then
    echo "  Note: a Telegram token usually contains a ':' — double-check you pasted all of it."
fi
if [[ ! "${TG_USER_ID}" =~ ^[0-9]+$ ]]; then
    echo "  Note: your Telegram user ID should be just digits — double-check that value."
fi

echo
echo "About to connect to root@${SERVER_IP} and set everything up."
echo "You'll be asked for the server's ROOT PASSWORD (the one Hetzner emailed"
echo "you) in a moment. Typing it may show nothing on screen — that's normal."
echo

# Single SSH session does all of steps 2–6. The secret values are interpolated
# into the here-doc locally and travel over the encrypted connection via stdin,
# so they never appear in the server's process list. The password prompt is read
# from the terminal, so it still works even though stdin is this here-doc.
if ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 "root@${SERVER_IP}" "bash -s" <<EOF_REMOTE
set -e
export DEBIAN_FRONTEND=noninteractive

echo "==> [1/5] Installing git..."
apt-get update -qq
apt-get install -y -qq git

echo "==> [2/5] Downloading the bot code..."
rm -rf /tmp/instatank42
git clone --quiet ${REPO_URL} /tmp/instatank42

echo "==> [3/5] Running the server setup script (Python, service, user, etc.)..."
bash /tmp/instatank42/deploy/setup_vps.sh ${REPO_URL}

echo "==> [4/5] Saving your secret keys..."
cat > /opt/instatank-agent/.env <<'ENVEOF'
TELEGRAM_BOT_TOKEN=${TG_TOKEN}
ANTHROPIC_API_KEY=${ANTHROPIC_KEY}
TELEGRAM_ALLOWED_USER_ID=${TG_USER_ID}
ENVEOF
chown agent:agent /opt/instatank-agent/.env
chmod 600 /opt/instatank-agent/.env

echo "==> [5/5] Starting the bot..."
systemctl restart telegram-agent
sleep 2
echo
echo "----- Service status -----"
systemctl --no-pager --full status telegram-agent || true
EOF_REMOTE
then
    echo
    echo "=================================================================="
    echo "  Done!"
    echo "=================================================================="
    echo
    echo "If the status above shows a green 'active (running)', your bot is"
    echo "live. Open Telegram and send it a message — it should reply."
    echo
    echo "If it does NOT reply, it's almost always a typo in one of the three"
    echo "keys. Re-run this script to set them again, or see the Troubleshooting"
    echo "section in DEPLOY.md."
else
    echo
    echo "Something went wrong while setting up the server (see the messages"
    echo "above for the exact error). Common causes:"
    echo "  - wrong server IP, or the server isn't ready yet (wait a minute)"
    echo "  - wrong root password"
    echo "It's safe to just run this script again."
    exit 1
fi
