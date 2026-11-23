# bg-pos-price-checker-release
BiG Price Checker 正式包发布仓库

## 公开发布说明约束

发布说明只写用户可感知的功能、修复、已知限制和必要升级注意事项。可以保留版本号、构建号、安装包文件名、公开下载链接、大小及安装包 SHA-256；安装包校验值不属于源码提交 ID。

禁止包含业务服务器域名、IP、端口、内网地址、连接串、账号密码、Token、密钥；禁止包含私有源码仓库链接及源码提交 ID；禁止包含 CI 运行编号、runner 状态、构建机磁盘占用、测试失败日志和内部排障细节。内部验证记录保存在私有开发记录中，不得把未验收改写为已通过。

`release.sh` 在登录 GitHub、输出预览或修改远程之前，对最终说明运行 `scripts/validate-release-notes.py`。不合规时直接停止，诊断只显示行号和类别，不回显原文。草稿、续传和预览同样受此约束。单独编辑历史 Release 正文前也必须检查：

```bash
python3 scripts/validate-release-notes.py release-notes.md
```

自动检查覆盖常见禁项，发布人仍须人工核对语义、升级限制及未知格式的敏感内容；校验器不会自动删除或改写说明。

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

新版查价机检查更新不调用 GitHub REST API，也不读取 AIO 目录。AIO 应用管理和旧版查价机仍长期依赖 `bg-pos-aio-release/application/application-catalog.json`，因此每次正式发布都必须同步该文件；这不是仅在迁移期间执行的步骤。

### 每次正式发布同步 AIO 应用目录

正式 Release 的两个附件校验通过后，`release.sh` 自动执行 `scripts/sync-aio-catalog.py`，将同一份 `update.json` 的 `version`、`versionCode`、`packageUrl`、`sha256` 和 `size` 提交到 `B-G-HITECH-S-L/bg-pos-aio-release` 的 `main`，文件路径固定为 `application/application-catalog.json`。应用名称、多语言名称、图标、其他配置及其他应用记录保持原值。

同步工具重新确认源版本为 Latest 正式版，核对已发布 APK 和更新附件的大小及 SHA-256。通过 GitHub Contents API 携带原文件 blob SHA 创建提交，目录并发变更会报错，不覆盖他人的修改。相同信息重复执行不产生新提交；更高构建号、同构建号但信息冲突、缺失或重复条目均会阻止更新。

`--draft` 不修改 AIO 目录，也不要求 AIO 写权限。正式发布和默认 `--dry-run` 预览会提前检查两个仓库的写权限。目录同步失败时，已发布的 Release 保留，但脚本返回失败，不报告发布全部完成；修复权限或并发冲突后单独重试：

```bash
# 只读预览已发布版本对应的目录更新
python3 scripts/sync-aio-catalog.py v0.1.23 --dry-run

# 读取并验证正式 Release 附件，再提交目录；不重建、不重发 APK
python3 scripts/sync-aio-catalog.py v0.1.23
```

独立同步命令只需要 Python 和已登录的 `gh`，不依赖本地 APK、Android SDK 或 AIO 仓库 checkout。若本地已有 AIO checkout，远程同步后可在工作区无冲突时执行 `git pull --ff-only` 获取提交。

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
- GitHub.com 当前登录账号具备本发布仓库及 `B-G-HITECH-S-L/bg-pos-aio-release` 的写入权限；只准备草稿时仅需本仓库写权限。

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
正式发布还会提交同步 AIO 应用目录，全部成功后输出 Release 地址、两个附件的下载地址及 APK SHA-256。

## 重复执行与失败恢复

| 情况 | 处理方式 |
| --- | --- |
| 版本不存在 | 创建草稿、上传校验，再按参数发布或保留草稿 |
| 已有同版本草稿 | 必须显式添加 `--resume`，预览同样如此 |
| 草稿没有附件 | 上传 APK 和生成的 `update.json`，全部校验后发布 |
| 草稿只有 APK 或 `update.json`，内容与本地一致 | 复用已校验附件，仅补传缺失附件 |
| 草稿两个附件均与本地一致 | 全部复用，不重复上传 |
| 草稿任一附件内容或下载地址不同、上传未完成，或存在重复 / 额外附件 | 停止，需人工核对，不自动覆盖或删除 |
| 同版本已正式发布 | 发布命令停止；若只需补同步目录，使用独立同步命令 |
| Release 已发布但目录同步失败 | 返回失败，保留 Release；修复后独立重试目录同步，避免重复发包 |
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
[Latest 附件链接规则](https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases)、
[目录提交与 blob SHA](https://docs.github.com/en/rest/repos/contents#create-or-update-file-contents)。
