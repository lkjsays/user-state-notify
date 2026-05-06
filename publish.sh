#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI(gh)가 필요합니다: brew install gh" >&2
  exit 2
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "GitHub 로그인이 필요합니다. 먼저 실행하세요:" >&2
  echo "  gh auth login -h github.com" >&2
  exit 2
fi

if gh repo view lkjsays/user-state-notify >/dev/null 2>&1; then
  echo "Remote repository already exists."
else
  gh repo create lkjsays/user-state-notify \
    --public \
    --description "macOS/iPhone user state notification bootstrap for Hermes Agent" \
    --disable-wiki
fi

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin git@github.com:lkjsays/user-state-notify.git
else
  git remote add origin git@github.com:lkjsays/user-state-notify.git
fi

git push -u origin main

echo "Published: https://github.com/lkjsays/user-state-notify"
