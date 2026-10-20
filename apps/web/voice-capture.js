/* Fixed-size PCM chunks. No audio is played back through this worklet. */
class JarvisCapture extends AudioWorkletProcessor {
 constructor(){super();this.block=new Float32Array(2048);this.offset=0;this.count=0;this.finished=false;
  this.port.onmessage=e=>{if(e.data==='finish')this.finish();};
 }
 flush(){if(this.offset){const block=this.block.slice(0,this.offset);this.port.postMessage({samples:block},[block.buffer]);this.offset=0;}}
 finish(){if(this.finished)return;this.finished=true;this.flush();this.port.postMessage({finished:true});}
 process(inputs){
  if(this.finished)return false;
  const data=inputs[0]?.[0];if(!data)return true;
  for(const value of data){
   this.block[this.offset++]=value;this.count++;
   if(this.offset===this.block.length)this.flush();
   if(this.count>=sampleRate*20){this.finish();return false;}
  }
  return true;
 }
}
registerProcessor('jarvis-capture',JarvisCapture);
