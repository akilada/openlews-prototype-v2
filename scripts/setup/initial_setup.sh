#!/usr/bin/env sh
# OpenLEWS Prototype - Initial Setup (POSIX sh)
# Works in: sh, bash, zsh, dash, ash (BusyBox), Git Bash
# Installs CLI tools into: $HOME/.local/bin (override with OPENLEWS_BIN_DIR)

set -eu

# ----------------------------
# Basics / UI helpers
# ----------------------------
is_tty=0
[ -t 1 ] && is_tty=1

if [ "${NO_COLOR:-}" != "" ] || [ "$is_tty" -eq 0 ]; then
  RED=""; GREEN=""; YELLOW=""; NC=""
else
  RED="$(printf '\033[0;31m')"
  GREEN="$(printf '\033[0;32m')"
  YELLOW="$(printf '\033[1;33m')"
  NC="$(printf '\033[0m')"
fi

info() { printf '%s\n' "$*"; }
ok()   { printf '%s✓ %s%s\n' "$GREEN" "$*" "$NC"; }
warn() { printf '%s⚠ %s%s\n' "$YELLOW" "$*" "$NC"; }
err()  { printf '%s✗ %s%s\n' "$RED" "$*" "$NC" >&2; }

die() { err "$*"; exit 1; }

prompt_yes_no() {
  q="$1"
  def="${2:-y}"

  if [ "${OPENLEWS_ASSUME_YES:-}" = "1" ]; then
    return 0
  fi

  case "$def" in
    y|Y) suffix="Y/n" ;;
    n|N) suffix="y/N" ;;
    *) suffix="y/n"; def="y" ;;
  esac

  while :; do
    printf '%s [%s]: ' "$q" "$suffix"
    IFS= read ans || ans=""
    [ "$ans" = "" ] && ans="$def"
    case "$ans" in
      y|Y|yes|YES) return 0 ;;
      n|N|no|NO)   return 1 ;;
    esac
  done
}

mk_tmpdir() {
  d="$(mktemp -d 2>/dev/null || mktemp -d -t openlews)"
  printf '%s' "$d"
}

command_exists() { command -v "$1" >/dev/null 2>&1; }

# ----------------------------
# OS / ARCH detection
# ----------------------------
UNAME_S="$(uname -s 2>/dev/null || echo unknown)"
UNAME_M="$(uname -m 2>/dev/null || echo unknown)"

case "$UNAME_S" in
  Linux*)  OS="linux" ;;
  Darwin*) OS="darwin" ;;
  CYGWIN*|MINGW*|MSYS*) OS="windows" ;;
  *) OS="linux" ;;
esac

case "$UNAME_M" in
  x86_64|amd64) ARCH="amd64" ;;
  aarch64|arm64) ARCH="arm64" ;;
  armv7l|armv6l) ARCH="arm" ;;
  i386|i686) ARCH="386" ;;
  *) ARCH="amd64" ;;
esac

if command_exists git && git rev-parse --show-toplevel >/dev/null 2>&1; then
  REPO_ROOT="$(git rev-parse --show-toplevel)"
  cd "$REPO_ROOT"
fi

BIN_DIR="${OPENLEWS_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"

case ":$PATH:" in
  *":$BIN_DIR:"*) : ;;
  *) PATH="$BIN_DIR:$PATH"; export PATH ;;
esac

persist_path_hint() {
  line='export PATH="$HOME/.local/bin:$PATH"'
  shell_name="$(basename "${SHELL:-sh}")"
  profile=""

  case "$shell_name" in
    bash) profile="$HOME/.bashrc" ;;
    zsh)  profile="$HOME/.zshrc" ;;
    sh|dash|ash) profile="$HOME/.profile" ;;
    *) profile="$HOME/.profile" ;;
  esac

  if [ "${OPENLEWS_SKIP_PROFILE_UPDATE:-}" = "1" ]; then
    warn "Skipping profile update. Ensure $BIN_DIR is on PATH in future shells."
    return 0
  fi

  if [ -n "$profile" ]; then
    if [ -f "$profile" ] && grep -F "$line" "$profile" >/dev/null 2>&1; then
      return 0
    fi
    {
      printf '\n# OpenLEWS tools\n%s\n' "$line"
    } >> "$profile"
  fi
}

detect_install_hint() {
  # Best-effort, just for user guidance.
  if command_exists apt-get; then
    info "Install hint (Debian/Ubuntu): sudo apt-get update && sudo apt-get install -y git python3 python3-pip python3-venv curl unzip awscli"
  elif command_exists dnf; then
    info "Install hint (Fedora/RHEL): sudo dnf install -y git python3 python3-pip python3-virtualenv curl unzip awscli"
  elif command_exists yum; then
    info "Install hint (RHEL/CentOS): sudo yum install -y git python3 python3-pip curl unzip awscli"
  elif command_exists apk; then
    info "Install hint (Alpine): sudo apk add --no-cache git python3 py3-pip py3-virtualenv curl unzip aws-cli"
  elif command_exists brew; then
    info "Install hint (macOS/Homebrew): brew install git python@3.12 curl unzip awscli"
  else
    info "Install hint: install git, python3 (+pip/venv), curl, unzip, aws cli using your OS package manager."
  fi
}

