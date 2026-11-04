(() => {
"use strict";
let pdfLib=null;
function imageEditor(host,blob,options={}){
 return new Promise((resolve,reject)=>{
  const url=URL.createObjectURL(blob),image=new Image();
  image.onload=()=>{
   const canvas=document.createElement("canvas");canvas.width=image.naturalWidth||image.width;canvas.height=image.naturalHeight||image.height;
   const ctx=canvas.getContext("2d");if(!ctx){URL.revokeObjectURL(url);reject(new Error("Le canevas d’image est indisponible."));return;}
   ctx.drawImage(image,0,0);
   host.innerHTML='<div class="work-image-editor"><div class="work-media-toolbar">'+
    '<button data-image-action="left">↶ Rotation</button><button data-image-action="right">↷ Rotation</button>'+
    '<button data-image-action="flipx">Miroir H</button><button data-image-action="flipy">Miroir V</button>'+
    '<label>Largeur <input data-image-width type="number" min="1" max="12000"></label><label>Hauteur <input data-image-height type="number" min="1" max="12000"></label>'+
    '<button data-image-action="resize">Redimensionner</button><button data-image-action="reset">Réinitialiser</button></div>'+
    '<div class="work-image-stage"></div><p class="work-media-note">Édition locale de l’image. Enregistrer crée une version précédente récupérable.</p></div>';
   host.querySelector(".work-image-stage").appendChild(canvas);
   const setDimensions=()=>{host.querySelector("[data-image-width]").value=canvas.width;host.querySelector("[data-image-height]").value=canvas.height;};
   const mark=()=>{if(typeof options.onChange==="function")options.onChange();};
   const rotate=dir=>{
    const old=document.createElement("canvas");old.width=canvas.width;old.height=canvas.height;old.getContext("2d").drawImage(canvas,0,0);
    canvas.width=old.height;canvas.height=old.width;const c=canvas.getContext("2d");c.translate(canvas.width/2,canvas.height/2);c.rotate(dir*Math.PI/2);c.drawImage(old,-old.width/2,-old.height/2);setDimensions();mark();
   };
   const flip=axis=>{
    const old=document.createElement("canvas");old.width=canvas.width;old.height=canvas.height;old.getContext("2d").drawImage(canvas,0,0);
    const c=canvas.getContext("2d");c.clearRect(0,0,canvas.width,canvas.height);c.save();
    if(axis==="x"){c.translate(canvas.width,0);c.scale(-1,1);}else{c.translate(0,canvas.height);c.scale(1,-1);}
    c.drawImage(old,0,0);c.restore();mark();
   };
   const click=e=>{
    const b=e.target.closest("[data-image-action]");if(!b)return;const action=b.dataset.imageAction;
    if(action==="left")rotate(-1);else if(action==="right")rotate(1);else if(action==="flipx")flip("x");else if(action==="flipy")flip("y");
    else if(action==="resize"){
     const w=Number(host.querySelector("[data-image-width]").value),h=Number(host.querySelector("[data-image-height]").value);
     if(!Number.isInteger(w)||!Number.isInteger(h)||w<1||h<1||w>12000||h>12000||w*h>40000000)return;
     const old=document.createElement("canvas");old.width=canvas.width;old.height=canvas.height;old.getContext("2d").drawImage(canvas,0,0);
     canvas.width=w;canvas.height=h;canvas.getContext("2d").drawImage(old,0,0,w,h);mark();
    }else if(action==="reset"){canvas.width=image.naturalWidth||image.width;canvas.height=image.naturalHeight||image.height;canvas.getContext("2d").drawImage(image,0,0);mark();}
    setDimensions();
   };
   host.addEventListener("click",click);setDimensions();URL.revokeObjectURL(url);
   resolve({async toBlob(){const type=["image/png","image/jpeg","image/webp"].includes(blob.type)?blob.type:"image/png";return await new Promise((done,fail)=>canvas.toBlob(v=>v?done(v):fail(new Error("Export de l’image impossible.")),type,.92));},destroy(){host.removeEventListener("click",click);host.innerHTML="";}});
  };
  image.onerror=()=>{URL.revokeObjectURL(url);reject(new Error("Ce format image ne peut pas être édité par ce navigateur."));};image.src=url;
 });
}
async function getPdfLib(){
 if(!pdfLib)pdfLib=import("https://cdn.jsdelivr.net/npm/pdf-lib@1.17.1/+esm").catch(()=>{pdfLib=null;throw new Error("Le moteur PDF n’a pas pu être chargé. Vérifie la connexion.");});
 return pdfLib;
}
function pdfEditor(host,blob,options={}){
 const url=URL.createObjectURL(blob),annotations=[],rotations={};
 host.innerHTML='<div class="work-pdf-editor"><div class="work-media-toolbar work-pdf-toolbar">'+
  '<label>Page <input data-pdf-page type="number" min="1" value="1"></label><label>Texte <input data-pdf-text maxlength="500" placeholder="Texte à ajouter"></label>'+
  '<label>X <input data-pdf-x type="number" min="0" value="48"></label><label>Y <input data-pdf-y type="number" min="0" value="48"></label>'+
  '<label>Taille <input data-pdf-size type="number" min="6" max="96" value="12"></label>'+
  '<button data-pdf-action="add">Ajouter le texte</button><button data-pdf-action="rotate">Tourner +90°</button></div>'+
  '<iframe class="work-binary-pdf" title="Aperçu du PDF original" src="'+url+'"></iframe>'+
  '<div class="work-pdf-annotations" data-pdf-annotations>Aucune annotation ajoutée.</div>'+
  '<p class="work-media-note">Llink ajoute du texte et tourne des pages. Le texte déjà présent dans le PDF n’est pas réécrit.</p></div>';
 const list=host.querySelector("[data-pdf-annotations]");
 const click=e=>{
  const b=e.target.closest("[data-pdf-action]");if(!b)return;
  const page=Number(host.querySelector("[data-pdf-page]").value);if(!Number.isInteger(page)||page<1)return;
  if(b.dataset.pdfAction==="add"){
   const text=host.querySelector("[data-pdf-text]").value.trim(),x=Number(host.querySelector("[data-pdf-x]").value),y=Number(host.querySelector("[data-pdf-y]").value),fontSize=Number(host.querySelector("[data-pdf-size]").value);
   if(!text||!Number.isFinite(x)||!Number.isFinite(y)||!Number.isFinite(fontSize)||fontSize<6||fontSize>96)return;
   annotations.push({page:page-1,text,x:Math.max(0,x),y:Math.max(0,y),fontSize});
  }else rotations[page-1]=(rotations[page-1]||0)+90;
  const lines=annotations.map(a=>"Texte · page "+(a.page+1)+" · "+a.text.slice(0,80));
  Object.keys(rotations).forEach(k=>lines.push("Rotation · page "+(Number(k)+1)+" · "+rotations[k]+"°"));
  list.textContent=lines.length?lines.join(" | "):"Aucune annotation ajoutée.";
  if(typeof options.onChange==="function")options.onChange();
 };
 host.addEventListener("click",click);
 return {
  async toBlob(){
   if(!annotations.length&&!Object.keys(rotations).length)return blob;
   const lib=await getPdfLib(),doc=await lib.PDFDocument.load(await blob.arrayBuffer()),font=await doc.embedFont(lib.StandardFonts.Helvetica),pages=doc.getPages();
   annotations.forEach(a=>{const p=pages[a.page];if(!p)throw new Error("La page "+(a.page+1)+" n’existe pas.");p.drawText(a.text,{x:Math.min(a.x,p.getWidth()),y:Math.max(0,p.getHeight()-a.y-a.fontSize),size:a.fontSize,font,color:lib.rgb(.08,.12,.18),maxWidth:Math.max(24,p.getWidth()-a.x)});});
   Object.entries(rotations).forEach(([i,angle])=>{const p=pages[Number(i)];if(!p)throw new Error("Une page à tourner n’existe pas.");p.setRotation(lib.degrees(((p.getRotation().angle||0)+angle)%360));});
   return new Blob([await doc.save()],{type:"application/pdf"});
  },
  destroy(){host.removeEventListener("click",click);URL.revokeObjectURL(url);host.innerHTML="";}
 };
}
window.LlinkBinaryEditors={openImage:imageEditor,openPdf:pdfEditor,version:"1.0.0"};
})();