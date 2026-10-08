#!/usr/bin/env bash
# 一键为 NfoGapFill_v1.7.2 补建 GitHub Release（含 zip 附件）
# 用法：GH_TOKEN=你的PAT bash create_release_v172.sh
set -euo pipefail
: "${GH_TOKEN:?请先设置 GH_TOKEN 环境变量}"
OWNER=2804826634; REPO=moviepilot-nfo-gapfill
T="$(mktemp -d)"
cd "$(dirname "$0")"

# 1) 打包（顶层目录 nfogapfill/）
python - "$T" <<'PY'
import sys, zipfile, os
T = sys.argv[1]
out = f"{T}/nfogapfill_v1.7.2.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    zf.write("plugins.v2/nfogapfill/__init__.py", "nfogapfill/__init__.py")
print("zip:", os.path.getsize(out), "bytes ->", out)
PY

# 2) 取远端 main 的 SHA 作为 target
SHA=$(curl -sS -H "Authorization: Bearer $GH_TOKEN" -H "User-Agent: nfg" \
      "https://api.github.com/repos/$OWNER/$REPO/git/ref/heads/main" \
      | python -c "import sys,json;print(json.load(sys.stdin)['object']['sha'])")
echo "target SHA = ${SHA:0:8}"

# 3) 建 release
python - "$T" "$SHA" <<'PY'
import json, sys
T, sha = sys.argv[1], sys.argv[2]
body = open("RELEASE_v1.7.2.md", encoding="utf-8").read() if __import__("os").path.exists("RELEASE_v1.7.2.md") else "修图片写入偶发失败（临时文件名冲突）"
json.dump({"tag_name": "NfoGapFill_v1.7.2", "target_commitish": sha,
           "name": "NfoGapFill_v1.7.2", "body": body,
           "draft": False, "prerelease": False, "make_latest": "true"},
          open(f"{T}/payload.json", "w", encoding="utf-8"), ensure_ascii=False)
PY
RID=$(curl -sS -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
      -H "User-Agent: nfg" -H "Content-Type: application/json; charset=utf-8" \
      --data-binary "@$T/payload.json" \
      "https://api.github.com/repos/$OWNER/$REPO/releases" \
      | python -c "import sys,json;d=json.load(sys.stdin);print(d.get('id') or 'ERR:'+str(d.get('message')))")
echo "release id = $RID"

# 4) 上传附件
curl -sS -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
     -H "User-Agent: nfg" -H "Content-Type: application/zip" \
     --data-binary "@$T/nfogapfill_v1.7.2.zip" \
     "https://uploads.github.com/repos/$OWNER/$REPO/releases/$RID/assets?name=nfogapfill_v1.7.2.zip" \
     | python -c "import sys,json;d=json.load(sys.stdin);print('asset:', d.get('name'), d.get('size'), d.get('state'))"

rm -rf "$T"
echo "完成：https://github.com/$OWNER/$REPO/releases/tag/NfoGapFill_v1.7.2"
