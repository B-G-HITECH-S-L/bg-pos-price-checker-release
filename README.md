# bg-pos-price-checker-release
BiG Price Checker 正式包发布仓库

## 准备发布文件

在源码项目中准备好已签名的正式 APK，并确认包内版本与要发布的版本一致。
将 APK 和本次发布说明放入本仓库的版本目录：

```text
dist/
└── v0.0.1/
    ├── big-price-checker.apk
    └── release-notes.md
```

- 版本号格式为 `v主版本.次版本.修订版本`，例如 `v0.0.1`；各部分不允许前导零。
- 目录中必须恰好有一个非空的 `.apk` 普通文件，以及非空的 `release-notes.md`。
- `release-notes.md` 只作为 Release 正文，不上传为附件；其他本地文件不会上传。
- `/dist/` 已被 Git 忽略，APK 和发布说明都保留在本机。脚本和本文档纳入 Git 管理。
- 推荐使用 `big-price-checker.apk` 这种简单的附件名。脚本不改本地文件名，但 GitHub
  可能规范化上传名称中的空格或特殊字符，最终以脚本输出的远程附件名、下载地址为准。
  路径中的 `#`、换行和制表符不受支持。

脚本检查 ZIP 完整性及根目录 `AndroidManifest.xml`，计算 SHA-256；这些检查不验证
Android 签名、包内版本号或真机安装行为，正式 APK 仍需先完成对应验收。

## 环境要求

- Bash 3.2 或以上（兼容 macOS 自带 Bash）。
- GitHub CLI `gh`，以及系统工具 `git`、`unzip`、`shasum` 等。
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
# 先预览：校验本地输入并联网读取远程状态，不修改远程
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

新版本以运行时远程 `main` 的提交作为目标，先创建草稿，上传并校验 APK 后再正式发布。
若同名标签已经存在，只有它指向该提交时才允许创建 Release；脚本不会移动标签。
续传已有草稿时保留其目标和标签，标题与正文使用本次版本号及本地 `release-notes.md`。
成功后输出 Release 地址、实际附件名、下载地址及 SHA-256。

## 重复执行与失败恢复

| 情况 | 处理方式 |
| --- | --- |
| 版本不存在 | 创建草稿、上传校验，再按参数发布或保留草稿 |
| 已有同版本草稿 | 必须显式添加 `--resume`，预览同样如此 |
| 草稿没有附件 | 上传本地 APK |
| 草稿只有一个 APK，内容与本地一致 | 校验后复用；以远程实际名称为准 |
| 草稿 APK 内容不同、上传未完成，或存在非 APK / 多个附件 | 停止，需人工核对，不自动覆盖或删除 |
| 同版本已正式发布 | 停止并输出已有 Release 地址 |
| 登录、权限或远程查询失败 | 报错，不把失败当成版本不存在 |
| 上传、更新说明或发布请求失败 | 报告失败阶段，保留已完成的远程操作，提示恢复方式 |

内容校验优先使用 GitHub 返回的 SHA-256；旧附件没有此值时，下载到本地临时目录计算后比较。
发布请求可能已经成功但响应丢失；重试前先检查 GitHub。若已经正式发布，脚本会停止；若仍为草稿，
使用 `--resume` 继续。上传失败也可能留下未完成的附件，需先在草稿页核对并处理，再重试。

脚本退出码为 `0` 表示完成（或预览通过）；非 `0` 表示校验或操作失败。

## 本地验证

```bash
/bin/bash -n scripts/release.sh
python3 -B -m unittest discover -s tests -v
```

测试使用临时版本目录、结构测试用 APK 和模拟的 `gh` / `git`，不会访问或修改真实 GitHub Release。
测试文件都位于被忽略的 `dist/` 下，并在测试结束后清理。

参考：[GitHub CLI](https://cli.github.com/manual/gh_release_create)、
[Release 附件及文件名规则](https://docs.github.com/en/rest/releases/assets)。
