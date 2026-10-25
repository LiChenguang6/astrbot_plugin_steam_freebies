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
  top.append(e('span',({steam_candidate:'Steam 商店折扣候选',third_party:'第三方赠 Key / 活动',paid_to_free:'付费转免费候选',promo_api:'促销 API 线索',watch_price:'关注价格变化',bilibili_tip:'B站待核验线索'}[game.kind]||'未知活动'),game.kind==='third_party'?'chip':'chip steam'));
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
    if(t.enabled){const button=e('button','发送测试消息','btn ghost');button.addEventListener('click',()=>apiAction('test-send',{target_id:t.id}));item.append(button);}
    const summary=data.test_results?.[String(t.id)];
    const delivery=data.delivery_last?.[String(t.id)];
    const detail=e('small',`待推送 ${data.pending_counts?.[String(t.id)]??0} 条（去重后） · 最近正式推送：${delivery?new Date(delivery).toLocaleString():'暂无'}`+(summary?` · 最近测试：${summary.ok?'已发送':'失败'}（${new Date(summary.at).toLocaleString()}）`:''));
    left.append(detail);
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
  $('scan-status').textContent=data.scan_running?'正在扫描数据源…':data.last_scan?'扫描已完成':'等待首次扫描';
  $('scan-status').className=`pill ${data.scan_running?'neutral':data.last_scan?'ok':'neutral'}`;
  $('scan').disabled=Boolean(data.scan_running);
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
  $('price-monitor').checked=data.settings.price_monitor_enabled;
  $('push-convert').checked=data.settings.push_paid_to_free;
  $('push-watch-prices').checked=data.settings.push_watch_prices;
  $('bili-enabled').checked=data.settings.bili_enabled;
  $('push-bilibili').checked=data.settings.push_bilibili;
  $('bili-ai-enabled').checked=data.settings.bili_ai_enabled;
  $('bili-ai-calls').value=String(data.settings.bili_ai_calls??2);
  $('steam-proxy-mode').value=data.settings.steam_proxy_mode||'auto';
  if(document.activeElement!==$('steam-proxy-url'))$('steam-proxy-url').value=data.settings.steam_proxy_url||'';
  $('steam-search-fallback').checked=Boolean(data.settings.steam_search_fallback);
  $('steam-network-status').textContent='Steam 请求：'+(data.steam_network?.via||'直连')+
    ' · '+(data.settings.steam_search_fallback?'网页搜索后备源开启':'网页搜索后备源已关闭（推荐）');
  if(document.activeElement!==$('bili-keywords'))$('bili-keywords').value=data.settings.bili_keywords||'';
  showGames(); showClaimHistory(); showTargets(); showASF(); showPrices(); showBili(); syncAsfProgress();
}
async function reload(){
  if(!bridge)return;
  try{data=await bridge.apiGet('snapshot');render();}
  catch(err){toast('控制台连接失败：'+err.message);}
}
function showPrices(){
  const prices=data?.prices||{total:0,paid:0,free:0,watch:[]};
  $('itad-status').textContent=data.itad_configured?'ITAD 已配置':'ITAD 未配置（可选）';
  $('price-status').textContent=`正在关注 ${prices.watch?.length||0} 个 AppID · 只检查你的关注列表，不再随机抽样`;
  const rows=(prices.watch||[]).map(item=>{
    const row=e('div',undefined,'activity-item');
    const side=e('div');
    side.append(e('strong',item.name),e('small',`AppID ${item.appid} · ${item.state==='paid'? '收费 '+((item.amount||0)/100).toFixed(2)+' '+(item.currency||'') : item.state==='free'?'当前免费':'尚未采集'} · 手动关注`));
    const url=e('a','Steam ↗'); url.href=`https://store.steampowered.com/app/${item.appid}/`;url.target='_blank';url.rel='noopener noreferrer';
    const remove=e('button','移除','btn ghost');remove.type='button';remove.addEventListener('click',()=>apiAction('price/unwatch',{appid:item.appid},'已移除关注'));
    row.append(side,url,remove);return row;
  });
  $('watch-list').replaceChildren(...(rows.length?rows:[e('p','暂无价格记录；可手动添加 AppID，然后点击立即扫描。','empty')]));
}
function showBili(){
  const creators=data.bili_creators||[];
  const ai=data.ai||{};
  $('bili-ai-status').textContent=ai.configured?`AI Key 已配置 · ${ai.provider||'openai'}`:'AI 默认关闭';
  const login=data.bili_login||{};
  $('bili-login-status').textContent=login.status||'未登录';
  $('bili-login-status').className='pill '+(login.configured?'ok':'neutral');
  $('bili-login-logout').disabled=!login.configured;
  $('ai-provider').value=ai.provider||'openai';
  if(document.activeElement!==$('ai-model'))$('ai-model').value=ai.model||'gpt-4o-mini';
  $('bili-status').textContent=`已订阅 ${creators.length} 位 UP 主 · ${data.settings.bili_enabled?'B站监控已开启':'B站监控已关闭'} · ${data.settings.bili_ai_enabled?'AI 辅助已开启':'AI 不消耗 Token'}`;
  const rows=creators.map(creator=>{
    const item=e('div',undefined,'activity-item');
    const left=e('div');left.append(e('strong',creator.name),e('small',`UID: ${creator.mid}`));
    const rm=e('button','取消订阅','btn ghost');rm.type='button';rm.addEventListener('click',()=>apiAction('bili/remove',{mid:creator.mid}));
    item.append(left,rm);return item;
  });
  $('bili-creators').replaceChildren(...(rows.length?rows:[e('p','还没有订阅的 UP 主。','empty')]));
}
$('ai-save').addEventListener('click',async()=>{
  const key=$('ai-key').value.trim();
  const result=await apiAction('ai/settings',{provider:$('ai-provider').value,model:$('ai-model').value.trim(),...(key?{api_key:key}:{})});
  $('ai-key').value='';
  if(result)toast('AI Key 已保存在 AstrBot 私有目录；开启 AI 辅助后才可能消耗 Token');
});
$('ai-clear').addEventListener('click',async()=>{
  if(!await askUser('确定删除插件本地保存的 AI Key？Docker 环境变量里的 Key 不受此操作影响。',{title:'清除 AI Key'}))return;
  await apiAction('ai/settings',{clear_key:true});
  $('ai-key').value='';
});
$('bili-add').addEventListener('click',async()=>{
  const video=$('bili-video').value.trim();
  if(!/BV[0-9a-zA-Z]{10}/.test(video)){toast('请填写有效的 BV 视频链接或 BV 号');return;}
  const result=await apiAction('bili/add',{video});
  if(result)$('bili-video').value='';
});
$('bili-uid-add').addEventListener('click',async()=>{
  const id=Number($('bili-uid').value);
  if(!Number.isSafeInteger(id)||id<1){toast('UP 主 UID 应是正整数');return;}
  const result=await apiAction('bili/add',{mid:id});
  if(result)$('bili-uid').value='';
});
// Bilibili login operates entirely inside the restricted AstrBot plugin iframe.
// Never navigate the parent page, open a popup, expose session cookies, or log SMS codes.
let qrTimer=null, qrPrepareTimer=null, qrPreparing=false;
function endQrPolling(){if(qrTimer!==null){clearInterval(qrTimer);qrTimer=null;}if(qrPrepareTimer!==null){clearInterval(qrPrepareTimer);qrPrepareTimer=null;}qrPreparing=false;}
function renderBiliQr(matrix){
  if(!Array.isArray(matrix)||matrix.length<21||matrix.length>180||!matrix.every(row=>typeof row==='string' && row.length===matrix.length && /^[01]+$/.test(row)))throw new Error('服务器二维码矩阵格式不正确');
  const n=matrix.length, ns='http://www.w3.org/2000/svg';
  const svg=document.createElementNS(ns,'svg');
  svg.setAttribute('viewBox',`0 0 ${n} ${n}`);svg.setAttribute('width','232');svg.setAttribute('height','232');
  svg.setAttribute('role','img');svg.setAttribute('aria-label','B站官方登录二维码');
  const bg=document.createElementNS(ns,'rect');bg.setAttribute('width',String(n));bg.setAttribute('height',String(n));bg.setAttribute('fill','#fff');svg.appendChild(bg);
  const black=document.createElementNS(ns,'path');let d='';
  for(let y=0;y<n;y++)for(let x=0;x<n;x++)if(matrix[y][x]==='1')d+=`M${x} ${y}h1v1h-1z`;
  black.setAttribute('d',d);black.setAttribute('fill','#000');svg.appendChild(black);
  $('bili-qr-grid').replaceChildren(svg);
}
async function checkBiliQr(){
  try{
    const result=await bridge.apiPost('bili/login/poll',{});
    $('bili-qr-hint').textContent=result.notice||'正在等待手机确认';
    if(['success','expired'].includes(result.state)){
      endQrPolling();
      if(result.state==='success'){
        $('bili-qr-box').hidden=true;
        toast('B站扫码登录成功；现在可以使用已登录的会话读取 B站公开内容');
        await reload();
      }
    }
  }catch(err){endQrPolling();$('bili-qr-hint').textContent='查询失败：'+(err?.message||String(err));}
}
async function checkBiliQrPreparation(){
  if(qrPreparing)return;
  qrPreparing=true;
  try{
    const result=await bridge.apiGet('bili/login/prepare');
    if(result.state==='ready'){
      renderBiliQr(result.matrix);
      $('bili-qr-hint').textContent=result.notice||'请使用手机 B站 App 扫码确认';
      $('bili-qr-box').hidden=false;
      $('bili-qr-check').hidden=false;
      $('bili-qr-progress').textContent='二维码已生成，请在约 180 秒内扫码';
      endQrPolling();qrTimer=setInterval(checkBiliQr,3500);
    }else if(['failed','expired'].includes(result.state)){
      endQrPolling();
      $('bili-qr-box').hidden=true;
      $('bili-qr-progress').textContent='二维码申请失败：'+(result.notice||'未知错误');
    }else{
      $('bili-qr-progress').textContent=result.notice||'正在申请二维码…';
    }
  }catch(err){
    endQrPolling();
    $('bili-qr-progress').textContent='查询二维码申请状态失败：'+(err?.message||String(err));
  }finally{qrPreparing=false;}
}
$('bili-login-start').addEventListener('click',async()=>{
  const btn=$('bili-login-start');btn.disabled=true;
  endQrPolling();$('bili-qr-box').hidden=true;
  $('bili-qr-check').hidden=true;
  $('bili-qr-grid').replaceChildren();
  $('bili-qr-progress').textContent='正在提交 B站二维码申请…';
  try{
    const result=await bridge.apiPost('bili/login/start',{});
    $('bili-qr-progress').textContent=result.notice||'正在准备二维码…';
    qrPrepareTimer=setInterval(checkBiliQrPreparation,1500);
    await checkBiliQrPreparation();
  }catch(err){$('bili-qr-progress').textContent='启动二维码申请失败：'+(err?.message||String(err));}
  finally{btn.disabled=false;}
});
$('bili-qr-check').addEventListener('click',checkBiliQr);
$('bili-mode-qr-tab').addEventListener('click',()=>{
  $('bili-mode-qr').hidden=false;$('bili-mode-sms').hidden=true;
  $('bili-mode-qr-tab').classList.add('selected');$('bili-mode-sms-tab').classList.remove('selected');
});
$('bili-mode-sms-tab').addEventListener('click',()=>{
  endQrPolling();$('bili-mode-qr').hidden=true;$('bili-mode-sms').hidden=false;
  $('bili-mode-sms-tab').classList.add('selected');$('bili-mode-qr-tab').classList.remove('selected');
});
let geetestProof=null;
let geetestLoader=null;
function smsInfo(message){$('bili-sms-status').textContent=message;}
function loadOfficialGeetest(){
  if(typeof window.initGeetest==='function')return Promise.resolve();
  if(geetestLoader)return geetestLoader;
  geetestLoader=new Promise((resolve,reject)=>{
    const script=document.createElement('script');
    script.src='https://static.geetest.com/static/tools/gt.js';script.async=true;
    script.onload=()=>typeof window.initGeetest==='function'?resolve():reject(new Error('极验组件未初始化'));
    script.onerror=()=>reject(new Error('极验脚本被网络或浏览器拦截'));
    document.head.appendChild(script);
  }).catch(err=>{geetestLoader=null;throw err;});
  return geetestLoader;
}
$('bili-sms-captcha').addEventListener('click',async()=>{
  const btn=$('bili-sms-captcha');btn.disabled=true;geetestProof=null;$('bili-sms-send').disabled=true;
  $('bili-geetest').replaceChildren();smsInfo('正在从 B站获取人机验证并加载极验组件…');
  try{
    const captcha=await bridge.apiPost('bili/sms/captcha',{});
    await loadOfficialGeetest();
    window.initGeetest({gt:captcha.gt,challenge:captcha.challenge,offline:false,new_captcha:true,product:'embed',width:'100%'},obj=>{
      if(!obj||typeof obj.onSuccess!=='function'){smsInfo('极验组件接口不兼容，请改用扫码登录');return;}
      const attach=obj.appendTo||obj.appendto;
      if(typeof attach==='function')attach.call(obj,'#bili-geetest');
      obj.onSuccess(()=>{
        const proof=obj.getValidate();
        if(proof?.geetest_validate && proof?.geetest_challenge && proof?.geetest_seccode){
          geetestProof={challenge:proof.geetest_challenge,validate:proof.geetest_validate,seccode:proof.geetest_seccode};
          $('bili-sms-send').disabled=false;smsInfo('人机验证通过，可以点击「发送短信验证码」');
        }
      });
      if(typeof obj.onError==='function')obj.onError(()=>smsInfo('极验加载或验证失败，请重试；也可以选择扫码登录'));
    });
  }catch(err){smsInfo('无法完成人机验证：'+(err?.message||String(err))+'。请尝试扫码登录。');}
  finally{btn.disabled=false;}
});
$('bili-sms-send').addEventListener('click',async()=>{
  const tel=$('bili-sms-phone').value.trim();
  if(!/^\d{6,20}$/.test(tel)){smsInfo('请输入有效手机号（只填数字）');return;}
  if(!geetestProof){smsInfo('请先完成人机验证');return;}
  const btn=$('bili-sms-send');btn.disabled=true;
  try{
    const result=await bridge.apiPost('bili/sms/send',{tel,cid:1,...geetestProof});
    geetestProof=null;$('bili-sms-login').disabled=false;
    smsInfo(result.notice||'短信发送成功，请输入短信验证码');
  }catch(err){
    geetestProof=null;
    smsInfo('短信请求失败：'+(err?.message||String(err))+'。人机验证票据只可使用一次；若需重试，请等待至少 60 秒后重新开始验证。');
  }
});
$('bili-sms-login').addEventListener('click',async()=>{
  const input=$('bili-sms-code'),code=input.value.trim();
  if(!/^\d{4,8}$/.test(code)){smsInfo('请输入 4–8 位数字短信验证码');return;}
  const btn=$('bili-sms-login');btn.disabled=true;input.value='';
  try{
    const result=await bridge.apiPost('bili/sms/login',{code});
    smsInfo(result.notice||'B站登录成功');
    toast('B站已登录；插件只保存 B站登录会话，不保存手机号或验证码');
    await reload();
  }catch(err){smsInfo('短信登录失败：'+(err?.message||String(err))+'；可重新申请验证码');btn.disabled=false;}
});
$('bili-login-logout').addEventListener('click',async()=>{
  if(!await askUser('只清除插件的 B站本地会话；这不会退出你手机上的 B站 App。',{title:'清除 B站会话'}))return;
  endQrPolling();$('bili-qr-box').hidden=true;geetestProof=null;
  await apiAction('bili/logout',{});
});
$('bili-save').addEventListener('click',()=> $('save').click());
$('watch-add').addEventListener('click',async()=>{
  const id=Number($('watch-appid').value);
  if(!Number.isSafeInteger(id)||id<1||id>2147483647){toast('请输入有效的 Steam 游戏 AppID');return;}
  const result=await apiAction('price/watch',{appid:id});
  if(result)$('watch-appid').value='';
});
$('refresh').addEventListener('click',reload);
$('scan').addEventListener('click',()=>apiAction('scan',{},'扫描已在后台开始，稍后刷新页面查看结果；无需等待页面请求完成。'));
$('save').addEventListener('click',()=>apiAction('settings',{
  scan_minutes:Number($('interval').value),push_enabled:$('push').checked,
  push_steam:$('push-steam').checked,push_third_party:$('push-key').checked,
  push_claim_results:$('push-result').checked,auto_claim_enabled:$('autoclaim').checked,
  price_monitor_enabled:$('price-monitor').checked,push_paid_to_free:$('push-convert').checked,
  push_watch_prices:$('push-watch-prices').checked,
  bili_enabled:$('bili-enabled').checked,push_bilibili:$('push-bilibili').checked,
  bili_ai_enabled:$('bili-ai-enabled').checked,bili_ai_calls:Number($('bili-ai-calls').value),
  bili_keywords:$('bili-keywords').value.trim(),
  steam_proxy_mode:$('steam-proxy-mode').value,steam_proxy_url:$('steam-proxy-url').value.trim(),
  steam_search_fallback:$('steam-search-fallback').checked
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
      (status.configured&&status.running?` · ${status.loaded?'Bot 已加载':'ASF 尚未加载这个 Bot'}`:'') +
      (status.required_input?` · ASF 要求输入：${status.required_input}`:'') +
      (status.status_note?` · ${status.status_note}`:'');
    $('asf-ui-enable').textContent=status.enabled?'禁用 Bot':'启用 Bot';
    $('asf-ui-enable').dataset.next=status.enabled?'false':'true';
    $('asf-ui-enable').disabled=!status.running||!status.configured;
    $('asf-ui-bot-start').disabled=!status.running||!status.configured||!status.enabled;
    $('asf-ui-bot-stop').disabled=!status.running||!status.configured||!status.loaded;
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
