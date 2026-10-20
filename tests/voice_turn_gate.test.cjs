/* Pure sample-clock tests: no browser, microphone or timer mocks. */
const assert=require('node:assert/strict');
const {VoiceTurnGate}=require('../apps/web/voice-session-capture.js');
const events=[],gate=new VoiceTurnGate(16000,e=>events.push(e));
function feed(seconds,value=0){for(let n=0;n<seconds*16000;n+=160)gate.push(new Float32Array(160).fill(value));}
feed(60,.1);assert.equal(events.length,0);
gate.enable(true);feed(60);assert.equal(events.length,0);assert.equal(gate.length,0);
feed(.1,.05);feed(.4);assert.equal(events.length,0,'short click cannot open a turn');
feed(.3,.05);assert.equal(events[0].type,'speech-start');
feed(.6);assert.equal(events.length,1,'hesitation is not immediately a completed turn');
feed(.2,.05);feed(1.1);
assert.equal(events[1].type,'segment');assert.equal(events[1].limited,false);
assert.ok(events[1].samples.length<=18*16000);
feed(30,.05);assert.equal(events.length,2,'inference/playback muted intervals never queue');
gate.enable(true);feed(21,.05);
assert.equal(events.length,4);assert.equal(events[3].limited,true);assert.equal(events[3].samples.length,288000);
gate.enable(true);feed(.3,.05);gate.enable(false);gate.enable(true);feed(2);
assert.equal(events.length,5,'disable erases partially captured utterance');
assert.equal(gate.buffer.length,288000);assert.equal(gate.pre.length,3840);
console.log('Voice gate: silence, clicks, hesitation, cap, mute and erase passed');
