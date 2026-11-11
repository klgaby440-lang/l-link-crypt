(() => {
 const root=document.documentElement, saved=localStorage.getItem("llink_help_theme");
 if(saved==="light"||saved==="dark")root.dataset.theme=saved;
 const toggle=document.getElementById("theme-toggle");
 toggle?.addEventListener("click",()=>{const next=root.dataset.theme==="light"?"dark":"light";root.dataset.theme=next;localStorage.setItem("llink_help_theme",next);toggle.textContent=next==="dark"?"☼":"☾";});
 if(toggle)toggle.textContent=root.dataset.theme==="light"?"☾":"☼";
 const search=document.getElementById("help-search"),sections=[...document.querySelectorAll(".help-section")],nav=[...document.querySelectorAll(".quick-nav a")];
 function filter(){const q=(search?.value||"").trim().toLocaleLowerCase("fr");sections.forEach(section=>{const text=(section.innerText+" "+(section.dataset.search||"")).toLocaleLowerCase("fr"),matches=!q||text.includes(q);section.classList.toggle("hidden-by-search",!matches);section.querySelectorAll("details.faq").forEach(item=>{const ok=!q||(item.innerText+" "+(section.dataset.search||"")).toLocaleLowerCase("fr").includes(q);item.classList.toggle("hidden-by-search",!ok);if(q&&ok)item.open=true;if(!q)item.open=false;});});nav.forEach(a=>{const section=document.querySelector(a.getAttribute("href"));a.classList.toggle("hidden-by-search",!!q&&(!section||section.classList.contains("hidden-by-search")));});}
 search?.addEventListener("input",filter);
 document.addEventListener("keydown",e=>{if(e.key==="/"&&document.activeElement!==search){e.preventDefault();search?.focus();}if(e.key==="Escape"&&search){search.value="";filter();search.blur();}});
 document.getElementById("copy-diagnostic")?.addEventListener("click",async()=>{const report=["Llink · rapport de diagnostic",new Date().toISOString(),navigator.userAgent,String(screen.width)+"x"+String(screen.height),navigator.onLine?"en ligne":"hors ligne"].join("\n"),status=document.getElementById("copy-status");try{await navigator.clipboard.writeText(report);status.textContent="Diagnostic copié. Tu peux le joindre à ton signalement.";}catch(_){status.textContent="Copie indisponible sur cet appareil. Vérifie les autorisations.";}});
})();