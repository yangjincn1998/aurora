from pathlib import Path
from unittest.mock import Mock

import pytest

from aurora.domain.enums import StageStatus
from aurora.domain.pipeline import PipelineContext
from aurora.orms.models import VideoStageStatus
from aurora.services.pipeline.pipeline import Pipeline
from aurora.services.scanner.filesystem_scanner import LibraryScanner
from aurora.services.stages.base import PipelineStage


@pytest.fixture
def mock_scanner():
    return Mock(spec=LibraryScanner)


@pytest.fixture
def mock_context(session):
    context = PipelineContext(session=session)
    return context


# 辅助函数：快速构建 Mock Stage 列表
def create_mock_stages(names):
    stages = []
    for name in names:
        mock_stage = Mock(spec=PipelineStage)
        mock_stage.name = name
        stages.append(mock_stage)
    return stages


stage_names = ["stage1", "stage2", "stage3", "stage4"]


@pytest.fixture
def pipeline(mock_scanner, mock_context):
    stages = create_mock_stages(stage_names)
    pipeline = Pipeline([], stages, mock_scanner, mock_context)
    return pipeline


@pytest.fixture
def local_sample_video(session, sample_video, tmp_path, pipeline):
    by_product_dir = tmp_path / "by_product"
    by_product_dir.mkdir()
    for stage in stage_names:
        (by_product_dir / stage).touch()
    for stage in ["stage1", "stage2", "stage3", "stage4"]:
        sample_video.stages[stage] = VideoStageStatus(
            stage_name=stage,
            by_product_path=str(by_product_dir / stage),
            status=StageStatus.SUCCESS.value,
        )
    session.add(sample_video)
    session.commit()
    yield sample_video
    session.delete(sample_video)
    session.commit()


