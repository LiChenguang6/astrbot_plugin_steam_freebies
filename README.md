# Steam 喜加一监控 · AstrBot 插件

> **v0.3.2（功能测试版）** · Steam 商店免费活动 + 第三方 Steam Key 赠送 + QQ 推送 + WebUI 控制台 + 可选插件托管 ASF

独立插件，适用于 AstrBot ≥ 4.29.1 / Python ≥ 3.12；支持 AstrBot 的 OneBot（如 NapCat）与 QQ 官方适配器。借鉴 [原项目](https://github.com/LiChenguang6/astrbot_plugin_steam_status_monitor) 的插件面板架构，**不影响该项目**。

**注意**：当前检测来源提供的是免费活动候选，既不能保证每个 Steam 商店 100% 折扣是可永久入库，也不能保证第三方赠送仍有库存。本项目不代替官方活动资格验证。

## 功能

| 模块 | 当前能力 |
| --- | --- |
| Steam 商店 | 搜索 100% 折扣游戏候选；跳转 Steam 官方商店 |
| 第三方 Steam Key | 通过 GamerPower 收集外部 Steam 游戏/Key 赠送活动；附原始领取地址，明确注明第三方来源 |
| QQ 推送 | 新活动按群去重、失败重试，推送 Steam 和第三方活动；可分别关闭两种来源 |
| ASF 领取结果通知 | 向各个绑定群推送**失败**、**ASF 报告成功（待核验）**、**已提交待核验**；独立记录与发送状态 |
| 管理面板 | 深色响应式工作台、活动分类、搜索、ASF 领取历史、扫描错误、QQ群、通知开关 |
| 托管 ASF | 从 ASF 官方 GitHub Release 下载**匹配系统的独立版**、检查 SHA256、安装到插件私有目录、启动/停止、可选择随 AstrBot 启动 |
| Steam 领取 | 对管理员确认的 Free-to-Keep **SubID** 提交 `addlicense`；可手动或在批准后自动尝试；默认禁用自动领取 |

**默认会推送全部发现的 Steam 商店候选和第三方赠送线索。** 第三方赠送并不等于直接 Steam 入库：例如 Alienware Arena 可能需要积分、地区资格或仍有 Steam Key 库存。ASF 的 `addlicense` 只能适用于合适的 Steam 许可证包，**无法自动从第三方网站取得或兑换 Key**。

## 安装插件

1. 在 AstrBot 插件管理中输入此仓库 URL：`https://github.com/LiChenguang6/astrbot_plugin_steam_freebies`，安装依赖并重载插件。
2. 确保 QQ OneBot/NapCat 或 QQ 官方适配器已连接。官方 QQ 主动推送需额外权限、额度。
3. 以 AstrBot 管理员身份在要推送的群发送 `/喜加一绑定`。
4. 在 AstrBot 插件详情页打开 `steam-freebies` 管理页面。可以立即扫描、筛选活动、调整推送来源。

群聊命令：`/喜加一` 查看最近 5 条线索；`/喜加一绑定` 绑定当前群；`/喜加一解绑` 暂停当前群的推送。

## ASF 一键安装与下载加速（无需手动下载 ZIP）

安装这个 AstrBot 插件后，在 **插件详情 → steam-freebies 管理页面 → 内置 ASF**：

1. 「ASF 安装包下载方式」建议保持 **自动加速**（默认）；也可选「只用加速镜像」或「只用 GitHub 官方源」，改动后先点 **保存 ASF 设置**。
2. 点击 **安装 / 更新 ASF**，插件自动识别操作系统和 CPU，下载官方 ASF 安装包，显示当前下载源和收到的 MB；若镜像连接或校验失败，自动尝试下一来源。
3. 安装完毕点击 **启动 ASF**。安装/启动在运行 AstrBot 的服务器上完成；无需先在自己的电脑上下载 ZIP 再上传。

自动加速使用公开的 GH-Proxy（`gh-proxy.org`）与 GHProxy（`ghproxy.net`），随后回退 GitHub 官方下载。这两个加速节点属于**第三方中转**，会接触安装包请求，无法保证速度与可用性；下载内容必须经过 **ASF 官方 SHA256 校验**，校验失败拒绝安装。**只用镜像**模式不再尝试 GitHub 的大文件下载。

校验元数据优先取 ASF 官方 GitHub Release API；如果 GitHub API 不可达，插件内置 ASF **6.3.10.6** 官方发布的各平台 SHA256 和精确版本下载路径作为备用。内置固定版本不会自动更新，恢复官方 API 后将恢复检查最新版。两者都不可验证时则拒绝安装。安装后的 ASF 本体和账号数据位于 AstrBot 私有数据目录，**不会上传到 GitHub，也无需把大型二进制提交到你的源码仓库**。

**注意：** 一键安装 ≠ Steam 账号自动登录。ASF 首次授权仍需你通过本地 ASF-ui/Steam Guard 完成。AstrBot 在 Docker 里时，下载和 ASF 均运行在容器内，IPC 只能从同一容器访问；需保证持久化数据卷。服务器完全无法访问任何镜像或 GitHub 时，网络限制仍然存在，插件无法保证成功下载。

## 插件内置管理 ASF（可选）

**ASF 是在 AstrBot 所在服务器上运行的另一独立进程，不是 Python 库，也不会一起提交到 GitHub 仓库。** 本插件让你从管理页面自动安装/启动/停止它，进程和 Steam 账号配置仍由 ASF 自身维护。

1. 打开 WebUI → **内置 ASF** → 选择下载模式（默认自动加速）→ 点击 **安装 / 更新 ASF**。安装器自动选择官方 Release 或经过 SHA256 校验的加速中转，网络不通可使用固定版本的官方校验清单。
2. 安装完成后点击 **启动 ASF**。运行中不能覆盖安装包；错误与 ASF 本地日志位于 `data/plugin_data/astrbot_plugin_steam_freebies/asf-manager/` 下（实际位置以 AstrBot 数据目录为准）。
3. 可以在面板中填写 **ASF Bot 名称** 和 **Steam 登录名**，点击 **创建本地 Bot 配置**。该配置默认关闭自动挂卡（`FarmingPreferences: 1`），不含密码且默认 `Enabled: false`；再使用 ASF-ui 完成密码/Steam Guard 和启用。此操作不会覆盖已有 Bot 配置。
4. ASF 默认 IPC 地址为 `http://127.0.0.1:1242`，首次托管安装生成随机 IPC 密码，只保存在插件私有数据目录的 `runtime/config/ASF.json` 内。**ASF 账号密码及 Steam Guard 请使用 ASF 自身的受信配置功能**，本插件面板不要求 Steam 密码。
5. 在 ASF 内创建、登录并启用 Bot（Steam 账号实例）。在本插件管理面板设置 **ASF Bot 名称** 与连接模式 **插件托管 ASF**；可选勾选随 AstrBot 启动。
6. 访问远程服务器上的 ASF-ui 时，**不要直接将 ASF 的 IPC 端口对公网开放**。用 SSH 安全转发到本机的 `127.0.0.1:1242` 再访问；如果只是本地 AstrBot，可直接打开 ASF-ui。IPC 密码可在服务器的私有配置中查看，切勿发送到 QQ 群或 GitHub。
7. 在 Steam 商店或可信来源确认有效的永久免费包 **SubID**，在活动卡片「批准免费包 SubID」，再手动测试 ASF 领取。可选开启「已批准免费 SubID 自动领取」。

目前支持 Windows、Linux、macOS 常见 x64/ARM64 平台。实际下载、操作系统依赖和 Steam 登录需要你在部署环境测试。**自动安装需有网络、写入权限，且要信任 ASF 官方发布的可执行文件。**

如已安装独立 ASF，也可继续选择「已有的 ASF / 环境变量」模式：

```sh
export ASTR_STEAM_ASF_URL=http://127.0.0.1:1242
export ASTR_STEAM_ASF_BOT=MyBot
export ASTR_STEAM_ASF_PASSWORD='your-local-ASF-IPC-password'
```

只能连接本机 loopback IPC；不接收任意远程 ASF 地址。

### ASF 的 CPU 和内存占用

单个账号、少量请求、没有大量挂卡任务时，一般不会持续占用很多 CPU。启动、账号同步和处理命令期间会有短暂升高。ASF/.NET 为提高性能可能保留一部分内存；插件托管的新 ASF 安装默认设置了 `OptimizationMode: 1`（优先节省内存）。**没有跨机器通用的 CPU/内存固定数值，请以你的服务器实际监控为准。** 若你不需要自动领取，可以不安装也不启动 ASF，活动推送照常工作。

### 为什么“ASF 报告成功”仍要求核验？

ASF IPC 的 HTTP/API 成功只能说明命令已执行/被接收；其文本输出有时可能报告许可证已添加、已拥有或访问失败。插件将返回结果分为：

- `failed`：连接失败、命令失败或 ASF 文本明确指出错误（向群推送失败）。
- `reported_success`：ASF 文本显示 `OK`/`granted`/`added` 等成功线索（向群推送“ASF 报告成功 · 待核验”）。
- `submitted`：未能明确判断已获许可证（向群推送“已提交 · 待核验”）。

**三者都不能替代 Steam 官方账号许可证验证。** 不会把请求接受冒充为永久入库成功，且失败不会自动无限重试。管理员可以在 WebUI 手动重试，并看到多次尝试历史。

## 隐私和安全

- `.gitignore` 排除 SQLite、配置凭据、缓存、私有 ASF 数据等文件。插件托管 ASF 独立存放于 `StarTools.get_data_dir()` 指定位置，不上传到仓库。
- 后台管理 API 依赖已登录的 AstrBot WebUI 会话；不要在不可信网络开放 AstrBot 管理后台。
- 插件不会输入或绕过 Steam Guard、验证码，不尝试抓取第三方 Key；遇到已发完、地区限制、积分门槛时，活动仍可能失效。
- 官方 GitHub Release 的哈希验证确保下载文件与发布元数据一致；不代表替代独立代码审计或零风险保证。
- ASF 可执行文件由用户在面板主动下载安装；默认不启动，自动领取默认关闭。GitHub 不包含 ASF 第三方二进制。

## 开发验证

```sh
python -m pip install -r requirements.txt pytest
python -m pytest -q
python -m compileall -q .
node --check views/steam-freebies/app.js
node tests/asf_button_smoke.js
```

目前只通过离线语法检查和模拟测试，**尚未在真实 Steam 账号、QQ 群、真实 ASF 安装与领取上完成端到端验证**。请先在测试 AstrBot 和不含重要资产的测试 Steam 账号上核验权限与行为。

## 已知限制与后续计划

1. Steam 100% 折扣不一定是“永久免费入库”；第三方 Key 可能过期、需积分、已缺货，也不保证全量发现。
2. 当前只针对管理员批准的 SubID 调用 ASF，**不会自动识别并批准所有永久限免包**。
3. QQ 主动推送受对应适配器的权限、额度、平台风控约束；历史通知保留但不保证跨进程恰好一次发送。
4. 托管 ASF 进程不会直接在面板接受 Steam 登录密码，配置登录仍需要 ASF-ui、账号持有人授权与 Steam Guard；云服务器需安全访问 IPC。
5. 对 HTTP/IP C 返回文本进行有限分类，并非正式 Steam 许可证验证接口，可能有未识别的错误文本。

ASF 官方资料：[项目](https://github.com/JustArchiNET/ArchiSteamFarm) · [IPC](https://github.com/JustArchiNET/ArchiSteamFarm/wiki/IPC) · [配置](https://github.com/JustArchiNET/ArchiSteamFarm/wiki/Configuration)。

## 群晖 NAS / Docker：安装按钮没有反应怎么办（v0.3.1）

旧版本使用了 `window.confirm()`，但 AstrBot 插件面板运行在**不允许浏览器原生弹窗**的沙箱 iframe 中，导致「安装 ASF」点击后没有提交请求，安装状态始终是 `idle`。v0.3.1 已移除所有原生 `confirm()` / `prompt()`，使用页面内交互层，并且安装按钮直接发起后台 API；错误显示在 ASF 按钮下方。

操作顺序：

1. 在 AstrBot 插件管理选择**从 GitHub 更新本插件**，确保详情版本显示 **0.3.1**。重载插件；浏览器使用 `Ctrl+Shift+R` 刷新页面。
2. 打开「内置 ASF」→ 选择「自动加速」→ 保存 ASF 设置 → 点击「安装 / 更新 ASF」。按钮下方应立即显示「正在提交请求」然后显示下载、校验或明确的失败原因。
3. 如果显示「目录不可写」，检查 DSM **Container Manager → AstrBot 容器 → 存储空间/卷映射**对 AstrBot 数据目录的读写权限。不要为了修复问题向整个 NAS 开放写入权限；只调整 AstrBot 对应目录。
4. 如果显示网络错误，请检查**容器内部**能否访问 GitHub 或镜像域名。AstrBot WebUI 里的 GitHub 加速配置与插件自己的下载源是不同的，插件有独立加速切换设置。
5. 如果下载安装成功但启动失败，可能是容器运行时依赖或挂载点限制。查看本地 `data/plugin_data/astrbot_plugin_steam_freebies/asf-manager/asf.log`，并确认容器的 Linux 运行时/权限匹配。

状态 `ASF-linux-x64.zip` 说明识别到 **AstrBot 运行环境的 Linux x64 架构**，不是需要在电脑手工下载安装。安装位置属于 AstrBot 的私有持久数据目录；不应把含 Steam 身份凭据的整个目录提交到公开 GitHub。

**GitHub 仓库只托管安装器源码和可信校验值。** ASF 二进制仍需由运行 AstrBot 的 NAS/容器首次获取一次。把 ASF 程序二进制直接打包进公开仓库不会消除部署到 NAS 的网络传输，还会让仓库膨胀、难以跨架构更新，并增加供应链维护成本。

## v0.3.2：群晖 / Docker 中 ASF 安装成功但启动失败

此前的启动命令只有 `--no-restart`。**ASF 在没有任何已启用 Steam Bot 时可能主动退出**，尤其是新安装后还没有创建账号的情形。v0.3.2 增加 `--process-required`，使 IPC 服务在没有账号时也可以持续运行，方便首次配置 Bot。

- 「启动 ASF」按钮现在在 ASF 面板内显示进度及启动失败原因，不再只有 `管理操作失败：RuntimeError`。
- 如果仍然启动失败，面板会根据**本地 ASF 启动日志**识别缺少 `libicu`、`libssl`、glibc/musl 兼容性、执行权限和架构错误。**只显示概括性诊断，不会把 Steam 凭据或完整日志公开到页面**。
- 群晖容器如果提示原生库缺失，需要修改 **AstrBot Docker 容器运行镜像**，仅仅在 DSM 宿主机安装依赖并不能让容器里获得这些库。
- 不要随意把 ASF IPC 端口映射到公网；账号授权仍在 ASF 管理端完成。
- 更新插件无需重新安装 ASF，已有的 ASF 二进制、Bot 配置和数据库位于 AstrBot 私有数据目录，不随代码更新被覆盖。
