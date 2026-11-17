# bg-pos-price-checker-release
BiG Price Checker 正式包发布仓库

## 准备发布文件

在源码项目中准备好已签名的正式 APK，并确认包内版本与要发布的版本一致。
将 APK 放入本仓库的版本目录；发布说明可以提前填写，也可以由脚本生成：

```text
dist/
└── v0.0.1/
    ├── big-price-checker.apk
    ├── release-notes.md       # 可选，脚本自动补齐
    └── update.json            # 脚本从实际 APK 自动生成
```

- 版本号格式为 `v主版本.次版本.修订版本`，例如 `v0.0.1`；各部分不允许前导零。
- 目录中必须恰好有一个非空的 `.apk` 普通文件，文件名固定为 `big-price-checker.apk`，与客户端已有校验保持一致。
- `release-notes.md` 缺失、为空或只有空白时，脚本自动生成版本标题和安装包信息。
- `release-notes.md` 只作为 Release 正文；公开附件固定为 `big-price-checker.apk` 和自动生成的 `update.json`，其他本地文件不会上传。
- `/dist/` 已被 Git 忽略，APK、发布说明与更新文件都保留在本机。脚本和本文档纳入 Git 管理。
- APK 包名必须为 `com.byghitech.bg_pos_price_checker`，版本名必须与标签去掉 `v` 后一致，构建号须在 1 至 2100000000 之间；可调试 APK 会被拒绝。

脚本检查 ZIP 完整性及根目录 `AndroidManifest.xml`，使用 Android SDK `aapt dump badging` 读取实际版本，计算 SHA-256；Android 签名与真机安装验收仍须在正式发布前完成。

### 自动生成更新附件

`update.json` 沿用客户端现有格式，示例如下：

```json
{
  "schemaVersion": 2,
  "applications": [
    {
      "id": "com.byghitech.bg_pos_price_checker",
      "platform": "android",
      "version": "0.1.22",
      "versionCode": 23,
      "packageFileName": "big-price-checker.apk",
      "packageUrl": "https://github.com/B-G-HITECH-S-L/bg-pos-price-checker-release/releases/download/v0.1.22/big-price-checker.apk",
      "sha256": "由实际 APK 计算的 64 位 SHA-256",
      "size": 67123379
    }
  ]
}
```

版本与构建号来自包内信息，大小与哈希来自实际上传的 APK 快照，不能通过标签推算构建号。下载地址固定到本次具体版本，不使用 `latest` APK 地址。脚本每次重新生成确定性的内容，复用草稿时也能逐字节校验；不需要手工编辑更新文件。

客户端直接访问：

```text
https://github.com/B-G-HITECH-S-L/bg-pos-price-checker-release/releases/latest/download/update.json
```

客户端检查不调用 GitHub REST API，也不依赖 AIO 仓库。发布脚本仍使用已登录的 `gh` 管理 Release。旧版客户端和 AIO 应用管理仍可能读取 AIO 目录，迁移期间按需保留维护；新入口只改变新版查价机的自更新来源。首次发布使用新入口的客户端时，必须同时提供这两个附件。

### 自动维护安装包信息

脚本基于本次实际上传的 APK 快照计算 SHA-256 和文件大小，并在发布说明中维护以下区块：

```markdown
<!-- release-package-info:start -->
## 安装包信息

- 文件名: big-price-checker.apk
- SHA-256: <本次 APK 的 64 位 SHA-256>
- Size: <本次 APK 的整数形式字节数>
<!-- release-package-info:end -->
```

`Size` 的单位固定为字节，例如 `43461008`，不换算为 KB / MB。
已有人工正文保留；首次追加自动区块，后续运行原位更新，避免重复追加或保留旧的校验数据。
自动区块的标记需要成对且唯一；标记损坏或重复时脚本报错，避免误删正文。

实际发布、保留草稿和续传时，在远程检查通过后、修改远程之前写回本地 `update.json` 与 `release-notes.md`，
发布说明作为 GitHub Release 正文，更新文件作为附件。若后续上传失败，本地文件仍保留。
`--dry-run` 只在终端展示拟生成的说明，不创建或修改版本目录中的说明文件或 `update.json`。

## 环境要求

