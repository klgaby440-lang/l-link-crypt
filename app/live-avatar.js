/* Llink Live — avatar 3D léger, interactif et réactif à la voix d'Elia. */
(() => {
  "use strict";

  const ROOT = document.getElementById("llcall");
  const TILE = document.getElementById("llcall-tile-ai");
  if (!ROOT || !TILE || TILE.dataset.llia3dInit === "1") return;
  TILE.dataset.llia3dInit = "1";

  const fallback = TILE.querySelector(".elia-svg, .elia-avatar-3d");
  let activeTile = TILE;
  let resizeObserver = null;
  let canvas = null;
  function resolveActiveTile() {
    if (ROOT.classList.contains("is-open")) return TILE;
    if (document.body.classList.contains("live-mode-active")) return document.getElementById("live-avatar-stage");
    return null;
  }
  function placeCanvas() {
    const next = resolveActiveTile();
    if (!next || !canvas) { stop(); return; }
    if (canvas.parentElement !== next) {
      next.insertBefore(canvas, next.firstChild);
      if (fallback) fallback.classList.toggle("llia-fallback-hidden", next === TILE);
      activeTile = next;
      if (resizeObserver) { resizeObserver.disconnect(); resizeObserver.observe(activeTile); }
      resize();
    }
    start();
  }
  const REDUCED_MOTION = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let renderer = null;
  let raf = 0;
  let running = false;
  let ready = false;
  let lastFrame = 0;
  let blinkAt = performance.now() + 2600;
  let blink = 0;
  let targetRotX = 0;
  let targetRotY = 0;
  let rotX = 0;
  let rotY = 0;
  let targetZoom = 7.7;
  let zoom = 7.7;
  let pinchStart = 0;
  let pinchZoom = 7.7;
  let drag = null;
  const pointers = new Map();
  const clamp = (v, min, max) => Math.max(min, Math.min(max, v));

  function loadThree() {
    return new Promise((resolve, reject) => {
      if (window.THREE) return resolve(window.THREE);
      const existing = document.querySelector("script[data-llia-three]");
      if (existing) {
        existing.addEventListener("load", () => window.THREE ? resolve(window.THREE) : reject(new Error("Three.js indisponible.")), { once: true });
        existing.addEventListener("error", reject, { once: true });
        return;
      }
      const script = document.createElement("script");
      script.src = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js";
      script.async = true;
      script.dataset.lliaThree = "1";
      script.onload = () => window.THREE ? resolve(window.THREE) : reject(new Error("Three.js indisponible."));
      script.onerror = () => reject(new Error("Le moteur 3D n'a pas pu être téléchargé."));
      document.head.appendChild(script);
    });
  }

  function isVisible() { return !!resolveActiveTile(); }

  function start() {
    if (!ready || running || document.hidden || !isVisible()) return;
    running = true;
    lastFrame = 0;
    raf = requestAnimationFrame(frame);
  }

  function stop() {
    running = false;
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  }

  function frame(now) {
    if (!running || !renderer) return;
    raf = requestAnimationFrame(frame);
    const dt = Math.min(0.05, (now - (lastFrame || now)) / 1000 || 0.016);
    lastFrame = now;

    rotY += (targetRotY - rotY) * Math.min(1, dt * 7);
    rotX += (targetRotX - rotX) * Math.min(1, dt * 7);
    zoom += (targetZoom - zoom) * Math.min(1, dt * 7);
    head.rotation.y = rotY + (REDUCED_MOTION ? 0 : Math.sin(now * 0.00055) * 0.014);
    head.rotation.x = rotX + (REDUCED_MOTION ? 0 : Math.sin(now * 0.0008) * 0.008);
    camera.position.z = zoom;
    camera.lookAt(0, -0.16, 0);

    const outputLevel = clamp(Number(window.llinkLiveOutputLevel) || 0, 0, 1);
    const speaking = ROOT.classList.contains("speaking");
    const mouthOpen = speaking
      ? 0.018 + Math.max(outputLevel, 0.035) * 0.36
      : 0.012 + (REDUCED_MOTION ? 0 : Math.sin(now * 0.0017) * 0.002);
    mouthCavity.scale.y = mouthOpen;
    upperLip.position.y = mouthOpen * 0.24;
    lowerLip.position.y = -mouthOpen * 0.30;

    if (now > blinkAt) {
      blink = 1;
      blinkAt = now + 3200 + Math.random() * 2200;
    }
    if (blink > 0) {
      blink = Math.max(0, blink - dt * 9);
      eyeGroups.forEach(group => { group.scale.y = Math.max(0.08, 1 - blink); });
    } else {
      eyeGroups.forEach(group => { group.scale.y += (1 - group.scale.y) * Math.min(1, dt * 12); });
    }

    renderer.render(scene, camera);
  }

  let scene, camera, head, mouthCavity, upperLip, lowerLip, eyeGroups;

  function build(T) {
    canvas = document.createElement("canvas");
    canvas.className = "llia-3d-canvas";
    canvas.tabIndex = 0;
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", "Visage 3D d'Elia. Fais glisser pour tourner la tête, utilise deux doigts pour zoomer et double-clique pour réinitialiser.");
    TILE.insertBefore(canvas, TILE.firstChild);

    try {
      renderer = new T.WebGLRenderer({
        canvas,
        alpha: true,
        antialias: true,
        powerPreference: "low-power",
        preserveDrawingBuffer: false
      });
    } catch (error) {
      canvas.remove();
      throw error;
    }

    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.setClearColor(0x000000, 0);
    renderer.outputEncoding = T.sRGBEncoding;
    renderer.toneMapping = T.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.12;

    scene = new T.Scene();
    camera = new T.PerspectiveCamera(31, 1, 0.1, 100);
    camera.position.set(0, 0.02, zoom);

    scene.add(new T.HemisphereLight(0xffffff, 0x82766f, 1.5));
    const key = new T.DirectionalLight(0xfff4e8, 2.15);
    key.position.set(-3, 4, 5);
    scene.add(key);
    const fill = new T.DirectionalLight(0xffffff, 1.05);
    fill.position.set(3, 1, 4);
    scene.add(fill);
    const rim = new T.DirectionalLight(0xe8dfd2, 1.25);
    rim.position.set(1, 3, -3);
    scene.add(rim);

    head = new T.Group();
    scene.add(head);

    const skin = new T.MeshStandardMaterial({ color: 0xf1e9df, roughness: 0.48, metalness: 0.015 });
    const skinLight = new T.MeshStandardMaterial({ color: 0xf8f2eb, roughness: 0.38 });
    const eyeWhite = new T.MeshStandardMaterial({ color: 0xfaf7f1, roughness: 0.25 });
    const irisMat = new T.MeshStandardMaterial({ color: 0x71513f, roughness: 0.3 });
    const pupilMat = new T.MeshStandardMaterial({ color: 0x191719, roughness: 0.2 });
    const lipMat = new T.MeshStandardMaterial({ color: 0x9f5e68, roughness: 0.44 });
    const mouthDark = new T.MeshStandardMaterial({ color: 0x392328, roughness: 0.86 });

    const make = (geometry, material, parent = head) => {
      const mesh = new T.Mesh(geometry, material);
      parent.add(mesh);
      return mesh;
    };

    const neck = make(new T.CylinderGeometry(0.43, 0.58, 1.25, 40, 1), skin);
    neck.position.set(0, -1.48, -0.04);

    /* Visage organique : mâchoire affinée, joues et front arrondi. */
    const vertices = [];
    const uvs = [];
    const indices = [];
    const rings = 72;
    const segments = 96;
    for (let iy = 0; iy <= rings; iy++) {
      const v = iy / rings;
      const theta = Math.PI * v;
      const y = 1.42 - 2.72 * v;
      const sn = Math.sin(theta);
      const jaw = 1 - 0.20 * Math.max(0, -y / 1.3) + 0.035 * Math.max(0, y);
      const rx = 0.94 * sn * jaw;
      const rz = 0.79 * sn * (1 - 0.06 * Math.max(0, -y));
      for (let j = 0; j <= segments; j++) {
        const a = 2 * Math.PI * j / segments;
        const x = Math.cos(a) * rx;
        const z = Math.sin(a) * rz;
        const front = Math.max(0, Math.sin(a));
        const cheek = Math.exp(-Math.pow((y + 0.28) / 0.42, 2)) * Math.exp(-Math.pow((Math.abs(x) - 0.48) / 0.28, 2));
        vertices.push(x, y, z + front * (0.045 * cheek + 0.035 * Math.exp(-Math.pow(y / 0.55, 2))));
        uvs.push(j / segments, 1 - v);
      }
    }
    for (let iy = 0; iy < rings; iy++) {
      for (let j = 0; j < segments; j++) {
        const a = iy * (segments + 1) + j;
        const b = a + segments + 1;
        indices.push(a, b, a + 1, b, b + 1, a + 1);
      }
    }
    const faceGeometry = new T.BufferGeometry();
    faceGeometry.setAttribute("position", new T.Float32BufferAttribute(vertices, 3));
    faceGeometry.setAttribute("uv", new T.Float32BufferAttribute(uvs, 2));
    faceGeometry.setIndex(indices);
    faceGeometry.computeVertexNormals();
    make(faceGeometry, skin);

    for (const side of [-1, 1]) {
      const ear = make(new T.SphereGeometry(1, 32, 24), skin);
      ear.position.set(side * 0.91, -0.02, -0.005);
      ear.scale.set(0.19, 0.34, 0.12);
      const inner = make(new T.SphereGeometry(1, 24, 16), lipMat);
      inner.position.set(side * 1.005, -0.03, 0.065);
      inner.scale.set(0.075, 0.19, 0.025);
    }

    eyeGroups = [];
    for (const side of [-1, 1]) {
      const eyeGroup = new T.Group();
      eyeGroup.position.set(side * 0.37, 0.27, 0.60);
      head.add(eyeGroup);
      eyeGroups.push(eyeGroup);

      const socket = make(new T.SphereGeometry(1, 32, 24), skinLight, eyeGroup);
      socket.scale.set(0.255, 0.145, 0.095);
      const eye = make(new T.SphereGeometry(1, 32, 24), eyeWhite, eyeGroup);
      eye.position.z = 0.065;
      eye.scale.set(0.205, 0.092, 0.075);
      const iris = make(new T.SphereGeometry(1, 28, 20), irisMat, eyeGroup);
      iris.position.set(0, 0, 0.128);
      iris.scale.set(0.071, 0.071, 0.026);
      const pupil = make(new T.SphereGeometry(1, 24, 16), pupilMat, eyeGroup);
      pupil.position.set(0, 0, 0.15);
      pupil.scale.set(0.034, 0.042, 0.014);
      const glint = make(new T.SphereGeometry(0.014, 12, 8), eyeWhite, eyeGroup);
      glint.position.set(-0.022, 0.026, 0.168);
      const brow = make(new T.SphereGeometry(1, 24, 16), skin, head);
      brow.position.set(side * 0.37, 0.49, 0.59);
      brow.scale.set(0.23, 0.045, 0.035);
      brow.rotation.z = side * 0.08;
    }

    const bridge = make(new T.SphereGeometry(1, 32, 24), skinLight);
    bridge.position.set(0, 0.015, 0.69);
    bridge.scale.set(0.105, 0.32, 0.14);
    const tip = make(new T.SphereGeometry(1, 32, 24), skin);
    tip.position.set(0, -0.19, 0.80);
    tip.scale.set(0.145, 0.105, 0.13);
    for (const side of [-1, 1]) {
      const wing = make(new T.SphereGeometry(1, 24, 16), skin);
      wing.position.set(side * 0.105, -0.22, 0.755);
      wing.scale.set(0.09, 0.065, 0.085);
    }

    const mouth = new T.Group();
    mouth.position.set(0, -0.49, 0.705);
    head.add(mouth);
    mouthCavity = make(new T.SphereGeometry(1, 32, 20), mouthDark, mouth);
    mouthCavity.scale.set(0.19, 0.018, 0.035);
    upperLip = make(new T.TorusGeometry(0.145, 0.027, 10, 40, Math.PI), lipMat, mouth);
    upperLip.rotation.z = Math.PI;
    upperLip.position.y = 0.005;
    upperLip.scale.set(1, 0.45, 1);
    lowerLip = make(new T.TorusGeometry(0.145, 0.027, 10, 40, Math.PI), lipMat, mouth);
    lowerLip.position.y = -0.008;
    lowerLip.scale.set(1, 0.48, 1);
    const chin = make(new T.SphereGeometry(1, 24, 16), skin);
    chin.position.set(0, -0.72, 0.54);
    chin.scale.set(0.30, 0.12, 0.10);

    head.position.y = 0.12;

    function resize() {
      const width = Math.max(1, activeTile.clientWidth);
      const height = Math.max(1, activeTile.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    }

    canvas.addEventListener("pointerdown", event => {
      try { canvas.setPointerCapture(event.pointerId); } catch (_) {}
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (pointers.size === 1) drag = { x: event.clientX, y: event.clientY, rx: targetRotX, ry: targetRotY };
      if (pointers.size === 2) {
        const pair = Array.from(pointers.values());
        pinchStart = Math.hypot(pair[0].x - pair[1].x, pair[0].y - pair[1].y);
        pinchZoom = targetZoom;
      }
      event.preventDefault();
    });
    canvas.addEventListener("pointermove", event => {
      if (!pointers.has(event.pointerId)) return;
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (pointers.size === 1 && drag) {
        targetRotY = drag.ry + (event.clientX - drag.x) * 0.009;
        targetRotX = clamp(drag.rx + (event.clientY - drag.y) * 0.006, -0.48, 0.48);
      } else if (pointers.size === 2) {
        const pair = Array.from(pointers.values());
        const distance = Math.hypot(pair[0].x - pair[1].x, pair[0].y - pair[1].y);
        if (pinchStart > 0) targetZoom = clamp(pinchZoom - (distance - pinchStart) * 0.012, 5.2, 10.5);
      }
      event.preventDefault();
    });
    const release = event => {
      pointers.delete(event.pointerId);
      if (pointers.size < 2) pinchStart = 0;
      if (!pointers.size) drag = null;
    };
    canvas.addEventListener("pointerup", release);
    canvas.addEventListener("pointercancel", release);
    canvas.addEventListener("wheel", event => {
      targetZoom = clamp(targetZoom + event.deltaY * 0.006, 5.2, 10.5);
      event.preventDefault();
    }, { passive: false });
    canvas.addEventListener("dblclick", () => {
      targetRotY = 0;
      targetRotX = 0;
      targetZoom = 7.7;
    });
    canvas.addEventListener("keydown", event => {
      if (event.key === "ArrowLeft") targetRotY -= 0.15;
      if (event.key === "ArrowRight") targetRotY += 0.15;
      if (event.key === "ArrowUp") targetRotX = clamp(targetRotX - 0.1, -0.48, 0.48);
      if (event.key === "ArrowDown") targetRotX = clamp(targetRotX + 0.1, -0.48, 0.48);
      if (event.key === "+" || event.key === "=") targetZoom = clamp(targetZoom - 0.3, 5.2, 10.5);
      if (event.key === "-") targetZoom = clamp(targetZoom + 0.3, 5.2, 10.5);
    });

    if (window.ResizeObserver) {
      resizeObserver = new ResizeObserver(resize);
      resizeObserver.observe(activeTile);
    } else window.addEventListener("resize", resize, { passive: true });
    resize();

    canvas.addEventListener("webglcontextlost", event => {
      event.preventDefault();
      stop();
      canvas.remove();
      if (fallback) fallback.classList.remove("llia-fallback-hidden");
      ready = false;
      window.llinkLiveAvatarStatus = "fallback";
    }, { once: true });

    ready = true;
    if (fallback) fallback.classList.add("llia-fallback-hidden");
    window.llinkLiveAvatarStatus = "ready";
    placeCanvas();
  }

  const observer = new MutationObserver(() => {
    if (document.hidden) { stop(); return; }
    placeCanvas();
  });
  observer.observe(ROOT, { attributes: true, attributeFilter: ["class"] });
  observer.observe(document.body, { attributes: true, attributeFilter: ["class"] });
  observer.observe(document.body, { childList: true, subtree: true });
  window.llinkLiveAvatarController = { start, stop, placeCanvas };
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop();
    else start();
  });

  loadThree().then(build).catch(error => {
    console.warn("Avatar 3D de Llink indisponible ; le visage de secours reste affiché.", error);
    window.llinkLiveAvatarStatus = "fallback";
  });
})();
