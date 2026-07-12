#!/usr/bin/env bash
#
# setup_vps.sh — one-shot (and safely re-runnable) setup for the Telegram bot
# on a fresh Ubuntu 24.04 server. Run as root:
#
#   bash setup_vps.sh <repo-url>
#
set -euo pipefail

APP_DIR=/opt/instatank-agent
APP_USER=agent
SERVICE_NAME=telegram-agent

# --- 0. Checks ---------------------------------------------------------------

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: this script must be run as root (try: sudo bash $0 <repo-url>)" >&2
    exit 1
fi

if [[ $# -lt 1 ]]; then
    echo "Usage: bash $0 <repo-url>" >&2
    echo "Example: bash $0 https://github.com/yourname/instatank42.git" >&2
    exit 1
fi

REPO_URL="$1"

# --- 1. System packages ------------------------------------------------------

echo "==> Installing system packages..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv git

# --- 2. System user ----------------------------------------------------------

if ! id -u "$APP_USER" >/dev/null 2>&1; then
    echo "==> Creating system user '$APP_USER'..."
    useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
else
    echo "==> User '$APP_USER' already exists, skipping."
fi

# --- 3. Get the code ---------------------------------------------------------

if [[ -d "$APP_DIR/.git" ]]; then
    echo "==> Repo already present, pulling latest changes..."
    git -C "$APP_DIR" pull
else
    echo "==> Cloning repo into $APP_DIR..."
    git clone "$REPO_URL" "$APP_DIR"
fi

# --- 4. Python virtual environment -------------------------------------------

echo "==> Setting up Python virtual environment..."
if [[ ! -d "$APP_DIR/venv" ]]; then
    python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

# --- 5. Memory directory ------------------------------------------------------

echo "==> Ensuring memory directory exists..."
mkdir -p "$APP_DIR/memory"

# --- 6. systemd service -------------------------------------------------------

echo "==> Installing systemd service..."
cp "$APP_DIR/deploy/$SERVICE_NAME.service" /etc/systemd/system/
cp "$APP_DIR/deploy/dayos-sync.service" /etc/systemd/system/
cp "$APP_DIR/deploy/dayos-sync.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
# DayOS sync timer: harmless before the Firebase key is configured (the script
# exits cleanly with a "not configured" note until then).
systemctl enable --now dayos-sync.timer

# --- 7. Env file with secrets -------------------------------------------------

NEED_ENV_EDIT=no
if [[ ! -f "$APP_DIR/.env" ]]; then
    NEED_ENV_EDIT=yes
    if [[ -f "$APP_DIR/.env.example" ]]; then
        cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    else
        cat > "$APP_DIR/.env" <<'EOF'
TELEGRAM_BOT_TOKEN=
ANTHROPIC_API_KEY=
TELEGRAM_ALLOWED_USER_ID=
EOF
    fi
    chmod 600 "$APP_DIR/.env"
    chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
fi

# --- 8. Ownership ---------------------------------------------------------------

echo "==> Setting file ownership..."
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# --- 9. Firewall (only if ufw is installed) -------------------------------------

if command -v ufw >/dev/null 2>&1; then
    echo "==> Configuring firewall (allowing SSH first so you don't get locked out)..."
    ufw allow OpenSSH
    ufw --force enable
else
    echo "==> ufw not installed, skipping firewall setup."
fi

# --- 10. Start or ask for secrets -----------------------------------------------

if [[ "$NEED_ENV_EDIT" == "yes" ]]; then
    cat <<'EOF'

##############################################################################
#                                                                            #
#   ALMOST DONE — ONE MANUAL STEP LEFT!                                      #
#                                                                            #
#   The bot needs your secret keys before it can start.                     #
#                                                                            #
#   1. Open the settings file:                                              #
#        nano /opt/instatank-agent/.env                                     #
#                                                                            #
#   2. Fill in these three values (paste after the = sign):                 #
#        TELEGRAM_BOT_TOKEN=...                                             #
#        ANTHROPIC_API_KEY=...                                              #
#        TELEGRAM_ALLOWED_USER_ID=...                                       #
#                                                                            #
#   3. Save (Ctrl+O, Enter) and exit (Ctrl+X), then start the bot:          #
#        systemctl start telegram-agent                                     #
#                                                                            #
##############################################################################

EOF
else
    echo "==> .env already configured, restarting the service..."
    systemctl restart "$SERVICE_NAME"
fi

echo "==> Done."