class TestPipelineSync:
    def test_initialize_sync(self, pipeline, sample_video, session):
        # 第一次执行，此时video的各阶段应该都没有状态
        pipeline._sync_video_status(sample_video)
        session.refresh(sample_video)

        for stage in stage_names:
            assert sample_video.stages[stage].status == StageStatus.PENDING.value

    def test_sync_happy_path(self, pipeline, local_sample_video, session):
        """
        场景 1: 快乐路径
        所有 Stage 都是 SUCCESS，所有文件都存在。
        预期: 没有任何状态被改变。
        """
        # 执行同步
        pipeline._sync_video_status(local_sample_video)
        session.refresh(local_sample_video)

        # 验证
        for stage in stage_names:
            assert local_sample_video.stages[stage].status == StageStatus.SUCCESS.value

    def test_sync_terminal_optimization(self, pipeline, local_sample_video, session):
        """
        场景 2: 终点优化
        最终产物 (stage4) 存在且成功。中间产物 (stage2) 丢失（模拟用户删除了中间文件）。
        预期: 因为终点完好，中间缺失不应该触发回滚，保持原样。
        """
        # 1. 删除 stage2 的文件
        stage2_path = Path(local_sample_video.stages["stage2"].by_product_path)
        stage2_path.unlink()
        assert not stage2_path.exists()

        # 2. 确保 stage4 (终点) 文件存在
        stage4_path = Path(local_sample_video.stages["stage4"].by_product_path)
        assert stage4_path.exists()

        # 3. 执行同步
        pipeline._sync_video_status(local_sample_video)
        session.refresh(local_sample_video)

        # 4. 验证：应该全部保持 SUCCESS
        assert local_sample_video.stages["stage2"].status == StageStatus.SUCCESS.value
        assert local_sample_video.stages["stage3"].status == StageStatus.SUCCESS.value

    def test_sync_cascade_rollback_missing_file(
            self, pipeline, local_sample_video, session, tmp_path
    ):
        """
        场景 3: 文件丢失导致的多米诺回滚
        终点文件 (stage4) 丢失（此时必须检查中间过程）。
        中间文件 (stage2) 也丢失。
        预期: 从 stage2 开始，stage2, stage3, stage4 全部重置为 PENDING。stage1 保持 SUCCESS。
        """
        # 1. 删除终点文件 (为了绕过终点优化检查)
        Path(local_sample_video.stages["stage4"].by_product_path).unlink()

        # 2. 删除 stage2 文件 (这是断点)
        Path(local_sample_video.stages["stage2"].by_product_path).unlink()

        # 3. 执行同步
        pipeline._sync_video_status(local_sample_video)
        session.refresh(local_sample_video)

        # 4. 验证
        assert (
                local_sample_video.stages["stage1"].status == StageStatus.SUCCESS.value
        )  # 没受影响
        assert (tmp_path / "by_product" / "stage1").exists()
        assert (
                local_sample_video.stages["stage2"].status == StageStatus.PENDING.value
        )  # 断点被重置
        assert not (tmp_path / "by_product" / "stage2").exists()
        assert (
                local_sample_video.stages["stage3"].status == StageStatus.PENDING.value
        )  # 后续被波及
        assert not (tmp_path / "by_product" / "stage3").exists()
        assert (
                local_sample_video.stages["stage4"].status == StageStatus.PENDING.value
        )  # 后续被波及
        assert not (tmp_path / "by_product" / "stage4").exists()

    def auxiliary_test_sync_cascade_rollbacked_or_skipped_state(
            self,
            pipeline,
            local_sample_video,
            session,
            fail_or_skipped_state: StageStatus,
            tmp_path,
    ):
        """
        场景 4: 状态异常导致的多米诺回滚
        终点文件丢失。
        Stage 2 的状态是 FAILED 或者 SKIPPED。
        预期: 从 stage2 开始回滚。
        """
        # 1. 删除终点文件
        Path(local_sample_video.stages["stage4"].by_product_path).unlink()

        # 2. 修改 Stage 2 为状态
        local_sample_video.stages["stage2"].status = fail_or_skipped_state.value
        session.commit()

        # 3. 执行同步
        pipeline._sync_video_status(local_sample_video)
        session.refresh(local_sample_video)

        # 4. 验证
        assert local_sample_video.stages["stage1"].status == StageStatus.SUCCESS.value
        assert (tmp_path / "by_product" / "stage1").exists()
        assert (
                local_sample_video.stages["stage2"].status == StageStatus.PENDING.value
        )  # FAILED | SKIPPED -> PENDING
        assert not (tmp_path / "by_product" / "stage2").exists()
        assert (
                local_sample_video.stages["stage3"].status == StageStatus.PENDING.value
        )  # SUCCESS -> PENDING (被回滚)
        assert not (tmp_path / "by_product" / "stage3").exists()
        assert not (tmp_path / "by_product" / "stage4").exists()

    def test_sync_cascade_rollback_failed_state(
            self, pipeline, local_sample_video, session, tmp_path
    ):
        self.auxiliary_test_sync_cascade_rollbacked_or_skipped_state(
            pipeline, local_sample_video, session, StageStatus.FAILED, tmp_path
        )

    def test_sync_cascade_rollback_skipped_state(
            self, pipeline, local_sample_video, session, tmp_path
    ):
        self.auxiliary_test_sync_cascade_rollbacked_or_skipped_state(
            pipeline, local_sample_video, session, StageStatus.SKIPPED, tmp_path
        )

    def test_sync_reset_all_if_first_missing(
            self, pipeline, local_sample_video, session, tmp_path
    ):
        """
        场景 5: 第一步就挂了
        终点丢失，Stage 1 文件丢失。
        预期: 全员重置。
        """
        Path(local_sample_video.stages["stage4"].by_product_path).unlink()
        Path(local_sample_video.stages["stage1"].by_product_path).unlink()

        pipeline._sync_video_status(local_sample_video)
        session.refresh(local_sample_video)

        for stage in stage_names:
            assert local_sample_video.stages[stage].status == StageStatus.PENDING.value
            assert not (tmp_path / "by_product" / stage).exists()

    def test_sync_partial_stages_in_db(
            self, pipeline, local_sample_video, session, tmp_path
    ):
        """
        场景 6: 数据库里只有前两步的记录 (模拟新添加了 Stage 的情况)
        Pipeline 有 4 步，但 Video 只有 stage1, stage2 的记录。
        预期: 逻辑应该能正常运行，不会因为 key error 报错。
        """
        # 1. 模拟数据库里缺少 stage3 和 stage4 的记录
        del local_sample_video.stages["stage3"]
        del local_sample_video.stages["stage4"]
        session.add(local_sample_video)
        session.commit()

        # 2. 删除 stage2 的文件，触发回滚
        # 注意：这里也需要删除终点文件判定，但因为数据库里没 stage4，
        # 代码里的 terminal_stage_info = get(...) 会返回 PENDING，自然会进入检查逻辑
        Path(local_sample_video.stages["stage2"].by_product_path).unlink()

        pipeline._sync_video_status(local_sample_video)
        session.refresh(local_sample_video)

        # 验证
        assert local_sample_video.stages["stage1"].status == StageStatus.SUCCESS.value
        assert (tmp_path / "by_product" / "stage1").exists()
        assert local_sample_video.stages["stage2"].status == StageStatus.PENDING.value
        assert not (tmp_path / "by_product" / "stage2").exists()
        # stage3, 4 本来就不在 status 字典里，所以不会报错，也不需要断言
