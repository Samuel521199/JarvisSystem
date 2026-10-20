/* Energy segmentation only; the local Silero gate verifies speech before ASR.
   The bounded ring is erased while disabled; muted intervals never queue. */
class VoiceTurnGate {
 constructor(rate, emit) {
  this.rate=rate;this.emit=emit;this.enabled=false;this.reset();
 }
 reset() {
  this.buffer=new Float32Array(Math.ceil(this.rate*18));
  this.pre=new Float32Array(Math.ceil(this.rate*.24));this.preAt=0;this.preCount=0;
  this.length=0;this.hot=0;this.quiet=0;this.started=false;this.noise=.001;
 }
 enable(value) {this.enabled=value;this.reset();}
 push(data) {
  if(!this.enabled)return;
  let sum=0;for(const x of data)sum+=x*x;
  const rms=Math.sqrt(sum/data.length),loud=rms>Math.max(.008,this.noise*3);
  if(!this.started&&!loud)this.noise=this.noise*.99+Math.min(rms,.006)*.01;
  if(!this.started) {
   for(const x of data){this.pre[this.preAt]=x;this.preAt=(this.preAt+1)%this.pre.length;this.preCount=Math.min(this.preCount+1,this.pre.length);}
   this.hot=loud?this.hot+data.length:0;
   if(this.hot<this.rate*.16)return;
   this.started=true;
   for(let i=0;i<this.preCount;i++)this.buffer[this.length++]=this.pre[(this.preAt-this.preCount+i+this.pre.length)%this.pre.length];
   this.emit({type:'speech-start'});
  }else{
   const take=Math.min(data.length,this.buffer.length-this.length);
   this.buffer.set(data.subarray(0,take),this.length);this.length+=take;
  }
  this.quiet=loud?0:this.quiet+data.length;
  if(this.quiet>=this.rate*1.1||this.length>=this.buffer.length){
   const samples=this.buffer.slice(0,this.length),limited=this.length>=this.buffer.length;
   this.enable(false);this.emit({type:'segment',samples,limited});
  }
 }
}
if(typeof module!=='undefined')module.exports={VoiceTurnGate};
if(typeof AudioWorkletProcessor!=='undefined'){
 class JarvisSessionCapture extends AudioWorkletProcessor{
  constructor(){super();this.epoch=0;this.gate=new VoiceTurnGate(sampleRate,data=>this.port.postMessage({...data,epoch:this.epoch},data.samples?[data.samples.buffer]:[]));
   this.port.onmessage=e=>{this.epoch=e.data.epoch;this.gate.enable(e.data.enabled===true);};}
  process(inputs){const data=inputs[0]?.[0];if(data)this.gate.push(data);return true;}
 }
 registerProcessor('jarvis-session-capture',JarvisSessionCapture);
}
