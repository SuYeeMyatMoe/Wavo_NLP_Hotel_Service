export default function({parentElement,data,setTriggerValue}){
 const box=parentElement.querySelector(".peer"),button=box.querySelector("button"),status=box.querySelector("small");
 let s=box.session;
 if(!s){
   s=box.session={closed:false,busy:false,lastOffer:""};
   s.close=()=>{s.closed=true;s.pc?.close();s.stream?.getTracks().forEach(t=>t.stop());};
 }
 s.data=data;
 async function sync(){
   if(s.closed||s.busy||!s.stream)return;
   const remote=s.data;
   s.busy=true;
   try{
     if(!s.pc||(remote.side==="staff"&&remote.offer&&s.lastOffer!==remote.offer)){
       s.pc?.close();const pc=s.pc=new RTCPeerConnection({iceServers:remote.ice||[]});
       s.stream.getTracks().forEach(t=>pc.addTrack(t,s.stream));
       pc.ontrack=e=>{const a=box.querySelector("audio");a.srcObject=e.streams[0];a.play().catch(()=>{});};
       pc.onconnectionstatechange=()=>status.textContent=pc.connectionState;
       if(remote.side==="guest")await publish(pc,await pc.createOffer());
     }
     if(remote.side==="staff"&&remote.offer&&s.lastOffer!==remote.offer){
       s.lastOffer=remote.offer;
       await s.pc.setRemoteDescription({type:"offer",sdp:remote.offer});
       await publish(s.pc,await s.pc.createAnswer());
     }else if(remote.side==="guest"&&remote.answer&&s.pc.signalingState==="have-local-offer"){
       await s.pc.setRemoteDescription({type:"answer",sdp:remote.answer});
     }
   }catch(e){status.textContent=remote.error;}finally{s.busy=false;}
 }
 async function publish(pc,desc){
   const gathered=new Promise(resolve=>{const timer=setTimeout(resolve,4000);pc.onicegatheringstatechange=()=>{if(pc.iceGatheringState==="complete"){clearTimeout(timer);resolve();}};});
   await pc.setLocalDescription(desc);await gathered;
   if(!s.closed)setTriggerValue("signal",pc.localDescription.toJSON());
 }
 button.textContent=data.microphone;
 button.onclick=async()=>{try{const media=await navigator.mediaDevices.getUserMedia({audio:true});if(s.closed){media.getTracks().forEach(t=>t.stop());return;}s.stream=media;button.hidden=true;await sync();}catch(e){status.textContent=data.error;}};
 sync();return s.close;
}
