#!/bin/bash
# Compatible with the Bash 3.2 bundled with macOS.
set -Eeuo pipefail

REPO='B-G-HITECH-S-L/bg-pos-price-checker-release'
AIO_REPO='B-G-HITECH-S-L/bg-pos-aio-release'
ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
VERSION=''
DRY_RUN=false
KEEP_DRAFT=false
RESUME=false
WORK_DIR=''
NOTES_TEMP=''
MANIFEST_TEMP=''
RELEASE_ID=''
REMOTE_TOUCHED=false
RELEASE_PUBLISHED=false
STAGE='检查参数'

usage() {
  cat <<'EOF'
用法：scripts/release.sh v主版本.次版本.修订版本 [选项]

输入：dist/<版本>/ 中恰好一个 .apk；release-notes.md 缺失或为空时自动生成。
从实际 APK 生成 update.json；说明中自动维护 SHA-256 和 Size，已有人工正文保留。

选项：
  --dry-run  校验并预览更新文件及发布说明；不修改本地文件或远程
  --draft    上传并校验后保留草稿
  --resume   继续已有的同版本草稿；相同内容复用，冲突时停止
  -h, --help 显示帮助

默认行为：校验 APK 与 update.json，正式发布为 Latest 后同步 AIO 应用目录。
目标仓库固定为 B-G-HITECH-S-L/bg-pos-price-checker-release。
EOF
}

die() {
  printf '错误：%s\n' "$*" >&2
  exit 1
}

on_exit() {
  local status=$?
  trap - EXIT
  if [[ -n "$NOTES_TEMP" && -f "$NOTES_TEMP" ]]; then
    rm -f -- "$NOTES_TEMP"
  fi
  if [[ -n "$MANIFEST_TEMP" && -f "$MANIFEST_TEMP" ]]; then
    rm -f -- "$MANIFEST_TEMP"
  fi
  if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
    rm -rf -- "$WORK_DIR"
  fi
  if [[ $status -ne 0 ]]; then
    printf '失败阶段：%s\n' "$STAGE" >&2
    if [[ "$REMOTE_TOUCHED" == true ]]; then
      printf '远程可能已完成部分操作，请先检查 Releases 页面；脚本不会自动删除草稿或附件。\n' >&2
      if [[ "$RELEASE_PUBLISHED" == true ]]; then
        printf 'Release 已正式发布；目录同步可单独重试：python3 %q %q\n' \
          "$ROOT/scripts/sync-aio-catalog.py" "$VERSION" >&2
      else
        printf '若仍为草稿，可重试：%q %q --resume' "$ROOT/scripts/release.sh" "$VERSION" >&2
        if [[ "$KEEP_DRAFT" == true ]]; then printf ' --draft' >&2; fi
        printf '\n' >&2
      fi
    fi
  fi
  exit "$status"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    --draft) KEEP_DRAFT=true ;;
    --resume) RESUME=true ;;
    -h|--help) usage; exit 0 ;;
    -*) die "未知选项：$1" ;;
    *)
      [[ -z "$VERSION" ]] || die '只能指定一个版本号。'
      VERSION=$1
      ;;
  esac
  shift
done

[[ "$VERSION" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] ||
  die '版本号格式应为 v0.0.1，不接受路径、前导零或预发布后缀。'

for dependency in gh git unzip shasum mktemp cp mv cmp awk wc tr grep python3; do
  command -v "$dependency" >/dev/null 2>&1 || die "缺少命令：$dependency"
done

# Pin all gh operations to GitHub.com, independent of the caller's GH_HOST/GH_REPO.
export GH_HOST=github.com GH_PROMPT_DISABLED=1 GH_PAGER=cat

STAGE='检查本地输入'
ORIGIN=$(git -C "$ROOT" remote get-url origin) || die '无法读取仓库 origin。'
case "$ORIGIN" in
  "git@github.com:$REPO.git"|"https://github.com/$REPO.git"|"https://github.com/$REPO"|"ssh://git@github.com/$REPO.git") ;;
  *) die "origin 与目标仓库不一致：$ORIGIN" ;;
esac

