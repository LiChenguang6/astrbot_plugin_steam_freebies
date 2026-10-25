# Steam 喜加一监控 · AstrBot 插件

> **v0.6.6（功能测试版）** · Steam 商店免费活动 + 第三方 Steam Key 赠送 + QQ 推送 + WebUI 控制台 + 可选插件托管 ASF

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

**注意：** 一键安装 ≠ Steam 账号自动登录。ASF 首次授权仍需账号持有人提供必要验证；v0.4.0 可以通过插件内的 ASF 账号管理提交一次性验证信息。AstrBot 在 Docker 里时，下载和 ASF 均运行在容器内，IPC 只能从同一容器访问；需保证持久化数据卷。服务器完全无法访问任何镜像或 GitHub 时，网络限制仍然存在，插件无法保证成功下载。

## 插件内置管理 ASF（可选）

**ASF 是在 AstrBot 所在服务器上运行的另一独立进程，不是 Python 库，也不会一起提交到 GitHub 仓库。** 本插件让你从管理页面自动安装/启动/停止它，进程和 Steam 账号配置仍由 ASF 自身维护。

1. 打开 WebUI → **内置 ASF** → 选择下载模式（默认自动加速）→ 点击 **安装 / 更新 ASF**。安装器自动选择官方 Release 或经过 SHA256 校验的加速中转，网络不通可使用固定版本的官方校验清单。
2. 安装完成后点击 **启动 ASF**。运行中不能覆盖安装包；错误与 ASF 本地日志位于 `data/plugin_data/astrbot_plugin_steam_freebies/asf-manager/` 下（实际位置以 AstrBot 数据目录为准）。
3. 可以在面板中填写 **ASF Bot 名称** 和 **Steam 登录名**，点击 **创建本地 Bot 配置**。该配置默认关闭自动挂卡（`FarmingPreferences: 1`），不含密码且默认 `Enabled: false`；可以在内置 ASF 账号管理区启用 Bot，并按 ASF 提示完成登录/Steam Guard。此操作不会覆盖已有 Bot 配置。
4. ASF 默认 IPC 地址为 `http://127.0.0.1:1242`，首次托管安装生成随机 IPC 密码，只保存在插件私有数据目录的 `runtime/config/ASF.json` 内。**内置账号管理可选择性提交一次性密码/Steam Guard 给本机 ASF**；插件本身不持久化这些验证信息。
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
4. 内置管理面板支持向本机 ASF 发送一次性登录信息，但需要账号本人授权并完成 Steam Guard；通过 HTTP 访问时请注意凭据的传输风险。
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

## v0.4.0：群晖 NAS 4GB 内存，ASF 一键切换高性能 / 低资源兼容

在插件 WebUI → **托管 ASF → ASF 运行模式**，有两个单选按钮：

| 模式 | 技术设置 | 适用条件 |
| --- | --- | --- |
| 高性能 | ASF `OptimizationMode=0`，仅 ASF 子进程使用标准 .NET 国际化模式（`DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0`）| 容器已安装 ICU，想保留完整国际化行为 |
| 低资源兼容（默认） | ASF `OptimizationMode=1`，仅 ASF 子进程环境变量 `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1`、`DOTNET_SYSTEM_GLOBALIZATION_PREDEFINED_CULTURES_ONLY=0` | 群晖 Docker 容器缺少 libicu，无法正常启动 |

**操作：** 选模式 →「保存 ASF 设置」→ 如正在运行先「停止 ASF」→「启动 ASF」。不必重新下载 ASF。切换只修改 ASF 私有目录 `config/ASF.json` 的 `OptimizationMode`，保留其他属性及本地 IPC 密码；兼容模式只修改 ASF 子进程的环境变量，不改变 AstrBot / 群晖宿主机环境，也不上传任何密码。

`.NET` invariant 兼容模式是微软支持的绕过缺失 ICU 的技术选项，但**不保证所有 Steam/ASF 工作流都正常**。语言排序、非英文区域行为可能发生变化。若出现其他本地库或连接错误，仍需调整容器镜像。`MinMemoryUsage` 只是 ASF 的执行并发策略，ASF 官方说明其牺牲较多性能但节省内存不一定明显；高性能模式通常更适合已安装完整依赖的普通机器。

