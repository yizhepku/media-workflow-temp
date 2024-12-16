import asyncio
import functools
import inspect
import sys
from datetime import timedelta
from json import dumps as json_dumps

from temporalio import workflow


with workflow.unsafe.imports_passed_through():
    from media_workflow.activities import document, font, image, utils, video

start = functools.partial(
    workflow.start_activity,
    start_to_close_timeout=timedelta(minutes=5),
    schedule_to_close_timeout=timedelta(minutes=20),
)


@workflow.defn(name="file-analysis")
class FileAnalysis:
    def __init__(self):
        self.results = {}

    @workflow.update
    async def get(self, key):
        await workflow.wait_condition(lambda: key in self.results)
        return self.results[key]

    @workflow.run
    async def run(self, request):
        try:
            datadir = await start(utils.datadir)

            file = await start(
                utils.download,
                utils.DownloadParams(request["file"], datadir),
                heartbeat_timeout=timedelta(minutes=1),
                start_to_close_timeout=timedelta(minutes=30),
                schedule_to_close_timeout=timedelta(minutes=60),
            )

            async with asyncio.TaskGroup() as tg:
                if "image-thumbnail" in request["activities"]:
                    tg.create_task(self.image_thumbnail(file, request, datadir))
                if "image-detail" in request["activities"]:
                    tg.create_task(self.image_detail(file, request, datadir))
                if "image-detail-basic" in request["activities"]:
                    tg.create_task(self.image_detail_basic(file, request, datadir))
                if "image-color-palette" in request["activities"]:
                    tg.create_task(self.image_color_palette(file, request, datadir))
                if "video-metadata" in request["activities"]:
                    tg.create_task(self.video_metadata(file, request, datadir))
                if "video-sprite" in request["activities"]:
                    tg.create_task(self.video_sprite(file, request, datadir))
                if "video-transcode" in request["activities"]:
                    tg.create_task(self.video_transcode(file, request, datadir))
                if "audio-waveform" in request["activities"]:
                    tg.create_task(self.audio_waveform(file, request, datadir))
                if "document-thumbnail" in request["activities"]:
                    tg.create_task(self.document_thumbnail(file, request, datadir))
                if "font-thumbnail" in request["activities"]:
                    tg.create_task(self.font_thumbnail(file, request, datadir))
                if "font-metadata" in request["activities"]:
                    tg.create_task(self.font_metadata(file, request, datadir))
                if "font-detail" in request["activities"]:
                    tg.create_task(self.font_detail(file, request, datadir))

            return {
                "id": workflow.info().workflow_id,
                "request": request,
                "result": self.results,
            }

        # If the workflow timeout, report the error via callback
        except Exception as err:
            if callback := request.get("callback"):
                data = {
                    "id": workflow.info().workflow_id,
                    "request": request,
                    "error": str(err),
                }
                await start("callback", args=[callback, data])
            raise

    async def submit(self, activity, request, result):
        self.results[activity] = result
        if callback := request.get("callback"):
            response = {
                "id": workflow.info().workflow_id,
                "request": request,
                "result": {
                    activity: result,
                },
            }
            await start("callback", args=[callback, response])

    async def image_thumbnail(self, file, request, datadir):
        activity = "image-thumbnail"
        file = await start(
            image.thumbnail,
            image.ThumbnailParams(
                file, datadir=datadir, **request.get("params", {}).get(activity, {})
            ),
        )
        result = await start(utils.upload, utils.UploadParams(file, "image/png"))
        await self.submit(activity, request, result)

    async def image_detail(self, file, request, datadir):
        activity = "image-detail"
        # convert image to PNG first
        png = await start(
            image.thumbnail,
            image.ThumbnailParams(file, datadir=datadir, size=(1000, 1000)),
        )
        url = await start(utils.upload, utils.UploadParams(png, "image/png"))
        result = await start(
            image.detail,
            image.DetailParams(url, **request.get("params", {}).get(activity, {})),
        )
        await self.submit(activity, request, result)

    async def image_detail_basic(self, file, request, datadir):
        activity = "image-detail-basic"
        # convert image to PNG first
        png = await start(
            image.thumbnail,
            image.ThumbnailParams(file, datadir=datadir, size=(1000, 1000)),
        )
        # invoke minicpm three times
        params = image.DetailBasicParams(
            png, **request.get("params", {}).get(activity, {})
        )
        basic = await start(image.minicpm_basic, params)
        tags = await start(image.minicpm_tags, params)
        details = await start(image.minicpm_details, params)
        result = {
            "title": basic["title"],
            "description": basic["description"],
            "tags": ",".join(value for values in tags.values() for value in values),
            "detailed_description": [{k: v} for k, v in details.items()],
        }
        await self.submit(activity, request, result)

    async def image_color_palette(self, file, request, _datadir):
        activity = "image-color-palette"
        result = await start(
            image.color_palette,
            image.ColorPaletteParams(
                file, **request.get("params", {}).get(activity, {})
            ),
        )
        await self.submit(activity, request, result)

    async def video_metadata(self, file, request, _datadir):
        activity = "video-metadata"
        result = await start(video.metadata, video.MetadataParams(file))
        await self.submit(activity, request, result)

    async def video_sprite(self, file, request, datadir):
        activity = "video-sprite"
        metadata = await start(video.metadata, video.MetadataParams(file))
        duration = metadata["duration"]
        images = await start(
            video.sprite,
            video.SpriteParams(
                file,
                duration,
                datadir=datadir,
                **request.get("params", {}).get(activity, {}),
            ),
        )
        result = await asyncio.gather(
            *[
                start(utils.upload, utils.UploadParams(image, "image/png"))
                for image in images
            ]
        )
        await self.submit(activity, request, result)

    async def video_transcode(self, file, request, datadir):
        activity = "video-transcode"
        params = video.TranscodeParams(
            file, datadir=datadir, **request.get("params", {}).get(activity, {})
        )
        path = await start(video.transcode, params)
        mimetype = f"video/{params.container}"
        result = await start(utils.upload, utils.UploadParams(path, mimetype))
        await self.submit(activity, request, result)

    async def audio_waveform(self, file, request, _datadir):
        activity = "audio-waveform"
        result = await start(
            video.waveform,
            video.WaveformParams(file, **request.get("params", {}).get(activity, {})),
        )
        await self.submit(activity, request, result)

    async def document_thumbnail(self, file, request, datadir):
        activity = "document-thumbnail"
        # convert the document to PDF
        pdf = await start(document.to_pdf, document.ToPdfParams(file, datadir=datadir))
        # extract thumbnails from pdf pages
        images = await start(
            document.thumbnail,
            document.ThumbnailParams(
                pdf, datadir=datadir, **request.get("params", {}).get(activity, {})
            ),
        )
        # upload thumbnails
        result = await asyncio.gather(
            *[
                start(utils.upload, utils.UploadParams(image, "image/png"))
                for image in images
            ]
        )
        await self.submit(activity, request, result)

    async def font_thumbnail(self, file, request, datadir):
        activity = "font-thumbnail"
        image = await start(
            font.thumbnail,
            font.ThumbnailParams(
                file, datadir=datadir, **request.get("params", {}).get(activity, {})
            ),
        )
        result = await start(utils.upload, utils.UploadParams(image, "image/png"))
        await self.submit(activity, request, result)

    async def font_metadata(self, file, request, _datadir):
        activity = "font-metadata"
        result = await start(
            font.metadata,
            font.MetadataParams(file, **request.get("params", {}).get(activity, {})),
        )
        await self.submit(activity, request, result)

    async def font_detail(self, file, request, datadir):
        activity = "font-detail"
        image = await start(font.thumbnail, font.ThumbnailParams(file, datadir=datadir))
        image_url = await start(utils.upload, utils.UploadParams(image, "image/png"))
        metadata = await start(font.metadata, font.MetadataParams(file))
        basic_info = {
            "name": metadata["full_name"],
            "designer": metadata["designer"],
            "description": metadata["description"],
            "supports_kerning": metadata["kerning"],
            "supports_chinese": metadata["chinese"],
        }
        result = await start(
            font.detail,
            font.DetailParams(
                url=image_url,
                basic_info=json_dumps(basic_info),
                **request.get("params", {}).get(activity, {}),
            ),
        )
        await self.submit(activity, request, result)


@workflow.defn(name="color-calibrate")
class ColorCalibrate:
    @workflow.run
    async def run(self, colors):
        return await start("calibrate", colors)


workflows = []
for _name, fn in inspect.getmembers(sys.modules[__name__]):
    if hasattr(fn, "__temporal_workflow_definition"):
        workflows.append(fn)
