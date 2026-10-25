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
// AstrBot Plugin Views use a sandboxed iframe without allow-modals.
// Native alert/confirm/prompt are not available; use an in-page, accessible dialog.
let activeDialog = false;
function askUser(message, options = {}) {
  if (activeDialog) return Promise.resolve(null);
  activeDialog = true;
  const overlay = $('action-overlay');
  const form = $('action-form');
  const input = $('action-input');
  $('action-message').textContent = message;
  $('action-title').textContent = options.title || '确认操作';
  $('action-confirm').textContent = options.confirmText || '确认';
  input.hidden = !options.input;
  input.required = Boolean(options.input);
  input.value = options.input ? String(options.value || '') : '';
  input.placeholder = options.placeholder || '';
  overlay.hidden = false;
  (options.input ? input : $('action-confirm')).focus();
  return new Promise(resolve => {
    const finish = value => {
      overlay.hidden = true;
      activeDialog = false;
      form.removeEventListener('submit', submit);
      $('action-cancel').removeEventListener('click', cancel);
      overlay.removeEventListener('keydown', keyboard);
      resolve(value);
    };
    const submit = ev => { ev.preventDefault(); finish(options.input ? input.value.trim() : true); };
    const cancel = () => finish(null);
    const keyboard = ev => { if (ev.key === 'Escape') { ev.preventDefault(); cancel(); } };
    form.addEventListener('submit', submit);
    $('action-cancel').addEventListener('click', cancel);
    overlay.addEventListener('keydown', keyboard);
  });
}
function asfFeedback(message, isError = false) {
  const node = $('asf-operation');
  node.textContent = String(message);
  node.hidden = false;
  node.classList.toggle('error', isError);
}
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
      const input=await askUser('输入已核实的 Free-to-Keep 永久免费包 SubID。仅填写当前有效的免费包；错误的 SubID 不能自动辨别。', {input:true, value:game.approved_subid||'', title:'批准免费包', confirmText:'批准 SubID'});
      if(input===null)return;
      if(!/^\d{1,10}$/.test(input)||Number(input)<1||Number(input)>2147483647){toast('SubID 必须是有效正整数');return;}
      await apiAction('approve',{key:game.key,subid:Number(input)},'SubID 已批准，若启用自动领取将在下次扫描尝试。');
    }); actions.append(approve);
    if(game.approved_subid){
      const claim=e('button',`通过 ASF 领取 · ${game.approved_subid}`,'btn primary');
      claim.addEventListener('click',async()=>{
        if(!await askUser('向 ASF 提交一次领取请求。ASF 报告成功也不等于账号已永久拥有游戏。', {title:'确认领取',confirmText:'执行领取'}))return;
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
  if(a.environment){
    const env=a.environment;
    status.push(`运行环境：${env.container?'Docker 容器':'非 Docker'}`);
    if(env.free_mb!==null && env.free_mb!==undefined)status.push(`可用磁盘：${env.free_mb} MB`);
    if(!env.writable)status.push('警告：ASF 数据目录不可写');
  }
  if(a.start_error){
    status.push(`启动诊断：${a.start_error}`);
    asfFeedback(`ASF 启动失败：${a.start_error}`,true);
  } else if(a.error){
    status.push(`安装异常：${a.error}`);
    asfFeedback(`ASF 安装失败：${a.error}`,true);
  } else if(a.running){
    asfFeedback('ASF 进程已启动。首次使用仍需要在 ASF 中授权登录 Steam 账号。');
  } else if(a.install_state==='installed'){
    asfFeedback(`ASF ${a.version||''} 安装完成。现在可以点击「启动 ASF」。`);
  }
  $('asf-status').textContent=status.join(' · ');
  $('start-asf').disabled=!a.installed||a.running;
  $('stop-asf').disabled=!a.running;
  $('install-asf').disabled=['downloading','verifying','extracting'].includes(a.install_state)||a.running;
  $('asf-mode').value=a.settings?.mode||'external';
  $('asf-download-mode').value=a.settings?.download_mode||'auto';
  $('asf-bot').value=a.settings?.bot_name||'';
  $('asf-boot').checked=Boolean(a.settings?.start_on_boot);
  const profile=a.settings?.profile||'compatible';
  for(const input of document.querySelectorAll('input[name="asf-profile"]'))input.checked=input.value===profile;
  $('asf-on-demand').checked=a.settings?.on_demand!==false;
  $('asf-idle').value=String(a.settings?.idle_minutes||10);
  const run = a.running_profile || '';
  const runLabel = {performance:'高性能 / 完整 ICU',compatible:'低资源兼容 / 绕过 ICU'};
  $('asf-runtime-note').textContent =
    `已选择：${runLabel[profile]} · ${a.running?'当前运行：'+(runLabel[run]||'未知'):'当前未运行'}` +
    (a.rss_mb!==null && a.rss_mb!==undefined?` · ASF 实际常驻内存：${a.rss_mb} MB`:'') +
    (a.idle_timer_active?' · 空闲停止倒计时中':'') +
    (a.running&&run!==profile?' · 注意：配置变更需重启 ASF 才生效':'');
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
async function installASF(){
  const b=$('install-asf');
  if(b.disabled)return;
  // The installer button is itself an explicit installation action. In particular,
  // never gate it behind native window.confirm: iframe sandbox silently blocks it.
  b.disabled=true;
  asfFeedback('正在向 AstrBot 提交 ASF 安装请求…');
  try {
    if(!bridge)throw new Error('插件页面桥接未就绪，请从 AstrBot 插件详情打开。');
    const result=await bridge.apiPost('asf/install',{});
    if(!result?.ok)throw new Error(result?.message||'服务器没有确认安装请求');
    asfFeedback('安装任务已启动；会自动下载、校验并显示进度。无需在自己的电脑下载 ASF。');
    await reload();
  }catch(error){
    asfFeedback(`安装请求失败：${error?.message||String(error)}。请核对 AstrBot 版本、插件是否已重载及管理员权限。`,true);
    b.disabled=false;
  }
}
$('install-asf').addEventListener('click',installASF);
$('start-asf').addEventListener('click',async()=>{
  const button=$('start-asf');
  if(button.disabled)return;
  button.disabled=true;
  asfFeedback('正在启动 ASF，检测容器运行时与进程状态…');
  try{
    await bridge.apiPost('asf/start',{});
    asfFeedback('ASF 进程已启动；可继续进行 Steam Bot 登录配置。');
  }catch(error){
    asfFeedback(`ASF 启动失败：${error?.message||String(error)}`,true);
  }finally{
    await reload();
    if(!data?.asf?.running)button.disabled=false;
  }
});
$('stop-asf').addEventListener('click',()=>apiAction('asf/stop',{},'托管 ASF 已停止。'));
$('create-bot').addEventListener('click',()=>{
  const bot_name=$('asf-bot').value.trim();
  const steam_login=$('steam-login').value.trim();
  if(!bot_name||!steam_login){toast('请填写 ASF Bot 名称和 Steam 登录名。');return;}
  askUser('将创建不含 Steam 密码的本地 ASF Bot 配置。仍需通过 ASF 界面完成 Steam Guard 登录验证。',{title:'创建 Steam Bot 配置',confirmText:'创建配置'}).then(async ok=>{
    if(!ok)return;
    const result=await apiAction('asf/bot',{bot_name,steam_login},'已在本机创建 Bot 配置，下一步请到 ASF-ui 配置登录和启用。');
    if(result)$('steam-login').value='';
  });
});
$('asf-save').addEventListener('click',()=>apiAction('asf/settings',{
  mode:$('asf-mode').value,bot_name:$('asf-bot').value.trim(),start_on_boot:$('asf-boot').checked,
  download_mode:$('asf-download-mode').value,
  profile:document.querySelector('input[name="asf-profile"]:checked')?.value||'compatible',
  on_demand:$('asf-on-demand').checked,idle_minutes:Number($('asf-idle').value)
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


// Embedded ASF control panel: all authentication goes through the AstrBot View bridge
// to a narrow, authenticated localhost IPC client. No direct browser access to :1242.
async function refreshEmbeddedASF() {
  const node=$('asf-ui-status');
  try {
    const status=await bridge.apiGet('asf/ui/status');
    const connected=status.connected?'已连接 Steam':'尚未确认登录 Steam';
    const enabled=status.enabled?'已启用':'未启用';
    node.textContent=status.message ||
      `Bot：${status.bot_name||'未配置'} · ${status.configured?'配置已创建':'未创建配置'} · ${enabled} · ${status.running?'ASF 运行中':'ASF 未运行'} · ${connected}` +
      (status.required_input?` · ASF 要求输入：${status.required_input}`:'') +
      (status.status_note?` · ${status.status_note}`:'');
    $('asf-ui-enable').textContent=status.enabled?'禁用 Bot':'启用 Bot';
    $('asf-ui-enable').dataset.next=status.enabled?'false':'true';
    for(const id of ['asf-ui-enable','asf-ui-bot-start','asf-ui-bot-stop'])
      $(id).disabled=!status.running||!status.configured;
    if(status.required_input && [...$('asf-ui-type').options].some(o=>o.value===status.required_input))
      $('asf-ui-type').value=status.required_input;
    return status;
  }catch(error){
    node.textContent='无法获取 ASF 状态：'+(error?.message||String(error));
    return null;
  }
}
async function embeddedAction(endpoint, body){
  try{
    const response=await bridge.apiPost(endpoint,body);
    $('asf-ui-status').textContent=response.notice||'请求已执行';
    await refreshEmbeddedASF();
    return response;
  }catch(err){
    $('asf-ui-status').textContent='操作失败：'+(err?.message||String(err));
    return null;
  }
}
$('asf-ui-refresh').addEventListener('click',refreshEmbeddedASF);
$('asf-ui-enable').addEventListener('click',async()=>{
  const enabled=$('asf-ui-enable').dataset.next==='true';
  const accepted=await askUser(enabled?'启用本地 ASF Bot 后它将允许连接 Steam。':'停用当前 ASF Bot？',
    {title:'确认 Bot 操作',confirmText:enabled?'启用':'停用'});
  if(accepted)await embeddedAction('asf/ui/enable',{enabled});
});
$('asf-ui-bot-start').addEventListener('click',()=>embeddedAction('asf/ui/control',{action:'Start'}));
$('asf-ui-bot-stop').addEventListener('click',()=>embeddedAction('asf/ui/control',{action:'Stop'}));
$('asf-ui-send').addEventListener('click',async()=>{
  const kind=$('asf-ui-type').value;
  const input=$('asf-ui-secret');
  const value=input.value;
  if(!$('asf-ui-trust').checked){
    $('asf-ui-status').textContent='请先确认访问 AstrBot 的网络安全。优先使用 HTTPS。';return;
  }
  if(!value || value.length>128){$('asf-ui-status').textContent='请填写有效验证信息（最长 128 字符）。';return;}
  input.value='';
  // The secret is only sent in this direct bridge request; it is never written to page history.
  await embeddedAction('asf/ui/input',{type:kind,value});
});
// Refresh once after AstrBot has injected its View bridge and session credentials.
if(bridge)bridge.ready().then(refreshEmbeddedASF).catch(()=>{});
