import pytest
from sqlalchemy import select

from aurora.orms.models import Movie, Video
from aurora.services.code_extract.extractor import CodeExtractor
from aurora.services.scanner.filesystem_scanner import LibraryScanner


@pytest.fixture
def mock_extractor(mocker):
    return mocker.Mock(spec=CodeExtractor)


@pytest.fixture
def mock_hasher(mocker):
    return mocker.patch("aurora.services.scanner.filesystem_scanner.sample_and_calculate_sha256")

@pytest.fixture
def scanner(session, mock_extractor):
    return LibraryScanner(session, mock_extractor)


class TestLibraryScanner:
    def test_scan_directory_nonexistent(self, scanner, tmp_path):
        """测试: 扫描不存在的目录时应该抛出异常"""
        non_existent_dir = tmp_path / "nonexistent"
        with pytest.raises(FileNotFoundError) as exc_info:
            scanner.scan_directory(str(non_existent_dir))
        assert str(non_existent_dir) in str(exc_info.value)

    def test_scan_new_video_standard(self, sha256, scanner, mock_extractor, mock_hasher, session, tmp_path):
        """
        测试：扫描一个全新的、标准番号视频
        流程: 文件 -> 哈希 -> 提取番号 -> 创建 Movie -> 创建 Video
        """
        # Set up
        video_file = tmp_path / "ABC-123-some-descriptions.mp4"
        video_file.touch()

        mock_hasher.return_value = sha256
        mock_extractor.extract_av_code.return_value = ("ABC", "123")

        result = scanner.scan_directory(str(tmp_path))

        # 验证返回值
        assert len(result) == 1
        assert result[0].code == "ABC-123"

        # 验证数据库状态
        movie = session.scalar(select(Movie).where(Movie.label == "ABC", Movie.number == "123"))
        assert movie is not None

        # 验证Video
        video = session.scalar(select(Video).where(Video.sha256 == sha256))
        assert video is not None
        assert video.movie_id == movie.id
        assert video.filename == "ABC-123-some-descriptions"
        assert video.suffix == "mp4"
        assert video.absolute_path == str(video_file)

    def test_scan_existing_video_unchanged(self, scanner, mock_extractor, mock_hasher, session, tmp_path):
        """
        测试：视频已存在且路径未变
        预期：不进行任何数据库写操作 (Idempotency)
        """
        # 1. 预先在 DB 创建数据
        movie = Movie(label="ABC", number="123")
        video = Video(
            sha256="hash_exist",
            filename="ABC-123",
            suffix="mp4",
            absolute_path=str(tmp_path / "ABC-123.mp4"),
            movie=movie
        )
        session.add_all([movie, video])
        session.commit()

        # 2. 准备文件
        (tmp_path / "ABC-123.mp4").touch()

        # 3. Mock
        mock_hasher.return_value = "hash_exist"  # 哈希一致
        # 此时 extractor 不应被调用，因为通过 hash 找到了 video

        # 4. 执行
        results = scanner.scan_directory(str(tmp_path))

        # 5. 验证
        assert len(results) == 1
        # 验证 Extractor 未被调用 (这也是一种优化验证)
        mock_extractor.extract_av_code.assert_not_called()
        # 验证 Video 记录没有变动
        current_video = session.scalar(select(Video).where(Video.sha256 == "hash_exist"))
        assert current_video.absolute_path == str(tmp_path / "ABC-123.mp4")

    def test_scan_existing_video_moved(self, scanner, mock_hasher, session, tmp_path):
        """
        测试：视频哈希存在，但文件路径变了
        预期：更新数据库中的路径
        """
        # 1. 预先创建数据 (旧路径)
        old_path = tmp_path / "old_folder" / "old_name.mp4"
        movie = Movie(label="ABC", number="123")
        video = Video(
            sha256="hash_move",
            filename="old_name",
            absolute_path=str(old_path),
            movie=movie
        )
        session.add_all([movie, video])
        session.commit()

        # 2. 在新路径创建文件
        new_file = tmp_path / "new_name.mp4"
        new_file.touch()

        # 3. Mock 哈希 (关键：哈希必须相同)
        mock_hasher.return_value = "hash_move"

        # 4. 执行
        scanner.scan_directory(str(tmp_path))

        # 5. 验证
        session.refresh(video)  # 刷新 Session 缓存
        assert video.filename == "new_name"
        assert video.absolute_path == str(new_file)
        assert session.query(Video).count() == 1  # 确保没有创建新记录

    def test_scan_ignore_files(self, scanner, mock_hasher, session, tmp_path):
        """测试：忽略非视频后缀的文件"""
        (tmp_path / "readme.txt").touch()
        (tmp_path / "cover.jpg").touch()

        scanner.scan_directory(str(tmp_path))

        assert mock_hasher.call_count == 0
        assert session.query(Video).count() == 0

    def test_scan_file_io_error_handling(self, scanner, mock_hasher, session, tmp_path):
        """测试：当计算哈希抛出 IOError 时，程序不应崩溃，而是跳过"""
        (tmp_path / "corrupt.mp4").touch()

        # 模拟抛出异常
        mock_hasher.side_effect = IOError("Disk error")

        # 执行 (不应报错)
        results = scanner.scan_directory(str(tmp_path))

        assert len(results) == 0
        assert session.query(Video).count() == 0
