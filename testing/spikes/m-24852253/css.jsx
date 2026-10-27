import React,{useState} from 'react';
import {createRoot} from 'react-dom/client';
import {flushSync} from 'react-dom';


const motionMode=false;

const items=()=>Array.from({length:20},(_,i)=>({id:'synthetic-'+i,title:'Propuesta '+(i+1)}));
function App(){const [cards,setCards]=useState(items),[exit,setExit]=useState('');const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
window.bench={reset(){flushSync(()=>{setExit('');setCards(items())})},remove(){if(motionMode||reduced){flushSync(()=>setCards(c=>c.filter(x=>x.id!=='synthetic-1')))}else{flushSync(()=>setExit('synthetic-1'));setTimeout(()=>setCards(c=>c.filter(x=>x.id!=='synthetic-1')),240)}}};
const card=x=><article className="card"><h2>{x.title}</h2><p>Texto sintético para revisar sin publicar.</p><button>Revisar</button></article>;
return <><header><h1>Por aprobar · prueba aislada</h1></header><main>{cards.map(x=><div data-id={x.id} key={x.id} className={'row '+(exit===x.id?'exit':'')}><div className="inner">{card(x)}</div></div>)}</main></>}
createRoot(document.getElementById('root')).render(<App/>);if(!motionMode)window.featuresReady=true;
