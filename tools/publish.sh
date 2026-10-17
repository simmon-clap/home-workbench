#!/bin/bash
# 一条命令发布到 GitHub（常态化推送）：
#   构建干净公开树 → 审计 → 同步进已有克隆 → 提交 → 推送（临时切代理全局模式，结束恢复）
# 个人配置放仓库外：
#   ~/.config/smart-home/public-repo   公开仓库 URL
#   ~/.config/smart-home/git-identity  "姓名 <邮箱>"
# 用法：bash tools/publish.sh [提交信息]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PUB="${SMART_HOME_PUBLIC_DIR:-$HOME/smart-home-public}"
BUILD="${SMART_HOME_PUBLIC_BUILD:-/tmp/home-workbench-build}"
PROXY="${SMART_HOME_PROXY:-http://127.0.0.1:7890}"
CLASH="${SMART_HOME_CLASH_API:-http://127.0.0.1:9090}"
MSG="${1:-release: 更新 $(date +%F\ %H:%M)}"
export https_proxy="$PROXY" http_proxy="$PROXY" PATH="$HOME/.local/bin:$PATH"

read_cfg() {  # $1=文件 $2=环境变量名
  local e="${2:-}"
  if [ -n "$e" ] && [ -n "${!e:-}" ]; then echo "${!e}"
  elif [ -f "$HOME/.config/smart-home/$1" ]; then head -1 "$HOME/.config/smart-home/$1"
  fi
}
REPO="$(read_cfg public-repo SMART_HOME_PUBLIC_REPO)"
IDENT="$(read_cfg git-identity SMART_HOME_GIT_IDENTITY)"
ORIG_MODE=""

restore_proxy() {
  if [ -n "$ORIG_MODE" ] && [ "$ORIG_MODE" != "global" ]; then
    curl -s -X PATCH -H 'Content-Type: application/json' -d "{\"mode\":\"$ORIG_MODE\"}" "$CLASH/configs" >/dev/null 2>&1 || true
  fi
}
trap restore_proxy EXIT

if curl -s -m 2 "$CLASH/configs" >/tmp/.clash-cfg.json 2>/dev/null; then
  ORIG_MODE=$(python3 -c "import json;print(json.load(open('/tmp/.clash-cfg.json')).get('mode',''))" 2>/dev/null || true)
  if [ -n "$ORIG_MODE" ] && [ "$ORIG_MODE" != "global" ]; then
    curl -s -X PATCH -H 'Content-Type: application/json' -d '{"mode":"global"}' "$CLASH/configs" >/dev/null
    sleep 1
  fi
fi

echo "[1/5] 构建干净公开树：$BUILD"
python3 "$ROOT/tools/build_public_repo.py" "$BUILD" --force >/dev/null

echo "[2/5] 发布审计"
python3 "$ROOT/tools/release_audit.py" --public-set "$BUILD"

echo "[3/5] 同步到克隆目录：$PUB"
if [ ! -d "$PUB/.git" ]; then
  mkdir -p "$PUB"
  git clone "$REPO" "$PUB"
fi
python3 - "$BUILD" "$PUB" <<'PY'
import filecmp, os, shutil, sys
src, dst = sys.argv[1], sys.argv[2]
for name in os.listdir(dst):
    if name == '.git':
        continue
    p = os.path.join(dst, name)
    shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)
for base, dirs, files in os.walk(src):
    rel = os.path.relpath(base, src)
    target = os.path.join(dst, rel) if rel != '.' else dst
    os.makedirs(target, exist_ok=True)
    for d in dirs:
        os.makedirs(os.path.join(target, d), exist_ok=True)
    for f in files:
        shutil.copy2(os.path.join(base, f), os.path.join(target, f))
print('  同步完成')
PY

echo "[4/5] 提交"
cd "$PUB"
if [ -n "$IDENT" ]; then
  git config user.name "${IDENT% <*}"
  git config user.email "$(echo "$IDENT" | sed -n 's/.*<\(.*\)>.*/\1/p')"
fi
git add -A
git commit -qm "$MSG" || echo "  无改动，跳过提交"

echo "[5/5] 推送"
git push origin main
echo "完成：$(git remote get-url origin) · $(git log --oneline -1)"
rm -rf "$BUILD"