- Bash 3.2 或以上（兼容 macOS 自带 Bash）。
- GitHub CLI `gh`、Python 3.8 或以上，以及系统工具 `git`、`unzip`、`shasum` 等。
- Android SDK Build Tools 的 `aapt`。可通过 `AAPT_BIN` 指定可执行文件；否则从 PATH、`ANDROID_HOME`、`ANDROID_SDK_ROOT` 或 macOS/Linux 默认 SDK 目录查找。缺失时在访问 GitHub 前报错。
- GitHub.com 当前登录账号具备本仓库写入权限。

macOS 安装并登录：

```bash
brew install gh
gh auth login --hostname github.com --git-protocol ssh --web --skip-ssh-key
gh auth status --active --hostname github.com
```

## 发布命令

在仓库根目录执行：

```bash
# 先预览：校验并展示计划、发布说明，不修改本地说明和远程
./scripts/release.sh v0.0.1 --dry-run

# 上传并发布为正式版，设为 Latest
./scripts/release.sh v0.0.1

# 只上传到草稿
./scripts/release.sh v0.0.1 --draft

# 预览或继续已有的同版本草稿
./scripts/release.sh v0.0.1 --resume --dry-run
./scripts/release.sh v0.0.1 --resume

# 继续草稿，但仍保留为草稿
./scripts/release.sh v0.0.1 --resume --draft
```

脚本根据自身位置定位仓库，从其他工作目录通过脚本的完整路径执行也可以。
它固定操作 `B-G-HITECH-S-L/bg-pos-price-checker-release`，并检查 `origin`，避免发布到其他仓库。
每次执行会在 `dist/` 下建立临时快照，退出时清理，确保上传内容与本次校验内容一致。

新版本以运行时远程 `main` 的提交作为目标，先创建草稿，上传并校验 APK 和 `update.json` 后再正式发布。
若同名标签已经存在，只有它指向该提交时才允许创建 Release；脚本不会移动标签。
续传已有草稿时保留其目标和标签，标题与正文使用本次版本号及更新包信息后的发布说明。
成功后输出 Release 地址、两个附件的下载地址及 APK SHA-256。

## 重复执行与失败恢复

| 情况 | 处理方式 |
| --- | --- |
| 版本不存在 | 创建草稿、上传校验，再按参数发布或保留草稿 |
| 已有同版本草稿 | 必须显式添加 `--resume`，预览同样如此 |
| 草稿没有附件 | 上传 APK 和生成的 `update.json`，全部校验后发布 |
| 草稿只有 APK 或 `update.json`，内容与本地一致 | 复用已校验附件，仅补传缺失附件 |
| 草稿两个附件均与本地一致 | 全部复用，不重复上传 |
| 草稿任一附件内容或下载地址不同、上传未完成，或存在重复 / 额外附件 | 停止，需人工核对，不自动覆盖或删除 |
| 同版本已正式发布 | 停止并输出已有 Release 地址 |
| 登录、权限或远程查询失败 | 报错，不把失败当成版本不存在 |
| 上传、更新说明或发布请求失败 | 报告失败阶段，保留已完成的远程操作，提示恢复方式 |

两个附件均先检查名称、上传状态、字节大小和版本下载地址；仅在草稿阶段允许 GitHub 返回本仓库的 `untagged-<十六进制>` 临时附件地址，正式发布后必须是本次版本的固定地址；内容校验优先使用 GitHub 返回的 SHA-256，没有此值时下载到临时目录计算。APK 或更新文件缺失、损坏均保留草稿，不发布半成品。
发布请求可能已经成功但响应丢失；重试前先检查 GitHub。若已经正式发布，脚本会停止；若仍为草稿，
使用 `--resume` 继续。上传失败也可能留下未完成的附件，需先在草稿页核对并处理，再重试。

脚本退出码为 `0` 表示完成（或预览通过）；非 `0` 表示校验或操作失败。

## 本地验证

```bash
/bin/bash -n scripts/release.sh
python3 -B -m unittest discover -s tests -v
```

测试使用临时版本目录、结构测试用 APK 和模拟的 `gh` / `git` / `aapt`，不会访问或修改真实 GitHub Release。
测试文件都位于被忽略的 `dist/` 下，并在测试结束后清理。

参考：[GitHub CLI](https://cli.github.com/manual/gh_release_create)、
[Release 附件及文件名规则](https://docs.github.com/en/rest/releases/assets)、
[Latest 附件链接规则](https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases)。
