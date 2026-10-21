# DCNC-DAG GitHub 发布教程

本教程把已核验的正式 release 包发布为一个可浏览源码、下载数据、运行
自动检查的 GitHub 仓库，并创建 `v0.1.1` Release。准备包不等于自动上传：
下面的建仓、提交、推送及发布操作由仓库所有者执行。

## 1. 确认使用的是正式包

在维护目录 `open_source_release` 下，正式交付文件放在
`dist/github-release-v0.1.1/`：

```text
github-release-v0.1.1/
  dcnc-dag-reproducibility-0.1.1.zip
  dcnc-dag-reproducibility-0.1.1.zip.sha256
  dcnc-dag-reproducibility-0.1.1.zip.json
  source/
    dcnc-dag-reproducibility-0.1.1/
      README.md
      LICENSE
      .github/
      src/
      scripts/
      evidence/
      ...
```

ZIP 是供 Release 附件下载的包，`source` 中的内层目录是供 Git 提交的
干净源码。仓库根目录必须直接看到 `README.md`、`LICENSE`、`src/`
和 `.github/`，不能再套一层 `source/` 或只上传一个 ZIP。

不要使用任何文件名包含 `candidate` 的旧包。不要上传维护目录本身、
整个论文工作目录或旧 `.git` 历史。正式包不含个人凭证、Gurobi 许可证、
运行环境缓存、审稿材料和完整论文工程；仅保留与数值核验有关的论文片段。

可以在交付文件所在目录执行下面的 PowerShell 检查：

```powershell
Get-FileHash .\dcnc-dag-reproducibility-0.1.1.zip -Algorithm SHA256
Get-Content .\dcnc-dag-reproducibility-0.1.1.zip.sha256
Get-Content .\dcnc-dag-reproducibility-0.1.1.zip.json
```

两处 SHA-256 应一致，JSON 中应为 `candidate: false`、
`strict_release_gate: true`。无需安装 Gurobi，也无需重跑整套实验才能上传。

## 2. 在 GitHub 建立空仓库

登录自己的 GitHub 账号，点击右上角 **+ → New repository**：

- Repository name：建议 `dcnc-dag-reproducibility`。
- Description：`Simulator, experiment data, and reproducibility tools for DCNC-DAG.`
- Visibility：建议先 **Private**，等 GitHub Actions 通过后再改为 **Public**。
- 不勾选生成 README，不添加 `.gitignore`，不另选许可证。
- 点击 **Create repository**，记录仓库的 HTTPS 地址。

本包已有 MIT `LICENSE`、README 和 `.gitignore`，不要让网页自动生成文件
与它们冲突。公开前也应确认作者、所在机构、资助协议及投稿规则允许实名
公开代码和数据；若仍处于双盲评审阶段，先核对期刊要求。

## 3. 用 Git 上传干净源码

先安装 Git for Windows，重新打开 PowerShell，以 `git --version` 检查。
下面命令从维护目录 `open_source_release` 开始执行；如果已经把交付包移到
其他位置，直接进入解压后包含 `README.md` 的内层目录即可。

```powershell
Set-Location .\dist\github-release-v0.1.1\source\dcnc-dag-reproducibility-0.1.1
Test-Path .\README.md
Test-Path .\LICENSE
Test-Path .\.github\workflows\artifact-integrity.yml
git init -b main
git add .
git status --short
git diff --cached --stat
```

三个 `Test-Path` 都应返回 `True`。检查暂存区含源码、证据数据和文档，
不含 `.runtime/`、虚拟环境、工作结果目录、私钥或许可证密钥。
包内有两千余个文件，不要使用浏览器逐个拖放上传，容易遗漏隐藏文件或
超过单次上传限制。当前单个文件均小于 GitHub 的 100 MiB 限制，无需 Git LFS。

确认后提交并推送。把 `YOUR_NAME` 改成自己的 GitHub 账号或组织名；
如果仓库名称不同，也要同步修改 URL。

```powershell
git commit -m "Release DCNC-DAG reproducibility artifact 0.1.1"
git remote add origin https://github.com/YOUR_NAME/dcnc-dag-reproducibility.git
git push -u origin main
```

首次提交若提示身份未配置，在这个新仓库中设置自己的 `user.name` 和
`user.email` 后重试；可使用 GitHub 提供的 noreply 邮箱。不要修改为论文中
其他作者的身份。首次推送通常会打开 Git Credential Manager 登录界面，
按提示登录即可；不要把访问令牌写入 URL、脚本、README 或发到聊天中。

