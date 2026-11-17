#!/usr/bin/env python3
"""Synchronize the published price checker release into the AIO application catalog."""
import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

SOURCE = "B-G-HITECH-S-L/bg-pos-price-checker-release"
TARGET = "B-G-HITECH-S-L/bg-pos-aio-release"
CATALOG = "application/application-catalog.json"
APP_ID = "com.byghitech.bg_pos_price_checker"
FIELDS = ("version", "versionCode", "packageUrl", "sha256", "size")
ENV = dict(os.environ, GH_HOST="github.com", GH_PROMPT_DISABLED="1", GH_PAGER="cat")


def api(endpoint, payload=None):
    args = ["gh", "api", "--hostname", "github.com", endpoint]
    if payload is not None:
        args += ["--method", "PUT", "--input", "-"]
    result = subprocess.run(args, input=None if payload is None else json.dumps(payload),
                            capture_output=True, text=True, check=True, env=ENV, timeout=60)
    return json.loads(result.stdout)


def read_asset(asset, hash_only=False):
    asset_id = asset.get("id")
    if type(asset_id) is not int or asset_id < 1:
        raise ValueError("Release 附件 ID 无效。")
    # File-backed output also bounds memory when an older APK has no API digest.
    with tempfile.TemporaryFile() as stream:
        subprocess.run(["gh", "api", "--hostname", "github.com",
                        f"repos/{SOURCE}/releases/assets/{asset_id}",
                        "-H", "Accept: application/octet-stream"],
                       stdout=stream, stderr=subprocess.PIPE, check=True, env=ENV, timeout=180)
        if stream.tell() != asset["size"]:
            raise ValueError("下载的 Release 附件大小不一致。")
        stream.seek(0)
        if hash_only:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            return digest.hexdigest()
        return stream.read()


def matching_app(document):
    if (not isinstance(document, dict) or document.get("schemaVersion") != 2
            or not isinstance(document.get("applications"), list)
            or len(document["applications"]) > 500):
        raise ValueError("应用目录格式无效。")
    rows = [row for row in document["applications"] if isinstance(row, dict)
            and row.get("id") == APP_ID and row.get("platform") == "android"]
    if len(rows) != 1 or rows[0].get("packageFileName") != "big-price-checker.apk":
        raise ValueError("必须存在唯一的 Android 查价机条目及正确的安装包文件名。")
    return rows[0]


