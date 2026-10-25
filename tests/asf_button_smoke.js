// Run with `node tests/asf_button_smoke.js`. No browser or AstrBot server is required.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const js = fs.readFileSync(require('path').join(__dirname, '../views/steam-freebies/app.js'), 'utf8');
const elements = new Map();
const element = name => {
  if (!elements.has(name)) {
    const listeners = {};
    elements.set(name, {disabled:false, hidden:true, value:'', textContent:'', checked:false,
      classList:{toggle(){}}, addEventListener(event, fn){listeners[event] = fn;},
      focus(){}, _listeners:listeners});
  }
  return elements.get(name);
};
let sent = [];
const bridge = {
  ready: () => new Promise(() => {}),
  apiPost: async (endpoint, body) => {sent.push({endpoint,body});return {ok:true};},
  apiGet: async () => new Promise(() => {})
};
const sandbox = {window:{AstrBotPluginView:bridge},document:{getElementById:element,querySelectorAll:()=>[],createElement:()=>({})},
  console,Promise,setInterval:()=>1,clearInterval:()=>{},Date,
  confirm:()=>{throw Error('native confirm must not be called')},
  prompt:()=>{throw Error('native prompt must not be called')},
};
vm.runInNewContext(js,sandbox);
assert(typeof element('install-asf')._listeners.click === 'function');
element('install-asf')._listeners.click();
setImmediate(()=>{
  assert.equal(sent.length,1);
  assert.equal(sent[0].endpoint,'asf/install');
  assert.equal(element('asf-operation').hidden,false);
  console.log('PASS: iframe ASF install click invokes backend without modal');
});
