function wav(chunks, sampleRate=16000) {
  if(sampleRate!==16000){
    const joined=new Float32Array(chunks.reduce((n,p)=>n+p.length,0));
    let at=0;for(const p of chunks){joined.set(p,at);at+=p.length;}
    const converted=new Float32Array(Math.floor(joined.length*16000/sampleRate));
    for(let i=0;i<converted.length;i++){const x=i*sampleRate/16000,j=Math.floor(x),fraction=x-j;converted[i]=joined[j]*(1-fraction)+(joined[Math.min(j+1,joined.length-1)]||0)*fraction;}
    chunks=[converted];
  }
  const length = chunks.reduce((sum, part) => sum + part.length, 0);
  const buffer = new ArrayBuffer(44 + 2 * length);
  const view = new DataView(buffer);
  const word = (offset, s) => [...s].forEach((c,i)=>view.setUint8(offset+i,c.charCodeAt(0)));
  word(0,"RIFF"); view.setUint32(4,36+length*2,true); word(8,"WAVE"); word(12,"fmt ");
  view.setUint32(16,16,true); view.setUint16(20,1,true); view.setUint16(22,1,true);
  view.setUint32(24,16000,true); view.setUint32(28,32000,true);
  view.setUint16(32,2,true); view.setUint16(34,16,true); word(36,"data"); view.setUint32(40,length*2,true);
  let offset=44;
  chunks.forEach(part=>part.forEach(value=>{ view.setInt16(offset,Math.max(-1,Math.min(1,value))*32767,true); offset+=2; }));
  const bytes=new Uint8Array(buffer); let string="";
  for(let i=0;i<bytes.length;i+=8192)string+=String.fromCharCode(...bytes.subarray(i,i+8192));
  return btoa(string);
}