def released_update(tag, manifest):
    release = api(f"repos/{SOURCE}/releases/tags/{tag}")
    if (release.get("tag_name") != tag or release.get("draft") is not False
            or release.get("prerelease") is not False):
        raise ValueError("仅允许同步已正式发布的版本。")
    require_latest(release)
    rows = release.get("assets", [])
    assets = {row["name"]: row for row in rows}
    if len(rows) != 2 or set(assets) != {"big-price-checker.apk", "update.json"}:
        raise ValueError("正式 Release 必须完整包含 APK 和 update.json。")
    for name, asset in assets.items():
        if (asset.get("state") != "uploaded" or type(asset.get("size")) is not int
                or asset["size"] < 1 or asset.get("browser_download_url") !=
                f"https://github.com/{SOURCE}/releases/download/{tag}/{name}"):
            raise ValueError("正式 Release 附件状态或版本地址无效。")
    metadata = assets["update.json"]
    if metadata["size"] > 1024 * 1024:
        raise ValueError("update.json 超过大小限制。")
    if manifest is not None and manifest.stat().st_size != metadata["size"]:
        raise ValueError("本地 update.json 大小与正式附件不一致。")
    content = manifest.read_bytes() if manifest is not None else read_asset(metadata)
    if (len(content) != metadata["size"] or metadata.get("digest") not in
            (None, "sha256:" + hashlib.sha256(content).hexdigest())):
        raise ValueError("update.json 与正式附件校验信息不一致。")
    if metadata.get("digest") is None and manifest is not None and content != read_asset(metadata):
        raise ValueError("本地 update.json 与正式附件内容不同。")
    app = matching_app(json.loads(content))
    if (app.get("version") != tag[1:] or type(app.get("versionCode")) is not int
            or not 1 <= app["versionCode"] <= 2100000000
            or not isinstance(app.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", app["sha256"])
            or type(app.get("size")) is not int or not 1 <= app["size"] <= 512 * 1024 * 1024
            or app.get("packageUrl") != assets["big-price-checker.apk"]["browser_download_url"]):
        raise ValueError("update.json 中的版本或安装包信息无效。")
    apk = assets["big-price-checker.apk"]
    if apk["size"] != app["size"]:
        raise ValueError("APK 大小与 update.json 不一致。")
    digest = apk.get("digest")
    if digest is None:
        digest = "sha256:" + read_asset(apk, hash_only=True)
    if digest != "sha256:" + app["sha256"]:
        raise ValueError("APK SHA-256 与 update.json 不一致。")
    return release, app


def require_latest(release):
    latest = api(f"repos/{SOURCE}/releases/latest")
    if latest.get("id") != release["id"] or latest.get("tag_name") != release["tag_name"]:
        raise ValueError("目标已不是 Latest Release，停止同步以免回退目录。")


def read_catalog():
    record = api(f"repos/{TARGET}/contents/{CATALOG}?ref=main")
    if (record.get("type") != "file" or record.get("encoding") != "base64"
            or not re.fullmatch(r"[0-9a-f]{40}", record.get("sha", ""))):
        raise ValueError("无法确认 AIO 目录文件及 blob SHA。")
    content = base64.b64decode("".join(record["content"].split()), validate=True)
    if len(content) > 1024 * 1024:
        raise ValueError("AIO 应用目录超过大小限制。")
    return record["sha"], json.loads(content)


def synchronize(tag, manifest=None, dry_run=False):
    if not re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag):
        raise ValueError("版本号格式应为 v主版本.次版本.修订版本。")
    release, app = released_update(tag, manifest)
    sha, original = read_catalog()
    updated = copy.deepcopy(original)
    row = matching_app(updated)
    if type(row.get("versionCode")) is not int or row["versionCode"] > app["versionCode"]:
        raise ValueError("AIO 目录构建号无效或更高，停止同步以免降级。")
    changes = {key: app[key] for key in FIELDS}
    if all(row.get(key) == value for key, value in changes.items()):
        print(f"AIO 应用目录已是 {app['version']}+{app['versionCode']}，无需重复提交。")
        return
    if row["versionCode"] == app["versionCode"]:
        raise ValueError("相同构建号的 AIO 目录与 Release 信息冲突，请先人工核对。")
    row.update(changes)
    print(json.dumps(changes, ensure_ascii=False, indent=2))
    if dry_run:
        print("AIO 目录同步预览完成，未修改远程。")
        return
    require_latest(release)
    # The current blob SHA makes a concurrent catalog edit fail instead of being lost.
    content = (json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode()
    result = api(f"repos/{TARGET}/contents/{CATALOG}", {
        "message": f"Update price checker to {app['version']}", "branch": "main",
        "sha": sha, "content": base64.b64encode(content).decode(),
    })
    commit = result["commit"]["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("AIO 目录已请求更新，但未能确认提交 SHA，请检查远程。")
    _, verified = read_catalog()
    if any(matching_app(verified).get(key) != value for key, value in changes.items()):
        raise ValueError("AIO 目录写入后核验不一致，请检查远程。")
    print(f"AIO 应用目录已提交至 main：https://github.com/{TARGET}/commit/{commit}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        synchronize(args.version, args.manifest, args.dry_run)
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        detail = ""
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            detail = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr
        parser.exit(1, f"AIO 目录同步失败：{error}\n{detail}")


if __name__ == "__main__":
    main()
