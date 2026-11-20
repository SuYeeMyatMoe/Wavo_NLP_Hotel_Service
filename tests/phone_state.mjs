// Deterministic media/network race tests; no real microphones or credentials.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {webcrypto} from 'node:crypto';
const render=(await import('data:text/javascript;base64,'+Buffer.from(readFileSync(new URL('../hotel/phone.js',import.meta.url))).toString('base64'))).default;
class Element {
 constructor(){this.nodes={};this.style={setProperty(){}};this.classList={toggle(){},remove(){},add(){}};this.dataset={};this.disabled=false;this.hidden=false;this.textContent='';this.attributes={};}
 querySelector(s){return this.nodes[s]??=new Element();}setAttribute(k,v){this.attributes[k]=v;}removeAttribute(k){delete this.attributes[k];}
 prepend(){}append(...nodes){for(const node of nodes){if(node.className)this.nodes["."+node.className]=node;}}after(){}remove(){this.removed=true;}pause(){this.paused=true;}play(){if(this.failPlay)return Promise.reject(new Error('blocked'));this.onplaying?.();return Promise.resolve();}
}
const flush=()=>new Promise(r=>setImmediate(r));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
function setup(){
 const calls=[],events=[],timers=[],rooms=[],state=[];let getMic,backend;
 const track={stopped:false,stop(){this.stopped=true;}},stream={getTracks:()=>[track],getAudioTracks:()=>[track]};
 class AudioContext{constructor(){this.state='suspended';}resume(){events.push('resume');this.state='running';return Promise.resolve();}close(){this.state='closed';return Promise.resolve();}createAnalyser(){return {fftSize:256,getByteTimeDomainData(a){a.fill(128);}};}createMediaStreamSource(){return {connect(){}};}}
 class Room{constructor(){rooms.push(this);this.handlers={};this.canPlaybackAudio=true;this.remoteParticipants=new Map();this.localParticipant={identity:'guest',audioTrackPublications:new Map(),publishTrack:async t=>{events.push('publish');this.localParticipant.audioTrackPublications.set('mic',{track:t});},setMicrophoneEnabled:async value=>{events.push('mic:'+value);}};}on(e,f){this.handlers[e]=f;}connect(){events.push('connect');return Promise.resolve();}disconnect(){events.push('disconnect');this.handlers.Disconnected?.();return Promise.resolve();}startAudio(){events.push('playback');return Promise.resolve();}}
 globalThis.window={AudioContext,addEventListener(){},removeEventListener(){},LivekitClient:{Room,Track:{Kind:{Audio:'audio'},Source:{Microphone:'microphone'}},RoomEvent:Object.fromEntries(['AudioPlaybackStatusChanged','TrackSubscribed','ActiveSpeakersChanged','TranscriptionReceived','Reconnecting','Reconnected','Disconnected'].map(v=>[v,v]))}};
 globalThis.document={createElement:()=>new Element()};Object.defineProperty(globalThis,'crypto',{value:webcrypto,configurable:true});
 Object.defineProperty(globalThis,'navigator',{value:{mediaDevices:{getUserMedia(){events.push('permission');return getMic?getMic():Promise.resolve(stream);}}},configurable:true});
 globalThis.setTimeout=(fn,ms)=>{timers.push({fn,ms});return timers.length;};globalThis.clearTimeout=()=>{};globalThis.setInterval=()=>1;globalThis.clearInterval=()=>{};
 globalThis.fetch=async(url,options)=>{events.push('fetch');calls.push({url,options});if(backend)return backend(url,options);return {ok:true,json:async()=>url.endsWith('/start')?{id:'call',room:'305',engine:'live',url:'wss://test',token:'test',transcript_consent:false}:{ended:true}};};
 const parent=new Element(),box=parent.querySelector('.call-avatar'),data={api:'http://test',accessToken:'test',room:'305',visible:true};
 const args={parentElement:parent,data,setStateValue:(k,v)=>state.push([k,v])};render(args);
 return {box,args,data,track,stream,calls,events,timers,rooms,state,start:()=>box.querySelector('.microphone').onclick(),end:()=>box.querySelector('.hangup').onclick(),mic:f=>getMic=f,backend:f=>backend=f};
}
{
 const t=setup();await t.start();assert.deepEqual(t.events.slice(0,3),['resume','permission','fetch']);
 assert.equal(JSON.parse(t.calls[0].options.body).transcript_consent,false);
 const room=t.rooms[0];render({...t.args,data:{...t.data,visible:false}});assert.equal(t.box.liveState.room,room);assert.equal(t.box.hidden,false);
 await t.start();assert.equal(t.box.liveState.muted,true);
 const a=new Element();a.failPlay=true;room.handlers.TrackSubscribed({kind:'audio',attach:()=>a});await flush();assert.equal(t.box.querySelector('.play-reply').hidden,false);
 room.canPlaybackAudio=true;await t.box.querySelector('.play-reply').onclick();assert.equal(t.box.querySelector('.play-reply').hidden,true);
 t.end();assert.equal(t.track.stopped,true);assert.equal(a.paused,true);assert.equal(a.srcObject,null);await flush();
 assert.equal(t.box.liveState.phase,'ended');assert.equal(t.box.querySelector('.microphone').textContent,'Call again');assert.equal(t.box.querySelector('.hangup').textContent,'Back to reception');
 const before=t.calls.length;room.handlers.Disconnected();room.handlers.TranscriptionReceived([{text:'late text'}]);assert.equal(t.calls.length,before);assert.equal(t.box.querySelector('.call-reply').textContent,'');
 console.log('PASS activation order, rerender, mute, blocked playback, local shutdown and late events');
}
{
 const t=setup();await t.start();const pending=deferred();t.backend(()=>pending.promise);
 t.end();assert.equal(t.track.stopped,true);assert.equal(t.state[0][0],'finalizing');assert.equal(t.state[0][1].status,'pending');assert.equal(t.state.filter(x=>x[0]==='completed_call').length,0);assert.equal(t.box.querySelector('small').textContent,'Checking your request…');
 t.end();assert.equal(t.calls.filter(c=>c.url.endsWith('/cancel')).length,1);
 render({...t.args,data:{...t.data,visible:false}});assert.equal(t.box.liveState.ending instanceof Promise,true);
 pending.resolve({ok:true,json:async()=>({ended:true,call_id:'call'})});await flush();await flush();
 assert.deepEqual(t.state.filter(x=>x[0]==='completed_call'),[['completed_call','call']]);assert.equal(t.box.liveState.completedCall,'call');
 render({...t.args,data:{...t.data,dismissedCall:'call'}});assert.equal(t.box.liveState.phase,'idle');
 console.log('PASS receipt retains call ID only after confirmed finalization; dismissal resets launcher');
}
{
 const t=setup();await t.start();t.backend(async()=>{throw new TypeError('offline');});
 t.end();await flush();await t.timers.filter(x=>x.ms===500).at(-1).fn();await flush();await t.timers.filter(x=>x.ms===1000).at(-1).fn();await flush();
 assert.equal(t.track.stopped,true);assert.equal(t.state.filter(x=>x[0]==='completed_call').length,0);assert.equal(t.state.at(-1)[1].status,'failed');assert.equal(t.box.querySelector('.hangup').textContent,'Retry finalization');
 t.backend(async()=>({ok:true,json:async()=>({ended:true,call_id:'call'})}));t.end();await flush();
 assert.deepEqual(t.state.filter(x=>x[0]==='completed_call'),[['completed_call','call']]);assert.equal(t.calls.filter(c=>c.url.endsWith('/start')).length,1);
 console.log('PASS failed finalization never claims assignment; retry ends the same call');
}
{
 const t=setup(),pending=deferred();t.mic(()=>pending.promise);const action=t.start();t.end();pending.resolve(t.stream);await action;assert.equal(t.track.stopped,true);assert.equal(t.calls.length,0);console.log('PASS hang-up while microphone permission is pending');
}
{
 const t=setup(),pending=deferred();t.backend((url)=>url.endsWith('/start')?pending.promise:Promise.resolve({ok:true,json:async()=>({ended:true})}));
 const action=t.start();await flush();t.end();await flush();pending.resolve({ok:true,json:async()=>({id:'late',engine:'live'})});await action;
 assert.equal(t.rooms.length,0);assert.equal(t.track.stopped,true);assert.equal(t.calls.filter(c=>c.url.endsWith('/cancel')).length,1);console.log('PASS hang-up during backend startup; no late room connection');
}
{
 const t=setup();t.mic(()=>Promise.reject(Object.assign(new Error(),{name:'NotAllowedError'})));await t.start();assert.match(t.box.querySelector('small').textContent,/permission was denied/);assert.equal(t.calls.length,0);console.log('PASS denied microphone has a useful error and creates no call');
}
{
 const t=setup(),pending=deferred();t.mic(()=>pending.promise);const action=t.start();await t.start();assert.equal(t.events.filter(x=>x==='permission').length,1);t.end();pending.resolve(t.stream);await action;console.log('PASS double click starts only one attempt');
}
{
 const t=setup();let starts=0;t.backend(async(url)=>{if(url.endsWith('/start')){if(++starts===1)throw new TypeError('network');return {ok:true,json:async()=>({id:'call',engine:'live',token:'test',url:'wss://test'})};}return {ok:true,json:async()=>({ended:true})};});await t.start();assert.equal(starts,2);assert.equal(t.calls[0].options.body,t.calls[1].options.body);t.end();await flush();console.log('PASS lost startup response retries the same idempotency key');
}
{
 const t=setup();await t.start();const room=t.rooms[0];room.handlers.Reconnecting();assert.equal(t.box.liveState.phase,'reconnecting');room.handlers.Reconnected();assert.equal(t.box.liveState.phase,'listening');
 t.backend(async()=>{throw new TypeError('offline');});await t.timers.find(x=>x.ms===5000).fn();assert.equal(t.track.stopped,false);assert.match(t.box.querySelector('.call-help').textContent,/temporarily unavailable/);
 t.backend(async()=>({ok:true,json:async()=>({status:'Ended'})}));await t.timers.filter(x=>x.ms===5000).at(-1).fn();await flush();assert.equal(t.track.stopped,true);console.log('PASS reconnect and transient heartbeat preserve audio; explicit Ended stops it');
}
{
 const t=setup();await t.start();t.timers.filter(x=>x.ms===10000).at(-1).fn();assert.match(t.box.querySelector('.call-help').textContent,/has not joined/);t.timers.find(x=>x.ms===30000).fn();await flush();assert.equal(t.track.stopped,true);console.log('PASS missing voice worker shows recovery then stops the microphone');
}