VERSION_DIR="$ROOT/dist/$VERSION"
SOURCE_NOTES="$VERSION_DIR/release-notes.md"
NOTES_EXISTED=false
SOURCE_MANIFEST="$VERSION_DIR/update.json"
MANIFEST_EXISTED=false
[[ -d "$VERSION_DIR" && ! -L "$ROOT/dist" && ! -L "$VERSION_DIR" ]] ||
  die "版本目录不存在或是符号链接：$VERSION_DIR"

shopt -s nullglob dotglob
APK_FILES=("$VERSION_DIR"/*.apk)
[[ ${#APK_FILES[@]} -eq 1 ]] ||
  die "版本目录必须恰好包含一个 .apk 文件，当前找到 ${#APK_FILES[@]} 个。.textClipping 不是 APK。"
APK=${APK_FILES[0]}
[[ -f "$APK" && -s "$APK" && ! -L "$APK" ]] || die 'APK 必须是非空的普通文件，不能是符号链接。'
if [[ -e "$SOURCE_MANIFEST" || -L "$SOURCE_MANIFEST" ]]; then
  [[ -f "$SOURCE_MANIFEST" && ! -L "$SOURCE_MANIFEST" ]] || die 'update.json 必须是普通文件，不能是目录或符号链接。'
  MANIFEST_EXISTED=true
fi
if [[ -e "$SOURCE_NOTES" || -L "$SOURCE_NOTES" ]]; then
  [[ -f "$SOURCE_NOTES" && ! -L "$SOURCE_NOTES" ]] || die '发布说明必须是普通文件，不能是目录或符号链接。'
  NOTES_EXISTED=true
fi
case "$APK" in
  *'#'*|*$'\n'*|*$'\r'*|*$'\t'*) die 'APK 路径不能包含 #、换行或制表符；# 会被 gh 解释为附件标签。' ;;
esac

# Upload a stable snapshot if the source APK/notes change while the script runs.
WORK_DIR=$(mktemp -d "$ROOT/dist/.release-$VERSION.XXXXXX")
APK_NAME=${APK##*/}
[[ "$APK_NAME" == big-price-checker.apk ]] || die 'APK 文件名必须为 big-price-checker.apk，与应用安装校验保持一致。'
if [[ "$MANIFEST_EXISTED" == true ]]; then
  cp -- "$SOURCE_MANIFEST" "$WORK_DIR/manifest-original.json"
fi
cp -- "$APK" "$WORK_DIR/$APK_NAME"
if [[ "$NOTES_EXISTED" == true ]]; then
  cp -- "$SOURCE_NOTES" "$WORK_DIR/notes-original.md"
else
  : > "$WORK_DIR/notes-original.md"
fi
APK="$WORK_DIR/$APK_NAME"
NOTES="$WORK_DIR/release-notes.md"
unzip -tqq "$APK" </dev/null || die 'APK 的 ZIP 完整性检查失败。'
unzip -Z1 "$APK" | LC_ALL=C grep -Fx 'AndroidManifest.xml' >/dev/null ||
  die 'APK 中缺少根目录 AndroidManifest.xml。'

sha256() {
  local result
  result=$(shasum -a 256 < "$1") || return 1
  printf '%s\n' "${result%% *}"
}

APK_SHA=$(sha256 "$APK")
APK_SIZE=$(wc -c < "$APK" | tr -d '[:space:]')
TITLE="BiG Price Checker $VERSION"

STAGE='生成更新文件'
MANIFEST="$WORK_DIR/update.json"
python3 "$ROOT/scripts/generate-update-manifest.py" --apk "$APK" --version "$VERSION" --output "$MANIFEST" ||
  die '生成 update.json 失败；请核对 APK 包名、版本、构建号和 Android SDK aapt。'
MANIFEST_SHA=$(sha256 "$MANIFEST")
MANIFEST_SIZE=$(wc -c < "$MANIFEST" | tr -d '[:space:]')

STAGE='生成发布说明'
# Keep the original snapshot separate so a later write can detect manual edits.
if [[ -n "$(LC_ALL=C tr -d '[:space:]' < "$WORK_DIR/notes-original.md")" ]]; then
  cp -- "$WORK_DIR/notes-original.md" "$WORK_DIR/notes-input.md"
