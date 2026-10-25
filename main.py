"""AstrBot QQ Steam freebies: discovery -> dedup -> push -> optional approved ASF claim."""
import asyncio
import aiohttp
import os
from datetime import datetime, timezone

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star, StarTools
from astrbot.api.web import error_response, json_response, request

from .steam_freebies.asf import claim_sub, claim_license
from .steam_freebies.manager import ManagedASF
from .steam_freebies.embedded_ui import EmbeddedUI
from .steam_freebies.sources import fetch_candidates
from .steam_freebies.steam_network import SteamNetwork, proxy_status
from .steam_freebies.bili_auth import BiliAuth
from .steam_freebies.promotions import fetch_itad_promotions
from .steam_freebies.bilibili import fetch_bilibili_tips, resolve_video_owner, extract_bvid
from .steam_freebies.ai_config import AIConfig
from .steam_freebies.price_monitor import monitor_prices
from .steam_freebies.bili_verify import verify_steam
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
        self.ai_config = AIConfig(data_dir)
        self.bili_auth = BiliAuth(data_dir)
        self.test_sent_at = {}
        self.last_test_result = {}
        self.scan_lock = asyncio.Lock()
        self.claim_lock = asyncio.Lock()
        self.claim_notifications_lock = asyncio.Lock()
        self.task = None
        self.errors = []
        self.last_scan = ""
        self.last_items = 0
        self.bili_test_task = None
        self.bili_test_result = {'state': 'idle', 'items': [], 'errors': []}
        self.manual_scan_task = None
        self.review_tasks = {}

    async def initialize(self):
        api = {
            ("GET", "snapshot"): self.web_snapshot,
            ("POST", "settings"): self.web_settings,
            ("POST", "scan"): self.web_scan,
            ("POST", "approve"): self.web_approve,
            ("POST", "claim"): self.web_claim,
            ("POST", "review/retry"): self.web_review_retry,
            ("POST", "review/resolve"): self.web_review_resolve,
            ("POST", "review/ai"): self.web_review_ai,
            ("POST", "test-send"): self.web_test,
            ("POST", "price/watch"): self.web_price_watch,
            ("POST", "price/unwatch"): self.web_price_unwatch,
            ("POST", "bili/add"): self.web_bili_add,
            ("POST", "bili/remove"): self.web_bili_remove,
            ("POST", "bili/test"): self.web_bili_test,
            ("GET", "bili/test/status"): self.web_bili_test_status,
            ("POST", "bili/login/start"): self.web_bili_login_start,
            ("GET", "bili/login/prepare"): self.web_bili_login_prepare,
            ("POST", "bili/login/poll"): self.web_bili_login_poll,
            ("POST", "bili/logout"): self.web_bili_logout,
            ("POST", "bili/session/import"): self.web_bili_session_import,
            ("POST", "bili/session/check"): self.web_bili_session_check,
            ("POST", "bili/sms/captcha"): self.web_bili_sms_captcha,
            ("POST", "bili/sms/send"): self.web_bili_sms_send,
            ("POST", "bili/sms/login"): self.web_bili_sms_login,
            ("POST", "ai/settings"): self.web_ai_settings,
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
            # The existing GamerPower REST API is available without a key.
            # ITAD's giveaway/deal APIs add structured Steam promotion coverage.
            itad_key = os.getenv('ASTR_STEAM_ITAD_API_KEY', '')
            candidates, errors = [], []
            network = SteamNetwork(self.store.settings())
            if itad_key:
                try:
                    more, issues = await fetch_itad_promotions(itad_key, network=network)
                    candidates.extend(more)
                    errors.extend(issues)
                except Exception as exc:
                    errors.append(f'ITAD 促销源失败：{type(exc).__name__}')
            more, issues = await fetch_candidates(network=network, search_fallback=self.store.settings()['steam_search_fallback'])
            candidates.extend(more)
            errors.extend(issues)
            if self.store.settings()['bili_enabled']:
                try:
                    tips, issues = await fetch_bilibili_tips(
                        self.store, self.ai_config.effective(), auth=self.bili_auth, network=network,
                        corroborated_appids={int(c['appid']) for c in candidates
                            if c.get('kind') == 'promo_api' and type(c.get('appid')) is int and c['appid'] > 0})
                    candidates.extend(tips)
                    errors.extend(issues)
                except Exception as exc:
                    errors.append(f'B站数据源失败：{type(exc).__name__}')
            if self.store.settings()['price_monitor_enabled']:
                try:
                    changes, price_errors = await monitor_prices(self.store, network=network)
                    candidates.extend(changes)
                    errors.extend(price_errors)
                except Exception as exc:
                    errors.append(f'价格监控失败：{type(exc).__name__}')
            self.errors = errors
            self.last_scan = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.last_items = len(candidates)
            if candidates:
                self.store.upsert_games(candidates)
            # Unattended creator claiming is deliberately opt-in and never attempts a purchase.
            if self.store.settings()['bili_enabled'] and self.store.settings()['bili_unattended_claim']:
                await self.process_unattended_creator_claims(network)
            # Legacy approved SubID claims remain supported.
            if self.store.settings()['bili_enabled'] and self.store.settings()['bili_auto_claim_creators']:
                await self.process_bili_creator_claims(candidates)
            # If all providers failed, don't treat that as an empty successful scan.
            if self.store.settings()['push_enabled']:
                await self.push_to_groups()
            if self.store.settings()['auto_claim_enabled'] and candidates:
                await self.process_approved_claims()
            # Only failed/uncertain automatic claims require the user's attention.
            await self.push_auto_review_notifications()
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
                        'watch_price':'关注游戏价格变动',
                        'bilibili_tip':'B站 Steam 游戏 · 已核查商店',
                        'promo_api':'促销 API / 免费赠送线索',
                        'third_party':'第三方 Steam Key / 活动赠送'}.get(g['kind'],'游戏活动')
                tip = ('Steam 商店活动需核实是否为永久入库。' if g['kind']=='steam_candidate'
                       else '本地价格记录显示先付费、现免费；请核实是否已转永久免费，此类不自动调用 ASF。' if g['kind']=='paid_to_free'
                       else '这是你关注游戏的价格变化，不会自动执行购买或领取。' if g['kind']=='watch_price'
                       else '只是促销或视频线索，需打开链接核实，不能自动领取。' if g['kind'] in ('bilibili_tip','promo_api')
                       else '第三方活动可能需要注册、积分、地区资格或库存，无法通过 ASF 直接领取 Key。')
                if g['kind'] == 'bilibili_tip':
                    # Both links always carried in the QQ message; source is never overwritten by Steam URL.
                    text = (f"🎮 B站 Steam 免费活动｜{g['source']}\n"
                            f"内容：{g['name']}\n"
                            f"Steam：{g['steam_url']}\n"
                            f"B站原始来源：{g['bili_source_url']}\n"
                            f"核验：{g['confidence']}\n"
                            "可领取不等于已永久入库；ASF 可能尝试免费 app/ 或管理员批准的 sub/，状态见待处理区。")
                else:
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

    async def push_auto_review_notifications(self):
        if not self.store.settings()['push_claim_results']:
            return
        for target in self.store.targets():
            if not target['enabled']:
                continue
            for task in self.store.pending_auto_review_pushes(target['id'],limit=4):
                text=(f'⚠ Steam 免费游戏自动领取需接管\n'
                      f'游戏：{task["name"]}\n'
                      f'结果：{task["status"]}；{task["result"][:160]}\n'
                      f'Steam：{task["steam_url"]}\n'
                      f'B站来源：{task["bili_source_url"]}\n'
                      '请在 AstrBot「自动领取与失败接管」面板中选择 AI 分析、重试或手动处理。')
                try:await self.send_group(target,text)
                except Exception as exc:
                    self.errors.append(f'自动领取审核通知失败：{type(exc).__name__}')
                    break
                else:self.store.mark_auto_review_sent(target['id'],task['game_key'])

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
                           f"商店：{ev['url']}\n" +
                           (f"B站原始来源：{ev['bili_source_url']}\n" if ev.get('bili_source_url') else '') +
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
            creator_bili = bool(row and row['kind'] == 'bilibili_tip' and row['bili_origin'] == 'creator'
                               and row['steam_url'] == f'https://store.steampowered.com/app/{row["appid"]}/')
            if not row or not row['approved_subid'] or (row['kind'] != 'steam_candidate' and not creator_bili):
                raise ValueError('请先人工核实并批准 Steam 候选或指定 UP 主活动的有效免费包 SubID')
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

    async def _automatic_claim(self, game, network, *, retry=False):
        """One app per attempt. Steam state is re-read immediately before every ASF call.

        app/ does not establish permanent ownership for 100% promos. For such promos use a
        previously user-approved sub/, otherwise an app/ trial is explicitly unconfirmed.
        """
        key=game['key'];appid=int(game['appid'])
        if not retry and self.store.auto_claim_get(key):return
        async with aiohttp.ClientSession() as session:
            state,reason=await verify_steam(session,appid,network)
        if state == 'free':
            # Ordinary F2P is not a limited Free-to-Keep license. No ASF or failure alert.
            self.store.auto_claim_record(key,appid,'app',appid,'handled',
                'Steam 仅证实普通免费状态，未发现 100% 限免，自动排除且没有调用 ASF')
            return
        if state != 'sale_100':
            self.store.auto_claim_record(key,appid,'app',appid,'failed',
                f'领取前 Steam 重新核验未通过：{reason}')
            return
        subid=int(game.get('approved_subid') or 0)
        kind='sub' if state=='sale_100' and subid>0 else 'app'
        lid=subid if kind=='sub' else appid
        # Save before the network request so a process restart cannot resend blindly.
        self.store.auto_claim_record(key,appid,kind,lid,'checking','向 ASF 提交免费许可证请求中')
        async with self.claim_lock:
            prepared=False
            try:
                prepared=await self.asf_manager.prepare_for_claim()
                status,result=await claim_license(kind,lid,self.asf_manager)
                # A Steam 100% discount may require a dedicated free SubID; app/ can grant
                # a temporary/limited license. Treat ambiguous results as review-worthy.
                if state=='sale_100' and kind=='app' and status=='reported_success':
                    status='submitted'
                    result='ASF 已报告接收 app/ 请求，但 100% 折扣未能证明永久入库；请核查 Free-to-Keep SubID。'+result[:330]
            except Exception as exc:
                status,result='failed',f'{type(exc).__name__}: {str(exc)[:240]}'
            finally:
                if prepared:self.asf_manager.finish_claim()
        self.store.auto_claim_record(key,appid,kind,lid,status,result)

    async def process_unattended_creator_claims(self, network):
        # At most 5 free-license requests each scan; SQLite deduplicates all runs.
        for game in self.store.auto_claim_pending(limit=5):
            try:
                await self._automatic_claim(game,network)
            except Exception as exc:
                self.store.auto_claim_record(game['key'],game['appid'],'app',game['appid'],
                                             'failed',f'自动领取异常：{type(exc).__name__}')
            await asyncio.sleep(.4)

    async def web_review_retry(self):
        body=await request.json(default={})
        key=body.get('key')
        rec=self.store.auto_claim_get(key)
        game=self.store.get_game(key)
        if not rec or not game or rec['status'] not in ('failed','submitted'):
            raise ValueError('找不到允许重试的待审核项目')
        if key in self.review_tasks and not self.review_tasks[key].done():
            raise ValueError('这项任务正在处理')
        async def runner():
            try:await self._automatic_claim(game,SteamNetwork(self.store.settings()),retry=True)
            except Exception as exc:
                self.store.auto_claim_record(key,game['appid'],'app',game['appid'],'failed',f'重试异常：{type(exc).__name__}')
        self.review_tasks[key]=asyncio.create_task(runner(),name='steam-review-retry')
        return json_response({'ok':True,'notice':'已启动重新核验与免费领取，请在待处理区刷新结果'})

    async def web_review_resolve(self):
        body=await request.json(default={})
        return json_response(self.store.auto_claim_resolve(body.get('key')))

    async def web_review_ai(self):
        body=await request.json(default={});key=body.get('key')
        row=self.store.auto_claim_get(key);game=self.store.get_game(key)
        if not row or not game or row['status'] not in ('failed','submitted'):
            raise ValueError('此项目不需要 AI 排障')
        if key in self.review_tasks and not self.review_tasks[key].done():
            raise ValueError('任务正在处理')
        config=self.ai_config.effective()
        if not config.get('api_key'):
            raise ValueError('请先在 B站高级选项配置 AI API Key')
        if row.get('ai_note'):
            raise ValueError('这个失败项已经申请过一次 AI 分析，重新领取后可再次分析')
        async def analyze():
            import aiohttp
            from .steam_freebies.bilibili import PROVIDERS
            provider=str(config.get('provider') or 'openai').lower()
            endpoint=PROVIDERS.get(provider)
            if not endpoint:
                self.store.auto_claim_set_note(key,'不支持该 AI 服务商');return
            # Never upload raw ASF output: it may contain bot names or sensitive diagnostics.
            raw=str(row['result']).lower()
            reason=('网络超时' if 'timeout' in raw or 'connect' in raw else
                    '地区限制' if 'region' in raw or 'country' in raw else
                    '权限拒绝' if 'denied' in raw or 'access' in raw else
                    '无法确认永久许可证' if row['status']=='submitted' else '其他领取错误')
            prompt=('请仅解释 Steam 免费领取的常见原因，给出最多三步排障建议。'
                    '不猜测 SubID、不声称已永久入库，不建议绕过验证。'
                    f'公开 AppID={game["appid"]}；模式={row["license_type"]}；错误类别={reason}。')
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=18)) as session:
                    async with session.post(endpoint,headers={'Authorization':'Bearer '+config['api_key']},
                     json={'model':config.get('model') or 'gpt-4o-mini','max_tokens':220,
                           'messages':[{'role':'user','content':prompt}]}) as response:
                        response.raise_for_status();data=await response.json(content_type=None)
                note=str(data['choices'][0]['message']['content'])[:450]
            except (aiohttp.ClientError,TimeoutError,ValueError,KeyError,IndexError,TypeError):
                note='AI 分析失败，请直接查看 Steam / ASF 记录人工处理'
            self.store.auto_claim_set_note(key,note)
        self.store.auto_claim_set_note(key,'AI 分析已启动，请刷新查看')
        self.review_tasks[key]=asyncio.create_task(analyze(),name='steam-review-ai')
        return json_response({'ok':True,'notice':'AI 排障任务已启动，仅发送公开 AppID、许可证类型和错误类别；不发送 ASF 原始输出或账号凭据'})

    async def process_bili_creator_claims(self, candidates):
        """Only trusted creator-origin links; prior explicit approval of Steam free package required.

        We never infer SubID from AppID, dynamic text or external website links.
        """
        for game in self.store.pending_bili_claims():
            if self.store.auto_claim_get(game['key']):
                # The unattended workflow already owns this claim attempt.
                continue
            try:
                await self.do_claim(game['key'])
            except Exception as exc:
                self.errors.append(f'B站关联的已批准包领取失败：{type(exc).__name__}')

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
            "bili_creators": self.store.bili_creators(),
            "bili_test": self.bili_test_result,
            "ai": self.ai_config.public(),
            "bili_login": self.bili_auth.status(),
            "steam_network": proxy_status(self.store.settings()),
            "test_results": self.last_test_result,
            "delivery_last": self.store.delivery_overview(),
            "pending_counts": {str(t["id"]): len(self.store.pending_pushes(t["id"],max_rows=100)) for t in targets if t["enabled"]},
            "itad_configured": bool(os.getenv("ASTR_STEAM_ITAD_API_KEY")),
            "last_scan": self.last_scan,
            "last_items": self.last_items,
            "scan_running": self.scan_lock.locked() or bool(self.manual_scan_task and not self.manual_scan_task.done()),
            "errors": self.errors[-10:],
            "claim_configured": bool(os.getenv('ASTR_STEAM_ASF_BOT')) or bool(self.asf_manager.settings()['bot_name']),
            "asf": self.asf_manager.status(),
            "claim_events": self.store.latest_claim_events(),
            "auto_claims": self.store.auto_claim_overview(),
            "disclaimer": "无人值守只尝试 Steam 免费许可证；ASF 接收不代表已永久入库。限免如需 Free-to-Keep SubID，失败后进入审核区。",
        }

    async def web_snapshot(self):
        return json_response(self.snapshot())

    async def web_settings(self):
        body = await request.json(default={})
        return json_response({"settings": self.store.update_settings(body)})

    async def web_scan(self):
        # A synchronous multi-source scan can outlive AstrBot's HTTP gateway deadline.
        # Queue the work and return immediately; clients poll /snapshot for completion.
        if self.scan_lock.locked() or (self.manual_scan_task is not None and not self.manual_scan_task.done()):
            raise ValueError("正在扫描，请等待当前任务完成")
        self.manual_scan_task = asyncio.create_task(self._manual_scan(), name='steam-freebies-manual-scan')
        return json_response({'ok': True, 'notice': '扫描已开始，将在后台继续；请稍后刷新查看结果'})

    async def _manual_scan(self):
        try:
            await self.scan_and_process()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.errors = [f'手动扫描失败：{type(exc).__name__}']
            logger.warning('[Steam喜加一] 手动扫描失败：%s', type(exc).__name__)

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

    async def web_ai_settings(self):
        body = await request.json(default={})
        return json_response({'ok':True,'ai':self.ai_config.save(body),
                              'notice':'AI 配置已保存到私有目录，不会返回 API Key；是否调用由 AI 开关控制'})

    async def web_price_unwatch(self):
        body = await request.json(default={})
        return json_response(self.store.remove_price_watch(body.get('appid')))

    async def web_bili_add(self):
        body = await request.json(default={})
        video = extract_bvid(body.get('video'))
        if video:
            mid, name = await resolve_video_owner(video, auth=self.bili_auth)
        else:
            mid, name = body.get('mid'), str(body.get('name') or '')
            if type(mid) is not int or mid <= 0:
                raise ValueError('请填写 B站 BV 视频链接或 UP 主 UID')
            name = name[:80] if name else f'UP {mid}'
        return json_response(self.store.add_bili_creator(mid, name))

    async def web_bili_remove(self):
        body = await request.json(default={})
        return json_response(self.store.remove_bili_creator(body.get('mid')))

    async def web_bili_test(self):
        body = await request.json(default={})
        mid = body.get('mid')
        if type(mid) is not int or mid not in {x['mid'] for x in self.store.bili_creators()}:
            raise ValueError('请先订阅要测试的 UP 主')
        if self.bili_test_task and not self.bili_test_task.done():
            raise ValueError('上一次 UP 主测试仍在进行')
        self.bili_test_result = {'state': 'running', 'mid': mid, 'items': [], 'errors': [],
                                 'notice': '正在读取视频和动态、提取 Steam 链接并核验（只测试，不推送、不领取）'}
        self.bili_test_task = asyncio.create_task(self._run_bili_test(mid), name='bili-test')
        return json_response({'ok': True, 'notice': '测试已在后台启动，请查看检测结果'})

    async def _run_bili_test(self, mid):
        report=[]
        try:
            events, errors = await fetch_bilibili_tips(
                self.store, auth=self.bili_auth, network=SteamNetwork(self.store.settings()),
                preview=True, creator_mid=mid, report=report)
            self.bili_test_result = {'state':'done', 'mid':mid, 'items':report[:30],
                                     'eligible':len(events), 'errors':errors[:8],
                                     'notice':'检测完成；本次测试未发送 QQ，也未调用 ASF 或 AI'}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.bili_test_result = {'state':'failed', 'mid':mid, 'items':report[:30],
                                     'errors':[f'测试失败：{type(exc).__name__}'],
                                     'notice':'请检查容器访问 B站和 Steam 的网络'}

    async def web_bili_test_status(self):
        return json_response(self.bili_test_result)

    async def web_bili_login_start(self):
        return json_response(self.bili_auth.qr_begin())

    async def web_bili_login_prepare(self):
        return json_response(self.bili_auth.qr_prepare_status())

    async def web_bili_login_poll(self):
        return json_response(await self.bili_auth.qr_poll())

    async def web_bili_session_import(self):
        body = await request.json(default={})
        return json_response(await self.bili_auth.import_session(body.get('cookie')))

    async def web_bili_session_check(self):
        return json_response(await self.bili_auth.verify_session())

    async def web_bili_logout(self):
        return json_response(self.bili_auth.logout())

    async def web_bili_sms_captcha(self):
        return json_response(await self.bili_auth.sms_captcha())

    async def web_bili_sms_send(self):
        body = await request.json(default={})
        return json_response(await self.bili_auth.sms_send(
            body.get('tel'), body.get('cid'), body.get('challenge'),
            body.get('validate'), body.get('seccode')))

    async def web_bili_sms_login(self):
        body = await request.json(default={})
        return json_response(await self.bili_auth.sms_login(body.get('code')))

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
        import time
        clock = time.monotonic()
        last = self.test_sent_at.get(target_id, 0)
        if last and clock - last < 30:
            raise ValueError(f"测试防刷屏：请 {max(1,int(30-(clock-last)))} 秒后再试；正式推送不受影响")
        try:
            await self.send_group(row, "✅ Steam 喜加一 QQ 测试消息：当前适配器可主动发送。此消息仅作连通性验证；老活动已去重，不会重复推送。")
        except Exception as exc:
            reason = f"{type(exc).__name__}"
            self.last_test_result[str(target_id)] = {'ok':False, 'at':datetime.now(timezone.utc).isoformat(timespec='seconds'), 'detail':reason}
            raise ValueError(f"QQ 测试发送失败：{reason}；请核对 NapCat 适配器状态及群主动发送权限") from exc
        self.test_sent_at[target_id] = clock
        stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
        self.last_test_result[str(target_id)] = {'ok':True, 'at':stamp, 'detail':'已提交到 QQ 适配器'}
        return json_response({'ok':True,'at':stamp,'notice':'QQ 测试已向适配器提交成功。没有新活动时，正式推送不会重复发送旧消息。'})

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
        if self.manual_scan_task and not self.manual_scan_task.done():
            self.manual_scan_task.cancel()
            try:
                await self.manual_scan_task
            except asyncio.CancelledError:
                pass
        # Do not leave an in-flight login preparation HTTP request on plugin unload.
        self.bili_auth.cancel_qr_preparation()
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        await self.asf_manager.close()
        self.store.db.close()
