"""AstrBot QQ Steam freebies: discovery -> dedup -> push -> optional approved ASF claim."""
import asyncio
import os
import time
from datetime import datetime, timezone

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star, StarTools
from astrbot.api.web import error_response, json_response, request

from .steam_freebies.asf import claim_sub
from .steam_freebies.sources import fetch_candidates
from .steam_freebies.store import Store

PLUGIN = "astrbot_plugin_steam_freebies"
SUPPORTED_QQ = {"aiocqhttp", "qq_official", "qq_official_webhook", "qqofficial"}
OFFICIAL_QQ = {"qq_official", "qq_official_webhook", "qqofficial"}


class Main(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.store = Store(StarTools.get_data_dir(PLUGIN) / "freebies.sqlite3")
        self.scan_lock = asyncio.Lock()
        self.claim_lock = asyncio.Lock()
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
            self.errors = errors
            self.last_scan = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.last_items = len(candidates)
            if candidates:
                self.store.upsert_games(candidates)
            # If all providers failed, don't treat that as an empty successful scan.
            if self.store.settings()["push_enabled"] and candidates:
                await self.push_to_groups()
            if self.store.settings()["auto_claim_enabled"] and candidates:
                await self.process_approved_claims()
            return {"candidates": len(candidates), "errors": errors}

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
                kind = "Steam 100% 折扣候选" if g["kind"] == "steam_candidate" else "第三方 Steam 游戏赠送"
                text = (f"🎁 Steam 喜加一线索｜{kind}\n"
                        f"游戏：{g['name']}\n原价：{g['original_price'] or '未知'}\n"
                        f"截止：{g['end_date'] or '以活动页面为准'}\n"
                        f"链接：{g['url']}\n提示：{g['confidence']}\n"
                        "请人工确认地区限制和是否永久入库。")
                try:
                    await self.send_group(target, text)
                except Exception as exc:
                    self.errors.append(f"群 {target['group_id']} 推送失败: {type(exc).__name__}")
                    break
                else:
                    self.store.marked(target["id"], g["key"])
                    await asyncio.sleep(1)

    async def do_claim(self, key):
        async with self.claim_lock:
            row = self.store.get_game(key)
            if not row or row["kind"] != "steam_candidate" or not row["approved_subid"]:
                raise ValueError("先在面板为 Steam 商店活动人工确认并批准正确 SubID")
            subid = int(row["approved_subid"])
            # No automatic repeated attempts after a recorded attempt; manually triggering can retry.
            try:
                result = await claim_sub(subid)
                status = "submitted"
            except Exception as exc:
                status, result = "failed", f"{type(exc).__name__}: {str(exc)[:160]}"
            self.store.claim_record(key, subid, status, result)
            return {"status": status, "result": result, "notice": "submitted 仅代表 ASF 命令接收，必须检查 Steam 许可证"}

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
            "last_scan": self.last_scan,
            "last_items": self.last_items,
            "errors": self.errors[-10:],
            "claim_configured": bool(os.getenv("ASTR_STEAM_ASF_BOT")),
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
        self.store.db.close()
