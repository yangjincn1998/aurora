from orms.models import Video


def test_create_video(session):
    video = Video(
        sha256="dummy_sha256",
        filename="example_video",
        absolute_path="/path/to/example_video.mp4",
        suffix=".mp4",
    )

    session.add(video)
    session.commit()

    saved = session.query(Video).first()