else
  printf '# %s\n' "$TITLE" > "$WORK_DIR/notes-input.md"
fi
{
  printf '%s\n' '<!-- release-package-info:start -->' '## 安装包信息' ''
  printf '%s\n' "- 文件名: $APK_NAME" "- SHA-256: $APK_SHA" "- Size: $APK_SIZE"
  printf '%s\n' '<!-- release-package-info:end -->'
} > "$WORK_DIR/package-info.md"

# Replace only the marked block, in place. Reject malformed/duplicate markers
# rather than accidentally discarding handwritten release notes.
awk '
  NR == FNR { block[++count] = $0; next }
  {
    marker = $0
    sub(/\r$/, "", marker)
    if (marker == "<!-- release-package-info:start -->") {
      if (inside || seen) { invalid = 1; exit 1 }
      inside = seen = 1
      for (i = 1; i <= count; i++) print block[i]
      next
    }
    if (marker == "<!-- release-package-info:end -->") {
      if (!inside) { invalid = 1; exit 1 }
      inside = 0
      next
    }
    if (!inside) print
  }
  END {
    if (invalid || inside) exit 1
    if (!seen) {
      print ""
      for (i = 1; i <= count; i++) print block[i]
    }
  }
' "$WORK_DIR/package-info.md" "$WORK_DIR/notes-input.md" > "$NOTES" ||
  die '发布说明的自动区块标记不完整或重复，请先修复 release-package-info 标记。'

persist_notes() {
  # Do not overwrite edits made during network preflight, or a newly created file.
  if [[ "$NOTES_EXISTED" == true ]]; then
    [[ -f "$SOURCE_NOTES" && ! -L "$SOURCE_NOTES" ]] &&
      cmp -s "$SOURCE_NOTES" "$WORK_DIR/notes-original.md" ||
      die '发布说明在执行期间发生变化，请核对后重新运行。'
    if cmp -s "$SOURCE_NOTES" "$NOTES"; then return 0; fi
  else
    [[ ! -e "$SOURCE_NOTES" && ! -L "$SOURCE_NOTES" ]] ||
      die '执行期间已出现新的发布说明，请核对后重新运行。'
  fi
  # The replacement is on the same filesystem, so readers never see a partial file.
  NOTES_TEMP=$(mktemp "$VERSION_DIR/.release-notes.XXXXXX")
  cp -- "$NOTES" "$NOTES_TEMP"
  mv -f -- "$NOTES_TEMP" "$SOURCE_NOTES"
  NOTES_TEMP=''
  printf '本地发布说明已更新：%s\n' "$SOURCE_NOTES"
}

persist_manifest() {
  if [[ "$MANIFEST_EXISTED" == true ]]; then
    [[ -f "$SOURCE_MANIFEST" && ! -L "$SOURCE_MANIFEST" ]] &&
      cmp -s "$SOURCE_MANIFEST" "$WORK_DIR/manifest-original.json" ||
      die 'update.json 在执行期间发生变化，请核对后重新运行。'
    if cmp -s "$SOURCE_MANIFEST" "$MANIFEST"; then return 0; fi
  else
    [[ ! -e "$SOURCE_MANIFEST" && ! -L "$SOURCE_MANIFEST" ]] ||
      die '执行期间已出现新的 update.json，请核对后重新运行。'
  fi
  MANIFEST_TEMP=$(mktemp "$VERSION_DIR/.update.XXXXXX")
  cp -- "$MANIFEST" "$MANIFEST_TEMP"
  mv -f -- "$MANIFEST_TEMP" "$SOURCE_MANIFEST"
  MANIFEST_TEMP=''
  printf '本地更新文件已生成：%s\n' "$SOURCE_MANIFEST"
}

api() { gh api --hostname github.com "$@"; }

