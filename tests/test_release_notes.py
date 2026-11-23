"""公开说明校验覆盖禁项、允许的安装包元信息和日志不回显。"""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate-release-notes.py"
SPEC = importlib.util.spec_from_file_location("release_notes_policy", SCRIPT)
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


class ReleaseNotesPolicyTests(unittest.TestCase):
    def test_user_notes_and_package_metadata_are_allowed(self):
        text = ("# BiG Price Checker v0.1.29\n构建号：30\n"
                "- 修复更新失败提示，测试连接失败时可以重试。\n"
                "- 设备覆盖安装仍需现场验收，磁盘空间不足时暂停录像。\n"
                "文件：big-price-checker.apk、update.json、latest.yml\n"
                "Size: 67238655\nSHA-256: " + "a" * 64 + "\nSHA-512: " + "b" * 128 + "\n"
                "https://github.com/B-G-HITECH-S-L/bg-pos-price-checker-release/releases/download/v0.1.29/big-price-checker.apk\n"
                "https://b-g-hitech-s-l.github.io/bg-pos-aio-release/latest.yml\n")
        self.assertEqual(POLICY.violations(text), [])

    def test_forbidden_content_is_rejected(self):
        cases = [
            "https://license.example/api", "license.example", "192.0.2.1", "[2001:db8::1]", "::1",
            "端口：39001", "Server=database.example;Password=example", "密码：example-value",
            "https://github.com/example/private-source/commit/" + "a" * 40,
            "源码提交：1234567", "1cd4da1", "a" * 40,
            "CI 运行编号 12345", "runner 离线", "run 123456789 queued", "GITHUB_RUN_ID=12345",
            "本机磁盘空间不足", "C 盘 85%", "%TEMP% 夹具", "/Users/example/work/app.py",
            "测试 13 例失败", "测试假红", "tests failed", "npm test 失败",
            "-----BEGIN PRIVATE KEY-----", "ghp_" + "a" * 36,
            "https://license.example/a?token=example", "https%3A%2F%2Flicense.example",
            "https://github.com/B-G-HITECH-S-L/bg-pos-aio-release/releases/download/v-0.2.0/file.exe?token=example",
        ]
        for text in cases:
            with self.subTest(text=text[:24]):
                self.assertTrue(POLICY.violations(text))

    def test_cli_fails_without_echoing_sensitive_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.md"
            secret = "example-sensitive-value"
            path.write_text("token=" + secret, encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(secret, result.stdout + result.stderr)
            self.assertIn("第 1 行", result.stderr)

    def test_missing_or_blank_file_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.md"
            for exists in (False, True):
                if exists:
                    path.write_text("  \n", encoding="utf-8")
                result = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True)
                self.assertNotEqual(result.returncode, 0)

    def test_user_notes_and_package_hash_are_allowed(self):
        text = "# BiG Price Checker v1.2.3\n\n- 修复下载失败后无法重试的问题。\n- 旧设备仍需安装验收。\n- 文件名: big-price-checker.apk\n- SHA-256: " + "a" * 64 + "\n- Size: 67238655\nhttps://github.com/B-G-HITECH-S-L/bg-pos-price-checker-release/releases/download/v1.2.3/big-price-checker.apk\n"
        self.assertEqual(POLICY.violations(text), [])

    def test_tag_mode_never_publishes_lightweight_commit_message(self):
        with tempfile.TemporaryDirectory() as directory:
            def git(*args):
                subprocess.run(["git", *args], cwd=directory, check=True, capture_output=True)
            git("init", "-q")
            git("config", "user.name", "Release Test")
            git("config", "user.email", "test@example.invalid")
            git("config", "commit.gpgsign", "false")
            git("config", "tag.gpgsign", "false")
            git("commit", "--allow-empty", "-qm", "CI runner offline; internal failure")
            git("tag", "v-1.2.3")
            git("tag", "-a", "v-1.2.4", "-m", "- 修复商品查询。")
            git("tag", "-a", "v-1.2.5", "-m", "地址 https://example.invalid")
            for tag, valid in [("v-1.2.3", True), ("v-1.2.4", True), ("v-1.2.5", False)]:
                path = Path(directory) / (tag + ".md")
                result = subprocess.run([sys.executable, str(SCRIPT), "--tag", tag, "--product", "BiG AIO", "--output", str(path)], cwd=directory, capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, valid, result.stderr)
                self.assertEqual(path.exists(), valid)
                if valid:
                    self.assertNotIn("runner", path.read_text())
                else:
                    self.assertNotIn("example.invalid", result.stderr)


if __name__ == "__main__":
    unittest.main()