# ----------------------------
# File helpers
# ----------------------------
upsert_env_kv() {
  k="$1"
  v="$2"
  f="$3"

  [ -f "$f" ] || : > "$f"

  if grep -E "^${k}=" "$f" >/dev/null 2>&1; then
    tmp="$(mk_tmpdir)/envtmp"
    awk -v key="$k" -v val="$v" '
      BEGIN { done=0 }
      {
        if (!done && index($0, key "=") == 1) {
          print key "=" val
          done=1
        } else {
          print $0
        }
      }
    ' "$f" > "$tmp"
    mv "$tmp" "$f"
  else
    printf '%s=%s\n' "$k" "$v" >> "$f"
  fi
}

ensure_gitignore_has_env() {
  if [ ! -f .gitignore ]; then
    : > .gitignore
  fi
  if ! grep -F ".env" .gitignore >/dev/null 2>&1; then
    printf '\n.env\n' >> .gitignore
    ok "Added .env to .gitignore"
  fi
}

ensure_env_template() {
  # Creates .env if missing, with placeholders.
  if [ -f .env ]; then
    return 0
  fi

  cat > .env <<'EOF'
# AWS Configuration
AWS_ACCOUNT_ID=
AWS_DEFAULT_REGION=ap-southeast-2

# Owner Email (for budget alerts)
OWNER_EMAIL=<email>

# Pinecone (set after signup)
PINECONE_API_KEY=<pinecone_api_key>
PINECONE_ENVIRONMENT=us-east-1

# ThingsBoard (set after deployment)
THINGSBOARD_HOST=mqtt.thingsboard.cloud
THINGSBOARD_TOKEN=your-device-token
EOF

  ok ".env file created"
  warn "Please edit .env and set OWNER_EMAIL (and other placeholders)."
}

# ----------------------------
# Tool installers (no sudo)
# ----------------------------
install_opentofu() {
  if command_exists tofu; then
    ok "OpenTofu already installed: $(tofu version 2>/dev/null | head -n 1 || echo tofu)"
    return 0
  fi

  if [ "${OPENLEWS_SKIP_TOOL_INSTALL:-}" = "1" ]; then
    warn "Skipping OpenTofu install (OPENLEWS_SKIP_TOOL_INSTALL=1)."
    return 0
  fi

  info "Installing OpenTofu..."

  TOFU_VERSION="${OPENLEWS_TOFU_VERSION:-}"
  if [ -z "$TOFU_VERSION" ]; then
    TOFU_VERSION="$(python3 - <<'PY' || true
import re, sys, urllib.request
url="https://get.opentofu.org/tofu/"
try:
    html=urllib.request.urlopen(url, timeout=15).read().decode("utf-8","ignore")
except Exception:
    sys.exit(1)

# Matches stable versions like tofu_1.11.2 (NOT tofu_1.11.0-rc4)
vers=set(re.findall(r"tofu_(\d+\.\d+\.\d+)(?!-)", html))
if not vers:
    sys.exit(1)

def key(v):
    return tuple(int(x) for x in v.split("."))

print(sorted(vers, key=key)[-1])
PY
)"
  fi

  [ -n "$TOFU_VERSION" ] || die "Could not determine OpenTofu version automatically. Set OPENLEWS_TOFU_VERSION=1.x.y and re-run."

  zip="tofu_${TOFU_VERSION}_${OS}_${ARCH}.zip"
  url="https://get.opentofu.org/tofu/${TOFU_VERSION}/${zip}"

  tmpdir="$(mk_tmpdir)"
  trap 'rm -rf "$tmpdir"' EXIT INT TERM

  info "Downloading: $zip"
  curl -fsSL "$url" -o "$tmpdir/$zip" || die "Failed to download $url"

  tofu_dst="$BIN_DIR/tofu"
  [ "$OS" = "windows" ] && tofu_dst="$BIN_DIR/tofu.exe"

  python3 - "$tmpdir/$zip" "$tofu_dst" <<'PY'
import sys, os, zipfile, shutil
zip_path, dst = sys.argv[1], sys.argv[2]
z = zipfile.ZipFile(zip_path)
member = None
for n in z.namelist():
    base = os.path.basename(n)
    if base in ("tofu", "tofu.exe"):
        member = n
        break
if not member:
    raise SystemExit("Could not find tofu/tofu.exe in the zip archive")
