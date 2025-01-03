import asyncio
import json
import math
import os
import re
from pathlib import Path
from uuid import uuid4

import numpy as np
from pydantic import BaseModel
from temporalio import activity

from media_workflow.activities.utils import get_datadir
from media_workflow.trace import instrument


class MetadataParams(BaseModel):
    file: Path


@instrument
@activity.defn(name="video-metadata")
async def metadata(params: MetadataParams) -> dict:
    process = await asyncio.subprocess.create_subprocess_exec(
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_entries",
        "format=duration",
        "-show_streams",
        params.file,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    (stdout, stderr) = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {stderr.decode()}")

    data = json.loads(stdout.decode())
    result = {}
    result["duration"] = float(data["format"]["duration"])
    for stream in data["streams"]:
        if stream["codec_type"] == "video":
            result["video_codec"] = stream["codec_name"]
            result["width"] = int(stream["width"])
            result["height"] = int(stream["height"])
            numerator, denominator = map(int, stream["avg_frame_rate"].split("/"))
            result["fps"] = float(numerator) / float(denominator)
            result["pix_fmt"] = stream["pix_fmt"]
            # bitrate info is not available in every video
            result["bit_rate"] = int(stream.get("bit_rate", 0))
            result["bits_per_raw_sample"] = int(stream.get("bits_per_raw_sample", 0))
        if stream["codec_type"] == "audio":
            result["audio_codec"] = stream["codec_name"]
            result["sample_fmt"] = stream["sample_fmt"]
            result["channel_layout"] = stream["channel_layout"]
            result["sample_rate"] = int(stream["sample_rate"])

    result["size"] = os.path.getsize(params.file)
    return result


class SpriteParams(BaseModel):
    file: Path
    duration: float
    layout: tuple[int, int] = (5, 5)
    count: int = 1
    width: int = 200
    height: int = -1


@instrument
@activity.defn(name="video-sprite")
async def sprite(params: SpriteParams) -> dict:
    datadir = get_datadir()
    # calculate time between frames (in seconds)
    interval = params.duration / float(params.count * params.layout[0] * params.layout[1])

    process = await asyncio.subprocess.create_subprocess_exec(
        "ffmpeg",
        "-i",
        params.file,
        "-vf",
        f"fps={1/interval},scale={params.width}:{params.height},tile={params.layout[0]}x{params.layout[1]}",
        "-vframes",
        str(params.count),
        f"{datadir}/%03d.png",
        stderr=asyncio.subprocess.PIPE,
    )
    (_, stderr) = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {stderr.decode()}")
    width = 0
    height = 0
    for line in stderr.decode().split("\n"):
        if match := re.search(r"Video: png.*?(\d+)x(\d+)", line):
            width = int(match.group(1))
            height = int(match.group(2))

    paths = [path for path in Path(datadir).iterdir() if path.suffix == ".png"]
    paths.sort(key=lambda p: int(p.stem))
    return {
        "interval": interval,
        "width": width // params.layout[0],
        "height": height // params.layout[1],
        "files": [str(path) for path in paths],
    }


class TranscodeParams(BaseModel):
    file: Path
    video_codec: str = "h264"
    audio_codec: str = "libopus"
    container: str = "mp4"


@instrument
@activity.defn(name="video-transcode")
async def transcode(params: TranscodeParams) -> Path:
    datadir = get_datadir()
    output = datadir / f"{uuid4()}.{params.container}"
    process = await asyncio.subprocess.create_subprocess_exec(
        "ffmpeg",
        "-i",
        params.file,
        "-codec:v",
        params.video_codec,
        "-codec:a",
        params.audio_codec,
        output,
        stderr=asyncio.subprocess.PIPE,
    )
    (_, stderr) = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {stderr.decode()}")
    assert output.exists()
    return output


class WaveformParams(BaseModel):
    file: Path
    num_samples: int = 1000


@instrument
@activity.defn(name="audio-waveform")
async def waveform(params: WaveformParams) -> list[float]:
    # Convert the audio to raw 16-bit little-endian samples.
    process = await asyncio.subprocess.create_subprocess_exec(
        "ffmpeg",
        "-i",
        params.file,
        "-f",
        "s16le",
        "-codec:a",
        "pcm_s16le",
        "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    (stdout, stderr) = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {stderr.decode()}")
    data = np.frombuffer(stdout, dtype=np.int16)

    samples = np.zeros(params.num_samples)
    step = math.ceil(len(data) / params.num_samples)
    for i in range(0, len(data), step):
        samples[i // step] = np.max(np.abs(data[i : i + step]))

    # Normalize the data
    samples = samples / np.max(samples)
    return samples.tolist()  # type: ignore
