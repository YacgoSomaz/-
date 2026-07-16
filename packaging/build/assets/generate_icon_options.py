from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "icon-options"
OUT.mkdir(exist_ok=True)


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    size = 1024
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    draw.rounded_rectangle((70, 86, 954, 970), radius=220, fill=(1, 10, 30, 125))
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    image.alpha_composite(shadow)
    return image, ImageDraw.Draw(image)


def rounded_base(image: Image.Image, colors: tuple[tuple[int, int, int], tuple[int, int, int]]) -> None:
    base = Image.new("RGBA", image.size, (0, 0, 0, 0))
    px = base.load()
    for y in range(1024):
        t = y / 1023
        color = tuple(round(colors[0][i] * (1 - t) + colors[1][i] * t) for i in range(3))
        for x in range(1024):
            px[x, y] = (*color, 255)
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((48, 48, 976, 976), radius=230, fill=255)
    image.alpha_composite(Image.composite(base, Image.new("RGBA", image.size), mask))


def save_icon(image: Image.Image, name: str) -> None:
    preview = OUT / f"{name}.png"
    image.resize((512, 512), Image.Resampling.LANCZOS).save(preview)
    image.save(OUT / f"{name}.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def neon_stroke(image: Image.Image, points: list[tuple[int, int]], color: tuple[int, int, int], width: int = 22) -> None:
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.line(points, fill=(*color, 210), width=width * 3, joint="curve")
    glow = glow.filter(ImageFilter.GaussianBlur(24))
    image.alpha_composite(glow)
    ImageDraw.Draw(image).line(points, fill=(*color, 255), width=width, joint="curve")


def neon_base() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image, draw = canvas()
    rounded_base(image, ((4, 10, 30), (9, 22, 55)))
    # A restrained grid gives the icon a cyber feel without becoming noisy.
    grid = Image.new("RGBA", image.size, (0, 0, 0, 0))
    grid_draw = ImageDraw.Draw(grid)
    for offset in range(96, 1024, 104):
        grid_draw.line((offset, 72, offset, 952), fill=(47, 103, 164, 34), width=3)
        grid_draw.line((72, offset, 952, offset), fill=(47, 103, 164, 34), width=3)
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((48, 48, 976, 976), radius=230, fill=255)
    image.alpha_composite(Image.composite(grid, Image.new("RGBA", image.size), mask))
    return image, ImageDraw.Draw(image)


def option_neon_signal() -> Image.Image:
    image, draw = neon_base()
    # Offset cyan/magenta strokes create a neon depth effect, not a copied logo.
    draw.arc((236, 228, 788, 780), start=34, end=308, fill=(255, 54, 180, 230), width=74)
    draw.arc((214, 228, 766, 780), start=34, end=308, fill=(44, 232, 255, 230), width=74)
    neon_stroke(image, [(264, 558), (326, 430), (414, 350), (534, 318), (660, 352), (742, 450)], (243, 247, 255), 34)
    draw.ellipse((398, 392, 626, 620), fill=(15, 28, 66, 255), outline=(243, 247, 255, 255), width=18)
    draw.ellipse((454, 448, 570, 564), fill=(45, 228, 218, 255))
    draw.ellipse((486, 480, 538, 532), fill=(255, 255, 255, 255))
    draw.ellipse((800, 174, 890, 264), fill=(255, 54, 180, 255))
    draw.ellipse((820, 194, 870, 244), fill=(255, 255, 255, 255))
    return image


def option_neon_playback() -> Image.Image:
    image, draw = neon_base()
    # The two offset camera frames read as live feed + replay frame.
    draw.rounded_rectangle((184, 226, 844, 742), radius=104, outline=(255, 54, 180, 230), width=46)
    draw.rounded_rectangle((160, 202, 820, 718), radius=104, outline=(44, 232, 255, 230), width=46)
    draw.rounded_rectangle((196, 238, 856, 754), radius=104, outline=(244, 248, 255, 255), width=30)
    draw.polygon([(454, 354), (454, 640), (704, 497)], fill=(255, 255, 255, 255))
    neon_stroke(image, [(162, 810), (286, 810), (350, 714), (420, 852), (490, 784), (600, 784), (660, 704), (724, 846), (854, 810)], (44, 232, 255), 28)
    neon_stroke(image, [(162, 820), (286, 820), (350, 724), (420, 862), (490, 794), (600, 794), (660, 714), (724, 856), (854, 820)], (255, 54, 180), 12)
    return image


def option_neon_radar() -> Image.Image:
    image, draw = neon_base()
    # Radar-like focus marks suggest monitoring and audience activity.
    for box, color, width in [((210, 210, 814, 814), (44, 232, 255), 32), ((260, 260, 764, 764), (255, 54, 180), 24), ((322, 322, 702, 702), (244, 248, 255), 18)]:
        draw.ellipse(box, outline=(*color, 255), width=width)
    draw.line((512, 300, 512, 724), fill=(244, 248, 255, 230), width=18)
    draw.line((300, 512, 724, 512), fill=(244, 248, 255, 230), width=18)
    draw.ellipse((408, 408, 616, 616), fill=(8, 22, 54, 255), outline=(244, 248, 255, 255), width=18)
    draw.polygon([(472, 444), (472, 580), (594, 512)], fill=(44, 232, 255, 255))
    draw.ellipse((760, 168, 864, 272), fill=(255, 54, 180, 255))
    draw.ellipse((790, 198, 834, 242), fill=(255, 255, 255, 255))
    return image


def option_orbit() -> Image.Image:
    image, draw = canvas()
    rounded_base(image, ((13, 35, 67), (11, 91, 133)))
    # Replay orbit with a clean, highly legible arrowhead.
    draw.arc((236, 228, 788, 780), start=34, end=308, fill=(239, 250, 255, 255), width=58)
    draw.polygon([(725, 236), (826, 252), (760, 330)], fill=(239, 250, 255, 255))
    draw.ellipse((392, 390, 632, 630), fill=(44, 211, 191, 255))
    draw.ellipse((454, 452, 570, 568), fill=(255, 255, 255, 255))
    draw.ellipse((818, 176, 884, 242), fill=(255, 255, 255, 255))
    draw.ellipse((836, 194, 866, 224), fill=(43, 211, 191, 255))
    return image


def option_playback() -> Image.Image:
    image, draw = canvas()
    rounded_base(image, ((25, 26, 72), (79, 54, 175)))
    # Camera frame and play symbol.
    draw.rounded_rectangle((188, 246, 836, 722), radius=96, outline=(235, 244, 255, 255), width=42)
    draw.polygon([(460, 350), (460, 618), (690, 484)], fill=(255, 255, 255, 255))
    # Live pulse, deliberately simple enough to survive 16px rendering.
    pulse = [(188, 770), (286, 770), (332, 708), (384, 832), (436, 770), (548, 770), (598, 714), (650, 826), (706, 770), (836, 770)]
    draw.line(pulse, fill=(66, 226, 184, 255), width=32, joint="curve")
    draw.ellipse((746, 158, 866, 278), fill=(66, 226, 184, 255))
    draw.ellipse((784, 196, 828, 240), fill=(25, 26, 72, 255))
    return image


def option_layers() -> Image.Image:
    image, draw = canvas()
    rounded_base(image, ((17, 40, 74), (24, 97, 145)))
    # Two offset frames: live source behind, replay card in front.
    draw.rounded_rectangle((198, 172, 784, 778), radius=76, outline=(93, 225, 211, 255), width=42)
    draw.rounded_rectangle((282, 254, 868, 860), radius=76, fill=(255, 255, 255, 255))
    draw.rounded_rectangle((324, 296, 826, 818), radius=48, outline=(18, 54, 90, 255), width=24)
    draw.polygon([(500, 420), (500, 680), (706, 550)], fill=(37, 104, 255, 255))
    draw.ellipse((144, 724, 272, 852), fill=(37, 104, 255, 255))
    draw.ellipse((188, 768, 228, 808), fill=(255, 255, 255, 255))
    return image


if __name__ == "__main__":
    save_icon(option_orbit(), "livewatch-orbit")
    save_icon(option_playback(), "livewatch-playback")
    save_icon(option_layers(), "livewatch-layers")
    contact = Image.new("RGBA", (1536, 512), (238, 244, 250, 255))
    for index, name in enumerate(("livewatch-orbit", "livewatch-playback", "livewatch-layers")):
        icon = Image.open(OUT / f"{name}.png").resize((420, 420), Image.Resampling.LANCZOS)
        contact.alpha_composite(icon, (48 + index * 512, 46))
    contact.save(OUT / "preview.png")
    neon_names = ("livewatch-neon-signal", "livewatch-neon-playback", "livewatch-neon-radar")
    save_icon(option_neon_signal(), neon_names[0])
    save_icon(option_neon_playback(), neon_names[1])
    save_icon(option_neon_radar(), neon_names[2])
    neon_contact = Image.new("RGBA", (1536, 512), (8, 14, 34, 255))
    for index, name in enumerate(neon_names):
        icon = Image.open(OUT / f"{name}.png").resize((420, 420), Image.Resampling.LANCZOS)
        neon_contact.alpha_composite(icon, (48 + index * 512, 46))
    neon_contact.save(OUT / "preview-neon.png")
