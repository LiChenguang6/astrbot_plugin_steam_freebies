"""AstrBot QQ Steam freebies: discovery -> dedup -> push -> optional approved ASF claim."""
import asyncio
import os
from datetime import datetime, timezone

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star, StarTools
from astrbot.api.web import error_response, json_response, request

from .steam_freebies.asf import claim_sub
from .steam_freebies.manager import ManagedASF
from .steam_freebies.embedded_ui import EmbeddedUI
from .steam_freebies.sources import fetch_candidates
from .steam_freebies.price_monitor import monitor_prices
from .steam_freebies.store import Store

PLUGIN = "astrbot_plugin_steam_freebies"
SUPPORTED_QQ = {"aiocqhttp", "qq_official", "qq_official_webhook", "qqofficial"}
OFFICIAL_QQ = {"qq_official", "qq_official_webhook", "qqofficial"}


class Main(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        data_dir = StarTools.get_data_dir(PLUGIN)
        self.store = Store(data_dir / "freebies.sqlite3")
        self.asf_manager = ManagedASF(data_dir / 'asf-manager')
        self.asf_ui = EmbeddedUI(self.asf_manager)
        self.scan_lock = asyncio.Lock()
        self.claim_lock = asyncio.Lock()
        self.claim_notifications_lock = asyncio.Lock()
        self.task = None
        self.errors = []
        self.last_scan = ""
        self.last_items = 0

    async def initialize(self):
        api = {
            ("GET", "snapshot"): self.web_snapshot,
            ("POST", "settings"): self.web_settings,
            ("POST", "scan"): self.web_scan,
            ("POST", "approve"): self.web_approve,
            ("POST", "claim"): self.web_claim,
            ("POST", "test-send"): self.web_test,
            ("POST", "price/watch"): self.web_price_watch,
            ("POST", "asf/install"): self.web_asf_install,
            ("POST", "asf/start"): self.web_asf_start,
            ("POST", "asf/stop"): self.web_asf_stop,
            ("POST", "asf/settings"): self.web_asf_settings,
            ("POST", "asf/bot"): self.web_asf_bot,
            ("GET", "asf/ui/status"): self.web_asf_ui_status,
            ("POST", "asf/ui/enable"): self.web_asf_ui_enable,
            ("POST", "asf/ui/control"): self.web_asf_ui_control,
            ("POST", "asf/ui/input"): self.web_asf_ui_input,
        }
        for (method, path), handler in api.items():
            async def guarded(handler=handler):
                if not request.username:
                    return error_response("请从已登录的 AstrBot 后台访问", status_code=401)
                try:
                    return await handler()
                except (KeyError, ValueError, TypeError) as exc:
                    return error_response(str(exc)[:200], status_code=400)
                except Exception as exc:
                    logger.warning("[Steam喜加一] 管理操作失败：%s", type(exc).__name__)
                    return error_response("操作失败，请查看 AstrBot 日志", status_code=503)
            self.context.register_web_api(f"/{PLUGIN}/{path}", guarded, [method], "Steam喜加一后台")
        if self.asf_manager.installed() and self.asf_manager.settings()['mode'] == 'managed' and self.asf_manager.settings()['start_on_boot']:
            try:
                await self.asf_manager.start()
            except Exception as exc:
                self.errors.append(f'ASF 自动启动失败：{self.asf_manager.start_error or type(exc).__name__}')
        self.task = asyncio.create_task(self.run_loop(), name="steam-freebies-poll")

    async def run_loop(self):
        while True:
            try:
                await self.scan_and_process()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.errors = [f"调度错误: {type(exc).__name__}: {str(exc)[:100]}"]
                logger.warning("[Steam喜加一] 监控失败：%s", type(exc).__name__)
            await asyncio.sleep(self.store.settings()["scan_minutes"] * 60)

    async def scan_and_process(self):
        async with self.scan_lock:
            candidates, errors = await fetch_candidates()
            if self.store.settings()['price_monitor_enabled']:
                try:
                    changes, price_errors = await monitor_prices(self.store)
                    candidates.extend(changes)
                    errors.extend(price_errors)
                except Exception as exc:
                    errors.append(f'价格监控失败：{type(exc).__name__}')
            self.errors = errors
            self.last_scan = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.last_items = len(candidates)
            if candidates:
                self.store.upsert_games(candidates)
            # If all providers failed, don't treat that as an empty successful scan.
            if self.store.settings()['push_enabled']:
                await self.push_to_groups()
            if self.store.settings()['auto_claim_enabled'] and candidates:
                await self.process_approved_claims()
            # Delivery is retried even if both activity sources are unavailable.
            await self.push_claim_events()
            return {'candidates': len(candidates), 'errors': errors}

    async def send_group(self, target, text):
        platform = self.context.get_platform_inst(target["platform_id"])
        if platform is None:
            raise RuntimeError("QQ 适配器离线")
        if target["official"]:
            response = await platform.get_client().api.post_group_message(
                group_openid=target["group_id"], msg_type=0, content=text)
            if not isinstance(response, dict) or not response.get("id"):
                raise RuntimeError("官方 QQ 未确认主动消息，检查主动消息权限及额度")
        else:
            if not target["session"]:
                raise RuntimeError("缺少群会话，管理员请重新绑定")
            result = await self.context.send_message(target["session"], MessageChain([Plain(text)]))
            if result is False:
                raise RuntimeError("适配器拒绝发送")

    async def push_to_groups(self):
        for target in self.store.targets():
            if not target["enabled"]:
                continue
            for g in self.store.pending_pushes(target["id"], max_rows=10):
                kind = {'steam_candidate':'Steam 商店 100% 折扣候选',
                        'paid_to_free':'曾经付费 → 当前免费候选',
                        'third_party':'第三方 Steam Key / 活动赠送'}.get(g['kind'],'游戏活动')
                tip = ('Steam 商店活动需核实是否为永久入库。' if g['kind']=='steam_candidate'
                       else '本地价格记录显示先付费、现免费；请核实是否已转永久免费，此类不自动调用 ASF。' if g['kind']=='paid_to_free'
                       else '第三方活动可能需要注册、积分、地区资格或库存，无法通过 ASF 直接领取 Key。')
                text = (f"🎁 免费游戏发现｜{kind}\n"
                        f"游戏：{g['name']}\n标价：{g['original_price'] or '未知'}\n"
                        f"截止：{g['end_date'] or '以活动页面为准'}\n"
                        f"领取页面：{g['url']}\n{tip}\n"
                        f"来源提示：{g['confidence']}")
                try:
                    await self.send_group(target, text)
                except Exception as exc:
                    self.errors.append(f"群 {target['group_id']} 推送失败: {type(exc).__name__}")
                    break
                else:
                    self.store.marked(target["id"], g["key"])
                    await asyncio.sleep(1)

    async def push_claim_events(self):
        if not self.store.settings()['push_claim_results']:
            return
        async with self.claim_notifications_lock:
            for target in self.store.targets():
                if not target['enabled']: continue
                for ev in self.store.pending_claim_events(target['id']):
                    status = {'failed':'❌ 领取失败',
                              'reported_success':'✅ ASF 报告成功（待账户核验）',
                              'submitted':'🕓 已提交（待账户核验）'}.get(ev['status'],'🕓 待核验')
                    msg = (f"🎮 Steam 自动领取结果｜{status}\n"
                           f"游戏：{ev['name']}\nSubID：{ev['subid']}\n"
                           f"ASF 响应：{ev['result'][:220]}\n"
                           f"商店：{ev['url']}\n"
                           '最终是否永久入库，请在 Steam 账号许可证中核实。')
                    try:
                        await self.send_group(target,msg)
                    except Exception as exc:
                        self.errors.append(f"群 {target['group_id']} 领取结果通知失败: {type(exc).__name__}")
                        break
                    else:
                        self.store.mark_claim_event(target['id'],ev['id'])
                        await asyncio.sleep(1)

    async def do_claim(self, key):
        async with self.claim_lock:
            row = self.store.get_game(key)
            if not row or row["kind"] != "steam_candidate" or not row["approved_subid"]:
                raise ValueError("先在面板为 Steam 商店活动人工确认并批准正确 SubID")
            subid = int(row["approved_subid"])
            # The on-demand manager starts ASF only for an actual approved free SubID.
            # Third-party Key promotions never reach this route.
            prepared = False
            try:
                prepared = await self.asf_manager.prepare_for_claim()
                status, result = await claim_sub(subid,self.asf_manager)
            except Exception as exc:
                status, result = 'failed', f'{type(exc).__name__}: {str(exc)[:160]}'
            finally:
                if prepared:
                    self.asf_manager.finish_claim()
            self.store.claim_record(key, subid, status, result)
        # Broadcast after releasing claim_lock, avoiding blocking the next ASF command.
        await self.push_claim_events()
        return {'status':status,'result':result,
                'notice':'ASF 的返回不代表 Steam 永久许可证已经得到核验'}

    async def process_approved_claims(self):
        for row in self.store.pending_claims():
            # only act on recent entries, not historical promotions
            try:
                last = datetime.fromisoformat(row["last_seen"])
                if (datetime.now(timezone.utc) - last).total_seconds() > 7200:
                    continue
                await self.do_claim(row["key"])
            except Exception as exc:
                self.errors.append(f"ASF 执行失败: {type(exc).__name__}")

    def snapshot(self):
        targets = self.store.targets()
        return {
            "settings": self.store.settings(),
            "targets": targets,
            "games": self.store.games(),
            "prices": self.store.price_overview(),
            "itad_configured": bool(os.getenv("ASTR_STEAM_ITAD_API_KEY")),
            "last_scan": self.last_scan,
            "last_items": self.last_items,
            "errors": self.errors[-10:],
            "claim_configured": bool(os.getenv('ASTR_STEAM_ASF_BOT')) or bool(self.asf_manager.settings()['bot_name']),
            "asf": self.asf_manager.status(),
            "claim_events": self.store.latest_claim_events(),
            "disclaimer": "搜索到的候选不保证是永久入库；仅通过人工批准 SubID 的 Steam 商店候选才能调用 ASF。",
        }

    async def web_snapshot(self):
        return json_response(self.snapshot())

    async def web_settings(self):
        body = await request.json(default={})
        return json_response({"settings": self.store.update_settings(body)})

    async def web_scan(self):
        if self.scan_lock.locked():
            raise ValueError("正在扫描，请稍后刷新")
        return json_response(await self.scan_and_process())

    async def web_approve(self):
        body = await request.json(default={})
        key = body["key"]
        subid = body["subid"]
        self.store.approve(key, subid)
        return json_response({"ok": True, "warning": "管理员应在 Steam 商店或可信信息源核对免费永久领取包和地区资格"})

    async def web_claim(self):
        body = await request.json(default={})
        return json_response(await self.do_claim(body["key"]))

    async def web_price_watch(self):
        body = await request.json(default={})
        return json_response(self.store.add_price_watch(body.get('appid')))

    async def web_asf_install(self):
        self.asf_manager.install()
        return json_response({'ok': True, 'state':self.asf_manager.status(),
                              'notice':'ASF 安装任务已启动，将自动下载、校验并安装到插件私有目录'})

    async def web_asf_start(self):
        try:
            await self.asf_manager.start()
        except RuntimeError:
            # Only the manager's allowlisted diagnosis reaches the dashboard.
            return error_response(
                f"ASF 启动失败：{self.asf_manager.start_error}",
                status_code=503
            )
        return json_response({'ok':True, 'notice':'托管 ASF 已启动'})

    async def web_asf_stop(self):
        await self.asf_manager.stop()
        return json_response({'ok':True})

    async def web_asf_settings(self):
        body = await request.json(default={})
        cfg = self.asf_manager.save_settings(body)
        return json_response({'settings':cfg, 'notice': 'ASF 设置已保存。如 ASF 正在运行，更改性能模式需要先停止并重新启动 ASF 才会生效。'})

    async def web_asf_bot(self):
        body=await request.json(default={})
        return json_response(self.asf_manager.prepare_bot(body.get('bot_name'),body.get('steam_login')))

    async def web_asf_ui_status(self):
        return json_response(await self.asf_ui.status())

    async def web_asf_ui_enable(self):
        body = await request.json(default={})
        return json_response(await self.asf_ui.set_enabled(body.get('enabled')))

    async def web_asf_ui_control(self):
        body = await request.json(default={})
        return json_response(await self.asf_ui.control(body.get('action')))

    async def web_asf_ui_input(self):
        body = await request.json(default={})
        # Never log or return body.value (Steam password or one-time code).
        return json_response(await self.asf_ui.input_secret(body.get('type'), body.get('value')))

    async def web_test(self):
        body = await request.json(default={})
        target_id = body.get("target_id")
        if type(target_id) is not int:
            raise ValueError("缺少目标群 ID")
        row = next((v for v in self.store.targets() if v["id"] == target_id and v["enabled"]), None)
        if row is None:
            raise ValueError("目标群不存在或已暂停")
        day = datetime.now(timezone.utc).date().isoformat()
        key = f"__test__:{day}"
        if self.store.db.execute("SELECT 1 FROM sent WHERE target_id=? AND game_key=?", (target_id, key)).fetchone():
            raise ValueError("每群每天最多测试推送一次")
        await self.send_group(row, "✅ Steam 喜加一插件推送测试成功。")
        self.store.marked(target_id, key)
        return json_response({"ok": True})

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("喜加一绑定")
    async def bind(self, event: AstrMessageEvent):
        if not event.get_group_id() or event.get_platform_name() not in SUPPORTED_QQ:
            yield event.plain_result("请在目标 QQ 群内执行 /喜加一绑定（需要 AstrBot 管理员权限）。")
            return
        self.store.bind(platform_id=event.get_platform_id(), bot_id=event.get_self_id(),
                        group_id=event.get_group_id(), session=event.unified_msg_origin,
                        official=event.get_platform_name() in OFFICIAL_QQ)
        yield event.plain_result("✅ 已将本群加入 Steam 喜加一推送列表，可在 AstrBot 插件后台查看。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("喜加一解绑")
    async def unbind(self, event: AstrMessageEvent):
        if not event.get_group_id():
            yield event.plain_result("请在群内执行。")
            return
        self.store.disable_target(platform_id=event.get_platform_id(), bot_id=event.get_self_id(), group_id=event.get_group_id())
        yield event.plain_result("已暂停向本群推送 Steam 限免线索。")

    @filter.command("喜加一")
    async def list_freebies(self, event: AstrMessageEvent):
        rows = self.store.games(limit=5)
        if not rows:
            yield event.plain_result("尚无缓存的 Steam 免费活动线索，请稍后查看。")
            return
        lines = ["🎁 Steam 喜加一候选（不保证永久入库）："]
        for g in rows:
            lines.append(f"{g['name']}｜{g['source']}\n{g['url']}")
        yield event.plain_result("\n".join(lines))

    async def terminate(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        await self.asf_manager.close()
        self.store.db.close()
