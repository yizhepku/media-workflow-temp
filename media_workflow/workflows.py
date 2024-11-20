import functools
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

start = functools.partial(
    workflow.start_activity, start_to_close_timeout=timedelta(seconds=60)
)


@workflow.defn(name="image-thumbnail")
class ImageThumbnail:
    @workflow.run
    async def run(self, params):
        result = {
            "id": workflow.info().workflow_id,
            "file": await start("image_thumbnail", params),
        }
        if callback_url := params.get("callback_url"):
            await start("callback", args=[callback_url, result])
        return result


@workflow.defn(name="pdf-thumbnail")
class PdfThumbnail:
    @workflow.run
    async def run(self, params):
        result = {
            "id": workflow.info().workflow_id,
            "files": await start("pdf_thumbnail", params),
        }
        if callback_url := params.get("callback_url"):
            await start("callback", args=[callback_url, result])
        return result


@workflow.defn(name="document-thumbnail")
class DocumentThumbnail:
    @workflow.run
    async def run(self, params):
        pdf = await start("convert_to_pdf", params)
        result = {
            "id": workflow.info().workflow_id,
            "files": await start("pdf_thumbnail", {**params, "file": pdf}),
        }
        if callback_url := params.get("callback_url"):
            await start("callback", args=[callback_url, result])
        return result


@workflow.defn(name="image-detail")
class ImageDetail:
    @workflow.run
    async def run(self, params):
        result = await start("image_detail", params)
        result["id"] = workflow.info().workflow_id
        if callback_url := params.get("callback_url"):
            await start("callback", args=[callback_url, result])
        return result


@workflow.defn(name="video-sprite")
class VideoSprite:
    @workflow.run
    async def run(self, params):
        result = {
            "id": workflow.info().workflow_id,
            "files": await start("video_sprite", params),
        }
        if callback_url := params.get("callback_url"):
            await start("callback", args=[callback_url, result])
        return result


@workflow.defn(name="video-transcode")
class VideoTranscode:
    @workflow.run
    async def run(self, params):
        result = {
            "id": workflow.info().workflow_id,
            "file": await start("video_transcode", params),
        }
        if callback_url := params.get("callback_url"):
            await start("callback", args=[callback_url, result])
        return result


@workflow.defn(name="audio-waveform")
class AudioWaveform:
    @workflow.run
    async def run(self, params):
        result = {
            "id": workflow.info().workflow_id,
            "waveform": await start("audio_waveform", params),
        }
        if callback_url := params.get("callback_url"):
            await start("callback", args=[callback_url, result])
        return result


@workflow.defn(name="image-detail-basic")
class ImageDetailLocal:
    @workflow.run
    async def run(self, params):
        basic = await start("image_analysis_basic", params)
        tags = await start("image_analysis_tags", params)
        details = await start("image_analysis_details", params)
        result = {
            "id": workflow.info().workflow_id,
            "title": basic["title"],
            "description": basic["description"],
            "tags": ",".join(value for values in tags.values() for value in values),
            "detailed_description": [{k: v} for k, v in details.items()],
        }

        # replace Chinese comma `，` with regular comma `,`
        result["tags"] = result["tags"].replace("，", ",")

        if callback_url := params.get("callback_url"):
            await start("callback", args=[callback_url, result])
        return result
