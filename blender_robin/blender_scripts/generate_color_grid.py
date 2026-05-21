"""Generate color_grid.png — run once before using uv_checker_glb.py.

Usage: python generate_color_grid.py
Output: color_grid.png in the same directory as this script.
No external dependencies required.
"""
import struct
import zlib
import colorsys
import os


def _write_png(filename, width, height, raw_rgba_bytes):
    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)

    png = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    png += chunk(b'IHDR', ihdr)

    scanlines = bytearray()
    row_stride = width * 4
    for y in range(height):
        scanlines.append(0)
        start = y * row_stride
        scanlines.extend(raw_rgba_bytes[start:start + row_stride])

    png += chunk(b'IDAT', zlib.compress(scanlines, 6))
    png += chunk(b'IEND', b'')

    with open(filename, 'wb') as f:
        f.write(png)


def generate():
    width, height = 2048, 2048
    cell_size = 128
    grid_w = grid_h = width // cell_size

    # 3x5 bitmap font for hex digits (MSB = leftmost pixel)
    FONT = {
        '0': [0b111, 0b101, 0b101, 0b101, 0b111],
        '1': [0b010, 0b110, 0b010, 0b010, 0b111],
        '2': [0b111, 0b001, 0b111, 0b100, 0b111],
        '3': [0b111, 0b001, 0b111, 0b001, 0b111],
        '4': [0b101, 0b101, 0b111, 0b001, 0b001],
        '5': [0b111, 0b100, 0b111, 0b001, 0b111],
        '6': [0b111, 0b100, 0b111, 0b101, 0b111],
        '7': [0b111, 0b001, 0b010, 0b010, 0b010],
        '8': [0b111, 0b101, 0b111, 0b101, 0b111],
        '9': [0b111, 0b101, 0b111, 0b001, 0b111],
        'A': [0b010, 0b101, 0b111, 0b101, 0b101],
        'B': [0b110, 0b101, 0b110, 0b101, 0b110],
        'C': [0b011, 0b100, 0b100, 0b100, 0b011],
        'D': [0b110, 0b101, 0b101, 0b101, 0b110],
        'E': [0b111, 0b100, 0b110, 0b100, 0b111],
        'F': [0b111, 0b100, 0b110, 0b100, 0b100],
    }
    FONT_W, FONT_H, SCALE = 3, 5, 3

    # 256 distinct colors using golden angle hue spread
    cell_colors = []
    for i in range(grid_w * grid_h):
        hue = (i * 0.618033988749895) % 1.0
        sat = 0.5 + (i % 3) * 0.15
        val = 0.65 + (i % 2) * 0.2
        r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
        cell_colors.append((int(r * 255), int(g * 255), int(b * 255)))

    raw = bytearray(width * height * 4)

    def put(px, py, r, g, b):
        if 0 <= px < width and 0 <= py < height:
            idx = (py * width + px) * 4
            raw[idx] = r
            raw[idx + 1] = g
            raw[idx + 2] = b
            raw[idx + 3] = 255

    # Fill cell backgrounds using slice assignment (fast)
    for row in range(grid_h):
        for col in range(grid_w):
            r, g, b = cell_colors[row * grid_w + col]
            x0 = col * cell_size
            # Y-axis flip: PNG origin is top-left, Blender UV origin is bottom-left
            y0 = (grid_h - 1 - row) * cell_size
            row_cache = bytes([r, g, b, 255]) * cell_size
            for y in range(y0, y0 + cell_size):
                start = (y * width + x0) * 4
                raw[start:start + cell_size * 4] = row_cache

    # Draw decorations
    for row in range(grid_h):
        for col in range(grid_w):
            r, g, b = cell_colors[row * grid_w + col]
            x0 = col * cell_size
            y0 = (grid_h - 1 - row) * cell_size

            # Border (2px, darkened)
            br, bg, bb = r * 3 // 10, g * 3 // 10, b * 3 // 10
            for i in range(2):
                for x in range(x0, x0 + cell_size):
                    put(x, y0 + i, br, bg, bb)
                    put(x, y0 + cell_size - 1 - i, br, bg, bb)
                for y in range(y0, y0 + cell_size):
                    put(x0 + i, y, br, bg, bb)
                    put(x0 + cell_size - 1 - i, y, br, bg, bb)

            # Crosshair at center
            cx = x0 + cell_size // 2
            cy = y0 + cell_size // 2
            cr, cg, cb = r * 4 // 10, g * 4 // 10, b * 4 // 10
            for i in range(-12, 13):
                put(cx + i, cy, cr, cg, cb)
                put(cx, cy + i, cr, cg, cb)

            # Text color: contrast against background
            lum = (299 * r + 587 * g + 114 * b) // 1000
            tr, tg, tb = (13, 13, 13) if lum > 115 else (242, 242, 242)

            # Hex label (e.g. "3B")
            label = f"{row:X}{col:X}"
            char_w_scaled = FONT_W * SCALE
            spacing = SCALE
            total_w = len(label) * char_w_scaled + (len(label) - 1) * spacing
            text_x = x0 + (cell_size - total_w) // 2
            text_y = y0 + cell_size // 2 + 10

            for ci, ch in enumerate(label):
                glyph = FONT.get(ch)
                if not glyph:
                    continue
                gx0 = text_x + ci * (char_w_scaled + spacing)
                for gy, glyph_row in enumerate(glyph):
                    for gx in range(FONT_W):
                        if glyph_row & (1 << (FONT_W - 1 - gx)):
                            for sy in range(SCALE):
                                for sx in range(SCALE):
                                    put(gx0 + gx * SCALE + sx,
                                        text_y + (FONT_H - 1 - gy) * SCALE + sy,
                                        tr, tg, tb)

            # L-shape direction marker (bottom-left corner of cell)
            lx = x0 + 8
            ly = y0 + 6
            for i in range(20):
                for t in range(2):
                    put(lx + t, ly + i, tr, tg, tb)
                    put(lx + i, ly + t, tr, tg, tb)

    return raw


if __name__ == '__main__':
    print("Generating 2048x2048 color grid...")
    raw_data = generate()
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'color_grid.png')
    print(f"Writing PNG to: {output_path}")
    _write_png(output_path, 2048, 2048, raw_data)
    print("Done.")
