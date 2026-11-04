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
function docxBlob(payload={}){
 const O=window.LlinkOpenXml;if(!O?.zipStore)throw new Error("Le moteur DOCX local n’est pas chargé.");
 const x=O.escapeXml,run=r=>'<w:r><w:rPr>'+(r.bold?'<w:b/>':'')+(r.italic?'<w:i/>':'')+(r.underline?'<w:u w:val="single"/>':'')+(r.code?'<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/>':'')+'</w:rPr><w:t xml:space="preserve">'+x(r.text||"")+'</w:t></w:r>';
 const paragraph=(text,style,runs)=>'<w:p>'+(style?'<w:pPr><w:pStyle w:val="'+style+'"/></w:pPr>':'')+((runs&&runs.length)?runs.map(run).join(""):run({text:text||""}))+'</w:p>';
 const blocks=Array.isArray(payload.blocks)?payload.blocks:[{type:"paragraph",text:""}];
 let body="";
 for(const b of blocks){
  if(b.type==="page_break"){body+='<w:p><w:r><w:br w:type="page"/></w:r></w:p>';continue;}
  if(b.type==="table"){
   const rows=Array.isArray(b.rows)?b.rows:[];
   body+='<w:tbl><w:tblPr><w:tblBorders>'+["top","left","bottom","right","insideH","insideV"].map(n=>'<w:'+n+' w:val="single" w:sz="4" w:color="AAB3C2"/>').join("")+'</w:tblBorders></w:tblPr>';
   for(const row of rows)body+='<w:tr>'+row.map(cell=>'<w:tc><w:tcPr><w:tcW w:w="2400" w:type="dxa"/></w:tcPr>'+paragraph(String(cell??""))+'</w:tc>').join("")+'</w:tr>';
   body+='</w:tbl>';continue;
  }
  if(b.type==="image")continue;
  let text=String(b.text||"");
  if(b.type==="bullet")text="•  "+text;
  if(b.type==="numbered")text="1.  "+text;
  const style=b.type==="heading"?"Heading"+Math.min(3,Math.max(1,Number(b.level)||1)):b.type==="quote"?"Quote":null;
  body+=paragraph(text,style,b.runs);
 }
 const title=x(payload.title||"Document"),subtitle=x(payload.subtitle||""),author=x(payload.author||"Llink Work");
 if(payload.title)body=paragraph(payload.title,"Title")+body;
 if(payload.subtitle)body=paragraph(payload.subtitle,"Subtitle")+body;
 const documentXml='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>'+body+'<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr></w:body></w:document>';
 const contentTypes='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>';
 const rootRels='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>';
 const docRels='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>';
 const styles='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:sz w:val="22"/><w:rFonts w:ascii="Aptos" w:hAnsi="Aptos"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:rPr><w:i/><w:color w:val="667085"/><w:sz w:val="24"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="360"/></w:pPr><w:rPr><w:i/><w:color w:val="667085"/></w:rPr></w:style></w:styles>';
 const now=new Date().toISOString();
 const core='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>'+title+'</dc:title><dc:subject>'+subtitle+'</dc:subject><dc:creator>'+author+'</dc:creator><dcterms:created xsi:type="dcterms:W3CDTF">'+now+'</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">'+now+'</dcterms:modified></cp:coreProperties>';
 const app='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Llink Work</Application></Properties>';
 return O.zipStore({"[Content_Types].xml":contentTypes,"_rels/.rels":rootRels,"word/document.xml":documentXml,"word/_rels/document.xml.rels":docRels,"word/styles.xml":styles,"docProps/core.xml":core,"docProps/app.xml":app});
}
function blocksToHtml(blocks){
 const x=esc;return (Array.isArray(blocks)?blocks:[]).map(b=>{
  if(b.type==="page_break")return "<hr>";
  if(b.type==="table")return "<table><tbody>"+(b.rows||[]).map(row=>"<tr>"+row.map(v=>"<td>"+x(v)+"</td>").join("")+"</tr>").join("")+"</tbody></table>";
  if(b.type==="image")return b.data_url?'<p><img src="'+x(b.data_url)+'" alt="'+x(b.alt||"Illustration")+'"></p>':"";
  const text=(Array.isArray(b.runs)&&b.runs.length?b.runs.map(r=>{let t=x(r.text);if(r.bold)t="<strong>"+t+"</strong>";if(r.italic)t="<em>"+t+"</em>";if(r.underline)t="<u>"+t+"</u>";return t;}).join(""):x(b.text||"")).replace(/\n/g,"<br>");
  return b.type==="heading"?"<h"+Math.min(3,Math.max(1,Number(b.level)||1))+">"+text+"</h"+Math.min(3,Math.max(1,Number(b.level)||1))+">":b.type==="bullet"?"<ul><li>"+text+"</li></ul>":b.type==="numbered"?"<ol><li>"+text+"</li></ol>":b.type==="quote"?"<blockquote>"+text+"</blockquote>":"<p>"+text+"</p>";
 }).join("")||"<p>Document vide.</p>";
}
async function open(host,blob,options={}){
 if(!(blob instanceof Blob))throw new Error("Le document Word est indisponible.");
 const name=String(options.filename||"document.docx").replace(/\.docx$/i,"");
 let html;
 if(options.documentData&&Array.isArray(options.documentData.blocks))html=sanitize(blocksToHtml(options.documentData.blocks));
 else{
  const engine=await mammoth();
  const convertImage=engine.images?.inline?engine.images.inline(async image=>({src:"data:"+image.contentType+";base64,"+await image.read("base64")})):undefined;
  const result=await engine.convertToHtml({arrayBuffer:await blob.arrayBuffer()},convertImage?{convertImage}: {});
  html=sanitize(result.value||"<p>Document vide.</p>");
 }
 host.innerHTML='<div class="work-doc-editor"><div class="work-doc-meta">'+
  '<label>Titre<input data-doc-meta="title" maxlength="300" value="'+esc(options.documentData?.title||name)+'"></label>'+
  '<label>Sous-titre<input data-doc-meta="subtitle" maxlength="500" value="'+esc(options.documentData?.subtitle||'')+'" placeholder="Facultatif"></label>'+
  '<label>Auteur<input data-doc-meta="author" maxlength="160" value="'+esc(options.documentData?.author||'Llink Work')+'"></label></div>'+
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
  setPayload(payload){
   if(!payload||!Array.isArray(payload.blocks))throw new Error("Le brouillon Word reçu est invalide.");
   options.documentData=payload;
   host.querySelector('[data-doc-meta="title"]').value=String(payload.title||name).slice(0,300);
   host.querySelector('[data-doc-meta="subtitle"]').value=String(payload.subtitle||"").slice(0,500);
   host.querySelector('[data-doc-meta="author"]').value=String(payload.author||"Llink Work").slice(0,160);
   body.innerHTML=sanitize(blocksToHtml(payload.blocks));
  },
  async toBlob(){return docxBlob(this.toPayload());},
  destroy(){host.removeEventListener("input",input);host.removeEventListener("click",click);host.innerHTML="";}
 };
}
window.LlinkDocumentEditor={
 open,
 createBlank:()=>docxBlob({title:"Nouveau document",blocks:[{type:"paragraph",text:"Commence à rédiger ici…"}]}),
 createFromPayload:payload=>docxBlob(payload||{}),
 version:"1.2.0"
};
})();