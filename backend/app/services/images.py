from io import BytesIO

from PIL import Image, ImageOps

THUMBNAIL_PIXELS = 320
MAX_PIXELS = 40_000_000


def thumbnail_jpeg(data: bytes) -> bytes:
    """A small upright JPEG of the picture, transparency flattened onto white; ValueError when it is not a usable image."""
    try:
        picture = Image.open(BytesIO(data))
        if picture.width * picture.height > MAX_PIXELS:
            raise ValueError("The picture is too large")
        picture = ImageOps.exif_transpose(picture)
        if picture.mode in ("RGBA", "LA", "P"):
            picture = picture.convert("RGBA")
            flat = Image.new("RGB", picture.size, "white")
            flat.paste(picture, mask=picture.getchannel("A"))
            picture = flat
        else:
            picture = picture.convert("RGB")
        picture.thumbnail((THUMBNAIL_PIXELS, THUMBNAIL_PIXELS))
        out = BytesIO()
        picture.save(out, "JPEG", quality=78, optimize=True, progressive=True)
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("That file is not a usable picture") from exc
    return out.getvalue()