export default function({parentElement,data,setTriggerValue,setStateValue}) {
  const box=parentElement.querySelector(".call-avatar"),button=box.querySelector(".microphone"),status=box.querySelector("small");
  let state=box.voiceState;
  if(!state){
    state=box.voiceState={mode:"off",parts:[],pre:[],revision:"",closed:false};
    state.stop=()=>{
      state.closed=true;state.parts=[];state.pre=[];
      if(state.data){state.data.wav="";state.data.reply="";}
      setStateValue("turn",null);
      state.stream?.getTracks().forEach(track=>track.stop());
      state.context?.close().catch(()=>{}); state.audio?.pause(); clearTimeout(state.audioTimer);window.speechSynthesis?.cancel();
    };
  }
  state.data=data;
  box.dataset.ready=String(!!data.ready);
  box.dataset.busy=String(!!data.busy);
  const hangup=box.querySelector(".hangup"),play=box.querySelector(".play-reply"),send=box.querySelector(".send-turn");
  hangup.textContent=data.end||"End call";
  hangup.onclick=()=>{state.stop();box.dataset.mode="ended";button.disabled=true;hangup.disabled=true;status.textContent=data.ended||"Call ended";setStateValue("ended",true);};
  play.textContent=data.play||"Play reply";
  play.onclick=()=>{state.revision="";reply();};
  const submit=()=>{
    if(!state.parts.length||state.closed)return;
    const parts=state.parts;state.parts=[];state.pre=[];send.hidden=true;
    show("thinking");setStateValue("turn",{turn_id:crypto.randomUUID(),audio:wav(parts,state.context.sampleRate)});
  };
  send.textContent=data.send||"Send what I said";send.onclick=submit;
  box.querySelector(".call-reply").textContent=data.reply;
  const show=mode=>{
    if(mode==="listening"&&state.muted)mode="muted";
    state.mode=mode;box.dataset.mode=mode;status.textContent=state.data.labels[mode]||"";
  };
  const micLabel=()=>{
    button.textContent=state.stream?(state.muted?state.data.unmute:state.data.mute):state.data.microphone;
    button.setAttribute("aria-pressed",String(!!state.muted));
  };
  const mascot=box.querySelector(".mascot");
  mascot.setAttribute("aria-label",data.replay);
  mascot.title=data.replay;
  mascot.onanimationend=()=>mascot.classList.remove("wave");
  mascot.onclick=()=>{
    mascot.classList.remove("wave");void mascot.offsetWidth;mascot.classList.add("wave");
    if(!state.stream){button.onclick();return;}
    if(state.mode!=="thinking"){state.revision="";reply();}
  };
  if(!state.mode||state.mode==="off")show("off");
  const reply=async()=>{
    const d=state.data;
    if(state.closed||state.mode==="off")return;
    if(d.failure){show(state.muted?"muted":"listening");status.textContent=d.failure;return;}
    if(d.busy||!d.ready){show("thinking");return;}
    if(state.revision===d.revision)return;
    state.revision=d.revision;show("speaking");state.parts=[];state.pre=[];send.hidden=true;play.hidden=true;
    state.audio?.pause();window.speechSynthesis?.cancel();clearTimeout(state.audioTimer);
    const done=()=>{clearTimeout(state.audioTimer);if(!state.closed&&state.revision===d.revision){play.hidden=true;show("listening");}};
    const blocked=()=>{
      clearTimeout(state.audioTimer);state.audio?.pause();window.speechSynthesis?.cancel();
      if(!state.closed){play.hidden=false;show("paused");}
    };
    state.audioTimer=setTimeout(blocked,Math.max(15000,d.reply.split(/\s+/).length*900+8000));
    if(d.wav){
      const audio=state.audio=new Audio("data:audio/wav;base64,"+d.wav);
      audio.onended=done;audio.onerror=blocked;audio.play().catch(blocked);
    }else{
      const native=window.speechSynthesis?.getVoices().find(v=>v.lang.toLowerCase().split("-")[0]===d.lang);
      if(!native){blocked();return;}
      const utterance=new SpeechSynthesisUtterance(d.reply);
      utterance.voice=native;utterance.lang=native.lang;utterance.onend=done;utterance.onerror=blocked;
      state.utterance=utterance;window.speechSynthesis.speak(utterance);
    }
  };
  micLabel();
  button.onclick=async()=>{
    if(button.disabled)return;
    if(state.stream){
      state.muted=!state.muted;
      state.stream.getAudioTracks().forEach(track=>track.enabled=!state.muted);
      state.parts=[];state.pre=[];
      if(state.mode==="listening"||state.mode==="muted")show(state.muted?"muted":"listening");
      micLabel();return;
    }
    button.disabled=true;show("connecting");
    try{
      const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true},video:false});
      if(state.closed){stream.getTracks().forEach(t=>t.stop());return;}
      state.stream=stream;const ctx=state.context=new AudioContext({sampleRate:16000});
      await ctx.resume();
      const source=ctx.createMediaStreamSource(stream),proc=ctx.createScriptProcessor(2048,1,1);
      source.connect(proc);proc.connect(ctx.destination);
      proc.onaudioprocess=event=>{
        if(state.mode!=="listening"||state.closed||state.muted)return;
        const samples=event.inputBuffer.getChannelData(0).slice();
        const rms=Math.sqrt(samples.reduce((s,v)=>s+v*v,0)/samples.length);
        box.style.setProperty("--voice-level",String(Math.min(1,rms*12)));
        const now=performance.now();
        if(!state.parts.length){
          state.pre.push(samples);if(state.pre.length>3)state.pre.shift();
          const threshold=Math.max(0.004,(state.noise||0.0015)*2.8);
          if(rms<threshold){state.noise=(state.noise||0.0015)*.95+rms*.05;return;}
          state.parts=state.pre;state.pre=[];state.start=now;state.lastVoice=now;send.hidden=false;
        }else state.parts.push(samples);
        if(rms>=Math.max(0.004,(state.noise||0.0015)*2.8))state.lastVoice=now;
        if(now-state.lastVoice>850||now-state.start>45000){
          if(now-state.start<400){state.parts=[];send.hidden=true;return;}
          submit();
        }
      };
      button.disabled=false;micLabel();show("listening");await reply();
    }catch(e){state.stream?.getTracks().forEach(track=>track.stop());state.stream=null;state.context?.close().catch(()=>{});button.disabled=false;micLabel();show("off");status.textContent=data.error;}
  };
  if(state.mode!=="off")reply();
  return state.stop;
}
