#!/usr/bin/env python3
"""校验公开发布说明；诊断只输出行号和类别，不回显原文。"""
import argparse
import html
import ipaddress
from pathlib import Path
import re
import sys
import subprocess
from urllib.parse import unquote, urlsplit


PUBLIC_REPOSITORIES = {"bg-pos-price-checker-release", "bg-pos-aio-release"}
URL = re.compile(r"(?:https?|wss?|ftp|rtsp|rtmp|smb|ssh)://[^\s<>\"`]+", re.I)
DOMAIN = re.compile(r"(?<![\w@.-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}(?![\w.-])", re.I)
FILE_SUFFIXES = {"apk", "exe", "blockmap", "json", "yml", "yaml", "txt", "md", "png", "jpg", "svg", "mp4", "pdf", "zip", "gz", "so", "dll", "mjs", "ts", "js"}
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
IPV6 = re.compile(r"(?<!\w)(?:[a-f0-9]{0,4}:){2,}[a-f0-9:.]*(?:%[\w]+)?", re.I)
COMMIT = re.compile(r"(?<![a-z0-9])[a-f0-9]{7,40}(?![a-z0-9])", re.I)
RULES = (
    ("凭据或私钥", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:gh[pousr]_[a-z0-9]{20,}|github_pat_[a-z0-9_]{30,}|(?:AKIA|ASIA)[A-Z0-9]{16}|AIza[a-z0-9_-]{35}|xox[baprs]-[a-z0-9-]{20,})\b", re.I)),
    ("凭据赋值", re.compile(r"(?:\b(?:password|passwd|secret|token|api[_-]?key|storePassword|keyPassword)\b|密码|口令|令牌|私钥|密钥)\s*[:=：]\s*\S+", re.I)),
    ("源码提交或仓库信息", re.compile(r"源码(?:提交|仓库|链接)|提交\s*(?:ID|编号|哈希)|\bcommit(?:ish|\s*(?:id|sha|hash))?\b|(?:^|\s)[\w.-]+/[\w.-]+/(?:commit|tree|blob)/", re.I)),
    ("CI 或构建机记录", re.compile(r"\bCI\b|\brunner\b|self-hosted|GITHUB_RUN_(?:ID|NUMBER)|\bworkflow\b|\bActions?\s+Artifact\b|\brun\s*(?:id|number|#|\d{4,})|构建机|流水线(?:运行|编号|失败|离线)", re.I)),
    ("本机磁盘或临时目录记录", re.compile(r"(?:本机|构建机).{0,24}(?:磁盘|容量|[a-z]\s*盘)|[a-z]\s*盘\s*\d|磁盘(?:占用|使用率)|%TEMP%|/Users/|/home/|[a-z]:\\(?:Users|Work|Temp)\\", re.I)),
    ("测试失败或排障记录", re.compile(r"(?:单元|回归|自动化)?测试(?:结果|用例)?\s*(?:\d+\s*(?:例|项)\s*)?(?:失败|假红|超时)|\d+\s*(?:例|项).{0,4}失败|\btests?\s+(?:failed|failures?)\b|\bfailed\s*[:=]?\s*\d+|\b(?:npm test|runGit|stack trace|Traceback)\b", re.I)),
)


def public_download(value):
    try:
        parts = urlsplit(value)
        if parts.scheme != "https" or parts.username or parts.password or parts.port or parts.query or parts.fragment:
            return False
        if parts.hostname == "github.com":
            segments = parts.path.strip("/").split("/")
            return (len(segments) >= 4 and segments[0].lower() == "b-g-hitech-s-l"
                    and segments[1] in PUBLIC_REPOSITORIES and segments[2] == "releases"
                    and segments[3] in {"download", "latest", "tag"})
        return (parts.hostname == "b-g-hitech-s-l.github.io"
                and parts.path.startswith("/bg-pos-aio-release/"))
    except ValueError:
        return False


def violations(text):
    result = []
    # 解码常见转义后校验，防止 Markdown/HTML 转义绕过地址检查。
    for number, original in enumerate(text.splitlines(), 1):
        line = unquote(html.unescape(original))
        reasons = {label for label, pattern in RULES if pattern.search(line)}
        remaining = line
        for match in URL.finditer(line):
            value = match.group().rstrip(".,;)]}，。；")
            if not public_download(value):
                reasons.add("非公开下载地址")
            remaining = remaining.replace(match.group(), " ")
        if any(m.group().rsplit(".", 1)[-1].lower() not in FILE_SUFFIXES
               for m in DOMAIN.finditer(remaining)):
            reasons.add("服务器域名")
        for pattern in (IPV4, IPV6):
            for match in pattern.finditer(remaining):
                try:
                    ipaddress.ip_address(match.group().split("%", 1)[0])
                    reasons.add("服务器 IP 地址")
                except ValueError:
                    pass
        if re.search(r"(?:端口|\bport)\s*[:=：]?\s*\d{2,5}\b|\b(?:Server|Data Source|Host)\s*=|\blocalhost\b", remaining, re.I):
            reasons.add("服务器连接配置")
        for match in COMMIT.finditer(remaining):
            value = match.group()
            if value.lower() != "ed25519" and (re.search("[a-f]", value, re.I) or len(value) == 40):
                reasons.add("源码提交 ID")
        result.extend((number, reason) for reason in sorted(reasons))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--tag")
    parser.add_argument("--product", choices=["BiG AIO", "BiG Price Checker"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.tag:
        if args.files or not args.product or not args.output:
            parser.error("标签模式需要 --product 和 --output，且不能同时指定输入文件。")
        try:
            text = notes_for_tag(args.tag, args.product)
        except (ValueError, subprocess.CalledProcessError):
            print("无法读取发布标签的说明。", file=sys.stderr)
            return 1
        findings = violations(text)
        for number, reason in findings:
            print(f"标签说明第 {number} 行违反公开规则：{reason}。", file=sys.stderr)
        if findings:
            return 1
        with args.output.open("w", encoding="utf-8", newline="\n") as output:
            output.write(text.rstrip() + "\n")
        return 0
    if not args.files or args.product or args.output:
        parser.error("请指定发布说明文件，或使用完整的标签模式。")
    failed = False
    for index, path in enumerate(args.files, 1):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            print(f"发布说明 {index} 无法以 UTF-8 读取。", file=sys.stderr)
            failed = True
            continue
        if not text.strip():
            print(f"发布说明 {index} 为空。", file=sys.stderr)
            failed = True
        for number, reason in violations(text):
            print(f"发布说明 {index} 第 {number} 行违反公开规则：{reason}。", file=sys.stderr)
            failed = True
    return 1 if failed else 0


def notes_for_tag(tag, product):
    """只使用附注标签正文；轻量标签不能借用所指提交的内部说明。"""
    if not re.fullmatch(r"v-?(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", tag):
        raise ValueError("标签格式无效")
    ref = "refs/tags/" + tag
    kind = subprocess.check_output(["git", "cat-file", "-t", ref], text=True, stderr=subprocess.PIPE).strip()
    if kind not in ("tag", "commit"):
        raise ValueError("标签目标无效")
    text = ""
    if kind == "tag":
        text = subprocess.check_output(["git", "for-each-ref", "--format=%(contents)", ref], text=True)
        text = re.sub(r"^-----BEGIN PGP SIGNATURE-----.*?^-----END PGP SIGNATURE-----\s*", "", text, flags=re.M | re.S)
    version = tag[2:] if tag.startswith("v-") else tag[1:]
    return text if text.strip() else f"# {product} {version}\n\n正式安装包。\n"


if __name__ == "__main__":
    sys.exit(main())
