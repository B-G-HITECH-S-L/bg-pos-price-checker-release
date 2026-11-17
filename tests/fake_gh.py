"""Stateful GitHub CLI substitute; only used by test_release.py."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys

state_path = Path(os.environ["RELEASE_TEST_STATE"])
state = json.loads(state_path.read_text())
args = sys.argv[1:]
with Path(os.environ["RELEASE_TEST_CALLS"]).open("a") as stream:
    stream.write(json.dumps(args) + "\n")


def save():
    state_path.write_text(json.dumps(state))


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def tsv(values):
    def value(item):
        if isinstance(item, bool):
            return str(item).lower()
        return str(item)
    print("\t".join(value(item) for item in values))


def release_for_tag(tag):
    return next(item for item in state["releases"] if item["tag_name"] == tag)


def asset_for_file(path):
    data = Path(path).read_bytes()
    if state.get("corrupt_upload") in (True, Path(path).name):
        data = data[:-1] + bytes([data[-1] ^ 1])
    return {
        "id": 12 if Path(path).name == "update.json" else 11,
        "name": Path(path).name,
        "size": len(data),
        "state": "uploaded",
        "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
        "data": base64.b64encode(data).decode(),
        "browser_download_url": "https://github.com/B-G-HITECH-S-L/bg-pos-price-checker-release/releases/download/" + args[2] + "/" + Path(path).name,
    }


if args[:2] == ["auth", "status"]:
    sys.exit(1 if state.get("auth_failure") else 0)

if args[:2] == ["release", "upload"]:
    assert args[4:] == ["--repo", "B-G-HITECH-S-L/bg-pos-price-checker-release"]
    release = release_for_tag(args[2])
    if state.get("upload_failure") in (True, Path(args[3]).name):
        fail("simulated upload failure")
    if state.get("skip_upload") != Path(args[3]).name:
        release["assets"].append(asset_for_file(args[3]))
    save()
    sys.exit(0)

assert args[0] == "api", args
endpoint = None
method = "GET"
query = ""
fields = {}
headers = []
i = 1
while i < len(args):
    arg = args[i]
    if arg in ("--hostname", "--method", "--jq", "-f", "-F", "-H"):
        value = args[i + 1]
        if arg == "--hostname":
            assert value == "github.com"
        elif arg == "--method":
            method = value
        elif arg == "--jq":
            query = value
        elif arg == "-H":
            headers.append(value)
        else:
            key, content = value.split("=", 1)
            if arg == "-F" and content.startswith("@"):
                content = Path(content[1:]).read_text()
            elif arg == "-F" and content in ("true", "false"):
                content = content == "true"
            fields[key] = content
        i += 2
    elif arg in ("--paginate", "--silent"):
        i += 1
    else:
        assert endpoint is None, args
        endpoint = arg
        i += 1

prefix = "repos/B-G-HITECH-S-L/bg-pos-price-checker-release"
assert endpoint.startswith(prefix)
path = endpoint[len(prefix):].split("?")[0]

if path == "":
    print(str(state.get("can_push", True)).lower())
elif path == "/git/ref/heads/main":
    print(state["main_sha"])
elif path.startswith("/git/matching-refs/tags/"):
    tag = path.rsplit("/", 1)[1]
    if tag in state.get("tags", {}):
        print("refs/tags/" + tag)
elif path.startswith("/commits/"):
    print(state["tags"][path.rsplit("/", 1)[1]])
elif path == "/releases" and method == "GET":
    if state.get("query_failure"):
        fail("simulated API failure")
    if state.get("change_notes_during_preflight"):
        Path(state["change_notes_during_preflight"]).write_text("a new handwritten note\n")
    if state.get("change_manifest_during_preflight"):
        Path(state["change_manifest_during_preflight"]).write_text("concurrent edit\n")
    tag = re.search(r'\.tag_name == "([^"]+)"', query).group(1)
    for release in state["releases"]:
        if release["tag_name"] == tag:
            tsv([release["id"], release["draft"], release["html_url"], release["target_commitish"]])
elif path == "/releases" and method == "POST":
    release = dict(fields, id=1, html_url="https://github.com/example/releases/tag/" + fields["tag_name"], assets=[])
    state["releases"].append(release)
    save()
    if state.get("change_source_on_create"):
        Path(state["change_source_on_create"]).write_bytes(b"a new build replaced the source")
    if state.get("create_response_lost"):
        fail("simulated lost create response")
    print(release["id"])
elif path.startswith("/releases/assets/"):
    assert "Accept: application/octet-stream" in headers
    asset_id = int(path.rsplit("/", 1)[1])
    asset = next(asset for release in state["releases"] for asset in release["assets"] if asset["id"] == asset_id)
    sys.stdout.buffer.write(base64.b64decode(asset["data"]))
elif path.endswith("/assets"):
    release_id = int(path.split("/")[2])
    release = next(item for item in state["releases"] if item["id"] == release_id)
    for asset in release["assets"]:
        tsv([asset["id"], asset["name"], asset["size"], asset["state"], asset.get("digest") or "-", asset["browser_download_url"]])
elif path.startswith("/releases/"):
    release = next(item for item in state["releases"] if item["id"] == int(path.rsplit("/", 1)[1]))
    if method == "PATCH":
        # Reproduce GitHub's draft edit behavior (cli/cli#5422): PATCHing a
        # draft without tag_name can replace its tag with an untagged-* value.
        if release["draft"] and "tag_name" not in fields:
            release["tag_name"] = "untagged-test-placeholder"
        release.update(fields)
        save()
        if fields.get("draft") is False and state.get("publish_response_lost"):
            fail("simulated lost publish response")
    else:
        if state.get("external_publish"):
            release["draft"] = False
            save()
        tsv([release["html_url"], release["draft"], release["prerelease"], release["tag_name"]])
else:
    fail("unhandled test API endpoint: " + path)
