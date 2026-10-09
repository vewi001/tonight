"""Bounded raster decoding and privacy-safe pixel-only re-encoding."""
from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
import warnings

from PIL import Image, ImageOps

MAX_IMAGE_BYTES = 16*1024*1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_DIMENSION = 8192
FORMATS = {'.jpg':'JPEG','.jpeg':'JPEG','.png':'PNG','.webp':'WEBP'}


class CatalogMediaError(ValueError):
    pass


def _header(image,format):
    width,height = image.size
    if (image.format!=format or getattr(image,'n_frames',1)!=1 or min(width,height)<=0
            or max(width,height)>MAX_IMAGE_DIMENSION or width*height>MAX_IMAGE_PIXELS):
        raise CatalogMediaError('Изображение имеет неподдерживаемый формат, анимацию или размер')


@contextmanager
def _decoded(content: bytes,extension: str):
    format = FORMATS.get(extension.lower())
    if format is None or not isinstance(content,bytes) or not 0<len(content)<=MAX_IMAGE_BYTES:
        raise CatalogMediaError('Изображение превышает ограничения или имеет неподдерживаемый формат')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(BytesIO(content),formats=list(FORMATS.values())) as probe:
                _header(probe,format)
                probe.verify()
            with Image.open(BytesIO(content),formats=list(FORMATS.values())) as image:
                _header(image,format)
                image.load()
                yield image
    except (OSError,ValueError,SyntaxError,OverflowError,Image.DecompressionBombWarning,Image.DecompressionBombError):
        raise CatalogMediaError('Не удалось безопасно декодировать изображение каталога') from None


def validate_catalog_image(content: bytes,extension: str) -> None:
    with _decoded(content,extension):
        pass


def sanitize_catalog_image(content: bytes,extension: str) -> bytes:
    """Decode, orient and copy only pixels; never inherit provider metadata."""
    with _decoded(content,extension) as image:
        with ImageOps.exif_transpose(image) as oriented:
            mode = 'RGBA' if 'A' in oriented.getbands() or 'transparency' in oriented.info else 'RGB'
            if FORMATS[extension.lower()]=='JPEG':
                mode = 'RGB'
            with oriented.convert(mode) as converted, Image.new(mode,oriented.size) as clean:
                clean.paste(converted)
                output = BytesIO()
                options = {'quality':95,'subsampling':0} if FORMATS[extension.lower()]=='JPEG' else {}
                if FORMATS[extension.lower()]=='WEBP':
                    options = {'lossless':True,'exact':True}
                clean.save(output,format=FORMATS[extension.lower()],**options)
                result = output.getvalue()
                if len(result)>MAX_IMAGE_BYTES:
                    raise CatalogMediaError('Очищенное изображение превышает ограничения размера')
                return result
