function init(){var p=[];for(var i=0;i<4;i++){p.push({x:20+Math.random()*200,y:24+Math.random()*96});}return{px:120,py:67,score:0,colorIdx:0,parcels:p,trail:[],t:0,prevA:false,prevB:false};}
function update(state,input,dt){var jx=0,jy=0,ba=false,bb=false;if(input&&input.joystick){jx=input.joystick.x;jy=input.joystick.y;}if(input){ba=!!input.button_a;bb=!!input.button_b;}
var ci=state.colorIdx;if(ba&&!state.prevA){ci=(ci+1)%5;}
var px=state.px,py=state.py,score=state.score,parcels=state.parcels,trail=state.trail,t=state.t+dt;
if(bb&&!state.prevB){return{px:120,py:67,score:0,colorIdx:ci,parcels:[{x:20+Math.random()*200,y:24+Math.random()*96},{x:20+Math.random()*200,y:24+Math.random()*96},{x:20+Math.random()*200,y:24+Math.random()*96},{x:20+Math.random()*200,y:24+Math.random()*96}],trail:[],t:0,prevA:ba,prevB:bb};}
var sp=110;px+=jx*sp*dt;py+=jy*sp*dt;if(px<8)px=8;if(px>232)px=232;if(py<18)py=18;if(py>127)py=127;
var nt=trail.slice(-11);nt.push({x:px,y:py});
var np=[];for(var i=0;i<parcels.length;i++){var q=parcels[i];var dx=q.x-px,dy=q.y-py;if(dx*dx+dy*dy<144){score+=1;np.push({x:15+Math.random()*210,y:24+Math.random()*96});}else{np.push(q);}}
return{px:px,py:py,score:score,colorIdx:ci,parcels:np,trail:nt,t:t,prevA:ba,prevB:bb};}
function draw(state){var cols=["#00FFFF","#FF00FF","#00FF66","#FF3366","#3388FF"];var cc=cols[state.colorIdx%5];var c=[{op:"clear",color:"#05051A"}];for(var gx=20;gx<240;gx+=20){c.push({op:"line",x:gx,y:14,x2:gx,y2:135,color:"#151545"});}for(var gy=29;gy<135;gy+=15){c.push({op:"line",x:0,y:gy,x2:240,y2:gy,color:"#151545"});}
c.push({op:"rect",x:0,y:0,w:240,h:14,color:"#0A0A2A"});c.push({op:"line",x:0,y:14,x2:240,y2:14,color:"#00FFFF"});
for(var i=0;i<state.parcels.length;i++){var q=state.parcels[i];var bob=Math.sin(state.t*4+i*1.7)*2;var yy=q.y+bob;c.push({op:"circle",x:q.x,y:yy,r:9,color:"#554400"});c.push({op:"rect",x:q.x-5,y:yy-5,w:10,h:10,color:"#FFE433"});c.push({op:"rect",x:q.x-5,y:yy-1,w:10,h:2,color:"#AA8800"});c.push({op:"circle",x:q.x,y:yy,r:2,color:"#FFFFFF"});}
for(var k=0;k<state.trail.length;k++){var tr=state.trail[k];if(k===state.trail.length-1)continue;c.push({op:"circle",x:tr.x,y:tr.y,r:3,color:"#0A4444"});}
c.push({op:"circle",x:state.px,y:state.py,r:10,color:"#222222"});c.push({op:"circle",x:state.px,y:state.py,r:7,color:cc});c.push({op:"circle",x:state.px,y:state.py,r:3,color:"#FFFFFF"});c.push({op:"rect",x:state.px-8,y:state.py-12,w:16,h:3,color:cc});
c.push({op:"text",x:4,y:2,text:"SCORE "+state.score,size:10,color:"#FFFF66"});c.push({op:"text",x:130,y:2,text:"A:color B:reset",size:8,color:"#88FFFF"});return c;}