**按需启动：** 在「需要领取时自动启动 ASF」启用时，管理员批准的 SubID 触发实际领取前自动启动托管 ASF，领取结束后按设置等待 5 / 10 / 15 / 30 分钟，无后续领取任务则自动停止。手动点击启动用于首次账号配置，不会马上被定时器结束；已有进程不会重复启动。这个选项不自动识别 SubID，不为第三方赠 Key 活动领取 Key。已登录的 Steam Bot 重新启动时仍可能需要 Steam 验证，无法保证全程无人值守。

**NAS 内存:** 面板能够显示 Linux `/proc` 中 ASF 进程的实际常驻物理内存（RSS），不是预测值。缓存页通常可回收，但不要把 NAS 的缓存值全部当成可用内存。对 4GB 机器，建议保持足够的系统余量，并先尝试低资源兼容模式。

资料： [.NET Globalization Invariant Mode](https://learn.microsoft.com/en-us/dotnet/core/runtime-config/globalization) · [ASF OptimizationMode](https://github.com/JustArchiNET/ArchiSteamFarm/wiki/Configuration#optimizationmode)


## v0.4.0：AstrBot 面板内置 ASF 账号管理（无需 Firefox / NAS 1242 映射）

打开 AstrBot `http://NAS-IP:6185` → Steam 喜加一插件 → 控制台 → 托管 ASF。选择「插件托管 ASF」，保持本地 ASF 进程正常运行，在新的**内置 ASF 账号管理**区域直接查看当前 Bot 的登录状态、启用/停用 Bot、启动/停止 Bot，以及提交 ASF 需要的密码或 Steam Guard 一次性验证码。

操作顺序：

1. **创建 Bot 配置**：填 Bot 名称、Steam 登录名，点击「创建本地 Bot 配置」。新配置不包含密码且初始禁用。
2. **启用**：选择「插件托管 ASF」，保存设置，启动 ASF，然后在新的内置区域点击「启用 Bot」。
3. **登录**：点击「启动 Bot」，按 ASF 提示选择「Steam 登录密码」或「Steam Guard 邮件验证码」等输入类型，提交给 ASF。若 ASF 表示需重新启动 Bot，则再次点击「启动 Bot」。部分设备确认需要在你本人的 Steam App 内操作。
4. **核验**：点击「刷新账号状态」。只有 ASF 返回 `IsConnectedAndLoggedOn` 时才显示「已连接 Steam」。

该页面**不是完整的上游 ASF-ui 源码嵌入**，而是在 AstrBot 插件 UI 里直接集成账号连接所需的常用能力，采用有限范围的 `/Api/Bot` IPC 请求，**不提供任意 URI 或命令代理**，不将原始 Bot 配置、Steam 密码、登录密钥、验证码和 IPC 密码回传到浏览器、QQ 群或日志。所有 IPC 请求仅发往插件所在容器的 `127.0.0.1:1242`。

**传输安全**：请尽可能使用 HTTPS 访问 AstrBot。仅通过普通 HTTP 远程打开 `:6185` 时，输入的 Steam 密码或验证码没有 TLS 传输保护。界面因此要求先明确确认当前环境仅为可信网络。不要将 AstrBot 管理后台直接公开到互联网；不要将敏感输入截图或粘贴到聊天中。

首次 Steam 登录及 Guard 确认仍需本人授权，不支持绕过 Steam 安全验证。离线测试无法代替真实 Docker + Steam 联调。


## v0.4.1：内置 ASF 管理返回 HTTP 400

旧版本发送身份验证输入时将 `Type` 写成字符串。新版本按 ASF 源码中 `EUserInputType` 的数字枚举值提交，解决某些 ASF 构建的 JSON 反序列化失败问题；不会保存用户密码或 Guard 码。

此外，所有常用操作现在分别显示「状态查询 / 启用 / 启动 / 停止 / 验证输入」及对应 HTTP 状态和安全处理过的提示。`HTTP 400` 并不等于密码错误：新建 Bot 尚未被 ASF 加载、配置有误或验证输入类型不对都可能发生。

建议操作：插件升级后重载并刷新浏览器；启动 ASF → 创建并保存 Bot 配置 → 启用 Bot → 启动 Bot；若状态显示「未加载」，可停止并重新启动 ASF 再刷新；当 ASF 请求密码或 Steam Guard 时，再提供相应输入并重新启动 Bot。不要把原始 ASF 日志、密码或验证码粘贴到公共对话中。

该修复通过离线模拟测试，不能证明你的 NAS 上 Steam 登录一定成功。


## v0.5.0：付费转永久免费候选检测与历史价格

新增 **Steam 当前免费 / 历史收费监控**，在「免费活动 → 付费转免费」分类浏览。**默认监控并推送经过本地先付费、后免费的候选变化**，第三方 Key 和 Steam 100% 折扣监控继续正常运行。此分类不会自动向 ASF 领取许可证。

- **来源：** Steam 商店搜索发现部分近期及免费游戏，使用 `https://store.steampowered.com/api/appdetails?appids=<AppID>&cc=cn&l=schinese` 读取 `is_free` 和当前 `price_overview.final`。不保证接口稳定，也不能扫描全部 Steam 游戏。
- **判断：** 只有数据库曾在最近 90 天记录该 AppID 处于 `is_free=false` 且 `price_overview.final>0`，后一次读取到 `is_free=true`，才新增「付费转免费候选」通知。首次发现已免费只建基线，不反推历史；`final=0` 但 `is_free=false` 的临时 100% 折扣不作为转免费。即便 `is_free=true` 也不保证永久授权，推送时请复核商店页面。
- **监控池：** 每轮最多抽查 12/18/24 个 AppID（默认 18）；已有记录优先复查，再从 Steam 搜索补充。可手动添加任意 Steam 游戏 AppID，首次扫描不误报。SQLite 自动建表，保留旧群绑定、领证记录和 ASF 配置。
- **可选 IsThereAnyDeal：** 从 [IsThereAnyDeal API 文档](https://docs.isthereanydeal.com/)申请 Key，在运行 AstrBot 的容器内设置环境变量 `ASTR_STEAM_ITAD_API_KEY`。检测到本地确切付费→免费变化时，使用 `GET /games/lookup/v1?appid=<AppID>` 和 `GET /games/history/v2?id=<GameID>&country=US&since=...` 检索近两年 Steam 店铺收费历史，最多 2 次候选校验/轮；若 API 不可用，仍按本地价格观测工作。**Key 不返回后台、不写入数据库或 GitHub。**没有历史匹配不代表过去从未收费，历史数据只作证据补充。遵守 ITAD 使用条款，使用者须自行取得授权密钥。
- **注意：** 这是按抽样监控的候选检测，**不能保证及时发现所有付费转免费游戏**。例如已经在插件安装前转换的老游戏，不会被错误标记为“现在刚转换”。区域价格在中国区和 ITAD 美国区可能不同；价格变化、免费周末与版权许可证变化仍需要人工核实。

更新历史统一见 [CHANGELOG.md](CHANGELOG.md)。


## v0.6.0 使用说明：促销 API + 关注游戏 + B站情报 + 可选 AI

### 促销来源和准确性

| 源 | 是否需要密钥 | 用途与限制 |
|---|---|---|
| GamerPower REST API | 不需要 | 完整游戏/第三方 Steam Key 赠送线索（原有功能） |
| IsThereAnyDeal `/giveaways/v1` | 需要 ITAD Key | 现成 Steam 赠送活动候选，包括截止日期和原始来源链接 |
| IsThereAnyDeal `/deals/v2` | 需要 ITAD Key | 100% 折扣促销候选；非正式永久入库证明 |
| IsThereAnyDeal `/lookup/shop/61/id/v1` | 需要 ITAD Key | ITAD 游戏 ID 映射 Steam AppID，供 Steam 交叉核验 |
| Steam `appdetails` | 不需要 | 对已知 AppID 确认 `is_free`、当前售价与折扣，仅作为商店状态 |
| Steam 搜索列表 | 不需要 | 兼容保底搜索，不再做任意抽样历史价格监控 |
| B站公开 WBI 视频接口 | 不需要 Key，但可能触发风控 | 用视频标题、简介、UP 主 UID 报告待核验情报 |

**促销 API 不能覆盖所有游戏**；不同地区、临时免费试玩、周末试玩、限时永久入库与永久转 F2P 必须分开判断。普通付费游戏的折扣、先付费再免费、0 元许可不是一回事。本插件只对管理员批准的合法 Free-to-Keep SubID 允许 ASF 领取，其余来源**不会自动执行 ASF 命令**。

ITAD：向 [IsThereAnyDeal 注册应用](https://isthereanydeal.com/apps/my/)申请 API Key，通过群晖容器变量设置 `ASTR_STEAM_ITAD_API_KEY`；若不设置，GamerPower 和 Steam 后备源仍然可用，ITAD API 则不启动。ITAD 保留来源 URL，注意其 [API 使用条款](https://docs.isthereanydeal.com/)。

### 只监控指定 Steam 游戏的价格

在后台 **「游戏关注」** 输入 Steam AppID（例如 `850170`）→「添加监控」→「立即扫描」。第一次只建立基线，后续若价格涨跌、或 `is_free` 变化才生成通知。可以独立关闭「关注游戏价格变动 QQ 提醒」与「付费转免费候选 QQ 推送」。移除关注会停止轮询；不扫描整个游戏目录。

v0.5.0 的旧自动抽样游戏记录在升级时清理（`manual=0`），**手动添加的监控不受影响**；原有的价格事件历史、ASF Bot、本地登录凭据、QQ 绑定和领取记录不因插件更新而删除。

### Bilibili 免费游戏 UP 主/关键词

后台 **「B站线索」** → 将 `https://www.bilibili.com/video/BV16mnt6iEiZ/` 粘贴到输入框 →「订阅这个 UP 主」。插件通过公开 B站视频元数据读取作者 UID 并保存，之后轮询 UP 主新投稿；如果此接口在你的网络上被 B站拦截，可以在浏览器 B站 UP 主空间地址找到 `space.bilibili.com/<UID>`，在备用框直接填 UID。

可自定义关键词，如 `Steam 喜加一,Steam 限时免费,Steam 永久免费`，最多 5 个，每轮搜索前 2 个（限流考虑）；只判断一周内的视频标题和简介，按 BV 去重。B站接口有 WBI 签名和风控，不提供可保证稳定的开放“全站免费游戏 API”，遇到 -412/-352 等拒绝访问时报告错误并停止本轮 B站源。**不会获取视频全部字幕或下载视频，也不会绕过站点保护。**

### AI（自选是否花 Token）

进入后台 **「B站线索」**，选择 AI 提供商，填写模型名及 API Key，按「保存 AI 配置」。推荐优先在受信的 HTTPS AstrBot 地址操作；在普通 HTTP 的 `:6185` 输入 Key 存在网络窃听风险。密钥保存在私有数据目录中的 `ai-config.json`，不会回显。也支持预先配置环境变量：

```sh
ASTR_STEAM_AI_PROVIDER=deepseek
ASTR_STEAM_AI_MODEL=deepseek-chat
ASTR_STEAM_AI_API_KEY=your_private_key
```

然后在 **「监控设置」** 单独开启「B站线索发现」和「使用我的 AI API 辅助判断 B站线索」，可以选每轮最多调用 **0、1、2 或 3 次**。默认 AI **关闭**，不会向 AI 服务发送请求或消耗 Token。只有新出现并通过本地规则的短视频标题和描述才可能送去 AI，并在本地去重以免重复收费。每家服务的每 Token 实际价格不同，由你的 AI 服务商计算。

如果 AI 只报告不确定，仍按视频线索处理，不能替代 Steam 官方的当期价格和许可证核验。为了兼容不同服务商，AI 提供商仅支持预设 HTTPS 域名，不允许通过 WebUI 输入任意 API 端点；如使用非列表中的自建模型，则当前版本暂不支持，请不要用公网暴露的无鉴权模型服务。

### 开发核验

```sh
python -m pytest -q
python -m compileall -q steam_freebies main.py
node --check views/steam-freebies/app.js
```

更新日志见 [CHANGELOG.md](CHANGELOG.md)。本版本尚未在真实群晖 Docker + B站接口 + ITAD 实时数据上联调；如果页面显示数据源不可用，先查看安全的错误提示，避免贴出 API Key 或 Steam 登录信息。


## v0.6.1：群晖网络与 B站登录、QQ 推送修复

### Steam API 加速（适用于 Docker）

在「监控与推送设置 → Steam 网络加速」中选择：

- **自动（默认）**：存在自定义 HTTP 代理就使用它，否则自动读取 AstrBot **容器内部**的 `HTTPS_PROXY` / `https_proxy` 环境变量。否则直连。
- **指定代理**：输入 `http://代理IP:端口`，例如 `http://192.168.1.20:7890`。注意要填**容器可以访问的地址**，Docker 容器中的 `127.0.0.1` 不指群晖宿主机。仅支持不带账号密码的普通 HTTP CONNECT 代理；不要输入订阅链接、Clash YAML URL 或未知的 Steam 镜像域名。
- **始终直连**：忽略容器代理。

实际 Steam 商店请求始终连向官方 `store.steampowered.com`，会进行少量超时重试，保留 TLS 校验。**配置了代理但容器无法连通时仍会失败，插件不能凭空产生代理服务**。`Steam 商店搜索后备源` 现默认关闭，避免影响现成促销 API 的扫描；如果需要补充搜索，可自行开启。GamerPower/ITAD/B站请求保持独立，**不会**因为只给 Steam 配置了代理而自动走代理。

### B站官方二维码扫码

「B站线索中心」现在按 01 登录 → 02 订阅 UP 主 → 03 关键词/QQ 推送 → 04 高级 AI 分组。用手机 B站 App 扫描官方登录二维码并确认。密码不会提交到 AstrBot；**扫码确认后获得的 B站网页登录 Cookie 相当于登录凭据**，仅在 AstrBot 私有数据目录的 `bili-session.json` 中以 0600 权限存储、不会返回管理页面或上传 GitHub。请保护 NAS 和管理员账号；本地可点「清除登录」删除 Cookie。

登录不保证绕过 B站的 WBI/412、地域、IP 或接口限流。登录态有失效可能，登录状态只表明本地存在会话，不能证明每次请求已通过 B站验证。遇到明确风控应稍后重试，**不使用批量代理/验证码绕过**。此功能主要读取公开视频标题与简介，既不是官方稳定开放 API，也不是永久免费许可证明。

### QQ 测试推送与消息去重

以前同群每天只能测试一次，新版改为**同群每 30 秒允许重发一次测试**。测试失败明确显示适配器异常类型；成功显示最近测试时间。QQ 群面板增加当前待推送数量和最近正式推送时间。

新游戏活动仍按群独立去重：如果已经向某 QQ 群发送过某条活动，点击「立即扫描」不会再次发送旧活动；即使本轮没有新活动，测试推送仍可手动验证 OneBot/NapCat 通道。

### 升级

AstrBot 插件管理更新至 v0.6.1 → 安装更新依赖（新增 `qrcode`）→ 重载 → `Ctrl+Shift+R` 强制刷新页面。SQLite 和 ASF 登录配置保持不变；不会修改群晖容器端口映射。真实 B站扫码和群晖代理需在用户 NAS 网络环境自行验证；离线测试不能保证特定网络可用。


## v0.6.2：B站登录不跳转网页，支持短信验证码

- 新版 B站线索页面提供两个登录标签：「手机扫码登录」与「短信验证码登录」。扫码二维码由插件直接在受限制的 AstrBot iframe 内绘制成 SVG，不依赖 data: 图片或外部弹窗；用户用 B站 App 扫码、确认即可。
- 短信方式通过 `passport.bilibili.com/x/passport-login/captcha` 获取人机验证挑战，调用官方 GeeTest v3 客户端组件（`static.geetest.com`）由用户本人完成图形验证后，才允许使用 B站短信发送及验证码登录接口。**不允许绕过验证码或自动打码**。如果服务器或浏览器无法访问 GeeTest、B站更新接口或被反机器人拦截，则明确提示失败、可切换扫码方式；不保证所有 AstrBot 受限 iframe 内均可用。
- 手机号码、短信码、GeeTest 登录令牌只在本次登录流程中使用（短信登录阶段暂存于插件内存，过期失效），不会被写入 SQLite、配置文件或回应到浏览器。登录成功才保存白名单 B站 Cookie 到 AstrBot 私有目录，限制 Linux 文件权限为 `0600`。不要在 HTTP 公网连接上传输手机号、验证码；建议在可信 HTTPS 局域网管理页操作。
- **登录不等于能无限访问 B站**：即使登录成功，WBI、搜索接口仍可能因 IP 风控返回 412/其他代码；插件不绕过限制。

官方 B站并未承诺向第三方长期提供稳定的 SMS Web API，极验前端也依赖外部 CDN，真实联调可能需要后续适配；见 [CHANGELOG.md](CHANGELOG.md)。


## v0.6.3：B站登录错误处理

如果旧版「生成二维码」失败，新版不再要求额外安装 Python `qrcode` 依赖。点击「生成二维码」后，在二维码区可看到失败原因：若提示接口超时或拒绝，说明 AstrBot Docker 与 `passport.bilibili.com` 的连接或 B站风控需要处理，不能通过变更二维码绘制代码解决。

短信接口返回 `86005` 是 B站拒绝发送请求，无法凭该代码确定具体原因。不要连续重试；至少间隔 60 秒并重新完成官方人机验证，或优先使用 B站 App 扫码。跨设备（电脑浏览器和 NAS）极验会话可能受 B站额外校验，插件不提供绕过。

附带第三方二维码矩阵生成器受 `steam_freebies/_qr_vendor/LICENSE` 许可；只用于离线生成二维码图案，授权链接不会发送给第三方二维码服务。


## v0.6.4：B站扫码初始化与网关 502 修复

B站二维码申请通过后台异步任务完成：点击“生成登录二维码”会立即返回，再由管理面板定时查询进度。若 B站成功返回扫码密钥但二维码网址格式与旧版本不同，插件使用官方固定域名与该有效密钥形成扫码地址；**没有真实密钥时不会生成假二维码**。

点击“立即扫描”也变成后台任务，避免访问 Steam/ITAD/B站多个 API 时同步网页请求超时导致 502。提交请求成功不等于扫描已经完成，应等待运行状态消失后查看最近扫描时间及错误列表。B站短信 86005 是服务端拒绝，和 502 是两个独立问题。


## v0.6.5：B站扫码风险提示与官方 URL 校验

- 严格使用 `GET /x/passport-login/web/qrcode/generate` 返回的 **原始官方扫码 URL**，确认 URL 的 HTTPS 域名、路径及 `qrcode_key` 与接口响应一致；任一项不匹配则停止，不再将密钥拼接成插件自制扫码地址。
- NAS 上申请网页登录会话，B站 App 可能提示陌生设备、地区/IP 或登录风险。**这属于 B站账号风控，不能保证通过修改二维码消除。遇到风险提示应取消授权，优先使用 B站官方页面完成任何必要安全核验。**
- 不依赖 B站账号登录也可以尝试公开投稿搜索与手动 UP 主 UID 订阅，受 B站公开接口限流、WBI 与网络可用性影响。
- 若需要定位仍存在的风险，请只提供提示文字和 HTTP 状态码，不要提供二维码、`qrcode_key`、Cookie、手机号或验证码。


## v0.6.6：内置 B站账号会话管理（解决扫码/短信受阻）

B站线索中心新增 **「已有网页登录会话」**，与原有扫码/短信登录并列，默认选中。用户可在自己的浏览器中通过 B站官网正常登录后，使用登录后的 `SESSDATA` 或 `SESSDATA=...; bili_jct=...; DedeUserID=...` Cookie 字符串导入。不要将凭据提供给聊天机器人、QQ 群或其他人；不要从未知网站获取所谓“B站 API Token”。

- 后端只接受 B站网页会话相关白名单 Cookie；通过固定的 `https://api.bilibili.com/x/web-interface/nav` 账号状态接口验证 `isLogin=true`，再写入原插件私有目录 `bili-session.json`（Linux 权限 `0600`）。旧会话不会因失败导入而覆盖；WebUI 状态接口和响应从不返回敏感 Cookie。
- 内置管理区提供 **导入并验证、检查当前登录、清除本地会话**；无需把整个 B站网页嵌入 iframe，也不打开额外浏览器窗口。Web 登录 Cookie 不是正式开发者 OAuth Token，具有账号访问权限，必须像密码一样保护。优先使用 HTTPS 管理后台，且仅导入本人账号。
- 这不是绕过 B站安全机制：**B站可以拒绝 NAS IP / 会话请求**，而且登录有效也不意味着搜索 API 不受 412 等风控限制。NAS 到 `api.bilibili.com` 不通时也无法完成在线验证。
- 如 Cookie 已泄露，应从 B站官方安全设置撤销对应会话。公开 GitHub 仓库不包含私人 Cookie、Steam 密码和 ASF 私有数据。
