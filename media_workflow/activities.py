import math
import mimetypes
import os
import re
import subprocess
import tempfile
from base64 import b64encode
from inspect import cleandoc
from io import BytesIO
from json import loads as json_loads
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from temporalio import activity, workflow

with workflow.unsafe.imports_passed_through():
    import aiohttp
    import boto3
    import ffmpeg
    import numpy as np
    import pymupdf
    from botocore.config import Config
    from fontTools.ttLib import TTFont
    from PIL import Image
    from pydub import AudioSegment

    import media_workflow.utils
    from media_workflow.color import rgb2hex, snap_to_palette
    from media_workflow.font import metadata, preview
    from media_workflow.imread import imread
    from media_workflow.trace import span_attribute, tracer
    from media_workflow.utils import fetch, upload
    from pylette.color_extraction import extract_colors


def image2png(image: Image.Image) -> bytes:
    # If the image is in floating point mode, scale the value by 255
    # See https://github.com/python-pillow/Pillow/issues/3159
    if image.mode == "F":
        image = Image.fromarray((np.array(image) * 255).astype(np.uint8), mode="L")

    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="png")
    return buffer.getvalue()


def page2image(page: pymupdf.Page) -> Image.Image:
    pix = page.get_pixmap()
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


@activity.defn
async def callback(url: str, json):
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=json) as r:
            if r.status != 200:
                raise Exception(f"callback failed: {await r.text()}")


# @activity.defn
# async def image_thumbnail(params) -> str:
#     image = await imread(params["file"])
#     with tracer.start_as_current_span("make-thumbnail"):
#         if size := params.get("size"):
#             image.thumbnail(size, resample=Image.LANCZOS)
#     return upload(f"{uuid4()}.png", image2png(image), content_type="image/png")


@activity.defn
async def pdf_thumbnail(params) -> list[str]:
    images = []
    with pymupdf.Document(stream=await fetch(params["file"])) as doc:
        if pages := params.get("pages"):
            for i in pages:
                images.append(page2image(doc[i]))
        else:
            for page in doc.pages():
                images.append(page2image(page))
    if size := params.get("size"):
        for image in images:
            image.thumbnail(size, resample=Image.LANCZOS)
    return [
        upload(f"{uuid4()}.png", image2png(image), content_type="image/png")
        for image in images
    ]


@activity.defn
async def font_thumbnail(params) -> str:
    bytes = await fetch(params["file"])
    image = preview(
        BytesIO(bytes),
        size=params.get("size", (800, 600)),
        font_size=params.get("font_size", 200),
    )
    return upload(f"{uuid4()}.png", image2png(image), content_type="image/png")


@activity.defn
async def font_metadata(params) -> str:
    bytes = await fetch(params["file"])
    return metadata(
        TTFont(BytesIO(bytes), fontNumber=0),
        language=params.get("language", "English"),
    )


@activity.defn
async def image_detail(params) -> dict:
    headers = {"Authorization": f"Bearer {os.environ["DIFY_IMAGE_DETAIL_KEY"]}"}
    json = {
        "inputs": {
            "language": params["language"],
            "image": {
                "type": "image",
                "transfer_method": "remote_url",
                "url": params["file"],
            },
        },
        "user": os.environ["DIFY_USER"],
        "response_mode": "blocking",
    }
    async with aiohttp.ClientSession() as session:
        url = f"{os.environ["DIFY_ENDPOINT_URL"]}/workflows/run"
        async with session.post(url, headers=headers, json=json) as r:
            result = await r.json()
    assert result["data"]["status"] == "succeeded"
    assert isinstance(result["data"]["outputs"]["tags"], str)
    return result["data"]["outputs"]


@activity.defn
async def font_detail(params) -> dict:
    headers = {"Authorization": f"Bearer {os.environ["DIFY_FONT_DETAIL_KEY"]}"}
    json = {
        "inputs": {
            "language": params["language"],
            "basic_info": params["basic_info"],
            "image": {
                "type": "image",
                "transfer_method": "remote_url",
                "url": params["file"],
            },
        },
        "user": os.environ["DIFY_USER"],
        "response_mode": "blocking",
    }
    async with aiohttp.ClientSession() as session:
        url = f"{os.environ["DIFY_ENDPOINT_URL"]}/workflows/run"
        async with session.post(url, headers=headers, json=json) as r:
            r.raise_for_status()
            result = await r.json()
    assert result["data"]["status"] == "succeeded"
    output = result["data"]["outputs"]

    assert isinstance(output["description"], str)
    assert isinstance(output["tags"], str)
    assert isinstance(output["font_category"], str)
    assert isinstance(output["stroke_characteristics"], str)
    assert isinstance(output["historical_period"], str)
    return output


