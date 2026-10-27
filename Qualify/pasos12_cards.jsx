import React,{useState} from 'react';
import {createRoot} from 'react-dom/client';
import {flushSync} from 'react-dom';
import {LazyMotion,AnimatePresence,useReducedMotion} from 'motion/react';
import * as m from 'motion/react-m';
const motionMode=true;
const loadFeatures=()=>import('./pasos12_features.js').then(x=>{window.featuresReady=true;return x.default});
const items=()=>Array.from({length:20},(_,i)=>({id:'synthetic-'+i,title:'Propuesta '+(i+1)}));
function App(){const [cards,setCards]=useState(items),[exit,setExit]=useState('');const reduced=motionMode?useReducedMotion():matchMedia('(prefers-reduced-motion: reduce)').matches;
window.bench={reset(){flushSync(()=>{setExit('');setCards(items())})},remove(){if(motionMode||reduced){flushSync(()=>setCards(c=>c.filter(x=>x.id!=='synthetic-1')))}else{flushSync(()=>setExit('synthetic-1'));setTimeout(()=>setCards(c=>c.filter(x=>x.id!=='synthetic-1')),240)}}};
const card=x=><article className="card"><h2>{x.title}</h2><p>Texto sintético para revisar sin publicar.</p><button>Revisar</button></article>;
return <><header><h1>Por aprobar · prueba aislada</h1></header><main>{motionMode?<LazyMotion strict features={loadFeatures}><AnimatePresence initial={false} mode="popLayout">{cards.map(x=><m.div key={x.id} data-id={x.id} layout={reduced?false:'position'} initial={false} exit={reduced?{opacity:1,x:0}:{opacity:0,x:-12}} transition={{duration:reduced?0:.24,ease:[.22,1,.36,1]}}>{card(x)}</m.div>)}</AnimatePresence></LazyMotion>:cards.map(x=><div data-id={x.id} key={x.id} className={'row '+(exit===x.id?'exit':'')}><div className="inner">{card(x)}</div></div>)}</main></>}

export { App as MotionCardList };
