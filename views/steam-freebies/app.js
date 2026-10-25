const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
const $ = id => document.getElementById(id);
const e = (tag, content, cls) => {
  const node = document.createElement(tag);
  if (content !== undefined) node.textContent = String(content);
  if (cls) node.className = cls;
  return node;
};
let data = null;
let filter = 'all';
let search = '';
const labels = {submitted:'已提交 · 待核验',reported_success:'ASF 报告成功 · 待核验',failed:'领取失败'};
function toast(value){ const node=$('notice'); node.textContent=String(value); node.hidden=false; }
async function apiAction(endpoint, body, ok){
  try { const result = await bridge.apiPost(endpoint,body); toast(ok||result.notice||'操作已执行'); await reload(); return result; }
  catch(err) { toast('操作失败：'+err.message); return null; }
}
function makeGame(game){
  const card=e('article',undefined,'game');
  const top=e('div',undefined,'game-top');
  top.append(e('span',game.kind==='steam_candidate'?'Steam 商店折扣候选':'第三方赠 Key / 活动',game.kind==='steam_candidate'?'chip steam':'chip'));
  top.append(e('span',game.source,'meta')); card.append(top);
  card.append(e('div',game.name,'game-title'),e('div',`原价：${game.original_price||'未知'} · 截止：${game.end_date||'以活动页为准'}`,'meta'));
  card.append(e('p',game.confidence));
  const actions=e('div',undefined,'actions');
  const url=e('a','打开领取页面 ↗');url.href=game.url;url.target='_blank';url.rel='noopener noreferrer';actions.append(url);
  if(game.kind==='steam_candidate'){
    const approve=e('button','批准免费包 SubID','btn ghost');
    approve.addEventListener('click',async()=>{
      const input=prompt('请输入已在 Steam 官方页面或可信数据源确认的免费永久领取包 SubID：',game.approved_subid||'');
      if(input===null) return;
      if(!/^\d{1,10}$/.test(input)||Number(input)<1||Number(input)>2147483647){toast('SubID 必须是有效正整数');return;}
      if(!confirm('已确认这属于当前有效的 Free-to-Keep 免费永久领取包？'))return;
      await apiAction('approve',{key:game.key,subid:Number(input)},'SubID 已批准，若启用自动领取将在下次扫描尝试。');
    }); actions.append(approve);
    if(game.approved_subid){
      const claim=e('button',`通过 ASF 领取 · ${game.approved_subid}`,'btn primary');
      claim.addEventListener('click',async()=>{
        if(!confirm('执行 Steam 免费包领取？ASF 成功响应不代表账号已实际获得许可证。'))return;
        const result=await apiAction('claim',{key:game.key});
        if(result)toast(`${labels[result.status]||result.status}\n${result.result}\n请核对 Steam 账号的实际许可证。`);
      });actions.append(claim);
    }
    if(game.claim_status)card.append(e('div',`上次 ASF 反馈：${labels[game.claim_status]||game.claim_status} · ${(game.claim_result||'').slice(0,140)}`,'record-text'));
  }
  card.append(actions);return card;
}
function showGames(){
  if(!data)return;
  const games=data.games.filter(g=>(filter==='all'||g.kind===filter)&&(!search||g.name.toLowerCase().includes(search)));
  $('activity-count').textContent=`显示 ${games.length} 条 / 最近缓存 ${data.games.length} 条`;
  $('games').replaceChildren(...(games.length?games.map(makeGame):[e('p','没有符合当前筛选条件的免费活动。','empty')]));
}
function showClaimHistory(){
  const events=data.claim_events||[];
  const items=events.map(x=>{
    const item=e('div',undefined,'activity-item'),left=e('div');
    left.append(e('strong',x.name||x.game_key),e('small',`SubID ${x.subid} · ${new Date(x.at).toLocaleString()} · ${(x.result||'').slice(0,180)}`));
    item.append(left,e('span',labels[x.status]||x.status,`result-status ${x.status}`));return item;
  });
  $('claim-history').replaceChildren(...(items.length?items:[e('p','还没有 ASF 领取记录。','empty')]));
}
function showTargets(){
  const targets=data.targets||[];
  const rows=targets.map(t=>{
    const item=e('div',undefined,'activity-item');const left=e('div');
    left.append(e('strong',`QQ群 ${t.group_id}`),e('small',`${t.platform_id} · ${t.official?'QQ 官方':'OneBot'} · ${t.enabled?'推送已启用':'已暂停'}`));
    item.append(left);
    if(t.enabled){const button=e('button','发送测试消息','btn ghost');button.addEventListener('click',()=>apiAction('test-send',{target_id:t.id},'已向该群执行测试推送'));item.append(button);}
    return item;
  });
  $('target-list').replaceChildren(...(rows.length?rows:[e('p','暂未绑定QQ群，请在目标群发送 /喜加一绑定。','empty')]));
}
function showASF(){
  const a=data.asf||{};
  $('asf-badge').textContent=a.running?'运行中':a.installed?'已安装 · 未运行':'尚未安装';
  $('asf-badge').className=`pill ${a.running?'ok':a.installed?'warn':'neutral'}`;
  const status=[`平台包：${a.variant||'未知'}`,`安装状态：${a.install_state||'未操作'}`];
  if(a.version)status.push(`版本：${a.version}`);
  if(a.metadata_source)status.push(`校验数据：${a.metadata_source}`);
  if(a.download_source)status.push(`下载源：${a.download_source}`);
  if(a.download_bytes && ['downloading','verifying','extracting'].includes(a.install_state))
    status.push(`已接收：${(a.download_bytes / 1024 / 1024).toFixed(1)} MB` +
                (a.download_total?` / ${(a.download_total / 1024 / 1024).toFixed(1)} MB`:''));
  if(a.error)status.push(`异常：${a.error}`);
  $('asf-status').textContent=status.join(' · ');
  $('start-asf').disabled=!a.installed||a.running;
  $('stop-asf').disabled=!a.running;
  $('install-asf').disabled=['downloading','verifying','extracting'].includes(a.install_state)||a.running;
  $('asf-mode').value=a.settings?.mode||'external';
  $('asf-download-mode').value=a.settings?.download_mode||'auto';
  $('asf-bot').value=a.settings?.bot_name||'';
  $('asf-boot').checked=Boolean(a.settings?.start_on_boot);
}
function render(){
  $('total').textContent=data.games.length;
  $('steam-count').textContent=data.games.filter(g=>g.kind==='steam_candidate').length;
  $('key-count').textContent=data.games.filter(g=>g.kind==='third_party').length;
  $('groups').textContent=data.targets.filter(x=>x.enabled).length;
  $('last').textContent=data.last_scan?`最近扫描：${new Date(data.last_scan).toLocaleString()}`:'尚未扫描';
  $('scan-status').textContent=data.last_scan?'扫描已执行':'等待首次扫描';
  $('scan-status').className=`pill ${data.last_scan?'ok':'neutral'}`;
  const errorCount=(data.errors||[]).length;
  $('source-status').textContent=errorCount?`${errorCount} 项数据源/通知异常，请查看下面详情`:'未发现数据源异常';
  $('errors').hidden=!errorCount;
  $('errors').textContent=(data.errors||[]).join('\n');
  $('interval').value=data.settings.scan_minutes;
  $('push').checked=data.settings.push_enabled;
  $('push-steam').checked=data.settings.push_steam;
  $('push-key').checked=data.settings.push_third_party;
  $('push-result').checked=data.settings.push_claim_results;
  $('autoclaim').checked=data.settings.auto_claim_enabled;
  showGames(); showClaimHistory(); showTargets(); showASF(); syncAsfProgress();
}
async function reload(){
  if(!bridge)return;
  try{data=await bridge.apiGet('snapshot');render();}
  catch(err){toast('控制台连接失败：'+err.message);}
}
$('refresh').addEventListener('click',reload);
$('scan').addEventListener('click',()=>apiAction('scan',{},'已完成一次扫描，请查看最新发现和数据源提示。'));
$('save').addEventListener('click',()=>apiAction('settings',{
  scan_minutes:Number($('interval').value),push_enabled:$('push').checked,
  push_steam:$('push-steam').checked,push_third_party:$('push-key').checked,
  push_claim_results:$('push-result').checked,auto_claim_enabled:$('autoclaim').checked
},'推送和扫描设置已保存。'));
for(const button of document.querySelectorAll('[data-filter]')){
  button.addEventListener('click',()=>{
    filter=button.dataset.filter;
    for(const node of document.querySelectorAll('[data-filter]'))node.classList.toggle('selected',node===button);
    showGames();
  });
}
$('search').addEventListener('input',ev=>{search=ev.target.value.trim().toLowerCase();showGames();});
$('install-asf').addEventListener('click',()=>{
  if(confirm('自动下载 ASF 并安装到 AstrBot 私有数据目录？将按当前设置使用加速镜像或官方源，并且严格核验官方 SHA256。'))
    apiAction('asf/install',{},'已开始下载。页面会自动更新下载源及校验进度。');
});
$('start-asf').addEventListener('click',()=>apiAction('asf/start',{},'托管 ASF 已启动。'));
$('stop-asf').addEventListener('click',()=>apiAction('asf/stop',{},'托管 ASF 已停止。'));
$('create-bot').addEventListener('click',()=>{
  const bot_name=$('asf-bot').value.trim();
  const steam_login=$('steam-login').value.trim();
  if(!bot_name||!steam_login){toast('请填写 ASF Bot 名称和 Steam 登录名。');return;}
  if(!confirm('只创建本地 ASF Bot 文件，不保存 Steam 密码，也不会自动登录。稍后需到 ASF-ui 完成账号验证。'))return;
  apiAction('asf/bot',{bot_name,steam_login},'已在本机创建 Bot 配置，下一步请到 ASF-ui 配置登录和启用。');
  $('steam-login').value='';
});
$('asf-save').addEventListener('click',()=>apiAction('asf/settings',{
  mode:$('asf-mode').value,bot_name:$('asf-bot').value.trim(),start_on_boot:$('asf-boot').checked,
  download_mode:$('asf-download-mode').value
},'ASF 连接设置已保存。'));
const navLinks=[...document.querySelectorAll('.sidebar nav a')];
for(const link of navLinks)link.addEventListener('click',()=>{for(const x of navLinks)x.classList.toggle('active',x===link);});
$('clock').textContent=new Date().toLocaleDateString('zh-CN',{year:'numeric',month:'long',day:'numeric'});
if(bridge)bridge.ready().then(reload).catch(err=>toast('面板桥接连接失败：'+err.message));
else toast('请从已登录的 AstrBot 插件详情页打开此控制台。');

// Only poll while managed ASF is actively downloading; avoid unnecessary dashboard traffic.
let asfPoll = null;
function syncAsfProgress(){
  const active = ['downloading','verifying','extracting'].includes(data?.asf?.install_state);
  if(active && asfPoll===null)asfPoll=setInterval(reload,2500);
  if(!active && asfPoll!==null){clearInterval(asfPoll);asfPoll=null;}
}
