const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
const $ = id => document.getElementById(id);
function el(tag, txt, className) { const n = document.createElement(tag); if (txt !== undefined) n.textContent = String(txt); if (className) n.className = className; return n; }
function info(text){ $('notice').textContent = text; }
async function action(endpoint, payload, message){ try { const result = await bridge.apiPost(endpoint,payload); info(message || '操作完成'); await refresh(); return result; }catch(e){ info('操作失败：'+ e.message); throw e; } }
function drawGame(g){
  const card=el('article',undefined,'game');
  card.append(el('h4',g.name),el('div',`${g.source} · ${g.original_price || '未知价格'} · ${g.end_date || '结束时间待核实'}`,'meta'));
  card.append(el('span',g.kind==='steam_candidate'?'100% 折扣候选':'第三方赠送','chip'));
  card.append(el('p',g.confidence));
  const foot=el('div',undefined,'foot');
  const link=el('a','查看领取页面'); link.href=g.url;link.target='_blank';link.rel='noopener noreferrer';foot.append(link);
  if(g.kind==='steam_candidate'){
    const approve=el('button','批准 SubID');approve.className='secondary';approve.addEventListener('click',async()=>{
      const answer=prompt('请输入已核实的 Free-to-Keep 免费领取包 SubID（纯数字）：',g.approved_subid||'');
      if(answer===null) return;
      if(!/^\d{1,10}$/.test(answer)||Number(answer)<1||Number(answer)>2147483647){info('SubID 不合法');return;}
      if(!confirm('确认已核实该 Steam 免费永久领取包？错误的 SubID 可能导致领取失败。'))return;
      await action('approve',{key:g.key,subid:Number(answer)},'已批准 SubID；自动领取开启时下次扫描会尝试执行');
    });foot.append(approve);
    if(g.approved_subid){
      const claim=el('button',`执行 ASF 领取 (${g.approved_subid})`);
      claim.addEventListener('click',async()=>{if(!confirm('确认向你配置的 ASF Steam 账号发送免费领取命令？'))return;
        const res=await action('claim',{key:g.key},'已发送 ASF 命令，结果请核对');info(`ASF 状态：${res.status}\n${res.result}`);
      });foot.append(claim);
    }
    if(g.claim_status) card.append(el('p',`ASF：${g.claim_status} · ${(g.claim_result||'').slice(0,170)}`));
  }
  card.append(foot);return card;
}
async function refresh(){
  try{
    const s=await bridge.apiGet('snapshot');
    $('total').textContent=s.games.length+ (s.games.length===150?'+':'');
    $('groups').textContent=s.targets.filter(v=>v.enabled).length;
    $('last').textContent=s.last_scan?new Date(s.last_scan).toLocaleString():'尚未扫描';
    $('interval').value=s.settings.scan_minutes; $('push').checked=s.settings.push_enabled; $('autoclaim').checked=s.settings.auto_claim_enabled;
    $('errors').textContent=(s.errors||[]).join('\n');
    $('games').replaceChildren(...(s.games.length?s.games.map(drawGame):[el('div','暂无发现。可点击「立即扫描」检查网络与数据源。','muted')]));
    const targets=s.targets.map(t=>{const row=el('div',undefined,'target');const desc=el('div');desc.append(el('strong',`群 ${t.group_id}`),el('div',`${t.platform_id} · ${t.official?'QQ 官方':'OneBot'} · ${t.enabled?'已启用':'已暂停'}`,'meta'));row.append(desc);
      if(t.enabled){const b=el('button','测试推送');b.className='secondary';b.addEventListener('click',()=>action('test-send',{target_id:t.id},'已尝试测试推送'));row.append(b);}return row;});
    $('target-list').replaceChildren(...(targets.length?targets:[el('div','暂无绑定群。请在 QQ 群使用 /喜加一绑定','muted')]));
  }catch(e){info('后台读取失败：'+e.message);}
}
$('refresh').addEventListener('click',refresh);
$('scan').addEventListener('click',()=>action('scan',{},'扫描完成'));
$('save').addEventListener('click',()=>action('settings',{scan_minutes:Number($('interval').value),push_enabled:$('push').checked,auto_claim_enabled:$('autoclaim').checked},'设置已保存'));
if(!bridge)info('没有找到 AstrBot 面板桥接 API，请从插件详情页打开。'); else bridge.ready().then(refresh).catch(e=>info('桥接连接失败：'+e.message));
