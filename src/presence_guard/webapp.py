"""Live demo app: watch face detection and phone distance in real time.

Read-only. It never locks, never authenticates, never touches PAM. Its whole
job is to make the two measured factors visible while you tune them.
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import time

import cv2
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from . import camera, config, recognizer
from .fingerprint import enrolled_fingers
from .policy import FactorState, Policy
from .proximity import ProximityEngine, rssi_to_meters

INDEX = """<!doctype html>
<html><head><meta charset="utf-8"><title>Lockdown — live factors</title>
<style>
:root{--bg:#0b0d10;--panel:#14181d;--line:#242a32;--fg:#e6edf3;--dim:#8b949e;
      --ok:#3fb950;--bad:#f85149;--warn:#d29922;--accent:#58a6ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
     font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;padding:20px}
h1{font-size:16px;font-weight:600;margin:0 0 4px;letter-spacing:.02em}
.sub{color:var(--dim);font-size:12px;margin-bottom:18px}
.grid{display:grid;grid-template-columns:1.15fr 1fr;gap:16px;max-width:1180px}
@media(max-width:860px){.grid{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.card h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;
         color:var(--dim);margin:0 0 10px;font-weight:600}
video,img{width:100%;border-radius:6px;background:#000;display:block}
.row{display:flex;justify-content:space-between;padding:5px 0;
     border-bottom:1px solid var(--line);font-size:13px}
.row:last-child{border:0}
.row span:last-child{color:var(--dim)}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;
      font-weight:600;letter-spacing:.04em}
.ok{background:rgba(63,185,80,.15);color:var(--ok)}
.bad{background:rgba(248,81,73,.15);color:var(--bad)}
.warn{background:rgba(210,153,34,.15);color:var(--warn)}
.bar{height:8px;background:#1f252d;border-radius:99px;overflow:hidden;margin:8px 0 2px}
.fill{height:100%;transition:width .3s,background .3s}
.big{font-size:26px;font-weight:600;font-variant-numeric:tabular-nums}
.mono{font-variant-numeric:tabular-nums}
.matrix div{padding:5px 0;font-size:12px;color:var(--dim)}
.matrix .on{color:var(--ok)}
.tabs{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap}
.tab{background:var(--panel);border:1px solid var(--line);color:var(--dim);
     padding:6px 14px;border-radius:999px;font:inherit;font-size:12px;cursor:pointer}
.tab:hover{border-color:var(--accent);color:var(--fg)}
.tab.on{background:rgba(88,166,255,.15);border-color:var(--accent);color:var(--accent)}
.act{width:100%;margin:10px 0 6px;background:rgba(88,166,255,.12);border:1px solid var(--accent);
     color:var(--accent);padding:8px;border-radius:6px;font:inherit;font-size:12px;cursor:pointer}
.act:disabled{opacity:.5;cursor:wait}
/* focus mode: hide everything that is not the chosen card */
body[data-view="face"]  [data-card="phone"],
body[data-view="face"]  [data-card="policy"],
body[data-view="phone"] [data-card="face"],
body[data-view="phone"] [data-card="policy"],
body[data-view="policy"] [data-card="face"],
body[data-view="policy"] [data-card="phone"]{display:none}
body[data-view="face"] .grid,
body[data-view="phone"] .grid,
body[data-view="policy"] .grid{grid-template-columns:minmax(0,760px)}
body[data-view] [data-card="side"]{display:contents}
</style></head><body>
<h1>lockdown · live factors</h1>
<div class="sub">read-only demo — nothing here locks or authenticates</div>
<div class="tabs">
  <button class="tab on" data-view="all">all</button>
  <button class="tab" data-view="face">face only</button>
  <button class="tab" data-view="phone">phone only</button>
  <button class="tab" data-view="policy">policy only</button>
</div>
<div class="grid">
  <div class="card" data-card="face">
    <h2>face</h2>
    <img id="feed" src="/api/stream" alt="camera">
    <div class="row"><span>state</span><span id="face-state">—</span></div>
    <div class="row"><span>similarity</span><span id="face-dist" class="mono">—</span></div>
    <div class="row"><span>threshold</span><span id="face-thr" class="mono">—</span></div>
    <div class="bar"><div class="fill" id="face-bar" style="width:0%"></div></div>
    <div class="sub" style="margin:6px 0 0">higher is a better match; bar fills toward the threshold</div>
  </div>
  <div data-card="side">
    <div class="card" data-card="phone" style="margin-bottom:16px">
      <h2>phone proximity (BLE)</h2>
      <div class="big" id="phone-m"><span class="mono">—</span> <span style="font-size:13px;color:var(--dim)">m</span></div>
      <div class="row"><span>mode</span><span id="phone-mode">—</span></div>
      <div class="row"><span>state</span><span id="phone-state">—</span></div>
      <div class="row"><span>rssi (smoothed)</span><span id="phone-rssi" class="mono">—</span></div>
      <div class="bar"><div class="fill" id="phone-bar" style="width:0%"></div></div>
      <div class="sub" style="margin:6px 0 0">near &lt; 2.5 m · far &gt; 6 m · hysteresis between</div>
    </div>
    <div class="card" data-card="policy">
      <h2>policy</h2>
      <div class="row"><span>fingerprint</span><span id="f-fp">—</span></div>
      <div class="row"><span>enrolled fingers</span><span id="f-enrolled">—</span></div>
      <div class="row"><span>last scan</span><span id="f-scan">—</span></div>
      <button id="f-btn" class="act">scan fingerprint now</button>
      <div class="row"><span>satisfied now</span><span id="pol">—</span></div>
      <div class="matrix" id="matrix"></div>
    </div>
  </div>
</div>
<script>
// Focus mode: remember the chosen view across reloads, and keep the tab
// buttons in sync. Purely client-side; the server does not care.
const saved = localStorage.getItem('lockdown-view') || 'all';
document.body.dataset.view = saved;
document.querySelectorAll('.tab').forEach(t => {
  t.classList.toggle('on', t.dataset.view === saved);
  t.onclick = () => {
    document.body.dataset.view = t.dataset.view;
    localStorage.setItem('lockdown-view', t.dataset.view);
    document.querySelectorAll('.tab').forEach(x => x.classList.toggle('on', x === t));
  };
});
async function tick(){
  try{
    const r = await fetch('/api/state'); const s = await r.json();
    const fs=document.getElementById('face-state');
    if(s.face.detected){
      const d=s.face.similarity, th=s.face.threshold;
      fs.innerHTML = d>=th ? '<span class="pill ok">match</span>' : '<span class="pill bad">impostor</span>';
      document.getElementById('face-dist').textContent=d.toFixed(3);
      document.getElementById('face-thr').textContent=th.toFixed(3);
      const pct=Math.min(100, Math.max(0, (d/1.0)*100));
      const bar=document.getElementById('face-bar');
      bar.style.width=pct+'%'; bar.style.background = d>=th?'var(--ok)':'var(--bad)';
    } else {
      fs.innerHTML='<span class="pill warn">no face</span>';
      document.getElementById('face-dist').textContent='—';
    }
    document.getElementById('phone-mode').textContent = s.phone_mode || '—';
    const ph=s.phone;
    if(ph.meters!=null){
      document.getElementById('phone-m').innerHTML='<span class="mono">'+ph.meters.toFixed(1)+'</span> <span style="font-size:13px;color:var(--dim)">m</span>';
      document.getElementById('phone-rssi').textContent=ph.rssi.toFixed(0)+' dBm';
      const b=document.getElementById('phone-bar');
      const pct=Math.min(100, (ph.meters/8)*100);
      b.style.width=pct+'%'; b.style.background=ph.near?'var(--ok)':'var(--bad)';
      document.getElementById('phone-state').innerHTML = ph.near?'<span class="pill ok">near</span>':'<span class="pill bad">far</span>';
    } else {
      document.getElementById('phone-state').innerHTML='<span class="pill warn">'+(s.phone_error||'no signal')+'</span>';
      document.getElementById('phone-m').innerHTML='<span style="color:var(--dim)">— m</span>';
    }
    document.getElementById('f-fp').innerHTML= s.fingerprint.available?'<span class="pill ok">present</span>':'<span class="pill bad">absent</span>';
    document.getElementById('f-enrolled').textContent=(s.fingerprint.enrolled||[]).join(', ')||'none';
    document.getElementById('pol').innerHTML= s.policy.satisfied?'<span class="pill ok">yes</span>':'<span class="pill bad">no</span>';
    document.getElementById('matrix').innerHTML=s.policy.matrix.map(m=>'<div>'+m+'</div>').join('');
  }catch(e){}
}
document.getElementById('f-btn').onclick = async (e) => {
  const b=e.target; b.disabled=true; b.textContent='touch the sensor…';
  try{
    const r=await fetch('/api/fingerprint',{method:'POST'});
    const d=await r.json();
    document.getElementById('f-scan').innerHTML = d.matched
      ? '<span class="pill ok">matched</span>'
      : '<span class="pill bad">'+ (d.message||'no match') +'</span>';
  }catch(err){
    document.getElementById('f-scan').innerHTML='<span class="pill warn">error</span>';
  }
  b.disabled=false; b.textContent='scan fingerprint now';
};
setInterval(tick, 1000); tick();
</script>
</body></html>"""


class DemoState:
    def __init__(self):
        self.cfg = config.load()
        self.rec = recognizer.Recognizer(self.cfg.verify.threshold)
        try:
            self.rec.load()
            self.model_loaded = True
        except FileNotFoundError:
            self.model_loaded = False
        self.prox = ProximityEngine(
            near_m=2.5,
            far_m=6.0,
            mode=self.cfg.phone.mode,
            hotspot_ssid=self.cfg.phone.hotspot_ssid,
        )
        self.lock = threading.Lock()
        self.face = {"detected": False, "similarity": None, "threshold": self.cfg.verify.threshold}
        self.phone = {"meters": None, "rssi": None, "near": False}
        self._started = False
        # One shared capture handle: opening the device per frame both fails
        # (the device allows a single opener) and costs ~940 ms each time.
        # RLock because read_frame() -> _camera() re-enters while holding it.
        self._cap = None
        self._cap_lock = threading.RLock()
        self._latest_jpeg: bytes | None = None
        self._last_face: tuple[int, int, int, int] | None = None
        self.last_error: str | None = None

    def _camera(self):
        with self._cap_lock:
            if self._cap is None or not self._cap.isOpened():
                self._cap = camera.open_camera(
                    self.cfg.camera.device,
                    self.cfg.camera.width,
                    self.cfg.camera.height,
                    self.cfg.camera.warmup_frames,
                )
            return self._cap

    def read_frame(self, drain: bool = True):
        with self._cap_lock:
            cap = self._camera()
            if drain:
                # A read after an idle period returns in <1 ms, i.e. it serves a
                # frame queued by the driver possibly seconds ago. One grab
                # discards the pending slot so the following read blocks for a
                # fresh capture (~50 ms on this sensor) instead of replaying.
                cap.grab()
            ok, frame = cap.read()
            if not ok or frame is None:
                raise RuntimeError("camera returned no frame")
            return frame

    def start(self):
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._capture_loop, daemon=True).start()
        threading.Thread(target=self._phone_loop, daemon=True).start()

    def _capture_loop(self):
        """Capture and encode continuously; detect on a slower cadence.

        The sensor delivers ~20 fps. Detection costs ~8 ms on a 320-wide copy
        and the LBPH match is sub-millisecond, so running them on every frame
        would still fit -- but they are kept on their own cadence so the
        preview never waits behind a slow detection.
        """
        detect_w = 320
        last_detect = 0.0
        while True:
            try:
                frame = self.read_frame()
                now = time.time()
                with self.lock:
                    face = self._last_face
                if face is not None:
                    h, w = frame.shape[:2]
                    scale = detect_w / float(w) if w > detect_w else 1.0
                    inv = 1.0 / scale
                    x, y, fw, fh = face
                    cv2.rectangle(
                        frame,
                        (int(x * inv), int(y * inv)),
                        (int((x + fw) * inv), int((y + fh) * inv)),
                        (0, 255, 0),
                        2,
                    )
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok:
                    self._latest_jpeg = buf.tobytes()

                if now - last_detect >= 0.15:  # ~6.5 detection passes per second
                    last_detect = now
                    self._detect_once(frame, detect_w)
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"

    def _detect_once(self, frame, detect_w: int):
        h, w = frame.shape[:2]
        scale = detect_w / float(w) if w > detect_w else 1.0
        small = (
            cv2.resize(frame, (detect_w, int(h * scale)), interpolation=cv2.INTER_AREA)
            if scale < 1.0
            else frame
        )
        face = recognizer.largest_face(small)
        if face is None:
            with self.lock:
                self._last_face = None
                self.face = {
                    "detected": False,
                    "similarity": None,
                    "threshold": self.cfg.verify.threshold,
                }
            return
        with self.lock:
            self._last_face = face[0]
        if not self.model_loaded:
            with self.lock:
                self.face = {
                    "detected": True,
                    "similarity": None,
                    "threshold": self.cfg.verify.threshold,
                }
            return
        result = self.rec.predict(face[1])
        with self.lock:
            self.face = {
                "detected": True,
                "similarity": result.similarity,
                "threshold": result.threshold,
            }

    def _phone_loop(self):
        while True:
            try:
                reading = self.prox.poll()
                with self.lock:
                    self.phone = {
                        "meters": reading.meters if reading else None,
                        "rssi": reading.rssi if reading else None,
                        "near": bool(reading and self.prox.near),
                    }
            except Exception:
                pass
            time.sleep(1.0)

    def snapshot(self) -> dict:
        with self.lock:
            face = dict(self.face)
            phone = dict(self.phone)
        state = FactorState(
            password=False,
            fingerprint=False,
            phone=phone["near"],
            face=bool(face["similarity"] is not None and face["similarity"] >= face["threshold"]),
            phone_meters=phone["meters"],
            face_similarity=face["similarity"],
            face_threshold=face["threshold"],
        )
        policy = Policy()
        return {
            "face": face,
            "phone": phone,
            "phone_mode": self.cfg.phone.mode,
            "phone_error": self.prox.last_error,
            "fingerprint": {"available": _fp_available(), "enrolled": _fp_enrolled()},
            "policy": policy.evaluate(state),
            "error": self.last_error,
        }


_cache: dict = {}


def _fp_available() -> bool:
    from . import fingerprint

    if "fp_avail" not in _cache:
        _cache["fp_avail"] = fingerprint.available()
    return _cache["fp_avail"]


def _fp_enrolled() -> list[str]:
    from . import fingerprint

    if "fp_enrolled" not in _cache:
        _cache["fp_enrolled"] = fingerprint.enrolled_fingers()
    return _cache["fp_enrolled"]


state = DemoState()


def create_app() -> FastAPI:
    app = FastAPI(title="lockdown demo")

    @app.on_event("startup")
    def _startup():
        state.start()

    @app.get("/", response_class=HTMLResponse)
    def index():
        return INDEX

    @app.get("/api/state")
    def api_state():
        return JSONResponse(state.snapshot())

    @app.get("/api/frame")
    def api_frame():
        # Serve the frame the loop already captured; opening the camera here
        # would collide with the loop's handle.
        jpeg = state._latest_jpeg
        if jpeg is None:
            return JSONResponse({"error": "no frame yet"}, status_code=503)
        return JSONResponse(
            {"image": base64.b64encode(jpeg).decode(), "at": time.time()}
        )

    @app.get("/api/stream")
    def api_stream():
        def gen():
            last = None
            while True:
                jpeg = state._latest_jpeg
                if jpeg is not None and jpeg is not last:
                    last = jpeg
                    yield (
                        b"--frame\r\nContent-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                        + jpeg + b"\r\n"
                    )
                # Poll the shared buffer frequently. The camera paces the
                # producer at ~20 fps, so a long sleep here is what made the
                # preview look a quarter of its real rate.
                time.sleep(0.02)

        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.post("/api/fingerprint")
    def api_fingerprint():
        # Blocks while it tries each enrolled finger, so the browser shows a
        # waiting state. Read-only: it reports a match, it never authenticates.
        from . import fingerprint

        try:
            matched, message = fingerprint.verify_any(timeout=8, verbose=True)
        except Exception as exc:
            return JSONResponse({"matched": False, "message": str(exc)}, status_code=500)
        return JSONResponse({"matched": matched, "message": message})

    return app


app = create_app()