extract_dir = os.path.dirname(zip_path)
z.extract(member, extract_dir)
src = os.path.join(extract_dir, member)
os.makedirs(os.path.dirname(dst), exist_ok=True)
# Ensure parent dirs exist and move binary
shutil.move(src, dst)
PY

  if [ "$OS" != "windows" ]; then
    chmod 0755 "$tofu_dst" || true
  fi

  persist_path_hint
  ok "OpenTofu installed: $(tofu version 2>/dev/null | head -n 1 || echo tofu)"
}

install_terragrunt() {
  if command_exists terragrunt; then
    ok "Terragrunt already installed: $(terragrunt --version 2>/dev/null | head -n 1 || echo terragrunt)"
    return 0
  fi

  if [ "${OPENLEWS_SKIP_TOOL_INSTALL:-}" = "1" ]; then
    warn "Skipping Terragrunt install (OPENLEWS_SKIP_TOOL_INSTALL=1)."
    return 0
  fi

  info "Installing Terragrunt..."

  TERRAGRUNT_VERSION="${OPENLEWS_TERRAGRUNT_VERSION:-}"
  if [ -z "$TERRAGRUNT_VERSION" ]; then
    TERRAGRUNT_VERSION="$(python3 - <<'PY' || true
import json, sys, urllib.request
url="https://api.github.com/repos/gruntwork-io/terragrunt/releases/latest"
try:
    data=json.loads(urllib.request.urlopen(url, timeout=15).read().decode("utf-8","ignore"))
    tag=data.get("tag_name","")
    if tag.startswith("v"): tag=tag[1:]
    print(tag)
except Exception:
    print("")
PY
)"
  fi

  [ -n "$TERRAGRUNT_VERSION" ] || TERRAGRUNT_VERSION="0.55.1"

  bin="terragrunt_${OS}_${ARCH}"
  dst="$BIN_DIR/terragrunt"

  if [ "$OS" = "windows" ]; then
    bin="${bin}.exe"
    dst="$BIN_DIR/terragrunt.exe"
  fi

  url="https://github.com/gruntwork-io/terragrunt/releases/download/v${TERRAGRUNT_VERSION}/${bin}"

  tmpdir="$(mk_tmpdir)"
  trap 'rm -rf "$tmpdir"' EXIT INT TERM

  info "Downloading: $bin"
  curl -fsSL "$url" -o "$tmpdir/$bin" || die "Failed to download $url"

  mkdir -p "$BIN_DIR"
  mv "$tmpdir/$bin" "$dst"
  if [ "$OS" != "windows" ]; then
    chmod 0755 "$dst" || true
  fi

  persist_path_hint
  ok "Terragrunt installed: $(terragrunt --version 2>/dev/null | head -n 1 || echo terragrunt)"
}

# ----------------------------
# Steps
# ----------------------------
info "=========================================="
info "OpenLEWS Prototype - Initial Setup"
info "=========================================="
info ""

info "Step 1/8: Checking prerequisites..."
info "------------------------------------"

missing=""

for c in git python3 curl; do
  if command_exists "$c"; then
    ok "$c found"
  else
    err "$c not found"
    missing="$missing $c"
  fi
done

if python3 -m pip --version >/dev/null 2>&1; then
  ok "pip (python3 -m pip) found"
elif command_exists pip3; then
  ok "pip3 found"
else
  err "pip not found"
  missing="$missing pip"
fi

if command_exists unzip; then
  ok "unzip found"
else
  warn "unzip not found (OK; installer uses python's zipfile)."
fi

if [ -n "$missing" ]; then
  warn "Missing:$missing"
  detect_install_hint
  exit 1
fi

info ""
info "Step 2/8: Installing OpenTofu..."
info "------------------------------------"
install_opentofu

info ""
info "Step 3/8: Installing Terragrunt..."
info "------------------------------------"
install_terragrunt

info ""
info "Step 4/8: Setting up Python virtual environment..."
info "------------------------------------"

if [ ! -d "venv" ]; then
  if python3 -m venv venv >/dev/null 2>&1; then
    ok "Virtual environment created"
  else
    die "python3 -m venv failed. Install the venv module (e.g., python3-venv / py3-virtualenv) and re-run."
  fi
else
  warn "Virtual environment already exists"
fi

if [ -f "venv/bin/activate" ]; then
  . "venv/bin/activate"
elif [ -f "venv/Scripts/activate" ]; then
  . "venv/Scripts/activate"
else
  die "Could not find venv activation script."
fi

python -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1 || true
ok "pip/setuptools/wheel updated"

info ""
info "Step 5/8: Installing Python dependencies..."
info "------------------------------------"

if [ -f "requirements.txt" ]; then
  python -m pip install -r requirements.txt
  ok "Installed requirements.txt"
