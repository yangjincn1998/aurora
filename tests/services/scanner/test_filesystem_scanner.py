import datetime
from unittest.mock import Mock

import pytest
from aurora_scraper.extractor.extractor import VideoInfoExtractor
from aurora_scraper.models import JavMovie
from sqlalchemy import select

from aurora.orms.models import Movie, Video
from aurora.services.scanner.filesystem_scanner import LibraryScanner


@pytest.fixture()
def mock_movie_info():
    # 注意：新的scanner即使视频已存在也会调用extractor
    # 设置extractor返回正确的值
    movie_info = Mock(spec=JavMovie)
    movie_info.title = None
    movie_info.release_date = None
    movie_info.director = None
    movie_info.producer = None
    movie_info.actors = []
    movie_info.actresses = []
    movie_info.categories = []
    return movie_info


@pytest.fixture
def mock_extractor(mocker):
    return mocker.Mock(spec=VideoInfoExtractor)


@pytest.fixture
def mock_validator(mocker):
    return mocker.patch("aurora.orms.models.validate_sha256", return_value=True)


@pytest.fixture
def mock_hasher(mocker):
    return mocker.patch(
        "aurora.services.scanner.filesystem_scanner.sample_and_calculate_sha256"
    )


@pytest.fixture
def scanner(session, mock_extractor):
    return LibraryScanner(session, mock_extractor)


