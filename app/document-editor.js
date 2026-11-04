(() => {
"use strict";
let loader=null;
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function mammoth(){
 if(window.mammoth?.convertToHtml)return Promise.resolve(window.mammoth);
 if(loader)return loader;
 loader=new Promise((resolve,reject)=>{
  const script=document.createElement("script");
  script.src="https://cdnjs.cloudflare.com/ajax/libs/mammoth/1.8.0/mammoth.browser.min.js";
  script.onload=()=>window.mammoth?.convertToHtml?resolve(window.mammoth):reject(new Error("Le moteur DOCX est indisponible."));
  script.onerror=()=>reject(new Error("Impossible de charger le moteur Word. Vérifie ta connexion."));
  document.head.appendChild(script);
 }).catch(e=>{loader=null;throw e;});
 return loader;
}
function sanitize(html){
 if(window.DOMPurify?.sanitize)return window.DOMPurify.sanitize(html,{
  ALLOWED_TAGS:["p","h1","h2","h3","strong","b","em","i","u","s","ul","ol","li","blockquote","table","thead","tbody","tr","th","td","br","hr","img","span","a"],
  ALLOWED_ATTR:["src","alt","title","href"],FORBID_ATTR:["style","onclick","onerror"]
 });
 const t=document.createElement("template");t.innerHTML=html||"";
 t.content.querySelectorAll("script,iframe,object,embed,style,form,link,meta").forEach(n=>n.remove());
 t.content.querySelectorAll("*").forEach(n=>Array.from(n.attributes).forEach(a=>{
  if(/^on/i.test(a.name)||a.name==="style")n.removeAttribute(a.name);
  if(["src","href"].includes(a.name)&&!(/^(https?:|data:image\/(png|jpeg);base64,)/i.test(a.value)))n.removeAttribute(a.name);
 }));
 return t.innerHTML;
}
function runsFrom(node){
 const out=[];
 function walk(n,s){
  if(n.nodeType===Node.TEXT_NODE){const value=n.nodeValue||"";if(value)out.push({text:value,bold:s.bold,italic:s.italic,underline:s.underline,code:s.code});return;}
  if(n.nodeType!==Node.ELEMENT_NODE)return;
  const tag=n.tagName.toLowerCase();if(tag==="img")return;
  if(tag==="br"){out.push({text:"\n",bold:s.bold,italic:s.italic,underline:s.underline,code:s.code});return;}
  const next={bold:s.bold||tag==="b"||tag==="strong",italic:s.italic||tag==="i"||tag==="em",underline:s.underline||tag==="u",code:s.code||tag==="code"||tag==="pre"};
  Array.from(n.childNodes).forEach(child=>walk(child,next));
 }
 Array.from(node.childNodes).forEach(n=>walk(n,{bold:false,italic:false,underline:false,code:false}));
 return out;
}
function textBlock(type,node,extra){
 const runs=runsFrom(node),text=runs.map(r=>r.text).join("").trim();
 if(!text)return null;
 return Object.assign({type,text,runs},extra||{});
}
function blocksFrom(root){
 const out=[];
 const visit=node=>{
  if(node.nodeType===Node.TEXT_NODE){const text=(node.nodeValue||"").trim();if(text)out.push({type:"paragraph",text});return;}
  if(node.nodeType!==Node.ELEMENT_NODE)return;
  const tag=node.tagName.toLowerCase();
  if(/^h[1-3]$/.test(tag)){const b=textBlock("heading",node,{level:Number(tag.slice(1))});if(b)out.push(b);}
  else if(tag==="p"||tag==="div"){const b=textBlock("paragraph",node);if(b)out.push(b);node.querySelectorAll(":scope > img").forEach(addImage);}
  else if(tag==="blockquote"){const b=textBlock("quote",node);if(b)out.push(b);}
  else if(tag==="ul"||tag==="ol"){node.querySelectorAll(":scope > li").forEach(li=>{const b=textBlock(tag==="ul"?"bullet":"numbered",li);if(b)out.push(b);});}
  else if(tag==="table"){const rows=Array.from(node.querySelectorAll("tr")).map(tr=>Array.from(tr.querySelectorAll("th,td")).map(td=>(td.innerText||td.textContent||"").trim())).filter(row=>row.length);if(rows.length)out.push({type:"table",rows});}
  else if(tag==="hr")out.push({type:"page_break"});
  else if(tag==="img")addImage(node);
  else Array.from(node.childNodes).forEach(visit);
 };
 const addImage=node=>{const src=node.getAttribute("src")||"";if(/^data:image\/(png|jpeg);base64,/i.test(src))out.push({type:"image",data_url:src,alt:node.getAttribute("alt")||"Illustration"});};
 Array.from(root.childNodes).forEach(visit);
 return out.length?out:[{type:"paragraph",text:(root.innerText||"").trim()||" "}];
}
async function open(host,blob,options={}){
 if(!(blob instanceof Blob))throw new Error("Le document Word est indisponible.");
 const engine=await mammoth();
 const convertImage=engine.images?.inline?engine.images.inline(async image=>({src:"data:"+image.contentType+";base64,"+await image.read("base64")})):undefined;
 const result=await engine.convertToHtml({arrayBuffer:await blob.arrayBuffer()},convertImage?{convertImage}: {});
 const html=sanitize(result.value||"<p>Document vide.</p>");
 const name=String(options.filename||"document.docx").replace(/\.docx$/i,"");
 host.innerHTML='<div class="work-doc-editor"><div class="work-doc-meta">'+
  '<label>Titre<input data-doc-meta="title" maxlength="300" value="'+esc(name)+'"></label>'+
  '<label>Sous-titre<input data-doc-meta="subtitle" maxlength="500" placeholder="Facultatif"></label>'+
  '<label>Auteur<input data-doc-meta="author" maxlength="160" value="Llink Work"></label></div>'+
  '<div class="work-doc-toolbar">'+
  '<button type="button" data-doc-action="bold"><b>G</b></button><button type="button" data-doc-action="italic"><i>I</i></button><button type="button" data-doc-action="underline"><u>S</u></button>'+
  '<button type="button" data-doc-action="h1">Titre 1</button><button type="button" data-doc-action="h2">Titre 2</button>'+
  '<button type="button" data-doc-action="bullet">• Liste</button><button type="button" data-doc-action="numbered">1. Liste</button>'+
  '<button type="button" data-doc-action="quote">Citation</button><button type="button" data-doc-action="table">Tableau</button><button type="button" data-doc-action="break">Saut de page</button></div>'+
  '<div class="work-doc-content" data-doc-content contenteditable="true" spellcheck="true">'+html+'</div>'+
  '<p class="work-media-note">L’éditeur conserve le texte, les titres, listes, tableaux et images reconnus. Les mises en page Word complexes peuvent être simplifiées à l’importation.</p></div>';
 const body=host.querySelector("[data-doc-content]");
 const changed=()=>{if(typeof options.onChange==="function")options.onChange();};
 const click=e=>{
  const b=e.target.closest("[data-doc-action]");if(!b)return;
  const action=b.dataset.docAction;body.focus();
  if(action==="table")document.execCommand("insertHTML",false,"<table><tbody><tr><td>Cellule 1</td><td>Cellule 2</td></tr><tr><td>Cellule 3</td><td>Cellule 4</td></tr></tbody></table><p><br></p>");
  else if(action==="h1"||action==="h2")document.execCommand("formatBlock",false,action);
  else if(action==="bullet")document.execCommand("insertUnorderedList");
  else if(action==="numbered")document.execCommand("insertOrderedList");
  else if(action==="quote")document.execCommand("formatBlock",false,"blockquote");
  else if(action==="break")document.execCommand("insertHTML",false,"<hr><p><br></p>");
  else document.execCommand(action);
  changed();
 };
 const input=()=>changed();host.addEventListener("input",input);host.addEventListener("click",click);
 return {
  toPayload(){
   return {filename:options.filename||"document.docx",title:host.querySelector('[data-doc-meta="title"]').value.trim().slice(0,300)||name,
    subtitle:host.querySelector('[data-doc-meta="subtitle"]').value.trim().slice(0,500),
    author:host.querySelector('[data-doc-meta="author"]').value.trim().slice(0,160),institution:"",
    blocks:blocksFrom(body)};
  },
  destroy(){host.removeEventListener("input",input);host.removeEventListener("click",click);host.innerHTML="";}
 };
}
window.LlinkDocumentEditor={open,version:"1.0.0"};
})();