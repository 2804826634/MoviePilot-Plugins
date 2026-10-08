#!/usr/bin/env bash
# 为 NfoGapFill 创建 GitHub Release（含 zip 附件）
#
# 用法：
#   GH_TOKEN=你的PAT bash create_release.sh1.7.8
#   GH_TOKEN=你的PAT bash create_release.sh              # 不带参数则自动读PLUGIN_VERSION
#
# 命名规范（MoviePilot 源码 app/helper/plugin.py::__build_plugin_release_item）：
#   tag   = {插件ID}_v{版本号}          例：NfoGapFill_v1.7.8
#   资产名 = {tag 全小写}.zip            例：nfogapfill_v1.7.8.zip
# 资产名大小写必须严格匹配，否则 MP 认不出这个 Release，插件列表里不会出现该版本。
set -euo pipefail
: "${GH_TOKEN:?请先设置 GH_TOKEN 环境变量}"
OWNER=2804826634; REPO=MoviePilot-Plugins; PLUGIN_ID=NfoGapFill
cd "$(dirname "$0")"

# 1) 版本号：优先用命令行参数，其次从插件源码里读 PLUGIN_VERSION
VER="${1:-}"
if [ -z "$VER" ]; then
  VER=$(grep -oP '^\s*PLUGIN_VERSION\s*=\s*"\K[^"]+' "plugins.v2/nfogapfill/__init__.py" | head -1)
  : "${VER:?无法自动读取 PLUGIN_VERSION，请显式传入版本号}"
fi
TAG="${PLUGIN_ID}_v${VER}"
ASSET="nfogapfill_v${VER}.zip"          # 全小写
T="$(mktemp -d)"
echo "版本 = $VER   tag = $TAG   资产 = $ASSET"

# 2) 打包（顶层目录 nfogapfill/，与既有19 个 Release 的结构一致）
python - "$T" "$ASSET" <<'PY'
import sys, zipfile, os
T, asset = sys.argv[1], sys.argv[2]
out = f"{T}/{asset}"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    zf.write("plugins.v2/nfogapfill/__init__.py", "nfogapfill/__init__.py")
print("zip:", os.path.getsize(out), "bytes")
PY

# 3) 取远端 main 的 SHA 作为 target
SHA=$(curl -sS -H "Authorization: Bearer $GH_TOKEN" -H "User-Agent: nfg" \
      "https://api.github.com/repos/$OWNER/$REPO/git/ref/heads/main" \
      | python -c "import sys,json;print(json.load(sys.stdin)['object']['sha'])")
echo "target SHA = ${SHA:0:8}"

# 4) 建 release（body 取同版本号的 RELEASE_vX.md，没有就给一行兜底）
python - "$T" "$SHA" "$TAG" "$VER" <<'PY'
import json, sys, os
T, sha, tag, ver = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
rel = f"RELEASE_v{ver}.md"
body = open(rel, encoding="utf-8").read() if os.path.exists(rel) else f"NfoGapFill {ver}"
json.dump({"tag_name": tag, "target_commitish": sha,
           "name": tag, "body": body,
           "draft": False, "prerelease": False, "make_latest": "true"},
          open(f"{T}/payload.json", "w", encoding="utf-8"), ensure_ascii=False)
print("body 来源:", rel if os.path.exists(rel) else "（无对应 RELEASE 文件，用兜底文案）")
PY
RID=$(curl -sS -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
      -H "User-Agent: nfg" -H "Content-Type: application/json; charset=utf-8" \
      --data-binary "@$T/payload.json" \
      "https://api.github.com/repos/$OWNER/$REPO/releases" \
      | python -c "import sys,json;d=json.load(sys.stdin);print(d.get('id') or 'ERR:'+str(d.get('message')))")
case "$RID" in ERR:*|"") echo "创建 Release 失败：$RID"; exit 1;; esac
echo "release id = $RID"

# 5) 上传附件
curl -sS -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
     -H "User-Agent: nfg" -H "Content-Type: application/zip" \
     --data-binary "@$T/$ASSET" \
     "https://uploads.github.com/repos/$OWNER/$REPO/releases/$RID/assets?name=$ASSET" \
     | python -c "import sys,json;d=json.load(sys.stdin);print('asset:', d.get('name'), d.get('size'), d.get('state'))"

rm -rf "$T"
echo "完成：https://github.com/$OWNER/$REPO/releases/tag/$TAG"