@activity.defn
async def video_sprite(params) -> list[str]:
    with TemporaryDirectory() as dir:
        stream = ffmpeg.input(params["file"])

        interval = params.get("interval", 5)
        expr = f"floor((t - prev_selected_t) / {interval})"
        stream = stream.filter("select", expr=expr)

        if layout := params.get("layout"):
            stream = stream.filter("tile", layout=f"{layout[0]}x{layout[1]}")

        stream = stream.filter(
            "scale", width=params.get("width", -1), height=params.get("height", -1)
        )

        filename = f"{dir}/%03d.png"
        if count := params.get("count"):
            stream = stream.output(filename, fps_mode="passthrough", vframes=count)
        else:
            stream = stream.output(filename, fps_mode="passthrough")

        stream.run()

        paths = list(Path(dir).iterdir())
        paths.sort(key=lambda p: int(p.stem))
        result = []
        for path in paths:
            with open(path, "rb") as file:
                result.append(
                    upload(f"{uuid4()}.png", file.read(), content_type="image/png")
                )
        return result


@activity.defn
async def video_transcode(params) -> str:
    with TemporaryDirectory() as dir:
        stream = ffmpeg.input(params["file"])

        container = params.get("container", "mp4")
        path = Path(f"{dir}/{uuid4()}.{container}")
        kwargs = {
            "codec:v": params.get("video-codec", "h264"),
            "codec:a": params.get("audio-codec", "libopus"),
        }
        stream = stream.output(str(path), **kwargs)
        stream.run()

        with open(path, "rb") as file:
            return upload(path.name, file.read(), content_type=f"video/{container}")


