from uuid import uuid4

import pytest
from aiohttp import web

from media_workflow.imread import imread
from media_workflow.worker import get_client


async def test_image_thumbnail():
    client = await get_client()
    arg = {
        "file": "https://sunyizhe.s3.us-west-002.backblazeb2.com/%E5%BC%B9%E6%A1%8612.psd",
        "size": (200, 200),
    }
    output = await client.execute_workflow(
        "image-thumbnail", arg, id=f"{uuid4()}", task_queue="media"
    )
    image = await imread(output["file"])
    assert image.size[0] <= 200
    assert image.size[1] <= 200


async def test_image_thumbnail_svg():
    client = await get_client()
    arg = {
        "file": "https://f002.backblazeb2.com/file/sunyizhe/cocktail.svg",
        "size": (200, 200),
    }
    output = await client.execute_workflow(
        "image-thumbnail", arg, id=f"{uuid4()}", task_queue="media"
    )
    image = await imread(output["file"])
    assert image.size[0] <= 200
    assert image.size[1] <= 200


async def test_image_thumbnail_hdr():
    client = await get_client()
    arg = {
        "file": "https://f002.backblazeb2.com/file/sunyizhe/apartment.hdr",
        "size": (200, 200),
    }
    output = await client.execute_workflow(
        "image-thumbnail", arg, id=f"{uuid4()}", task_queue="media"
    )
    image = await imread(output["file"])
    assert image.size[0] <= 200
    assert image.size[1] <= 200


@pytest.mark.skip(reason="we don't have an API endpoint for the callback")
async def test_image_thumbnail_with_callback():
    async def handler(request: web.Request):
        json = await request.json()
        image = await imread(output["file"])
        assert image.size[0] <= 200
        assert image.size[1] <= 200
        return web.Response()

    app = web.Application()
    app.add_routes([web.post("/", handler)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", "8000")
    await site.start()

    client = await get_client()
    arg = {
        "file": "https://sunyizhe.s3.us-west-002.backblazeb2.com/cat.jpg",
        "size": (200, 200),
        "callback_url": "http://localhost:8000",
    }
    output = await client.execute_workflow(
        "image-thumbnail", arg, id=f"{uuid4()}", task_queue="media"
    )
    assert "file" in output


async def test_pdf_thumbnail():
    client = await get_client()
    arg = {
        "file": "https://sunyizhe.s3.us-west-002.backblazeb2.com/sample-3.pdf",
        "size": (200, 200),
        "pages": [0],
    }
    output = await client.execute_workflow(
        "pdf-thumbnail", arg, id=f"{uuid4()}", task_queue="media"
    )
    assert len(output["files"]) == 1


async def test_font_thumbnail():
    client = await get_client()
    arg = {
        "file": "https://sunyizhe.s3.us-west-002.backblazeb2.com/%E5%BE%AE%E8%BD%AF%E9%9B%85%E9%BB%91.ttf",
        "size": (800, 600),
    }
    output = await client.execute_workflow(
        "font-thumbnail", arg, id=f"{uuid4()}", task_queue="media"
    )
    assert "file" in output


async def test_font_metadata():
    client = await get_client()
    arg = {
        "file": "https://sunyizhe.s3.us-west-002.backblazeb2.com/%E5%BE%AE%E8%BD%AF%E9%9B%85%E9%BB%91.ttf",
        "language": "Simplified Chinese",
    }
    output = await client.execute_workflow(
        "font-metadata", arg, id=f"{uuid4()}", task_queue="media"
    )
    assert "font_family" in output


async def test_font_detail():
    client = await get_client()
    arg = {
        "file": "https://sunyizhe.s3.us-west-002.backblazeb2.com/%E5%BE%AE%E8%BD%AF%E9%9B%85%E9%BB%91.ttf",
        "language": "Simplified Chinese",
    }
    output = await client.execute_workflow(
        "font-detail", arg, id=f"{uuid4()}", task_queue="media"
    )
    assert "description" in output


async def test_document_thumbnail():
    client = await get_client()
    arg = {
        "file": "https://sunyizhe.s3.us-west-002.backblazeb2.com/samplepptx.pptx",
        "size": (200, 200),
    }
    output = await client.execute_workflow(
        "document-thumbnail", arg, id=f"{uuid4()}", task_queue="media"
    )
    assert len(output["files"]) == 2


async def test_image_detail():
    client = await get_client()
    arg = {
        "file": "https://sunyizhe.s3.us-west-002.backblazeb2.com/cat.jpg",
        "language": "Simplified Chinese",
    }
    output = await client.execute_workflow(
        "image-detail", arg, id=f"{uuid4()}", task_queue="media"
    )
    assert "title" in output


async def test_image_detail_basic():
    client = await get_client()
    arg = {
        "file": "https://sunyizhe.s3.us-west-002.backblazeb2.com/cat.jpg",
        "language": "Simplified Chinese",
    }
    output = await client.execute_workflow(
        "image-detail-basic", arg, id=f"{uuid4()}", task_queue="media"
    )
    assert "title" in output


async def test_video_sprite():
    client = await get_client()
    arg = {
        "file": "https://sunyizhe.s3.us-west-002.backblazeb2.com/SampleVideo_720x480_10mb.mp4",
        "interval": 1.5,
        "layout": [6, 5],
        "width": 1000,
    }
    output = await client.execute_workflow(
        "video-sprite", arg, id=f"{uuid4()}", task_queue="media"
    )
    assert len(output["files"]) == 2


async def test_video_transcode():
    client = await get_client()
    arg = {
        "file": "https://sunyizhe.s3.us-west-002.backblazeb2.com/SampleVideo_720x480_10mb.mp4",
        "video-codec": "hevc",
        "audio-codec": "aac",
        "container": "mkv",
    }
    output = await client.execute_workflow(
        "video-transcode", arg, id=f"{uuid4()}", task_queue="media"
    )
    assert "file" in output


async def test_audio_waveform():
    client = await get_client()
    arg = {
        "file": "https://sunyizhe.s3.us-west-002.backblazeb2.com/SampleVideo_720x480_10mb.mp4",
        "num_samples": 1000,
    }
    output = await client.execute_workflow(
        "audio-waveform", arg, id=f"{uuid4()}", task_queue="media"
    )
    assert len(output["waveform"]) == 1000
    assert max(output["waveform"]) == 1.0


async def test_image_color_palette():
    client = await get_client()
    arg = {
        "file": "https://sunyizhe.s3.us-west-002.backblazeb2.com/cat.jpg",
        "count": 5,
    }
    output = await client.execute_workflow(
        "image-color-palette", arg, id=f"{uuid4()}", task_queue="media"
    )
    assert len(output["colors"]) == 5


async def test_image_color_palette_svg():
    client = await get_client()
    arg = {
        "file": "https://f002.backblazeb2.com/file/sunyizhe/cocktail.svg",
        "count": 5,
    }
    output = await client.execute_workflow(
        "image-color-palette", arg, id=f"{uuid4()}", task_queue="media"
    )
    assert len(output["colors"]) == 5


async def test_color_fixed_palette():
    client = await get_client()
    arg = {
        "colors": ["#000001", "#fffffd"],
    }
    output = await client.execute_workflow(
        "color-fixed-palette", arg, id=f"{uuid4()}", task_queue="media"
    )
    assert output["colors"] == ["#000000", "#FFFFFF"]
