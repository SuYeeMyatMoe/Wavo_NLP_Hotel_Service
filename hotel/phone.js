// Media belongs to this mounted element, not to Streamlit's render cycle.
export default function ({parentElement,data,setStateValue}) {
 const box=parentElement.querySelector('.call-avatar');
 if(box.liveState){box.liveState.data=data;box.liveState.emit=setStateValue;box.liveState.render();return box.liveState.dispose;}
 const $=s=>box.querySelector(s), start=$('.microphone'), end=$('.hangup'), status=$('small'), caption=$('.call-reply'), play=$('.play-reply'), mascot=$('.mascot');
 const s=box.liveState={data,emit:setStateValue,generation:0,phase:'idle',room:null,stream:null,audio:[],muted:false,call:null,startKey:null,timers:[],metrics:{},blocked:false};
 const title=document.createElement('h2');title.textContent='AI reception';box.prepend(title);
 const roomLabel=document.createElement('p');roomLabel.className='call-room';title.after(roomLabel);
 const help=document.createElement('p');help.className='call-help';help.setAttribute('role','status');box.append(help);
 const meter=document.createElement('meter');meter.min=0;meter.max=1;meter.setAttribute('aria-label','Microphone activity');meter.className='input-meter';$('.call-state').after(meter);
 const privacy=document.createElement('details');privacy.className='call-privacy';privacy.innerHTML='<summary>Call privacy</summary><label><input type="checkbox"> Save my transcript for staff review</label><p>Optional. Without permission, Wavo keeps only the service note and task. Speech is still processed by the voice providers.</p>';box.append(privacy);
 const consent=privacy.querySelector('input');consent.checked=false;
 const diagnostics=document.createElement('details');diagnostics.className='call-privacy';diagnostics.innerHTML='<summary>Audio check</summary><pre></pre>';box.append(diagnostics);
 const report=diagnostics.querySelector('pre');
 const active=()=>['connecting','waiting','listening','speaking','thinking','muted','reconnecting'].includes(s.phase);
 const mark=code=>{if(!(code in s.metrics))s.metrics[code]=Math.round(performance.now()-s.started);};
 const show=(phase,message='')=>{s.phase=phase;s.message=message;s.render();};
 s.render=()=>{
   if(s.data.retryFinalization&&s.data.retryFinalization!==s.lastRetry){s.lastRetry=s.data.retryFinalization;if(s.call||s.startKey)queueMicrotask(()=>{void finish();});}
   if(s.data.dismissedCall&&s.data.dismissedCall===s.completedCall&&!active()&&!s.ending){s.completedCall=null;s.phase='idle';s.message='';help.textContent='';}
   box.hidden=s.data.visible===false&&!active()&&!s.ending;
   if(!box.hidden&&!s.mascotMounted&&typeof WavoMascot!=='undefined'){
     s.mascotMounted=true;
     requestAnimationFrame(()=>{if(mascot.isConnected)WavoMascot.mountMascot(mascot);});
   }
   box.classList.toggle('live-launcher',Boolean(s.data.api));box.dataset.mode=s.phase;
   roomLabel.textContent=(s.call?.room||s.data.room)?'Room '+(s.call?.room||s.data.room):'';
   status.textContent=s.message||({idle:'Speak naturally. Wavo follows your language.',connecting:'Connecting…',waiting:'Waiting for AI…',listening:'Listening',speaking:'Wavo is speaking',thinking:'Checking with the hotel…',muted:'Microphone muted',reconnecting:'Reconnecting…',ended:'Call ended',error:'Call could not connect'})[s.phase];
   start.textContent=active()?(s.muted?'Unmute microphone':'Mute microphone'):(s.phase==='idle'?'Call AI Reception':'Call again');
   start.disabled=s.phase==='connecting'||s.phase==='reconnecting'||Boolean(s.ending);
   if(active())start.setAttribute('aria-pressed',String(s.muted));else start.removeAttribute('aria-pressed');
   end.hidden=s.phase==='idle';end.disabled=Boolean(s.ending);end.textContent=active()?'End call':(s.call||s.startKey)?'Retry finalization':'Back to reception';
   meter.hidden=!active();privacy.hidden=!s.data.api;consent.disabled=s.phase==='connecting';
   play.hidden=!s.blocked;play.textContent='Tap to hear Wavo';
   diagnostics.hidden=s.phase==='idle';
   if(!box.hidden && s.data.focusLauncher && !active()){
     s.data.focusLauncher=false;
     requestAnimationFrame(()=>{
       box.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'nearest'});
       start.focus({preventScroll:true});
     });
   }
   report.textContent='Microphone: '+(s.stream?(s.muted?'muted':'active'):'off')+'\nSpeaker playback: '+(s.blocked?'tap to enable':s.audioContext?.state==='running'?'ready':'off')+'\nAI audio: '+('first_signal_ms' in s.metrics?'received':'waiting')+'\n'+Object.entries(s.metrics).map(([k,v])=>k.replace(/_ms$/,'').replaceAll('_',' ')+': '+(v/1000).toFixed(1)+'s').join('\n');
 };
 async function api(path,body,method='POST',keepalive=false){
   const response=await fetch(s.data.api+path,{method,headers:{Authorization:'Bearer '+s.data.accessToken,'Content-Type':'application/json'},...(body!==undefined?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(15000),keepalive});
   if(!response.ok){const error=new Error('API_'+response.status);error.code='API_'+response.status;throw error;}return response.json();
 }
 async function ready(valid){
   const until=performance.now()+120000;
   while(valid()&&performance.now()<until){
     try{const response=await fetch(s.data.api+'/healthz',{signal:AbortSignal.timeout(Math.min(5000,Math.max(1,until-performance.now())))});if(response.ok&&(await response.json()).status==='ok')return;}
     catch{}
     if(valid())help.textContent='Starting the hotel service. This can take a minute…';
     await new Promise(resolve=>setTimeout(resolve,2000));
   }
   if(valid())throw Object.assign(new Error(),{code:'API_STARTING'});
 }
 function stopMedia(){
   ++s.generation;s.timers.forEach(clearTimeout);s.timers=[];clearInterval(s.meterTimer);
   // Stop actual devices synchronously, before any network work or rerender.
   s.stream?.getTracks().forEach(t=>t.stop());s.stream=null;
   s.room?.localParticipant.audioTrackPublications.forEach(p=>p.track?.stop());
   s.audio.forEach(a=>{a.pause();a.srcObject=null;a.remove();});s.audio=[];
   const room=s.room;s.room=null;if(room)Promise.resolve(room.disconnect()).catch(()=>{});
   s.audioContext?.close().catch(()=>{});s.audioContext=null;s.remoteAnalyser=null;s.blocked=false;
   caption.textContent='';meter.value=0;box.style.setProperty('--voice-level','0');
 }
 async function finish(unmount=false){
   if(s.ending)return s.ending;
   const hadCall=active()||s.call||s.startKey;const completedId=s.call?.id;stopMedia();show('ended');help.textContent='';
   if(!hadCall)return;
   if(!s.data.api){s.call=null;s.startKey=null;s.emit('ended',true);return;}
   if(!s.startKey&&!s.call)return; // Microphone permission was still pending.
   const path=s.startKey?'/calls/start/'+s.startKey+'/cancel':'/calls/'+s.call.id+'/end';
   s.finalizingKey=s.startKey||completedId;s.endedAt=performance.now();
   s.popupObserver?.disconnect();
   if(!unmount&&typeof MutationObserver!=='undefined'){
     s.popupObserver=new MutationObserver(()=>{const dialog=document.querySelector('[role="dialog"]');if(dialog?.textContent.includes('Request update')){s.metrics.popup_visible_ms=Math.round(performance.now()-s.endedAt);s.popupObserver.disconnect();s.render();}});
     s.popupObserver.observe(document.body,{childList:true,subtree:true});
   }
   if(!unmount)s.emit('finalizing',{key:s.finalizingKey,call_id:completedId||null,status:'pending'});
   show('ended','Checking your request…');
   s.ending=(async()=>{
     // One logical idempotent end action; retry only that action if delivery fails.
     for(let attempt=0;attempt<3;attempt++){
       try{const result=await api(path,{},'POST',unmount);s.metrics.finalization_ms=Math.round(performance.now()-s.endedAt);s.completedCall=result.call_id||completedId||null;s.call=null;s.startKey=null;help.textContent='';if(!unmount){s.emit('finalizing',{key:s.finalizingKey,call_id:s.completedCall,status:'complete',result:result.result||null});if(s.completedCall)s.emit('completed_call',s.completedCall);else show('ended');}else show('ended');return;}
       catch{if(attempt===2){show('ended','Call finalization needs a retry');help.textContent='Microphone is off. Could not confirm hang-up with the hotel. Tap Retry finalization.';if(!unmount)s.emit('finalizing',{key:s.finalizingKey,call_id:completedId||null,status:'failed'});return;}await new Promise(r=>setTimeout(r,500*(attempt+1)));}
     }
   })();s.render();await s.ending;s.ending=null;s.render();
 }
 s.dispose=()=>{s.popupObserver?.disconnect();void finish(true);window.removeEventListener('pagehide',s.dispose);};window.addEventListener('pagehide',s.dispose);
 function later(fn,ms){s.timers.push(setTimeout(fn,ms));}
 function playback(){
   if(!s.room)return;
   s.audioContext?.resume().catch(()=>{});
   return s.room.startAudio().then(()=>{s.blocked=!s.room.canPlaybackAudio;s.render();}).catch(()=>{s.blocked=true;s.render();});
 }
 play.onclick=playback;
 consent.onchange=async()=>{
   if(!s.call)return;consent.disabled=true;
   try{await api('/calls/'+s.call.id+'/transcript-consent?value='+consent.checked,undefined,'PUT');help.textContent='Privacy preference saved.';}
   catch{consent.checked=!consent.checked;help.textContent='Could not save privacy preference. Please retry.';}
   finally{consent.disabled=false;}
 };
 async function poll(g){
   if(g!==s.generation||!s.call||!s.data.api)return;
   try{const result=await api('/calls/'+s.call.id+'/status',undefined,'GET');if(g!==s.generation)return;if(!['Ringing','Connecting','Connected'].includes(result.status)){await finish();return;}}
   catch{if(g===s.generation)help.textContent='Hotel status is temporarily unavailable. Audio remains connected.';}
   if(g===s.generation)later(()=>poll(g),5000);
 }
 start.onclick=async()=>{
   if(start.disabled)return;
   if(active()){
     const room=s.room,g=s.generation;s.muted=!s.muted;
     try{await room.localParticipant.setMicrophoneEnabled(!s.muted);if(g===s.generation)show(s.muted?'muted':'listening');}
     catch{if(g===s.generation){s.muted=!s.muted;help.textContent='Could not change microphone. Check browser permission.';s.render();}}return;
   }
   if(s.call||s.startKey){await finish();if(s.call||s.startKey)return;}
   const g=++s.generation,valid=()=>g===s.generation;s.started=performance.now();s.metrics={};s.muted=false;s.blocked=false;help.textContent='';show('connecting');
   try{
     // Both start inside the original button activation, before fetch.
     s.audioContext=new (window.AudioContext||window.webkitAudioContext)();
     void s.audioContext.resume().catch(()=>{if(valid()){s.blocked=true;s.render();}});
     const mic=navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
     later(()=>{if(valid()&&s.phase==='connecting')help.textContent='Still connecting. Check the microphone prompt, or end this attempt and try again.';},10000);
     const stream=await mic;if(!valid()){stream.getTracks().forEach(t=>t.stop());return;}
     s.stream=stream;mark('microphone_ready_ms');let config=s.data;
     if(s.data.api){
       await ready(valid);if(!valid())return;
       s.startKey=crypto.randomUUID();const payload={key:s.startKey,transcript_consent:consent.checked};
       // A timeout may follow a commit: repeat with the same key only.
       try{config=await api('/calls/start',payload);}catch(e){if(!valid())return;if(e.code&&e.code!=='API_503')throw e;config=await api('/calls/start',payload);}
       if(!valid())return;s.call=config;consent.checked=config.transcript_consent;
       if(config.engine!=='live')throw Object.assign(new Error(),{code:'NO_WORKER_CONFIG'});
     }else{s.call={id:config.id};}
     mark('startup_ms');const {Room,RoomEvent,Track}=window.LivekitClient;
     const room=s.room=new Room({webAudioMix:{audioContext:s.audioContext}});
     room.on(RoomEvent.AudioPlaybackStatusChanged,()=>{if(valid()){s.blocked=!room.canPlaybackAudio;s.render();}});
     room.on(RoomEvent.TrackSubscribed,track=>{
       if(!valid()||track.kind!==Track.Kind.Audio)return;
       const element=track.attach();element.autoplay=true;element.playsInline=true;s.audio.push(element);box.append(element);
       if(track.mediaStreamTrack){s.remoteAnalyser=s.audioContext.createAnalyser();s.remoteAnalyser.fftSize=256;s.audioContext.createMediaStreamSource(new MediaStream([track.mediaStreamTrack])).connect(s.remoteAnalyser);}
       element.onplaying=()=>{if(valid()){mark('first_playback_ms');s.blocked=!room.canPlaybackAudio;help.textContent='';s.render();}};
       element.play().catch(()=>{if(valid()){s.blocked=true;s.render();}});
       mark('remote_audio_ms');show(s.muted?'muted':'listening');
     });
     room.on(RoomEvent.ParticipantAttributesChanged,(_,participant)=>{if(valid()&&participant.identity!==room.localParticipant.identity){s.agentState=participant.attributes?.['lk.agent.state'];if(s.agentState==='thinking')show('thinking');else if(s.agentState==='speaking')show('speaking');else if(s.agentState==='listening')show(s.muted?'muted':'listening');}});
     room.on(RoomEvent.ActiveSpeakersChanged,speakers=>{if(valid()){const local=speakers.some(p=>p.identity===room.localParticipant.identity);if(s.localSpeaking&&!local){s.speechEndedAt=performance.now();s.awaitingReplySignal=true;}s.localSpeaking=local;show(speakers.some(p=>p.identity!==room.localParticipant.identity)?'speaking':s.agentState==='thinking'?'thinking':s.muted?'muted':s.audio.length?'listening':'waiting');}});
     room.on(RoomEvent.TranscriptionReceived,(segments,participant)=>{if(valid()&&segments.length){caption.textContent=segments[segments.length-1].text;if(participant?.identity===room.localParticipant.identity&&segments.some(x=>x.final)&&s.speechEndedAt){s.metrics.last_transcript_ms=Math.round(performance.now()-s.speechEndedAt);}}});
     room.on(RoomEvent.Reconnecting,()=>{if(valid())show('reconnecting');});
     room.on(RoomEvent.Reconnected,()=>{if(valid())show(s.muted?'muted':'listening');});
     room.on(RoomEvent.Disconnected,()=>{if(valid()){void finish();help.textContent='Call disconnected. You can call again.';}});
     await room.connect(config.url,config.token);if(!valid()){await room.disconnect();return;}
     await room.localParticipant.publishTrack(stream.getAudioTracks()[0],{source:Track.Source.Microphone});
     if(!valid()){stream.getTracks().forEach(t=>t.stop());await room.disconnect();return;}
     mark('connected_ms');show(s.audio.length?'listening':'waiting');help.textContent='';await playback();if(!valid())return;
     const analyser=s.audioContext.createAnalyser();analyser.fftSize=256;s.audioContext.createMediaStreamSource(stream).connect(analyser);const samples=new Uint8Array(analyser.fftSize);
     s.meterTimer=setInterval(()=>{
       analyser.getByteTimeDomainData(samples);const level=s.muted?0:Math.min(1,Math.sqrt(samples.reduce((n,v)=>n+(v-128)**2,0)/samples.length)/32);meter.value=level;box.style.setProperty('--voice-level',String(level));
       if(s.remoteAnalyser){s.remoteAnalyser.getByteTimeDomainData(samples);if(samples.some(v=>Math.abs(v-128)>3)){mark('first_signal_ms');if(s.awaitingReplySignal&&!s.localSpeaking){s.metrics.last_audible_reply_ms=Math.round(performance.now()-s.speechEndedAt);s.awaitingReplySignal=false;}s.render();}}
     },100);
     later(()=>{if(valid()&&!s.audio.length)help.textContent='Wavo is starting. Please stay on the call…';},10000);
     later(()=>{if(valid()&&!s.audio.length){void finish();help.textContent='AI reception is unavailable right now. Please retry or send a message.';}},60000);
     later(()=>poll(g),5000);
   }catch(error){
     if(!valid())return;let code=error.code||error.name;
     if(error.reason===window.LivekitClient.ConnectionErrorReason?.NotAllowed&&error.reason!==undefined)code='CALL_TOKEN';
     await finish();
     const message=({NotAllowedError:'Microphone permission was denied. Allow the microphone in your browser and call again.',NotFoundError:'No microphone found. Connect one and call again.',NotReadableError:'Your microphone is busy. Close other recording apps and retry.',CALL_TOKEN:'The call connection was rejected or expired. Call again for a new connection. If it repeats, check that your computer time is correct.',API_401:'Your session expired. Sign in again to call.',API_403:'This call is unavailable for your reservation.',API_409:'This call attempt has ended. Call again.',NO_WORKER_CONFIG:'Live calling is unavailable. Use the text option for now.'})[code]||'Could not connect. Check your network and try again.';show('error',message);
   }
 };
 end.onclick=()=>{if(active()||s.call||s.startKey)void finish();else{caption.textContent='';help.textContent='';show('idle');}};
 mascot.setAttribute('aria-label',s.data.mascot||'Make Wavo wink');
 s.render();return s.dispose;
}