@activity.defn
async def audio_waveform(params) -> list[float]:
    bytes = await fetch(params["file"])
    audio = AudioSegment.from_file(BytesIO(bytes))
    data = np.array(audio.get_array_of_samples())

    samples = np.zeros(params["num_samples"])
    step = math.ceil(len(data) / params["num_samples"])
    for i in range(0, len(data), step):
        samples[i // step] = np.max(np.abs(data[i : i + step]))

    # Normalize the data
    samples = samples / np.max(samples)
    return samples.tolist()


@activity.defn
async def convert_to_pdf(params) -> str:
    with TemporaryDirectory() as dir:
        stem = str(uuid4())
        input = f"{dir}/{stem}"
        with open(input, "wb") as file:
            file.write(await fetch(params["file"]))
        subprocess.run(["soffice", "--convert-to", "pdf", "--outdir", dir, input])
        output = f"{input}.pdf"
        with open(output, "rb") as file:
            return upload(f"{stem}.pdf", file.read(), content_type="application/pdf")


async def minicpm(prompt: str, image_url: str, postprocess=None):
    async with aiohttp.ClientSession() as client:
        async with client.get(image_url) as r:
            b64image = b64encode(await r.read()).decode("ascii")

        url = f"{os.environ["OLLAMA_ENDPOINT"]}/api/chat"
        headers = {"Authorization": f"Bearer {os.environ["OLLAMA_KEY"]}"}
        json = {
            "model": "minicpm-v:8b-2.6-q4_K_S",
            "stream": False,
            "messages": [{"role": "user", "content": prompt, "images": [b64image]}],
        }
        async with client.post(url, headers=headers, json=json) as r:
            if r.status != 200:
                raise Exception(f"Ollama returned status {r.status}: {await r.text()}")
            json = await r.json()

        if error := json.get("error"):
            raise Exception(error)
        content = json["message"]["content"]
        if postprocess:
            content = postprocess(content)
        return content


@activity.defn
async def image_analysis_basic(params):
    def postprocess(content):
        json = json_loads(content)
        assert isinstance(json["title"], str)
        assert isinstance(json["description"], str)
        if json["title"].isascii() or json["description"].isascii():
            raise Exception(
                "Model generated English result when the requested language is not English"
            )
        return json

    prompt = cleandoc(
        f"""
        Extract a title and a detailed description from the image. The output should be in {params["language"]}.

        The output should be in JSON format. The output JSON should contain the following keys:
        - title
        - description

        The title should summarize the image in a short, single sentence using {params["language"]}.
        No punctuation mark should be in the title.

        The description should be a long text that describes the content of the image.
        All objects that appear in the image should be described.
        If there're any text in the image, mention the text and the font type of that text.
        """
    )
    return await minicpm(prompt, params["file"], postprocess)


@activity.defn
async def image_analysis_tags(params):
    def postprocess(content):
        keys = [
            "theme_identification",
            "emotion_capture",
            "style_annotation",
            "color_analysis",
            "scene_description",
            "character_analysis",
            "purpose_clarification",
            "technology_identification",
            "time_marking",
            "trend_tracking",
        ]

        json = json_loads(content)
        for key in keys:
            # check that each value is a list
            if key not in json or not isinstance(json[key], list):
                json[key] = []
            # check that each value inside that list is a string
            if json[key] and not isinstance(json[key][0], str):
                json[key] = []
            # split values that have commas
            json[key] = list(
                subvalue for value in json[key] for subvalue in re.split(",|，", value)
            )
        # reject English results if the language is not set to English
        if params["language"].lower() != "english":
            for tags in json.values():
                for tag in tags:
                    if tag.isascii():
                        raise Exception(
                            "Model generated English result when the requested language is not English"
                        )
        return json

    prompt = cleandoc(
        f"""
        Extract tags from the image according to some predefined aspects. The output should be in {params["language"]}.

        The output should be a JSON object with the following keys:
        - theme_identification: summarize the core theme of the material, such as education, technology, health, etc.
        - emotion_capture: summarize the emotional tone conveyed by the material, such as motivational, joyful, sad, etc.
        - style_annotation: summarize the visual or linguistic style of the material, such as modern, vintage, minimalist, etc.
        - color_analysis: summarize the main colors of the material, such as blue, red, black and white, etc.
        - scene_description: summarize the environmental background where the material takes place, such as office, outdoor, home, etc.
        - character_analysis: summarize characters in the material based on their roles or features, such as professionals, children, athletes, etc.
        - purpose_clarification: summarize the intended application scenarios of the material, such as advertising, education, social media, etc.
        - technology_identification: summarize the specific technologies applied in the material, such as 3D printing, virtual reality, etc.
        - time_marking: summarize time tags based on the material's relevance to time, if applicable, such as spring, night, 20th century, etc.
        - trend_tracking: summarize current trends or hot issues, such as sustainable development, artificial intelligence, etc.

        Each tag value should be a JSON list containing zero of more short strings.
        Each string should briefly describes the image in {params["language"]}.
        Only use strings inside lists, not complex objects.

        If the extracted value is vague or non-informative, or if the tag doesn't apply to this image, set the value to an empty list instead. 
        If the extracted value is a complex object instead of a string, summarize it in a short string instead.
        If the extracted value is too long, shorten it by summarizing the key information.
        """
    )
    return await minicpm(prompt, params["file"], postprocess)


@activity.defn
async def image_analysis_details(params):
    def postprocess(content):
        keys = [
            "usage",
            "mood",
            "color_theme",
            "culture_traits",
            "industry_domain",
            "seasonality",
            "holiday_theme",
        ]

        json = json_loads(content)
        for key in keys:
            if key not in json or not isinstance(json[key], str):
                json[key] = None

        # reject English results if the language is not set to English
        if params["language"].lower() != "english":
            for value in json.values():
                if value and value.isascii():
                    raise Exception(
                        "Model generated English result when the requested language is not English"
                    )
        return json

    prompt = cleandoc(
        f"""
        Extract detailed descriptions from the image according to some predefined aspects.
        The output should be in {params["language"]}.

        The output should be a JSON object with the following keys:
        - usage
        - mood
        - color_theme
        - culture_traits
        - industry_domain
        - seasonality
        - holiday_theme

        Each value should be a short phrase that describes the image in {params["language"]}.
        If the extracted value is not in {params["language"]}, translate the value to {params["language"]} instead.
        If no relevant information can be extracted from the image, or if the result is vague, set the value to null instead.
        """
    )
    return await minicpm(prompt, params["file"], postprocess)


@activity.defn
async def image_color_palette(params) -> list:
    image = await imread(params["file"])
    palette = extract_colors(image.convert("RGB"), params.get("count", 10))
    return [{"color": rgb2hex(color.rgb), "frequency": color.freq} for color in palette]


@activity.defn
async def color_fixed_palette(params) -> list:
    return snap_to_palette(params["colors"])


@activity.defn
async def download(url) -> str:
    """Download a file from a URL. Return the file path.

    The filename is randomly generated. If the server returns a Content-Type header, it will be
    used to attach a file extension."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            mimetype = response.headers.get("Content-Type")
            data = await response.read()

    dir = tempfile.gettempdir()
    filename = str(uuid4())
    if mimetype and (ext := mimetypes.guess_extension(mimetype)):
        filename += ext
    path = os.path.join(dir, filename)

    with open(path, "wb") as file:
        file.write(data)

    span_attribute("url", url)
    span_attribute("path", path)
    return path


@activity.defn
async def upload(path: str, content_type: str = "binary/octet-stream"):
    """Upload file to S3-compatible storage. Return a presigned URL that can be used to download
    the file."""
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT_URL"],
        config=Config(region_name=os.environ["S3_REGION"], signature_version="v4"),
    )
    with open(path, "rb") as file:
        key = Path(path).name
        data = file.read()
        s3.put_object(
            Bucket=os.environ["S3_BUCKET"],
            Key=key,
            Body=data,
            ContentType=content_type,
        )
    presigned_url = s3.generate_presigned_url(
        "get_object", Params=dict(Bucket=os.environ["S3_BUCKET"], Key=key)
    )
    span_attribute("key", key)
    span_attribute("path", path)
    span_attribute("content_type", content_type)
    span_attribute("presigned_url", presigned_url)
    return presigned_url


@activity.defn(name="image-thumbnail")
async def image_thumbnail(params) -> str:
    image = media_workflow.utils.imread(params["file"])
    if size := params.get("size"):
        image.thumbnail(size, resample=Image.LANCZOS)
    return media_workflow.utils.imwrite(image)
