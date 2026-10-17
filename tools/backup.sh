#!/bin/bash
# 备份（依据 docs/spec/07-数据与记忆规范 v1.0 §7）
# 排除：旧备份、集成源码副本、可再下载的大件（数据目录里的镜像、installers 里的安装包）、
#       以及**所有凭证文件**（凭证不进备份明文）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(date +%Y%m%d-%H%M)"
OUT="$ROOT/backups/smart-home-$STAMP.tgz"
# **先写临时文件，校验完整后再原子改名**（2026-10-17 实测踩坑：直接写最终文件名时，
# 同时在跑的恢复演练读到了半个包 → EOFError「压缩流未结束」。任何读者都不该看到半成品。）
TMP="$OUT.partial.$$"
trap 'rm -f "$TMP"' EXIT
# 先把 HA OS 虚拟机里的真实配置同步成本地镜像（否则备份打的是容器版旧配置）
if /usr/bin/python3 "$(dirname "$0")/sync_ha_config.py" 2>/dev/null; then :; else
  echo "  ⚠️ 未能同步 HA OS 配置（虚拟机没起/SSH 不通），本次备份使用本地既有镜像"
fi

tar --exclude='./backups' \
    --exclude='./vm' \
    --exclude='*.key' \
    --exclude='*.pem' \
    --exclude='*.crt' \
    --exclude='./node_modules' \
    --exclude='./vendor' \
    --exclude='./data/images' \
    --exclude='./installers' \
    --exclude='./config/homeassistant/.storage/auth*' \
    --exclude='./config/homeassistant/secrets.yaml' \
    --exclude='./config/homeassistant/.storage/*.corrupt' \
    --exclude='./config/homeassistant/home-assistant_v2.db-wal' \
    --exclude='./config/homeassistant/home-assistant_v2.db-shm' \
    --exclude='./data/export' \
    -czf "$TMP" -C "$ROOT" .
# 完整性校验：能列出内容才算写完（列出失败说明包不完整，直接丢弃，不污染 backups/）
if ! tar -tzf "$TMP" >/dev/null 2>&1; then
  echo "❌ 备份包不完整（tar 无法列出内容），已丢弃：$TMP"
  exit 1
fi
mv -f "$TMP" "$OUT"          # 原子改名：此刻起读者看到的都是完整包
trap - EXIT
# 保留策略按**天**而不是按"份"（07 §3：保留最近 14 天）。
# 2026-10-17 实测踩坑：原来按"最近 14 份"，测试/演练一天跑了十几次就把 14 份全占满，
# 反而把前几天的备份挤掉了 —— 既不符规范语义，也把一天内的重复份数堆成了 560MB。
# 做法：同一天只留最新一份；再按日期只留最近 14 天。
/usr/bin/python3 - "$ROOT/backups" <<'PRUNE'
import glob, os, re, sys
d = sys.argv[1]
pat = re.compile(r'smart-home-(\d{8})-(\d{4})\.tgz$')
by_day = {}
for f in glob.glob(os.path.join(d, 'smart-home-*.tgz')):
    m = pat.search(os.path.basename(f))
    if m:
        by_day.setdefault(m.group(1), []).append((m.group(2), f))
kept = 0
for day in sorted(by_day, reverse=True)[:14]:          # 最近 14 天
    files = sorted(by_day[day])                        # 同一天按 HHMM
    kept += 1
    for _, extra in files[:-1]:                        # 同日冗余：只留最新
        os.remove(extra)
for day in sorted(by_day, reverse=True)[14:]:          # 超出 14 天：整天删
    for _, f in by_day[day]:
        os.remove(f)
print(f'  备份保留：{kept} 份（按天，最近 14 天）')
PRUNE
echo "备份完成：$OUT"
du -h "$OUT"
# 自检：备份里不得出现凭证文件
# 自检不带管道：先落文件，再查退出码（09 §3）
tar -tzf "$OUT" > "$ROOT/logs/backup-list.tmp" 2>&1
if grep -q '\.storage/auth' "$ROOT/logs/backup-list.tmp"; then
  echo "❌ 备份里含凭证文件，已删除"
  rm -f "$OUT"
  exit 1
fi
echo "✅ 自检通过：备份内不含凭证文件"
rm -f "$ROOT/logs/backup-list.tmp"      # 校验用的临时清单，用完即删（别在 logs 里留垃圾）

# 体积自检（2026-10-17 实测踩坑：327MB 的 HA OS 镜像被打进备份，32MB → 372MB）
SIZE_MB=$(( $(stat -f%z "$OUT") / 1048576 ))
MAX_MB=100
if [ "$SIZE_MB" -gt "$MAX_MB" ]; then
  echo "⚠️  备份 ${SIZE_MB}MB 超过 ${MAX_MB}MB 上限，最大的几项："
  tar -tzvf "$OUT" | sort -k3 -rn | head -5 | awk '{printf "   %.1f MB  %s\n", $3/1048576, $6}'
  echo "   （可再下载的大文件请在 tar 的 --exclude 里排除，不要进备份）"
else
  echo "✅ 体积自检通过：${SIZE_MB}MB（上限 ${MAX_MB}MB）"
fi