load_release() {
  local record count=0
  RELEASE_ID=''
  RELEASE_DRAFT=''
  RELEASE_URL=''
  RELEASE_TARGET=''
  # A successful, fully paginated list distinguishes absence from API/network errors,
  # and includes drafts (which need not have a Git tag yet).
  api "repos/$REPO/releases?per_page=100" --paginate --jq \
    ".[] | select(.tag_name == \"$VERSION\") | [.id, .draft, .html_url, .target_commitish] | @tsv" \
    > "$WORK_DIR/releases.tsv" || die '查询版本失败，不能将查询错误当作版本不存在。'
  while IFS= read -r record; do
    [[ -n "$record" ]] || continue
    count=$((count + 1))
    IFS=$'\t' read -r RELEASE_ID RELEASE_DRAFT RELEASE_URL RELEASE_TARGET <<< "$record"
  done < "$WORK_DIR/releases.tsv"
  [[ $count -le 1 ]] || die '发现多个同版本 Release，请先在 GitHub 核对草稿。'
  if [[ $count -eq 1 ]]; then
    [[ "$RELEASE_ID" =~ ^[0-9]+$ ]] || die '远程 Release ID 无效。'
    [[ "$RELEASE_DRAFT" == true || "$RELEASE_DRAFT" == false ]] || die '无法确认远程草稿状态。'
  fi
}