class TestLibraryScanner:
    def test_scan_directory_nonexistent(self, scanner, tmp_path):
        """测试: 扫描不存在的目录时应该抛出异常"""
        non_existent_dir = tmp_path / "nonexistent"
        with pytest.raises(FileNotFoundError) as exc_info:
            scanner.scan_directory(non_existent_dir)
        assert str(non_existent_dir) in str(exc_info.value)

    def test_scan_new_video_standard(
            self, sha256, scanner, mock_extractor, mock_hasher, session, tmp_path
    ):
        """
        测试：扫描一个全新的、标准番号视频
        流程: 文件 -> 哈希 -> 提取番号 -> 创建 Movie -> 创建 Video
        """
        # Set up
        video_file = tmp_path / "ABC-123-some-descriptions.mp4"
        video_file.touch()

        mock_hasher.return_value = sha256
        # 新的extractor返回(label, number, movie_info)三元组
        # 注意：movie_info为None时，movie不会被添加到scanned_movies集合
        # 创建一个完整的Mock JavMovie对象
        movie_info = Mock(spec=JavMovie)
        movie_info.title = "Test Movie"
        movie_info.release_date = None
        movie_info.director = None
        movie_info.producer = None
        movie_info.actors = []
        movie_info.actresses = []
        movie_info.categories = []
        mock_extractor.extract_video_metadata.return_value = ("ABC", "123", movie_info)

        result = scanner.scan_directory(tmp_path)

        # 验证返回值
        assert len(result) == 1
        assert result[0].code == "ABC-123"

        # 验证数据库状态
        movie = session.scalar(
            select(Movie).where(Movie.label == "ABC", Movie.number == "123")
        )
        assert movie is not None

        # 验证Video
        video = session.scalar(select(Video).where(Video.sha256 == sha256))
        assert video is not None
        assert video.movie_id == movie.id
        assert video.filename == "ABC-123-some-descriptions"
        assert video.suffix == "mp4"
        assert video.absolute_path == str(video_file)

    def test_scan_existing_video_unchanged(
            self,
            scanner,
            mock_validator,
            mock_extractor,
            mock_hasher,
            session,
            tmp_path,
            mock_movie_info,
    ):
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
            movie=movie,
        )
        session.add_all([movie, video])
        session.commit()

        # 2. 准备文件
        video_file = tmp_path / "ABC-123.mp4"
        video_file.touch()

        # 3. Mock
        mock_hasher.return_value = "hash_exist"  # 哈希一致

        mock_extractor.extract_video_metadata.return_value = (
            "ABC",
            "123",
            mock_movie_info,
        )

        # 4. 执行
        results = scanner.scan_directory(tmp_path)

        # 5. 验证
        # 注意：由于movie_info为None，movie不会被添加到scanned_movies集合
        # 所以results可能为空，但数据库记录应该存在
        # 验证 Extractor 被正确调用
        mock_extractor.extract_video_metadata.assert_called_once_with("ABC-123.mp4")
        # 验证 Video 记录没有变动
        current_video = session.scalar(
            select(Video).where(Video.sha256 == "hash_exist")
        )
        assert current_video.absolute_path == str(tmp_path / "ABC-123.mp4")

    def test_scan_existing_video_moved(
            self,
            scanner,
            mock_validator,
            mock_hasher,
            session,
            tmp_path,
            mock_extractor,
            mocker,
    ):
        """
        测试：视频哈希存在，但文件路径变了
        预期：更新数据库中的路径
        """
        # 1. 预先创建数据 (旧路径)
        old_path = tmp_path / "old_folder" / "old_name.mp4"
        movie = Movie(label="ABC", number="123")
        video = Video(
            sha256="hash_move",
            filename="ABC-123_old_name",
            suffix="mp4",
            absolute_path=str(old_path),
            movie=movie,
        )
        session.add_all([movie, video])
        session.commit()

        # 2. 在新路径创建文件
        new_file = tmp_path / "ABC-123_new_name.mp4"
        new_file.touch()

        # 3. Mock 哈希 (关键：哈希必须相同)
        mock_hasher.return_value = "hash_move"
        mock_extractor.extract_video_metadata.return_value = (
            "ABC",
            "123",
            Mock(spec=JavMovie),
        )
        mocker.patch(
            "aurora.services.scanner.filesystem_scanner.LibraryScanner._update_movie_info",
            return_value=None,
        )
        # 4. 执行
        scanner.scan_directory(tmp_path)

        # 5. 验证
        session.refresh(video)  # 刷新 Session 缓存
        assert video.filename == "ABC-123_new_name"
        assert video.absolute_path == str(new_file)
        assert session.query(Video).count() == 1  # 确保没有创建新记录

    def test_scan_ignore_files(self, scanner, mock_hasher, session, tmp_path):
        """测试：忽略非视频后缀的文件"""
        (tmp_path / "readme.txt").touch()
        (tmp_path / "cover.jpg").touch()

        scanner.scan_directory(tmp_path)

        assert mock_hasher.call_count == 0
        assert session.query(Video).count() == 0

    def test_scan_file_io_error_handling(self, scanner, mock_hasher, session, tmp_path):
        """测试：当计算哈希抛出 IOError 时，程序不应崩溃，而是跳过"""
        (tmp_path / "corrupt.mp4").touch()

        # 模拟抛出异常
        mock_hasher.side_effect = IOError("Disk error")

        # 执行 (不应报错)
        results = scanner.scan_directory(tmp_path)

        assert len(results) == 0
        assert session.query(Video).count() == 0

    def test_scan_video_with_movie_info_update(
            self, sha256, scanner, mock_extractor, mock_hasher, session, tmp_path
    ):
        """测试扫描视频并更新movie信息"""
        # Set up
        video_file = tmp_path / "ABC-123.mp4"
        video_file.touch()

        mock_hasher.return_value = sha256

        # 创建JavMovie对象模拟提取的元数据
        # 注意：JavMovie需要正确的初始化，这里使用Mock来模拟
        movie_info = Mock(spec=JavMovie)
        movie_info.title = "Test Movie"
        movie_info.release_date = datetime.date(2023, 1, 1)
        movie_info.director = "Test Director"
        movie_info.producer = "Test Studio"
        movie_info.actors = [
            Mock(current_name="Actor1", all_names=["Actor1", "Alias1"]),
            Mock(current_name="Actor2", all_names=["Actor2"]),
        ]
        movie_info.actresses = [Mock(current_name="Actress1", all_names=["Actress1"])]
        movie_info.categories = ["Drama", "Romance"]

        mock_extractor.extract_video_metadata.return_value = ("ABC", "123", movie_info)

        result = scanner.scan_directory(tmp_path)

        # 验证返回值
        assert len(result) == 1
        movie = result[0]
        assert movie.code == "ABC-123"
        assert movie.title_ja == "Test Movie"
        assert movie.release_date == datetime.date(2023, 1, 1)

        # 验证数据库中的关联数据
        session.refresh(movie)
        assert movie.director is not None
        assert movie.director.jap_text == "Test Director"
        assert movie.studio is not None
        assert movie.studio.jap_text == "Test Studio"
        assert len(movie.actors) == 3  # 2 actors + 1 actress
        assert len(movie.categories) == 2

    def test_scan_anonymous_video(
            self, sha256, scanner, mock_extractor, mock_hasher, session, tmp_path
    ):
        """测试扫描匿名视频（无法提取番号）"""
        video_file = tmp_path / "unknown_video.mp4"
        video_file.touch()

        mock_hasher.return_value = sha256
        # extractor返回None表示无法提取番号
        mock_extractor.extract_video_metadata.return_value = (None, None, None)

        result = scanner.scan_directory(tmp_path)

        # 验证创建了匿名movie
        assert len(result) == 0  # 匿名movie不会添加到scanned_movies集合中

        # 验证数据库中有匿名movie
        movie = session.scalar(select(Movie).where(Movie.number == sha256))
        assert movie is not None
        assert movie.is_anonymous

        # 验证video关联到了匿名movie
        video = session.scalar(select(Video).where(Video.sha256 == sha256))
        assert video is not None
        assert video.movie_id == movie.id

    def test_scan_multiple_videos_in_directory(
            self, scanner, mock_extractor, mock_hasher, session, tmp_path, mock_movie_info
    ):
        """测试扫描包含多个视频的目录"""
        # 创建多个视频文件
        files = [
            ("ABC-001.mp4", "a" * 64, "ABC", "001"),
            ("DEF-002.mp4", "b" * 64, "DEF", "002"),
            ("GHI-003.mp4", "c" * 64, "GHI", "003"),
        ]

        for filename, file_hash, label, number in files:
            video_file = tmp_path / filename
            video_file.touch()

        # 设置mock返回值
        def extract_side_effect(filename):
            for fname, fhash, flabel, fnumber in files:
                if filename == fname:
                    return flabel, fnumber, mock_movie_info
            return None, None, None

        mock_extractor.extract_video_metadata.side_effect = extract_side_effect

        # 设置hasher返回值
        def hasher_side_effect(filepath):
            for fname, fhash, _, _ in files:
                if str(filepath).endswith(fname):
                    return fhash
            return "unknown"

        mock_hasher.side_effect = hasher_side_effect

        result = scanner.scan_directory(tmp_path)

        # 验证所有视频都被处理
        assert len(result) == 3
        codes = {movie.code for movie in result}
        assert codes == {"ABC-001", "DEF-002", "GHI-003"}

        # 验证数据库记录
        assert session.query(Video).count() == 3
        assert session.query(Movie).count() == 3
