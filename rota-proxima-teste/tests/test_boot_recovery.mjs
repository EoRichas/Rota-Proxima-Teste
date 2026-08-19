import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../static/app.js', import.meta.url), 'utf8');

class ClassList {
  constructor(values=[]) { this.values=new Set(values); }
  add(...values) { values.forEach(value=>this.values.add(value)); }
  remove(...values) { values.forEach(value=>this.values.delete(value)); }
  contains(value) { return this.values.has(value); }
  toggle(value, force) {
    const enabled=force===undefined ? !this.values.has(value) : !!force;
    if(enabled)this.values.add(value);else this.values.delete(value);
    return enabled;
  }
  toString() { return [...this.values].join(' '); }
}

function makeElement(classes=[]) {
  const element={
    classList:new ClassList(classes),
    textContent:'',
    innerHTML:'',
    value:'',
    style:{},
    addEventListener(){},
    querySelector(){return null;},
    querySelectorAll(){return [];},
  };
  Object.defineProperty(element,'className',{
    get(){return element.classList.toString();},
    set(value){element.classList=new ClassList(String(value).split(/\s+/).filter(Boolean));},
  });
  return element;
}

async function runScenario({setupFails=false}={}) {
  const elements=new Map([
    ['#toast',makeElement(['toast','hidden'])],
    ['#authScreen',makeElement(['auth-screen'])],
    ['#appShell',makeElement(['app-shell','hidden'])],
    ['#setupForm',makeElement(['stack','hidden'])],
    ['#loginForm',makeElement(['stack','hidden'])],
    ['#authStatus',makeElement(['warning','hidden'])],
  ]);
  const generic=makeElement();
  const calls=[];
  const document={
    body:{contains:()=>true},
    querySelector(selector){return elements.get(selector) || generic;},
    querySelectorAll(){return [];},
    createElement(){return makeElement();},
  };
  const fetch=async path=>{
    calls.push(path);
    if(path==='/api/me')return {ok:false,status:503,json:async()=>({error:'Sessão temporariamente indisponível.'})};
    if(path==='/api/setup-status' && setupFails)return {ok:false,status:503,json:async()=>({error:'Serviço temporariamente indisponível.'})};
    if(path==='/api/setup-status')return {ok:true,status:200,json:async()=>({needs_setup:false})};
    throw new Error(`Requisição inesperada: ${path}`);
  };
  const context=vm.createContext({
    console,
    document,
    fetch,
    navigator:{serviceWorker:{register:async()=>{}}},
    window:{addEventListener(){},open(){}},
    setTimeout:()=>1,
    clearTimeout(){},
    confirm:()=>false,
    prompt:()=>null,
    URL,
    Blob,
    FormData,
  });
  vm.runInContext(source,context,{filename:'static/app.js'});
  await new Promise(resolve=>setImmediate(resolve));
  await new Promise(resolve=>setImmediate(resolve));
  return {elements,calls};
}

for (const setupFails of [false,true]) {
  const {elements,calls}=await runScenario({setupFails});
  assert.deepEqual(calls,['/api/me','/api/setup-status']);
  assert.equal(elements.get('#authScreen').classList.contains('hidden'),false);
  assert.equal(elements.get('#appShell').classList.contains('hidden'),true);
  assert.equal(elements.get('#loginForm').classList.contains('hidden'),false);
  assert.equal(elements.get('#setupForm').classList.contains('hidden'),true);
  assert.equal(elements.get('#authStatus').classList.contains('hidden'),false);
  assert.match(elements.get('#authStatus').textContent,/indisponível/i);
}

console.log('boot recovery: 2 cenários aprovados');
