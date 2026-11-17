#!/usr/bin/env python3
"""Generate deterministic update.json from the APK that will be uploaded."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

REPO = "B-G-HITECH-S-L/bg-pos-price-checker-release"
APPLICATION_ID = "com.byghitech.bg_pos_price_checker"
APK_NAME = "big-price-checker.apk"


def find_aapt():
    override = os.environ.get("AAPT_BIN")
    if override:
        candidate = shutil.which(override)
        if not candidate:
            raise ValueError("AAPT_BIN 未指向可执行的 aapt。")
        return candidate
    candidate = shutil.which("aapt")
    if candidate:
        return candidate
    roots = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
             str(Path.home() / "Library/Android/sdk"), str(Path.home() / "Android/Sdk")]
    for root in roots:
        if not root:
            continue
        candidates = sorted(
            (Path(root) / "build-tools").glob("*/aapt"),
            key=lambda p: tuple(int(v) for v in re.findall(r"\d+", p.parent.name)),
            reverse=True,
        )
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    raise ValueError("找不到 Android SDK aapt，请配置 ANDROID_HOME、ANDROID_SDK_ROOT 或 AAPT_BIN。")


def generate(apk, tag):
    if not re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag):
        raise ValueError("版本号格式应为 v主版本.次版本.修订版本。")
    if apk.is_symlink() or not apk.is_file():
        raise ValueError("APK 必须为普通文件，不能是符号链接。")
    size = apk.stat().st_size
    if not 0 < size <= 512 * 1024 * 1024:
        raise ValueError("APK 大小必须为 1 字节至 512 MiB。")
    badging = subprocess.run([find_aapt(), "dump", "badging", str(apk)],
                             check=True, capture_output=True, text=True).stdout
    package = next((line for line in badging.splitlines() if line.startswith("package: ")), "")
    fields = dict(part.split("=", 1) for part in shlex.split(package)[1:] if "=" in part)
    if fields.get("name") != APPLICATION_ID:
        raise ValueError("APK 包名不是 BiG Price Checker。")
    if fields.get("versionName") != tag[1:]:
        raise ValueError("APK 版本名与 Release 标签不一致。")
    code = fields.get("versionCode", "")
    if not re.fullmatch(r"[1-9][0-9]*", code) or int(code) > 2100000000:
        raise ValueError("APK 构建号无效。")
    if "application-debuggable" in badging:
        raise ValueError("不能发布可调试 APK。")
    digest = hashlib.sha256()
    with apk.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    # Reuse the client's established schema and validation; no version-code guess.
    return {"schemaVersion": 2, "applications": [{
        "id": APPLICATION_ID,
        "platform": "android",
        "version": fields["versionName"],
        "versionCode": int(code),
        "packageFileName": APK_NAME,
        "packageUrl": f"https://github.com/{REPO}/releases/download/{tag}/{APK_NAME}",
        "sha256": digest.hexdigest(),
        "size": size,
    }]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        document = generate(args.apk, args.version)
        if args.output.is_symlink() or (args.output.exists() and not args.output.is_file()):
            raise ValueError("update.json 目标必须为普通文件，不能是符号链接或目录。")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent,
                                             prefix=".update-", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(document, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, args.output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"生成 update.json 失败：{error}\n")


if __name__ == "__main__":
    main()
