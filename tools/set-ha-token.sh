#!/bin/bash
# 把 HA 长期访问令牌安全地写入本机文件
# 依据：docs/spec/08 §6（凭证只进本机文件，不进代码/日志/对话）· 11 §9（脚本纪律）
#
# 用法：bash ~/smart-home/tools/set-ha-token.sh
#   → 提示后把令牌粘进去、按回车即可。输入不显示（-s），不写进 shell 历史，不经过任何网络。
# 可选：bash set-ha-token.sh [目标路径]     （默认 ~/.config/smart-home/ha-token）
set -euo pipefail

TARGET="${1:-$HOME/.config/smart-home/ha-token}"

printf '把 HA 长期访问令牌粘贴到这里，然后按回车（输入不会显示）：'
IFS= read -rs TOKEN || true      # 没有尾随换行时 read 会返回非零，这里允许（EOF 也算读到了）
echo

# 去掉空白（粘贴常带换行/空格），不经过管道
TOKEN="${TOKEN//[[:space:]]/}"

if [ -z "${TOKEN}" ]; then
  echo "❌ 没读到内容。可能粘贴失败，请重试。"
  exit 1
fi

case "${TOKEN}" in
  eyJ*) ;;
  *) echo "❌ 格式不对：HA 长期令牌应以 eyJ 开头，当前以「${TOKEN:0:3}…」开头。"; exit 1 ;;
esac

if [ "${#TOKEN}" -lt 100 ]; then
  echo "❌ 长度可疑：只有 ${#TOKEN} 个字符（HA 长期令牌通常 180+），可能没复制全。"
  exit 1
fi

umask 077
mkdir -p "$(dirname "$TARGET")"
printf '%s' "$TOKEN" > "$TARGET"
chmod 600 "$TARGET"
echo "✅ 已写入 ${TARGET}（长度 ${#TOKEN}；内容未显示、未进历史、未经过对话）"
echo "   下一步：python3 ~/smart-home/app/ha.py    # 验证可用性"