verify_assets() {
  local id name size state digest url remote_sha expected_sha expected_size temporary_tag
  local allow_draft_urls=${1:-false}
  ASSET_COUNT=0
  APK_PRESENT=false
  MANIFEST_PRESENT=false
  DOWNLOAD_URL=''
  MANIFEST_URL=''
  api "repos/$REPO/releases/$RELEASE_ID/assets?per_page=100" --paginate --jq \
    '.[] | [.id, .name, .size, .state, (.digest // "-"), .browser_download_url] | @tsv' \
    > "$WORK_DIR/assets.tsv" || die '读取远程附件失败。'
  while IFS=$'\t' read -r id name size state digest url; do
    [[ -n "$id" ]] || continue
    ASSET_COUNT=$((ASSET_COUNT + 1))
    [[ "$id" =~ ^[0-9]+$ ]] || die '远程附件 ID 无效。'
    case "${name}" in
      big-price-checker.apk)
        [[ "$APK_PRESENT" == false ]] || die '草稿含有多个附件同名 APK；不会自动删除。'
        APK_PRESENT=true
        expected_sha=$APK_SHA; expected_size=$APK_SIZE
        DOWNLOAD_URL=$url
        ;;
      update.json)
        [[ "$MANIFEST_PRESENT" == false ]] || die '草稿含有多个附件同名 update.json；不会自动删除。'
        MANIFEST_PRESENT=true
        expected_sha=$MANIFEST_SHA; expected_size=$MANIFEST_SIZE
        MANIFEST_URL=$url
        ;;
      *) die "草稿包含不支持的附件：${name}，请先人工核对；不会自动删除。" ;;
    esac
    [[ "$state" == uploaded ]] || die "远程附件 ${name} 未完整上传，请先人工核对。"
    [[ "$size" == "$expected_size" ]] || die "远程附件 ${name} 大小与本地不同，请先人工核对。"
    if [[ "$url" != "https://github.com/$REPO/releases/download/$VERSION/${name}" ]]; then
      # GitHub serves draft assets under an untagged-* URL until publication.
      # Only draft checks may accept that temporary tag, in this exact repo.
      temporary_tag=${url#"https://github.com/$REPO/releases/download/"}
      temporary_tag=${temporary_tag%"/${name}"}
      [[ "$allow_draft_urls" == true && "$temporary_tag" =~ ^untagged-[0-9a-f]+$ &&
         "$url" == "https://github.com/$REPO/releases/download/$temporary_tag/${name}" ]] ||
        die "远程附件 ${name} 的版本下载地址不一致。"
    fi
    if [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
      remote_sha=${digest#sha256:}
    else
      api "repos/$REPO/releases/assets/$id" -H 'Accept: application/octet-stream' \
        > "$WORK_DIR/remote-download-$id" || die "下载附件 ${name} 进行内容校验失败。"
      remote_sha=$(sha256 "$WORK_DIR/remote-download-$id") || die '计算远程附件 SHA-256 失败。'
    fi
    [[ "$remote_sha" == "$expected_sha" ]] || die "远程附件内容与本地 ${name} 不同；不会覆盖或发布。"
  done < "$WORK_DIR/assets.tsv"
}

assert_draft() {
  local record url draft prerelease tag
  record=$(api "repos/$REPO/releases/$RELEASE_ID" --jq \
    '[.html_url, .draft, .prerelease, .tag_name] | @tsv') || die '无法重新确认草稿状态。'
  IFS=$'\t' read -r url draft prerelease tag <<< "$record"
  [[ "$draft" == true && "$tag" == "$VERSION" ]] || die '版本已不再是本次草稿，停止修改。'
}

STAGE='检查 GitHub 登录和仓库权限'
gh auth status --active --hostname github.com >/dev/null 2>&1 || die 'GitHub 登录无效，请先执行 gh auth login。'
CAN_PUSH=$(api "repos/$REPO" --jq '.permissions.push // false') || die '无法访问目标仓库。'
[[ "$CAN_PUSH" == true ]] || die '当前账号没有目标仓库的写入权限。'
if [[ "$KEEP_DRAFT" == false ]]; then
  AIO_CAN_PUSH=$(api "repos/$AIO_REPO" --jq '.permissions.push // false') || die '无法访问 AIO 应用目录仓库。'
  [[ "$AIO_CAN_PUSH" == true ]] || die '当前账号没有 AIO 应用目录仓库的写入权限。'
fi
MAIN_SHA=$(api "repos/$REPO/git/ref/heads/main" --jq '.object.sha') || die '无法读取远程 main。'
[[ "$MAIN_SHA" =~ ^[0-9a-f]{40}$ ]] || die '远程 main 的提交 SHA 无效。'

STAGE='检查远程版本和附件'
load_release
ASSET_COUNT=0
APK_PRESENT=false
MANIFEST_PRESENT=false
if [[ -n "$RELEASE_ID" ]]; then
  [[ "$RELEASE_DRAFT" == true ]] || die "同版本已正式发布：$RELEASE_URL"
  [[ "$RESUME" == true ]] || die '已有同版本草稿。核对附件后，添加 --resume 继续（预览也需要此选项）。'
  verify_assets true
else
  [[ "$RESUME" == false ]] || die '没有找到同版本草稿，不能使用 --resume。'
  # --target does not move an existing tag. Reject one pointing away from main.
  TAG_REF=$(api "repos/$REPO/git/matching-refs/tags/$VERSION" --jq \
    ".[] | select(.ref == \"refs/tags/$VERSION\") | .ref") || die '检查远程标签失败。'
  if [[ -n "$TAG_REF" ]]; then
    TAG_SHA=$(api "repos/$REPO/commits/$VERSION" --jq '.sha') || die '无法解析已有标签的提交。'
    [[ "$TAG_SHA" == "$MAIN_SHA" ]] || die '已有标签不指向本次远程 main 提交；不会移动标签。'
  fi
fi

printf '仓库：%s\n版本：%s\nAPK：%s\nSize: %s bytes\nSHA-256：%s\n' \
  "$REPO" "$VERSION" "$APK_NAME" "$APK_SIZE" "$APK_SHA"
if [[ -n "$RELEASE_ID" ]]; then
  printf '计划：续传草稿（目标：%s），核对并使用本地发布说明。\n' "$RELEASE_TARGET"
else
  printf '计划：从远程 main（%s）创建草稿。\n' "$MAIN_SHA"
fi
printf '附件：big-price-checker.apk（已存在：%s）与 update.json（已存在：%s）；缺失时上传，逐项校验。\n' \
  "$APK_PRESENT" "$MANIFEST_PRESENT"
if [[ "$KEEP_DRAFT" == true ]]; then
  printf '结果：保留草稿。\n'
else
  printf '结果：发布为正式版并设为 Latest，然后提交同步 AIO 应用目录。\n'
fi
if [[ "$DRY_RUN" == true ]]; then
  printf '\n发布说明预览：\n'
  cat "$NOTES"
  printf '\nupdate.json 预览：\n'
  cat "$MANIFEST"
  printf '\n预览完成，未修改远程，也未修改本地发布说明或 update.json。\n'
  exit 0
fi

STAGE='保存本地发布文件'
persist_manifest
persist_notes

if [[ -z "$RELEASE_ID" ]]; then
  STAGE='创建草稿'
  REMOTE_TOUCHED=true
  RELEASE_ID=$(api "repos/$REPO/releases" --method POST \
    -f "tag_name=$VERSION" -f "target_commitish=$MAIN_SHA" -f "name=$TITLE" \
    -F "body=@$NOTES" -F draft=true -F prerelease=false --jq '.id') || die '创建草稿失败，请检查远程是否已创建。'
  [[ "$RELEASE_ID" =~ ^[0-9]+$ ]] || die '创建草稿后未获得有效 ID，请检查远程状态。'
fi

STAGE='上传 APK'
# Re-read before writing in case another process changed the draft after preflight.
assert_draft
verify_assets true
if [[ "$APK_PRESENT" == false ]]; then
  REMOTE_TOUCHED=true
  gh release upload "$VERSION" "$APK" --repo "$REPO" || die 'APK 上传失败，草稿已保留。'
fi

STAGE='上传更新文件'
verify_assets true
if [[ "$MANIFEST_PRESENT" == false ]]; then
  REMOTE_TOUCHED=true
  gh release upload "$VERSION" "$MANIFEST" --repo "$REPO" || die 'update.json 上传失败，草稿已保留。'
fi

STAGE='校验远程 APK 和更新文件'
verify_assets true
[[ $ASSET_COUNT -eq 2 && "$APK_PRESENT" == true && "$MANIFEST_PRESENT" == true ]] ||
  die '上传后 APK 或 update.json 不完整，草稿未发布。'

STAGE='更新发布说明'
assert_draft
REMOTE_TOUCHED=true
api "repos/$REPO/releases/$RELEASE_ID" --method PATCH \
  -f "tag_name=$VERSION" -f "name=$TITLE" -F "body=@$NOTES" -F prerelease=false --silent || die '更新草稿说明失败。'

if [[ "$KEEP_DRAFT" == false ]]; then
  STAGE='发布正式版'
  # GitHub may reset a draft to an untagged-* placeholder when a PATCH omits
  # tag_name. Pin it explicitly on every edit, including publication.
  api "repos/$REPO/releases/$RELEASE_ID" --method PATCH \
    -f "tag_name=$VERSION" -F draft=false -F prerelease=false -f make_latest=true --silent || die '发布请求失败，请先检查远程是否已发布。'
fi

STAGE='核验发布结果'
FINAL_RECORD=$(api "repos/$REPO/releases/$RELEASE_ID" --jq \
  '[.html_url, .draft, .prerelease, .tag_name] | @tsv') || die '无法核验发布结果，请检查远程状态。'
IFS=$'\t' read -r RELEASE_URL FINAL_DRAFT FINAL_PRERELEASE FINAL_TAG <<< "$FINAL_RECORD"
[[ "$FINAL_DRAFT" == "$KEEP_DRAFT" && "$FINAL_PRERELEASE" == false && "$FINAL_TAG" == "$VERSION" ]] ||
  die '远程发布状态与请求不一致，请检查 Releases 页面。'
verify_assets "$FINAL_DRAFT"
[[ $ASSET_COUNT -eq 2 && "$APK_PRESENT" == true && "$MANIFEST_PRESENT" == true && -n "$RELEASE_URL" ]] ||
  die '发布后附件或链接不完整。'
if [[ "$FINAL_DRAFT" == false ]]; then
  RELEASE_PUBLISHED=true
  STAGE='同步 AIO 应用目录'
  python3 "$ROOT/scripts/sync-aio-catalog.py" "$VERSION" --manifest "$MANIFEST" ||
    die 'Release 已发布，AIO 目录同步未完成；请使用独立同步命令恢复。'
fi
printf '\n完成。\nRelease：%s\n附件：%s 和 update.json\n下载：%s\nSHA-256：%s\n更新文件：%s\n' \
  "$RELEASE_URL" "$APK_NAME" "$DOWNLOAD_URL" "$APK_SHA" "$MANIFEST_URL"