else
  python -m pip install boto3 paho-mqtt python-dotenv pytest black
  ok "Installed core Python deps (boto3, paho-mqtt, python-dotenv, pytest, black)"
fi

info ""
info "Step 6/8: Configuring AWS credentials..."
info "------------------------------------"

if [ "${OPENLEWS_SKIP_AWS:-}" = "1" ]; then
  warn "Skipping AWS configuration (OPENLEWS_SKIP_AWS=1)."
  AWS_ACCOUNT_ID=""
else
  if ! command_exists aws; then
    die "aws CLI not found. Install awscli and re-run (or set OPENLEWS_SKIP_AWS=1)."
  fi

  if [ -f "$HOME/.aws/credentials" ]; then
    warn "AWS credentials file exists: $HOME/.aws/credentials"
    aws configure list || true
    if prompt_yes_no "Do you want to reconfigure AWS CLI?" "n"; then
      aws configure
    fi
  else
    info "No AWS credentials found. Running: aws configure"
    aws configure
  fi

  info "Verifying AWS credentials..."
  if aws sts get-caller-identity >/dev/null 2>&1; then
    ok "AWS credentials valid"
    AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
    info "AWS Account ID: $AWS_ACCOUNT_ID"
  else
    die "AWS credentials invalid or insufficient permissions."
  fi
fi

info ""
info "Step 7/8: Setting up environment variables..."
info "------------------------------------"

ensure_env_template
ensure_gitignore_has_env

REGION="${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null || true)}"
[ -n "$REGION" ] || REGION="ap-southeast-2"

if [ -n "${AWS_ACCOUNT_ID:-}" ]; then
  upsert_env_kv "AWS_ACCOUNT_ID" "$AWS_ACCOUNT_ID" ".env"
fi
upsert_env_kv "AWS_DEFAULT_REGION" "$REGION" ".env"
ok ".env updated (AWS_ACCOUNT_ID / AWS_DEFAULT_REGION)"

info ""
info "Step 8/8: Creating Terraform state backend..."
info "------------------------------------"

if [ "${OPENLEWS_SKIP_AWS:-}" = "1" ]; then
  warn "Skipping backend creation (OPENLEWS_SKIP_AWS=1)."
else
  STATE_BUCKET="openlews-terraform-state-${AWS_ACCOUNT_ID}"
  LOCK_TABLE="openlews-terraform-locks"

  if aws s3api head-bucket --bucket "$STATE_BUCKET" >/dev/null 2>&1; then
    warn "S3 state bucket already exists: $STATE_BUCKET"
  else
    info "Creating S3 bucket for Terraform state: $STATE_BUCKET ($REGION)"

    if [ "$REGION" = "us-east-1" ]; then
      aws s3api create-bucket --bucket "$STATE_BUCKET" --region "$REGION"
    else
      aws s3api create-bucket \
        --bucket "$STATE_BUCKET" \
        --region "$REGION" \
        --create-bucket-configuration "LocationConstraint=$REGION"
    fi

    aws s3api put-bucket-versioning \
      --bucket "$STATE_BUCKET" \
      --versioning-configuration Status=Enabled

    aws s3api put-bucket-encryption \
      --bucket "$STATE_BUCKET" \
      --server-side-encryption-configuration '{
        "Rules": [{
          "ApplyServerSideEncryptionByDefault": { "SSEAlgorithm": "AES256" }
        }]
      }'

    aws s3api put-public-access-block \
      --bucket "$STATE_BUCKET" \
      --public-access-block-configuration \
      "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

    ok "S3 state bucket created: $STATE_BUCKET"
  fi

  if aws dynamodb describe-table --table-name "$LOCK_TABLE" --region "$REGION" >/dev/null 2>&1; then
    warn "DynamoDB lock table already exists: $LOCK_TABLE"
  else
    info "Creating DynamoDB table for state locking: $LOCK_TABLE"
    aws dynamodb create-table \
      --table-name "$LOCK_TABLE" \
      --attribute-definitions AttributeName=LockID,AttributeType=S \
      --key-schema AttributeName=LockID,KeyType=HASH \
      --billing-mode PAY_PER_REQUEST \
      --region "$REGION" \
      --tags Key=Project,Value=OpenLEWS Key=ManagedBy,Value=Manual

    info "Waiting for DynamoDB table to be active..."
    aws dynamodb wait table-exists --table-name "$LOCK_TABLE" --region "$REGION"
    ok "DynamoDB lock table created: $LOCK_TABLE"
  fi
fi

info ""
info "=========================================="
ok "Setup Complete!"
info "=========================================="
info ""
info "Next Steps:"
info "1. Edit .env and set OWNER_EMAIL + any placeholders"
info "2. Deploy infrastructure:"
info "   cd infrastructure/environments/dev"
info "   terragrunt run-all init"
info "   terragrunt run-all plan"
info "   terragrunt run-all apply"
info ""
