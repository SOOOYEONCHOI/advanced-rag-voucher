import pytest

from app.services.ingest_pipeline import IngestPipeline


@pytest.mark.asyncio
async def test_pipeline_resumes_from_failed_step(tmp_path):
    calls = []

    class Step:
        def __init__(self, name, fail=False):
            self.name = name
            self.fail = fail

        async def run(self, service, context):
            calls.append(self.name)
            if self.fail:
                raise RuntimeError(self.name)
            context.data[self.name] = True
            if self.name == "index":
                context.data["result"] = {"status": "success"}

    checkpoint = str(tmp_path / "job.checkpoint")
    pipeline = IngestPipeline()
    pipeline.steps = (Step("parse"), Step("chunk"), Step("embed", fail=True), Step("index"))
    with pytest.raises(RuntimeError):
        await pipeline.run(object(), {}, checkpoint_path=checkpoint)

    pipeline.steps = (Step("parse"), Step("chunk"), Step("embed"), Step("index"))
    result = await pipeline.run(object(), {}, checkpoint_path=checkpoint, resume_from="embed")

    assert calls == ["parse", "chunk", "embed", "embed", "index"]
    assert result == {"status": "success"}
