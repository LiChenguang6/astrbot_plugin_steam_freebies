# Steam 喜加一监控 · AstrBot 插件（MVP）

这是独立插件，参考作者现有 [Word Guardian 项目](https://github.com/LiChenguang6/astrbot_plugin_steam_status_monitor) 的 **AstrBot + QQ 主动消息 + 插件内嵌 WebUI + SQLite** 架构重新开发。不会修改原仓库。当前版本为 **0.1.0 / 未完成实际机器人与 ASF 联调的 MVP**。

[GitHub 仓库](https://github.com/LiChenguang6/astrbot_plugin_steam_freebies) · [原项目参考](https://github.com/LiChenguang6/astrbot_plugin_steam_status_monitor)

## 当前实现

- Steam 商店搜索「100% 折扣」候选与 GamerPower Steam 游戏赠送线索；不是 Free-to-Keep 官方认证数据源。
- 自动轮询（30–360 分钟）、本地 SQLite 缓存、群消息去重、重启后保留历史。
- QQ 群 `/喜加一绑定`、`/喜加一解绑`（AstrBot 管理员）和 `/喜加一`（最近缓存 5 条）。
- 插件详情页内的 **Steam 喜加一控制台**：活动、数据源错误、机器人群组、测试推送、刷新、设置、批准 Steam 免费领取包 SubID、手动 ASF 领取。
- 可选「对**人工批准的 SubID**自动执行领取」：默认关闭。未经人工确认的搜索结果、GamerPower 第三方活动不可能触发领取。
- ASF 凭据仅使用进程环境变量，面板不会保存或返回密码。

## 核心安全边界

**非全自动无人工干预的领取器。** Steam 100% 折扣与「永久入库」不是一个概念。Steam Free-to-Keep 使用临时可领的许可包；自动领取需要正确的 SubID、地区资格、有效活动期及 Steam 登录状态。这些无法仅凭搜索结果安全推断。

已人工批准的 SubID，按设置调用 ASF `addlicense <Bot> sub/<SubID>`。ASF IPC 返回成功仅表示该命令被处理，**不代表永久领取成功**。必须到 Steam 账号库/许可证页面核验。免费周末、DLC、第三方 Key、账户地区限制、验证码等可能让领取失败。本插件不会破解验证码、绕过登录验证，也不会尝试用不可靠的 AppID 自动领取。

当前实现没有自动证明某个活动已经结束，管理员不要批准过期活动，且不应无条件开启自动领取。候选来源并不保证全量覆盖。

## 安装

环境要求：AstrBot ≥4.29.1、Python 3.12、可访问 Steam 与 GamerPower 的网络。

1. 推荐在 AstrBot 插件管理中通过 GitHub 地址安装：`https://github.com/LiChenguang6/astrbot_plugin_steam_freebies`。也可把仓库克隆至 `AstrBot/data/plugins/astrbot_plugin_steam_freebies`。安装 `requirements.txt` 的依赖并重载插件。
2. 运行 AstrBot，确认 QQ 官方或 aiocqhttp/OneBot（例如 NapCat）适配器在线。
3. 以 AstrBot 管理员身份在指定 QQ 群发送 `/喜加一绑定`，之后可发送 `/喜加一` 获取候选。
4. 进入 AstrBot → 扩展/插件 → Steam 喜加一监控 → 打开「steam-freebies」页面。配置扫描间隔、推送选项并测试。
5. 对于 QQ 官方机器人，**定时主动群发必须有官方主动消息权限及额度**；群内 `/喜加一` 作为被动命令不等于授予主动推送资格。

默认每 60 分钟检查。首次启动或后台「立即扫描」也会触发检查。若两个来源均异常，后台记录数据源错误；无法保证能够展示实时活动。

## ASF 可选配置

ASF 是独立进程，不是插件会自动安装或登录的组件。请先用 [ASF 官方文档](https://github.com/JustArchiNET/ArchiSteamFarm/wiki/IPC) 安全配置 Steam 帐号及 IPC，确认 ASF 正常工作。

在运行 AstrBot 的**同一机器**设置环境变量，例如 Linux：

```sh
export ASTR_STEAM_ASF_URL=http://127.0.0.1:1242
export ASTR_STEAM_ASF_BOT=MyBot
export ASTR_STEAM_ASF_PASSWORD='your-local-ASF-IPC-password'
```

推荐使用同一宿主机 localhost，不向公网开放 ASF IPC。容器与宿主机分离时，应调整部署网络，使插件访问安全的本地代理；当前版本出于安全考虑只允许 loopback 地址，不能直接连接外部 IP。ASF 密码切勿提交到 GitHub。

先在 Steam 官方商店或可信包数据中确认活动、SubID，然后在活动卡片中「批准 SubID」；**建议先点击手动领取**，检查 ASF 返回文本和 Steam 账号实际许可证，再决定是否打开「已批准 SubID 自动领取」。

## 免责声明与开发验证

- 源项目的 GitHub `main` 现为 QQ 单词守护，并非 Steam 状态监控代码。这个项目是新建而非原地修改。
- 免费线索数据来自非正式商店搜索 HTML 和 GamerPower API，页面 DOM、地区配置、API 可变更。GamerPower 使用请保留来源署名和链接。
- 后台 API 通过 AstrBot 登录态访问，领取仅由后台发起；不要将 AstrBot 管理面板开放至不可信网络。
- 只有本地单元测试（数据解析、配置与去重）可以在离线环境完成。QQ群发送、QQ 官方主动权限、Steam 实际免费领取、真实 ASF IPC 需在你的环境验证。发布生产环境前建议单独部署一个测试 AstrBot 实例。

## 测试

```sh
python -m pip install -r requirements.txt pytest
python -m pytest -q
python -m compileall -q .
node --check views/steam-freebies/app.js
```

## 下一阶段

可接入一个能验证 Free-to-Keep `package_id`、免费包起止时间、地区限制的可靠数据源，才有条件把「人工批准 SubID」升级为「可信的全自动领取」。另可增加到期时间本地时区转换、双源交叉核对、领取账户库内实际许可证验证、中文封面图片、群推送模板和更细的权限设置。
