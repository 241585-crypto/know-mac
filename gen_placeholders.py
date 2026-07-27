import struct, zlib, os

def create_png(w, h, r, g, b, name):
    raw = b''
    for y in range(h):
        raw += b'\x00'
        for x in range(w):
            raw += bytes([r, g, b])
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    idat = zlib.compress(raw)
    png = b'\x89PNG\r\n\x1a\n'
    png += struct.pack('>I', 13) + b'IHDR' + ihdr + struct.pack('>I', zlib.crc32(b'IHDR' + ihdr) & 0xffffffff)
    png += struct.pack('>I', len(idat)) + b'IDAT' + idat + struct.pack('>I', zlib.crc32(b'IDAT' + idat) & 0xffffffff)
    png += struct.pack('>I', 0) + b'IEND' + struct.pack('>I', zlib.crc32(b'IEND') & 0xffffffff)
    with open(name, 'wb') as f: f.write(png)
    print("Created", name)

os.makedirs('images', exist_ok=True)
create_png(800, 600, 255, 200, 180, 'images/nude.png')
create_png(800, 600, 0, 180, 0, 'images/money.png')
create_png(800, 600, 100, 150, 200, 'images/track.png')
print("Done! Replace these with your real images.")
