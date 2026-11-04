(() => {
"use strict";
const encoder = new TextEncoder();
function crc32(bytes) {
 let crc = 0xFFFFFFFF;
 for (const byte of bytes) {
  crc ^= byte;
  for (let i=0;i<8;i++) crc = (crc >>> 1) ^ (0xEDB88320 & -(crc & 1));
 }
 return (crc ^ 0xFFFFFFFF) >>> 0;
}
function dosDate(date=new Date()) {
 const year=Math.max(1980,date.getFullYear());
 return {time:(date.getHours()<<11)|(date.getMinutes()<<5)|(date.getSeconds()>>1),
 date:((year-1980)<<9)|((date.getMonth()+1)<<5)|date.getDate()};
}
function zipStore(files) {
 const chunks=[],central=[],stamp=dosDate(); let offset=0;
 for (const [name,value] of Object.entries(files)) {
  const filename=encoder.encode(name),data=typeof value==="string"?encoder.encode(value):value;
  const crc=crc32(data),local=new Uint8Array(30+filename.length),lv=new DataView(local.buffer);
  lv.setUint32(0,0x04034b50,true);lv.setUint16(4,20,true);lv.setUint16(6,0x0800,true);
  lv.setUint16(8,0,true);lv.setUint16(10,stamp.time,true);lv.setUint16(12,stamp.date,true);
  lv.setUint32(14,crc,true);lv.setUint32(18,data.length,true);lv.setUint32(22,data.length,true);
  lv.setUint16(26,filename.length,true);lv.setUint16(28,0,true);local.set(filename,30);
  chunks.push(local,data);
  const record=new Uint8Array(46+filename.length),cv=new DataView(record.buffer);
  cv.setUint32(0,0x02014b50,true);cv.setUint16(4,20,true);cv.setUint16(6,20,true);
  cv.setUint16(8,0x0800,true);cv.setUint16(10,0,true);cv.setUint16(12,stamp.time,true);cv.setUint16(14,stamp.date,true);
  cv.setUint32(16,crc,true);cv.setUint32(20,data.length,true);cv.setUint32(24,data.length,true);
  cv.setUint16(28,filename.length,true);cv.setUint16(30,0,true);cv.setUint16(32,0,true);
  cv.setUint16(34,0,true);cv.setUint16(36,0,true);cv.setUint32(38,0,true);cv.setUint32(42,offset,true);
  record.set(filename,46);central.push(record);offset+=local.length+data.length;
 }
 const centralSize=central.reduce((n,a)=>n+a.length,0),end=new Uint8Array(22),ev=new DataView(end.buffer);
 ev.setUint32(0,0x06054b50,true);ev.setUint16(4,0,true);ev.setUint16(6,0,true);
 ev.setUint16(8,central.length,true);ev.setUint16(10,central.length,true);
 ev.setUint32(12,centralSize,true);ev.setUint32(16,offset,true);ev.setUint16(20,0,true);
 return new Blob([...chunks,...central,end],{type:"application/vnd.openxmlformats-officedocument"});
}
window.LlinkOpenXml={zipStore,escapeXml:value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&apos;"}[c]))};
})();