## 4. 检查 GitHub Actions

打开仓库的 **Actions → Artifact integrity**，等待 `main` 对应的检查完成。
工作流检查文件哈希、第三方声明、原始数据与论文数值、回归测试、Python
编译和 shell 语法，并对生成的包做干净解压、wheel 构建与安装验证。

本地检查通过不代表托管 Actions 已经执行。只有看到该次运行的绿色成功
标记，才能认为 GitHub 上的副本也通过了检查。

若失败，点开红色步骤查看日志，不要通过删掉验证步骤解决：

- `hash mismatch`：文件可能被编辑、漏传或转换换行；优先恢复交付包中的
  对应字节。确有必要的修改必须复核后更新清单并重新构建，不能盲目刷新哈希。
- `unmanifested`：仓库多出了未登记文件，常见于网页自动生成 README 或
  上传了无关资料。返回干净源码目录检查。
- 依赖下载或网络错误：检查日志后重试对应工作流，不改实验数值。
- `refusing to archive a dirty worktree`：构建前还有未提交的源码变化；
  检查产生变化的步骤，不能简单禁用该检查。

工作流只读仓库，不会自动发布 Release，也不需要个人访问令牌。

## 5. 创建版本标签

确认 `main` 检查通过，且本地 `git status --short` 无未提交变化后，在
同一个干净源码仓库执行：

```powershell
git tag -a v0.1.1 -m "DCNC-DAG reproducibility artifact 0.1.1"
git push origin v0.1.1
```

回到 **Actions**，等待标签触发的检查通过。版本标签检查会额外要求
严格发布校验和正式 archive 构建。不要在标签失败时继续点击发布；不要
删除并重建一个已经公开的同名标签，后续修订应使用新版本号。

## 6. 公开仓库并发布 Release

如果最初选择了 Private，在所有检查通过、确认可公开后，通过仓库
**Settings → General → Danger Zone → Change repository visibility** 改为
Public。这里不要误点删除仓库或转移所有权。

进入 **Releases → Draft a new release**：

1. 选择已创建的 `v0.1.1` 标签。
2. Title 填 `DCNC-DAG reproducibility artifact v0.1.1`。
3. 正文复制包内 `RELEASE_NOTES.md` 的内容，并预览相对链接是否正确。
   若 Release 页面不能正确解析相对链接，改为该仓库 `blob/v0.1.1/` 下
   对应文件的完整链接；不要删掉源码核验范围的说明。
4. 将 ZIP、`.zip.sha256`、`.zip.json` 三个文件一并拖到附件区域。
5. 不选 pre-release；核对附件完整后点击 **Publish release**。

GitHub 自动生成的 `Source code (zip)` 和 `Source code (tar.gz)` 可以保留。
它们不一定与我们提供的 ZIP 具有相同压缩字节或 SHA-256；附带的校验文件
只对应手动上传的正式 ZIP。交付元数据如写明 `manifest-worktree`，表示
这是经过清单验证的工作树快照，并未虚构一个包含全部内容的既有 Git 提交。

## 7. 发布后自查

用未登录窗口访问仓库和 Release，确认都可公开访问。检查首页能够看到
README、MIT License、引用信息，`evidence/` 数据及 `.github/` 工作流完整。
从 Release 重新下载 ZIP，按第 1 节重新核对 SHA-256。

仓库地址用于论文中的 code/data availability；Release 的 `v0.1.1` 地址
用于引用固定版本。不要将新数据覆盖旧版本附件。未来更新应维护原始证据、
修订版本信息、重新验证并发布 `v0.1.1` 等新版本。

## 8. 本次发布的核验范围

Table 6 的十个时间值和正文 98.8% / 98.1% 降幅与完整 150 次实验一致。
对应的是 `DCNC_DAG_Table6_timing_updated_project.zip` 中的 LaTeX 源码。
尚未核验更新后的编译 PDF，不能把旧 PDF 描述为已经更新。
按所有者决定，不再扩写论文方法说明；release 保留既有计时范围和主机
负载记录，不把这些结果描述成隔离环境下的纯求解器 CPU 时间。

不需要在 GitHub 上传完整论文工程、论文 PDF、Overleaf 设置或 Gurobi。
读者检查数据使用 Python 标准库即可；运行绘图和测试需 README 中的依赖；
完整重跑 DynVMP 实验才需要原有 Python 2 环境和读者自己的 Gurobi 安装许可。
