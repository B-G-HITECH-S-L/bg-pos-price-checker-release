"""Release lifecycle regression tests; no real GitHub calls or Git writes."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPO = "B-G-HITECH-S-L/bg-pos-price-checker-release"


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "dist").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix=".release-tests-", dir=ROOT / "dist")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repository with spaces"
        self.version_dir = self.root / "dist/v0.0.1"
        self.version_dir.mkdir(parents=True)
        (self.root / "scripts").mkdir()
        self.script = self.root / "scripts/release.sh"
        shutil.copy2(ROOT / "scripts/release.sh", self.script)
        self.apk = self.version_dir / "BiG Price Checker.apk"
        with zipfile.ZipFile(self.apk, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"fixture manifest")
            archive.writestr("classes.dex", b"fixture bytecode")
        self.apk_bytes = self.apk.read_bytes()
        self.sha = hashlib.sha256(self.apk_bytes).hexdigest()
        self.notes = self.version_dir / "release-notes.md"
        self.notes.write_text("首个版本\n\n- 发布说明中的 `代码` 和 $变量保持原样。\n")
        self.state_path = self.root / "state.json"
        self.calls_path = self.root / "calls.jsonl"
        self.state = {"main_sha": "a" * 40, "releases": []}
        self.write_state()
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        gh = fake_bin / "gh"
        gh.write_text("#!" + sys.executable + "\n" + (ROOT / "tests/fake_gh.py").read_text())
        gh.chmod(0o755)
        git = fake_bin / "git"
        git.write_text('#!/bin/bash\nprintf "%s\\n" "${RELEASE_TEST_ORIGIN:-git@github.com:' + REPO + '.git}"\n')
        git.chmod(0o755)
        self.env = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ["PATH"],
                        RELEASE_TEST_STATE=str(self.state_path), RELEASE_TEST_CALLS=str(self.calls_path),
                        GH_HOST="unrelated.example", GH_REPO="unrelated/repository")

    def write_state(self):
        self.state_path.write_text(json.dumps(self.state))

    def read_state(self):
        self.state = json.loads(self.state_path.read_text())
        return self.state

    def calls(self):
        if not self.calls_path.exists():
            return []
        return [json.loads(line) for line in self.calls_path.read_text().splitlines()]

    def mutations(self):
        return [args for args in self.calls()
                if args[:2] == ["release", "upload"] or
                (args[0] == "api" and "--method" in args and args[args.index("--method") + 1] != "GET")]

    def run_release(self, *flags, version="v0.0.1"):
        # All tests run outside the repository to exercise path independence.
        result = subprocess.run(["/bin/bash", str(self.script), version, *flags],
                                cwd=self.temp.name, env=self.env, capture_output=True, text=True, timeout=15)
        self.assertFalse(list((self.root / "dist").glob(".release-v*")), "temporary snapshot leaked")
        return result

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_failure(self, result, message):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)

    def draft(self, assets=None):
        self.state["releases"] = [{"id": 1, "tag_name": "v0.0.1", "draft": True, "prerelease": False,
                                   "html_url": "https://github.com/example/releases/tag/v0.0.1",
                                   "target_commitish": "main", "assets": assets or []}]
        self.write_state()

    def asset(self, data=None):
        data = self.apk_bytes if data is None else data
        return {"id": 11, "name": "BiG.Price.Checker.apk", "size": len(data), "state": "uploaded",
                "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                "data": base64.b64encode(data).decode(), "browser_download_url": "https://github.com/example/app.apk"}

    def test_invalid_arguments_never_call_github(self):
        for version in ("", "0.0.1", "../v0.0.1", "v00.0.1", "v0.0.1-beta", "v0.0.1;touch x"):
            with self.subTest(version=version):
                self.assert_failure(self.run_release(version=version), "版本号格式")
        self.assert_failure(self.run_release("--unknown"), "未知选项")
        self.assert_failure(self.run_release("v0.0.2"), "只能指定一个")
        self.assertEqual(self.calls(), [])

    def test_help(self):
        self.assert_success(self.run_release(version="--help"))
        self.assertEqual(self.calls(), [])

    def test_text_clipping_is_not_apk(self):
        self.apk.rename(self.version_dir / "app.apk.textClipping")
        self.assert_failure(self.run_release("--dry-run"), ".textClipping 不是 APK")
        self.assertEqual(self.calls(), [])

    def test_multiple_apks(self):
        shutil.copy2(self.apk, self.version_dir / "second.apk")
        self.assert_failure(self.run_release(), "当前找到 2 个")
        self.assertEqual(self.calls(), [])

    def test_invalid_apk_structure(self):
        self.apk.write_text("not a zip")
        self.assert_failure(self.run_release(), "ZIP 完整性检查失败")
        with zipfile.ZipFile(self.apk, "w") as archive:
            archive.writestr("not-a-manifest.txt", "fixture")
        self.assert_failure(self.run_release(), "缺少根目录 AndroidManifest.xml")
        self.apk.write_bytes(b"")
        self.assert_failure(self.run_release(), "非空的普通文件")
        self.assertEqual(self.calls(), [])

    def test_notes_required(self):
        self.notes.write_text(" \n\t")
        self.assert_failure(self.run_release(), "不能只有空白")
        self.notes.unlink()
        self.assert_failure(self.run_release(), "非空的发布说明")
        self.assertEqual(self.calls(), [])

    def test_symlink_apk_rejected(self):
        stored = self.version_dir / "original.zip"
        self.apk.rename(stored)
        self.apk.symlink_to(stored)
        self.assert_failure(self.run_release(), "不能是符号链接")

    def test_wrong_origin_rejected(self):
        self.env["RELEASE_TEST_ORIGIN"] = "git@github.com:other/repository.git"
        self.assert_failure(self.run_release(), "origin 与目标仓库不一致")
        self.assertEqual(self.calls(), [])

    def test_gh_asset_label_character_rejected(self):
        self.apk.rename(self.version_dir / "app#label.apk")
        self.assert_failure(self.run_release(), "路径不能包含 #")
        self.assertEqual(self.calls(), [])

    def test_dry_run_has_no_remote_mutations(self):
        before = self.state_path.read_text()
        result = self.run_release("--dry-run")
        self.assert_success(result)
        self.assertIn(self.sha, result.stdout)
        self.assertIn("未修改远程", result.stdout)
        self.assertEqual(self.mutations(), [])
        self.assertEqual(self.state_path.read_text(), before)

    def test_publish_from_remote_main(self):
        result = self.run_release()
        self.assert_success(result)
        release = self.read_state()["releases"][0]
        self.assertFalse(release["draft"])
        self.assertFalse(release["prerelease"])
        self.assertEqual(release["make_latest"], "true")
        self.assertEqual(release["target_commitish"], "a" * 40)
        self.assertEqual(release["body"], self.notes.read_text())
        self.assertEqual(release["assets"][0]["digest"], "sha256:" + self.sha)
        self.assertIn("BiG.Price.Checker.apk", result.stdout)
        self.assertEqual(self.apk.read_bytes(), self.apk_bytes)

    def test_draft_then_resume_reuses_same_content(self):
        self.assert_success(self.run_release("--draft"))
        self.assertTrue(self.read_state()["releases"][0]["draft"])
        self.assert_success(self.run_release("--resume", "--dry-run"))
        self.assertTrue(self.read_state()["releases"][0]["draft"])
        self.assert_success(self.run_release("--resume"))
        self.assertFalse(self.read_state()["releases"][0]["draft"])
        self.assertEqual(sum(args[:2] == ["release", "upload"] for args in self.calls()), 1)

    def test_source_changes_do_not_change_uploaded_snapshot(self):
        self.state["change_source_on_create"] = str(self.apk)
        self.write_state()
        self.assert_success(self.run_release())
        self.assertNotEqual(self.apk.read_bytes(), self.apk_bytes)
        self.assertEqual(self.read_state()["releases"][0]["assets"][0]["digest"], "sha256:" + self.sha)

    def test_externally_published_draft_is_not_modified(self):
        self.draft()
        self.state["external_publish"] = True
        self.write_state()
        self.assert_failure(self.run_release("--resume"), "停止修改")
        self.assertEqual(self.mutations(), [])

    def test_draft_requires_resume(self):
        self.draft()
        self.assert_failure(self.run_release("--dry-run"), "添加 --resume")
        self.assertEqual(self.mutations(), [])

    def test_resume_requires_existing_draft(self):
        self.assert_failure(self.run_release("--resume"), "没有找到同版本草稿")
        self.assertEqual(self.mutations(), [])

    def test_resume_empty_draft(self):
        self.draft()
        self.assert_success(self.run_release("--resume", "--draft"))
        self.assertTrue(self.read_state()["releases"][0]["draft"])
        self.assertEqual(len(self.state["releases"][0]["assets"]), 1)

    def test_published_version_stops(self):
        self.draft()
        self.state["releases"][0]["draft"] = False
        self.write_state()
        self.assert_failure(self.run_release("--resume"), "同版本已正式发布")
        self.assertEqual(self.mutations(), [])

    def test_same_size_different_content_stops(self):
        data = self.apk_bytes[:-1] + bytes([self.apk_bytes[-1] ^ 1])
        self.draft([self.asset(data)])
        self.assert_failure(self.run_release("--resume"), "远程附件内容与本地 APK 不同")
        self.assertEqual(self.mutations(), [])

    def test_conflicting_draft_assets_stop(self):
        scenarios = [([self.asset(), dict(self.asset(), id=12)], "多个附件"),
                     ([dict(self.asset(), name="app.apk.textClipping")], "非 APK 附件"),
                     ([dict(self.asset(), state="starter")], "未完整上传"),
                     ([dict(self.asset(), size=0)], "大小与本地 APK 不同")]
        for assets, message in scenarios:
            with self.subTest(message=message):
                self.draft(assets)
                self.assert_failure(self.run_release("--resume"), message)
        self.assertEqual(self.mutations(), [])

    def test_legacy_asset_downloaded_and_hashed(self):
        asset = self.asset()
        asset.pop("digest")
        self.draft([asset])
        self.assert_success(self.run_release("--resume", "--draft"))
        self.assertTrue(any("Accept: application/octet-stream" in args for args in self.calls()))
        self.assertFalse(any(args[:2] == ["release", "upload"] for args in self.calls()))

    def test_api_failure_never_creates_version(self):
        self.state["query_failure"] = True
        self.write_state()
        self.assert_failure(self.run_release(), "不能将查询错误当作版本不存在")
        self.assertEqual(self.mutations(), [])

    def test_auth_and_permission_failures(self):
        self.state["auth_failure"] = True
        self.write_state()
        self.assert_failure(self.run_release(), "登录无效")
        self.state.pop("auth_failure")
        self.state["can_push"] = False
        self.write_state()
        self.assert_failure(self.run_release(), "没有目标仓库的写入权限")
        self.assertEqual(self.mutations(), [])

    def test_failed_upload_keeps_draft_and_can_resume(self):
        self.state["upload_failure"] = True
        self.write_state()
        self.assert_failure(self.run_release(), "APK 上传失败")
        self.assertTrue(self.read_state()["releases"][0]["draft"])
        self.state.pop("upload_failure")
        self.write_state()
        self.assert_success(self.run_release("--resume"))

    def test_corrupt_upload_is_never_published(self):
        self.state["corrupt_upload"] = True
        self.write_state()
        self.assert_failure(self.run_release(), "内容与本地 APK 不同")
        self.assertTrue(self.read_state()["releases"][0]["draft"])

    def test_lost_create_response_leaves_recoverable_draft(self):
        self.state["create_response_lost"] = True
        self.write_state()
        self.assert_failure(self.run_release(), "创建草稿失败")
        self.assertTrue(self.read_state()["releases"][0]["draft"])
        self.state.pop("create_response_lost")
        self.write_state()
        self.assert_success(self.run_release("--resume"))

    def test_lost_publish_response_does_not_republish(self):
        self.state["publish_response_lost"] = True
        self.write_state()
        self.assert_failure(self.run_release(), "发布请求失败")
        self.assertFalse(self.read_state()["releases"][0]["draft"])
        before = len(self.mutations())
        self.assert_failure(self.run_release("--resume"), "同版本已正式发布")
        self.assertEqual(len(self.mutations()), before)

    def test_existing_tag_is_not_moved(self):
        self.state["tags"] = {"v0.0.1": "b" * 40}
        self.write_state()
        self.assert_failure(self.run_release(), "不会移动标签")
        self.assertEqual(self.mutations(), [])
        self.state["tags"]["v0.0.1"] = "a" * 40
        self.write_state()
        self.assert_success(self.run_release())


if __name__ == "__main__":
    unittest.main()
