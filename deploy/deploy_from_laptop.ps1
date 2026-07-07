# deploy_from_laptop.ps1 — one-command deploy for the Telegram bot (Windows).
#
# Run this ONCE on your OWN Windows computer, AFTER you've created the Hetzner
# server (step 1 of deploy/DEPLOY.md). It connects to the server and performs
# steps 2-6 for you: installs everything, saves your secret keys, starts the bot.
#
# In PowerShell:
#   powershell -ExecutionPolicy Bypass -File deploy_from_laptop.ps1
#
# It asks you to paste four things (your server's IP + three secret keys), then
# asks for the server's root password once to connect. Your secrets are sent
# straight to your server over the encrypted SSH connection.

$ErrorActionPreference = 'Stop'
$RepoUrl = 'https://github.com/instatank/instatank42.git'

function Read-Required($label) {
    do {
        $v = Read-Host $label
    } while ([string]::IsNullOrWhiteSpace($v))
    return $v.Trim()
}

Write-Host "=================================================================="
Write-Host "  Telegram bot - one-command deploy"
Write-Host "=================================================================="
Write-Host ""
Write-Host "This runs on YOUR computer and sets up your Hetzner server for you."
Write-Host "Have these ready (see the table at the top of DEPLOY.md):"
Write-Host "  - your server's IP address (from Hetzner)"
Write-Host "  - your Telegram bot token   (from @BotFather)"
Write-Host "  - your Anthropic API key    (from console.anthropic.com)"
Write-Host "  - your Telegram user ID      (a number, from @userinfobot)"
Write-Host ""

$ServerIP     = Read-Required "Server IP address (e.g. 203.0.113.42)"
$TgToken      = Read-Required "Telegram bot token"
$AnthropicKey = Read-Required "Anthropic API key"
$TgUserId     = Read-Required "Your Telegram user ID (a number)"

if ($TgToken -notlike "*:*") {
    Write-Host "  Note: a Telegram token usually contains a ':' - double-check you pasted all of it."
}
if ($TgUserId -notmatch '^[0-9]+$') {
    Write-Host "  Note: your Telegram user ID should be just digits - double-check that value."
}

# The remote script that runs on the server. Secrets are interpolated here and
# sent over the encrypted SSH connection via stdin (a temp file), so they never
# appear in the server's process list. The inner 'ENVEOF' here-doc is quoted so
# the server writes the secret values literally.
$remote = @"
set -e
export DEBIAN_FRONTEND=noninteractive

echo "==> [1/5] Installing git..."
apt-get update -qq
apt-get install -y -qq git

echo "==> [2/5] Downloading the bot code..."
rm -rf /tmp/instatank42
git clone --quiet $RepoUrl /tmp/instatank42

echo "==> [3/5] Running the server setup script (Python, service, user, etc.)..."
bash /tmp/instatank42/deploy/setup_vps.sh $RepoUrl

echo "==> [4/5] Saving your secret keys..."
cat > /opt/instatank-agent/.env <<'ENVEOF'
TELEGRAM_BOT_TOKEN=$TgToken
ANTHROPIC_API_KEY=$AnthropicKey
TELEGRAM_ALLOWED_USER_ID=$TgUserId
ENVEOF
chown agent:agent /opt/instatank-agent/.env
chmod 600 /opt/instatank-agent/.env

echo "==> [5/5] Starting the bot..."
systemctl restart telegram-agent
sleep 2
echo
echo "----- Service status -----"
systemctl --no-pager --full status telegram-agent || true
"@

# Normalise line endings to LF (bash chokes on Windows CRLF) and write to a temp
# file with no BOM, then feed it to ssh's stdin. The password prompt still comes
# from the console, so connecting works even though stdin is the script.
$remote = $remote -replace "`r`n", "`n"
$tmp = [IO.Path]::GetTempFileName()
[IO.File]::WriteAllText($tmp, $remote, (New-Object System.Text.UTF8Encoding($false)))

Write-Host ""
Write-Host "About to connect to root@$ServerIP and set everything up."
Write-Host "You'll be asked for the server's ROOT PASSWORD (the one Hetzner"
Write-Host "emailed you) in a moment. Typing it may show nothing - that's normal."
Write-Host ""

try {
    cmd /c "ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 root@$ServerIP `"bash -s`" < `"$tmp`""
    $code = $LASTEXITCODE
}
finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}

Write-Host ""
if ($code -eq 0) {
    Write-Host "=================================================================="
    Write-Host "  Done!"
    Write-Host "=================================================================="
    Write-Host ""
    Write-Host "If the status above shows a green 'active (running)', your bot is"
    Write-Host "live. Open Telegram and send it a message - it should reply."
    Write-Host ""
    Write-Host "If it does NOT reply, it's almost always a typo in one of the three"
    Write-Host "keys. Re-run this script to set them again, or see the Troubleshooting"
    Write-Host "section in DEPLOY.md."
} else {
    Write-Host "Something went wrong while setting up the server (see the messages"
    Write-Host "above for the exact error). Common causes:"
    Write-Host "  - wrong server IP, or the server isn't ready yet (wait a minute)"
    Write-Host "  - wrong root password"
    Write-Host "It's safe to just run this script again."
    exit 1
}
