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
        shutil.copy2(ROOT / "scripts/generate-update-manifest.py", self.root / "scripts/generate-update-manifest.py")
        self.apk = self.version_dir / "big-price-checker.apk"
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
        aapt = fake_bin / "aapt"
        default_badging = "package: name='com.byghitech.bg_pos_price_checker' versionCode='7' versionName='0.0.1'"
        aapt.write_text("#!" + sys.executable + "\nimport os,sys\n"
                        "assert sys.argv[1:3] == ['dump', 'badging']\n"
                        f"print(os.environ.get('RELEASE_TEST_BADGING', {default_badging!r}))\n")
        aapt.chmod(0o755)
        self.env = dict(os.environ, AAPT_BIN=str(aapt), PATH=str(fake_bin) + os.pathsep + os.environ["PATH"],
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

    def assert_package_info(self, content, data=None):
        data = self.apk_bytes if data is None else data
        self.assertEqual(content.count("<!-- release-package-info:start -->"), 1)
        self.assertEqual(content.count("<!-- release-package-info:end -->"), 1)
        self.assertIn("- 文件名: " + self.apk.name, content)
        self.assertIn("- SHA-256: " + hashlib.sha256(data).hexdigest(), content)
        self.assertIn("- Size: " + str(len(data)) + "\n", content)

    def draft(self, assets=None):
        self.state["releases"] = [{"id": 1, "tag_name": "v0.0.1", "draft": True, "prerelease": False,
                                   "html_url": "https://github.com/example/releases/tag/v0.0.1",
                                   "target_commitish": "main", "assets": assets or []}]
        self.write_state()

    def asset(self, data=None, name="big-price-checker.apk"):
        data = self.apk_bytes if data is None else data
        return {"id": 12 if name == "update.json" else 11, "name": name, "size": len(data), "state": "uploaded",
                "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                "data": base64.b64encode(data).decode(), "browser_download_url": f"https://github.com/{REPO}/releases/download/v0.0.1/{name}"}

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
        self.notes.unlink()
        self.assert_failure(self.run_release("--dry-run"), ".textClipping 不是 APK")
        self.assertFalse(self.notes.exists())
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

    def test_missing_notes_are_created(self):
        self.notes.unlink()
        self.assert_success(self.run_release("--draft"))
        content = self.notes.read_text()
        self.assertTrue(content.startswith("# BiG Price Checker v0.0.1\n"))
        self.assert_package_info(content)
        self.assertEqual(self.read_state()["releases"][0]["body"], content)

    def test_blank_notes_are_completed(self):
        for initial in ("", " \n\t"):
            with self.subTest(initial=initial):
                self.state["releases"] = []
                self.write_state()
                self.notes.write_text(initial)
                self.assert_success(self.run_release("--draft"))
                self.assertTrue(self.notes.read_text().startswith("# BiG Price Checker v0.0.1\n"))
                self.assert_package_info(self.notes.read_text())

    def test_notes_symlink_and_directory_are_rejected(self):
        target = self.root / "other-notes.md"
        target.write_text("keep this content")
        self.notes.unlink()
        self.notes.symlink_to(target)
        self.assert_failure(self.run_release(), "不能是目录或符号链接")
        self.assertEqual(target.read_text(), "keep this content")
        self.notes.unlink()
        self.notes.mkdir()
        self.assert_failure(self.run_release(), "不能是目录或符号链接")
        self.assertEqual(self.calls(), [])

    def test_invalid_notes_markers_do_not_overwrite_manual_content(self):
        start = "<!-- release-package-info:start -->\n"
        end = "<!-- release-package-info:end -->\n"
        for markers in (start, end, start + start + end, start + end + start + end):
            with self.subTest(markers=markers):
                original = "手写正文\n" + markers + "保留结尾\n"
                self.notes.write_text(original)
                self.assert_failure(self.run_release(), "自动区块标记不完整或重复")
                self.assertEqual(self.notes.read_text(), original)
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
        original_notes = self.notes.read_bytes()
        result = self.run_release("--dry-run")
        self.assert_success(result)
        self.assertIn(self.sha, result.stdout)
        self.assertIn("未修改远程", result.stdout)
        self.assertFalse((self.version_dir / "update.json").exists())
        self.assertIn("update.json 预览", result.stdout)
        self.assert_package_info(result.stdout)
        self.assertEqual(self.notes.read_bytes(), original_notes)
        self.assertEqual(self.mutations(), [])
        self.assertEqual(self.state_path.read_text(), before)

    def test_dry_run_does_not_create_missing_notes(self):
        self.notes.unlink()
        result = self.run_release("--dry-run")
        self.assert_success(result)
        self.assertIn("# BiG Price Checker v0.0.1", result.stdout)
        self.assert_package_info(result.stdout)
        self.assertFalse(self.notes.exists())
        self.assertEqual(self.mutations(), [])

    def test_dry_run_does_not_replace_blank_notes(self):
        self.notes.write_bytes(b" \r\n\t")
        result = self.run_release("--dry-run")
        self.assert_success(result)
        self.assert_package_info(result.stdout)
        self.assertEqual(self.notes.read_bytes(), b" \r\n\t")
        self.assertEqual(self.mutations(), [])

    def test_publish_from_remote_main(self):
        result = self.run_release()
        self.assert_success(result)
        release = self.read_state()["releases"][0]
        self.assertFalse(release["draft"])
        self.assertFalse(release["prerelease"])
        self.assertEqual(release["make_latest"], "true")
        self.assertEqual(release["target_commitish"], "a" * 40)
        self.assertEqual(release["body"], self.notes.read_text())
        self.assert_package_info(release["body"])
        self.assertEqual(release["assets"][0]["digest"], "sha256:" + self.sha)
        self.assertIn("big-price-checker.apk", result.stdout)
        self.assertEqual(self.apk.read_bytes(), self.apk_bytes)

    def test_draft_then_resume_reuses_same_content(self):
        self.assert_success(self.run_release("--draft"))
        self.assertTrue(self.read_state()["releases"][0]["draft"])
        self.assert_success(self.run_release("--resume", "--dry-run"))
        self.assertTrue(self.read_state()["releases"][0]["draft"])
        self.assert_success(self.run_release("--resume"))
        self.assertFalse(self.read_state()["releases"][0]["draft"])
        self.assertEqual(sum(args[:2] == ["release", "upload"] for args in self.calls()), 2)

    def test_draft_metadata_edits_preserve_requested_tag(self):
        self.assert_success(self.run_release("--draft"))
        self.assertEqual(self.read_state()["releases"][0]["tag_name"], "v0.0.1")
        self.notes.write_text(self.notes.read_text() + "\n本次追加发布说明。\n")
        self.assert_success(self.run_release("--resume"))
        release = self.read_state()["releases"][0]
        self.assertEqual(release["tag_name"], "v0.0.1")
        self.assertFalse(release["draft"])

    def test_notes_block_updated_in_place_and_idempotent(self):
        prefix = "手写说明，保留 `代码`、$(literal) 和 $变量。\n\n"
        suffix = "\n补充说明保留在原位置。\n"
        self.notes.write_text(prefix + "<!-- release-package-info:start -->\n"
                              "old package metadata\n<!-- release-package-info:end -->\n" + suffix)
        self.assert_success(self.run_release("--draft"))
        first = self.notes.read_text()
        self.assertTrue(first.startswith(prefix))
        self.assertTrue(first.endswith(suffix))
        self.assertNotIn("old package metadata", first)
        self.assert_package_info(first)
        first_mtime = self.notes.stat().st_mtime_ns
        self.assert_success(self.run_release("--resume", "--draft"))
        self.assertEqual(self.notes.read_text(), first)
        self.assertEqual(self.notes.stat().st_mtime_ns, first_mtime)
        self.assertEqual(self.read_state()["releases"][0]["body"], first)

    def test_manual_crlf_notes_without_final_newline_preserved(self):
        original = "手写说明\r\n\r\nlast line".encode()
        self.notes.write_bytes(original)
        self.assert_success(self.run_release("--draft"))
        self.assertTrue(self.notes.read_bytes().startswith(original))
        self.assert_package_info(self.notes.read_text())

    def test_rebuilt_apk_refreshes_size_and_hash(self):
        self.assert_success(self.run_release("--draft"))
        with zipfile.ZipFile(self.apk, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"a new fixture manifest")
            archive.writestr("classes.dex", b"a different and longer build")
        # A fresh test remote permits the rebuilt package; conflicting real drafts
        # remain rejected by the existing asset checks.
        self.state["releases"] = []
        self.write_state()
        self.assert_success(self.run_release("--draft"))
        content = self.notes.read_text()
        self.assert_package_info(content, self.apk.read_bytes())
        self.assertNotIn(self.sha, content)
        self.assertEqual(self.read_state()["releases"][0]["body"], content)

    def test_notes_edited_during_preflight_are_not_overwritten(self):
        self.state["change_notes_during_preflight"] = str(self.notes)
        self.write_state()
        self.assert_failure(self.run_release(), "发布说明在执行期间发生变化")
        self.assertEqual(self.notes.read_text(), "a new handwritten note\n")
        self.assertEqual(self.mutations(), [])

    def test_notes_created_during_preflight_are_not_overwritten(self):
        self.notes.unlink()
        self.state["change_notes_during_preflight"] = str(self.notes)
        self.write_state()
        self.assert_failure(self.run_release(), "出现新的发布说明")
        self.assertEqual(self.notes.read_text(), "a new handwritten note\n")
        self.assertEqual(self.mutations(), [])

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
        self.assertEqual(len(self.state["releases"][0]["assets"]), 2)

    def test_published_version_stops(self):
        self.draft()
        self.state["releases"][0]["draft"] = False
        self.write_state()
        self.assert_failure(self.run_release("--resume"), "同版本已正式发布")
        self.assertEqual(self.mutations(), [])

    def test_same_size_different_content_stops(self):
        data = self.apk_bytes[:-1] + bytes([self.apk_bytes[-1] ^ 1])
        self.draft([self.asset(data)])
        self.assert_failure(self.run_release("--resume"), "远程附件内容与本地 big-price-checker.apk 不同")
        self.assertEqual(self.mutations(), [])

    def test_conflicting_draft_assets_stop(self):
        scenarios = [([self.asset(), dict(self.asset(), id=12)], "多个附件"),
                     ([dict(self.asset(), name="app.apk.textClipping")], "不支持的附件"),
                     ([dict(self.asset(), state="starter")], "未完整上传"),
                     ([dict(self.asset(), size=0)], "大小与本地不同")]
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
        uploads = [args for args in self.calls() if args[:2] == ["release", "upload"]]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(Path(uploads[0][3]).name, "update.json")

    def test_api_failure_never_creates_version(self):
        self.state["query_failure"] = True
        self.write_state()
        original_notes = self.notes.read_bytes()
        self.assert_failure(self.run_release(), "不能将查询错误当作版本不存在")
        self.assertEqual(self.notes.read_bytes(), original_notes)
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
        self.assert_failure(self.run_release(), "内容与本地 big-price-checker.apk 不同")
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


    def manifest_bytes(self):
        document = {"schemaVersion": 2, "applications": [{
            "id": "com.byghitech.bg_pos_price_checker", "platform": "android",
            "version": "0.0.1", "versionCode": 7, "packageFileName": "big-price-checker.apk",
            "packageUrl": f"https://github.com/{REPO}/releases/download/v0.0.1/big-price-checker.apk",
            "sha256": self.sha, "size": len(self.apk_bytes),
        }]}
        return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()

    def test_update_manifest_and_apk_are_verified_before_publication(self):
        self.assert_success(self.run_release())
        release = self.read_state()["releases"][0]
        self.assertEqual([asset["name"] for asset in release["assets"]], ["big-price-checker.apk", "update.json"])
        remote_manifest = base64.b64decode(release["assets"][1]["data"])
        self.assertEqual(remote_manifest, self.manifest_bytes())
        self.assertEqual((self.version_dir / "update.json").read_bytes(), remote_manifest)
        self.assertFalse(release["draft"])
        # The build number comes from the APK, not tag arithmetic (0.0.1 -> 7).
        self.assertEqual(json.loads(remote_manifest)["applications"][0]["versionCode"], 7)

    def test_invalid_apk_identity_never_contacts_github(self):
        fields = ("name='other.package' versionCode='7' versionName='0.0.1'",
                  "name='com.byghitech.bg_pos_price_checker' versionCode='7' versionName='0.0.2'",
                  "name='com.byghitech.bg_pos_price_checker' versionCode='0' versionName='0.0.1'",
                  "name='com.byghitech.bg_pos_price_checker' versionCode='2100000001' versionName='0.0.1'",
                  "name='com.byghitech.bg_pos_price_checker' versionCode='7.5' versionName='0.0.1'",
                  "name='com.byghitech.bg_pos_price_checker' versionCode='7' versionName='0.0.1'\napplication-debuggable",
                  "malformed output")
        for fields_value in fields:
            with self.subTest(badging=fields_value):
                self.env["RELEASE_TEST_BADGING"] = "package: " + fields_value
                self.assert_failure(self.run_release(), "生成 update.json 失败")
                self.assertFalse((self.version_dir / "update.json").exists())
        self.assertEqual(self.calls(), [])

    def test_missing_aapt_never_contacts_github(self):
        self.env["AAPT_BIN"] = str(self.root / "missing-aapt")
        self.assert_failure(self.run_release(), "生成 update.json 失败")
        self.assertEqual(self.calls(), [])

    def test_wrong_apk_filename_is_rejected(self):
        self.apk.rename(self.version_dir / "another.apk")
        self.assert_failure(self.run_release(), "文件名必须为 big-price-checker.apk")
        self.assertEqual(self.calls(), [])

    def test_manifest_symlink_and_directory_are_rejected(self):
        manifest = self.version_dir / "update.json"
        target = self.root / "keep.json"
        target.write_text("keep")
        manifest.symlink_to(target)
        self.assert_failure(self.run_release(), "update.json 必须是普通文件")
        self.assertEqual(target.read_text(), "keep")
        manifest.unlink()
        manifest.mkdir()
        self.assert_failure(self.run_release(), "update.json 必须是普通文件")
        self.assertEqual(self.calls(), [])

    def test_dry_run_does_not_replace_stale_manifest(self):
        manifest = self.version_dir / "update.json"
        manifest.write_text("old generated metadata")
        self.assert_success(self.run_release("--dry-run"))
        self.assertEqual(manifest.read_text(), "old generated metadata")
        self.assertEqual(self.mutations(), [])

    def test_manifest_edited_during_preflight_is_not_overwritten(self):
        manifest = self.version_dir / "update.json"
        manifest.write_bytes(self.manifest_bytes())
        self.state["change_manifest_during_preflight"] = str(manifest)
        self.write_state()
        self.assert_failure(self.run_release(), "update.json 在执行期间发生变化")
        self.assertEqual(manifest.read_text(), "concurrent edit\n")
        self.assertEqual(self.mutations(), [])

    def test_partial_apk_upload_resumes_only_missing_manifest(self):
        self.state["upload_failure"] = "update.json"
        self.write_state()
        self.assert_failure(self.run_release(), "update.json 上传失败")
        release = self.read_state()["releases"][0]
        self.assertTrue(release["draft"])
        self.assertEqual([a["name"] for a in release["assets"]], ["big-price-checker.apk"])
        self.state.pop("upload_failure")
        self.write_state()
        self.assert_success(self.run_release("--resume"))
        self.assertFalse(self.read_state()["releases"][0]["draft"])
        apk_uploads = [a for a in self.calls() if a[:2] == ["release", "upload"] and Path(a[3]).name.endswith(".apk")]
        self.assertEqual(len(apk_uploads), 1)

    def test_partial_manifest_upload_resumes_only_missing_apk(self):
        self.draft([self.asset(self.manifest_bytes(), name="update.json")])
        self.assert_success(self.run_release("--resume"))
        uploads = [a for a in self.calls() if a[:2] == ["release", "upload"]]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(Path(uploads[0][3]).name, "big-price-checker.apk")

    def test_conflicting_remote_manifest_stops_without_overwriting(self):
        manifest = self.manifest_bytes().replace(b'"versionCode": 7', b'"versionCode": 8')
        self.draft([self.asset(), self.asset(manifest, name="update.json")])
        self.assert_failure(self.run_release("--resume"), "内容与本地 update.json 不同")
        self.assertEqual(self.mutations(), [])

    def test_corrupted_or_missing_manifest_is_never_published(self):
        for key in ("corrupt_upload", "skip_upload"):
            with self.subTest(failure=key):
                self.state = {"main_sha": "a" * 40, "releases": [], key: "update.json"}
                self.write_state()
                result = self.run_release()
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertTrue(self.read_state()["releases"][0]["draft"])

    def test_manifest_without_digest_is_downloaded_and_verified(self):
        asset = self.asset(self.manifest_bytes(), name="update.json")
        asset.pop("digest")
        self.draft([self.asset(), asset])
        self.assert_success(self.run_release("--resume"))
        self.assertTrue(any(a[:2] == ["api", "--hostname"] and "Accept: application/octet-stream" in a for a in self.calls()))
        self.assertFalse(any(a[:2] == ["release", "upload"] for a in self.calls()))

    def test_manifest_with_wrong_download_address_is_not_published(self):
        asset = self.asset(self.manifest_bytes(), name="update.json")
        asset["browser_download_url"] = "https://github.com/other/releases/download/v0.0.1/update.json"
        self.draft([self.asset(), asset])
        self.assert_failure(self.run_release("--resume"), "版本下载地址不一致")
        self.assertEqual(self.mutations(), [])

    def test_duplicate_manifest_or_unexpected_third_asset_is_rejected(self):
        manifest = self.asset(self.manifest_bytes(), name="update.json")
        for assets in ([manifest, dict(manifest, id=13)],
                       [self.asset(), manifest, self.asset(b"symbols", name="debug.symbols")]):
            self.draft(assets)
            self.assertNotEqual(self.run_release("--resume").returncode, 0)
        self.assertEqual(self.mutations(), [])


if __name__ == "__main__":
    unittest.main()
