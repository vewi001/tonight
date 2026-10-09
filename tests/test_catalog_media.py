from io import BytesIO

from PIL import Image
import pytest

from backend.catalog_media import CatalogMediaError, sanitize_catalog_image, validate_catalog_image


def image_bytes(format='PNG',size=(8,12),mode='RGB',**options):
    output = BytesIO()
    with Image.new(mode,size,'red') as image:
        image.save(output,format=format,**options)
    return output.getvalue()


@pytest.mark.parametrize('format,extension',[('JPEG','.jpg'),('JPEG','.jpeg'),('PNG','.png'),('WEBP','.webp')])
def test_allowed_formats_decode_and_sanitize_deterministically(format,extension):
    source = image_bytes(format)
    result = sanitize_catalog_image(source,extension)
    assert sanitize_catalog_image(source,extension)==result
    validate_catalog_image(result,extension)
    with Image.open(BytesIO(result)) as image:
        assert image.size==(8,12) and image.format==format


def test_metadata_removed_and_orientation_applied():
    exif = Image.Exif()
    exif[270] = 'private note'
    exif[274] = 6
    source = image_bytes('JPEG',exif=exif,comment=b'private comment')
    result = sanitize_catalog_image(source,'.jpg')
    assert b'private' not in result
    with Image.open(BytesIO(result)) as image:
        assert image.size==(12,8) and not image.getexif()
        assert 'comment' not in image.info and 'icc_profile' not in image.info


def test_png_text_metadata_removed_and_alpha_kept():
    from PIL.PngImagePlugin import PngInfo
    metadata = PngInfo()
    metadata.add_text('Private','secret-location')
    result = sanitize_catalog_image(image_bytes('PNG',mode='RGBA',pnginfo=metadata),'.png')
    assert b'secret-location' not in result
    with Image.open(BytesIO(result)) as image:
        assert image.mode=='RGBA' and 'Private' not in image.info


@pytest.mark.parametrize('source,extension',[(b'not an image','.jpg'),(b'<svg/>','.png'),(image_bytes(),'.jpg'),(image_bytes('GIF'),'.gif')])
def test_invalid_or_mismatched_content_is_rejected(source,extension):
    with pytest.raises(CatalogMediaError):
        sanitize_catalog_image(source,extension)


def test_truncated_data_is_rejected():
    with pytest.raises(CatalogMediaError):
        sanitize_catalog_image(image_bytes('JPEG')[:-30],'.jpg')


def test_animation_is_rejected():
    output = BytesIO()
    with Image.new('RGB',(8,8),'red') as first, Image.new('RGB',(8,8),'blue') as second:
        first.save(output,format='WEBP',save_all=True,append_images=[second])
    with pytest.raises(CatalogMediaError):
        sanitize_catalog_image(output.getvalue(),'.webp')


def test_byte_pixel_and_dimension_limits_are_enforced(monkeypatch):
    import backend.catalog_media as media
    source = image_bytes()
    monkeypatch.setattr(media,'MAX_IMAGE_BYTES',len(source)-1)
    with pytest.raises(CatalogMediaError):
        validate_catalog_image(source,'.png')
    monkeypatch.setattr(media,'MAX_IMAGE_BYTES',16*1024*1024)
    monkeypatch.setattr(media,'MAX_IMAGE_PIXELS',10)
    with pytest.raises(CatalogMediaError):
        validate_catalog_image(source,'.png')
    monkeypatch.setattr(media,'MAX_IMAGE_PIXELS',16_000_000)
    monkeypatch.setattr(media,'MAX_IMAGE_DIMENSION',10)
    with pytest.raises(CatalogMediaError):
        validate_catalog_image(source,'.png')
