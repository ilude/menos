"""Unit tests for ingest_videos script."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from menos.services.youtube import TranscriptSegment, YouTubeTranscript
from scripts.ingest_videos import extract_url, fetch_transcript, load_secrets_file


class TestLoadSecretsFile:
    """Tests for load_secrets_file."""

    def test_loads_key_value_pairs(self, tmp_path, monkeypatch):
        """Test loading simple KEY=VALUE pairs."""
        secrets_dir = tmp_path / ".dotfiles"
        secrets_dir.mkdir()
        secrets_file = secrets_dir / ".secrets"
        secrets_file.write_text("FOO=bar\nBAZ=qux\n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("FOO", raising=False)
        monkeypatch.delenv("BAZ", raising=False)

        load_secrets_file()

        import os
        assert os.environ.get("FOO") == "bar"
        assert os.environ.get("BAZ") == "qux"
        monkeypatch.delenv("FOO", raising=False)
        monkeypatch.delenv("BAZ", raising=False)

    def test_skips_comments_and_blank_lines(self, tmp_path, monkeypatch):
        """Test that comments and blank lines are ignored."""
        secrets_dir = tmp_path / ".dotfiles"
        secrets_dir.mkdir()
        secrets_file = secrets_dir / ".secrets"
        secrets_file.write_text("# comment\n\nVALID_KEY=value\n  \n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("VALID_KEY", raising=False)

        load_secrets_file()

        import os
        assert os.environ.get("VALID_KEY") == "value"
        monkeypatch.delenv("VALID_KEY", raising=False)

    def test_handles_export_prefix(self, tmp_path, monkeypatch):
        """Test that 'export ' prefix is handled."""
        secrets_dir = tmp_path / ".dotfiles"
        secrets_dir.mkdir()
        secrets_file = secrets_dir / ".secrets"
        secrets_file.write_text("export MY_VAR=exported_value\n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("MY_VAR", raising=False)

        load_secrets_file()

        import os
        assert os.environ.get("MY_VAR") == "exported_value"
        monkeypatch.delenv("MY_VAR", raising=False)

    def test_strips_quotes(self, tmp_path, monkeypatch):
        """Test that single and double quotes are stripped from values."""
        secrets_dir = tmp_path / ".dotfiles"
        secrets_dir.mkdir()
        secrets_file = secrets_dir / ".secrets"
        secrets_file.write_text(
            "SINGLE='single_val'\nDOUBLE=\"double_val\"\n"
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("SINGLE", raising=False)
        monkeypatch.delenv("DOUBLE", raising=False)

        load_secrets_file()

        import os
        assert os.environ.get("SINGLE") == "single_val"
        assert os.environ.get("DOUBLE") == "double_val"
        monkeypatch.delenv("SINGLE", raising=False)
        monkeypatch.delenv("DOUBLE", raising=False)

    def test_does_not_overwrite_existing_env_vars(
        self, tmp_path, monkeypatch
    ):
        """Test that existing env vars are not overwritten."""
        secrets_dir = tmp_path / ".dotfiles"
        secrets_dir.mkdir()
        secrets_file = secrets_dir / ".secrets"
        secrets_file.write_text("EXISTING_VAR=new_value\n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("EXISTING_VAR", "original_value")

        load_secrets_file()

        import os
        assert os.environ.get("EXISTING_VAR") == "original_value"

    def test_handles_missing_file(self, tmp_path, monkeypatch):
        """Test that missing secrets file does not raise an error."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        load_secrets_file()


class TestExtractUrl:
    """Tests for extract_url."""

    def test_extracts_standard_youtube_url(self):
        """Test extracting a standard YouTube watch URL."""
        line = "https://www.youtube.com/watch?v=abc123def45"
        assert extract_url(line) == line

    def test_short_url_returns_none(self):
        """youtu.be does not contain 'youtube' so the regex won't match."""
        line = "https://youtu.be/abc123def45"
        assert extract_url(line) is None

    def test_extracts_url_with_surrounding_text(self):
        """Test extracting URL from text with surrounding content."""
        line = "Check out https://www.youtube.com/watch?v=abc text"
        assert (
            extract_url(line)
            == "https://www.youtube.com/watch?v=abc"
        )

    def test_returns_none_for_no_url(self):
        """Test that a line with no URL returns None."""
        assert extract_url("just some text") is None

    def test_returns_none_for_non_youtube_url(self):
        """Test that non-YouTube URLs return None."""
        assert extract_url("https://example.com/video") is None


class TestGetTranscriptApi:
    """Tests for get_transcript_api."""

    @patch("scripts.ingest_videos.WebshareProxyConfig")
    @patch("scripts.ingest_videos.YouTubeTranscriptApi")
    def test_creates_proxy_api_with_credentials(
        self, mock_api_cls, mock_proxy_cls, monkeypatch
    ):
        """Test that proxy config is used when credentials are set."""
        monkeypatch.setenv("WEBSHARE_PROXY_USERNAME", "user")
        monkeypatch.setenv("WEBSHARE_PROXY_PASSWORD", "pass")
        mock_proxy = MagicMock()
        mock_proxy_cls.return_value = mock_proxy

        from scripts.ingest_videos import get_transcript_api
        get_transcript_api()

        mock_proxy_cls.assert_called_once_with(
            proxy_username="user",
            proxy_password="pass",
        )
        mock_api_cls.assert_called_once_with(proxy_config=mock_proxy)

    @patch("scripts.ingest_videos.YouTubeTranscriptApi")
    def test_creates_direct_api_without_credentials(
        self, mock_api_cls, monkeypatch
    ):
        """Test that no proxy is used when credentials are absent."""
        monkeypatch.delenv("WEBSHARE_PROXY_USERNAME", raising=False)
        monkeypatch.delenv("WEBSHARE_PROXY_PASSWORD", raising=False)

        from scripts.ingest_videos import get_transcript_api
        get_transcript_api()

        mock_api_cls.assert_called_once_with()

    @patch("scripts.ingest_videos.YouTubeTranscriptApi")
    def test_creates_direct_api_with_partial_credentials(
        self, mock_api_cls, monkeypatch
    ):
        """Test that partial credentials fall back to direct API."""
        monkeypatch.setenv("WEBSHARE_PROXY_USERNAME", "user")
        monkeypatch.delenv("WEBSHARE_PROXY_PASSWORD", raising=False)

        from scripts.ingest_videos import get_transcript_api
        get_transcript_api()

        mock_api_cls.assert_called_once_with()


class TestFetchTranscript:
    """Tests for fetch_transcript."""

    def test_maps_api_entries_to_segments(self):
        """Test that API entries are mapped to TranscriptSegment objects."""
        mock_api = MagicMock()
        entry1 = MagicMock(text="Hello", start=0.0, duration=1.5)
        entry2 = MagicMock(text="World", start=1.5, duration=2.0)
        mock_api.fetch.return_value = [entry1, entry2]

        result = fetch_transcript(mock_api, "vid123")

        assert len(result.segments) == 2
        assert result.segments[0].text == "Hello"
        assert result.segments[0].start == 0.0
        assert result.segments[0].duration == 1.5
        assert result.segments[1].text == "World"
        assert result.segments[1].start == 1.5
        assert result.segments[1].duration == 2.0
        mock_api.fetch.assert_called_once_with(
            "vid123", languages=("en",)
        )

    def test_sets_language_to_english(self):
        """Test that language is set to 'en'."""
        mock_api = MagicMock()
        mock_api.fetch.return_value = []

        result = fetch_transcript(mock_api, "vid123")

        assert result.language == "en"

    def test_sets_video_id(self):
        """Test that video_id is set correctly."""
        mock_api = MagicMock()
        mock_api.fetch.return_value = []

        result = fetch_transcript(mock_api, "my_video_id")

        assert result.video_id == "my_video_id"


class TestMain:
    """Tests for main function."""

    def _build_transcript(self, video_id: str) -> YouTubeTranscript:
        """Build a simple transcript for testing."""
        return YouTubeTranscript(
            video_id=video_id,
            segments=[
                TranscriptSegment(
                    text="hello world", start=0.0, duration=1.0
                )
            ],
            language="en",
        )

    @patch("scripts.ingest_videos.fetch_transcript")
    @patch("scripts.ingest_videos.httpx.Client")
    @patch("scripts.ingest_videos.Path")
    @patch("scripts.ingest_videos.YouTubeService")
    @patch("scripts.ingest_videos.get_transcript_api")
    @patch("scripts.ingest_videos.RequestSigner.from_file")
    @patch("scripts.ingest_videos.load_secrets_file")
    def test_reads_videos_file_and_ingests(
        self,
        mock_load_secrets,
        mock_signer_from_file,
        mock_get_api,
        mock_yt_service_cls,
        mock_path_cls,
        mock_httpx_client_cls,
        mock_fetch_transcript,
    ):
        """Test happy path: reads file, fetches transcript, uploads."""
        mock_signer = MagicMock()
        mock_signer.sign_request.return_value = {
            "signature-input": "sig1=test",
            "signature": "sig1=:abc:",
        }
        mock_signer_from_file.return_value = mock_signer

        mock_yt_service = MagicMock()
        mock_yt_service.extract_video_id.return_value = "vid123"
        mock_yt_service_cls.return_value = mock_yt_service

        video_url = "https://www.youtube.com/watch?v=vid123"
        mock_videos_file = MagicMock()
        mock_videos_file.read_text.return_value = video_url
        # Path(__file__).parent.parent.parent / "data" / "youtube-videos.txt"
        mock_path_instance = MagicMock()
        mock_path_instance.parent.parent.parent.__truediv__.return_value = (
            MagicMock(__truediv__=MagicMock(return_value=mock_videos_file))
        )
        mock_path_cls.return_value = mock_path_instance

        transcript = self._build_transcript("vid123")
        mock_fetch_transcript.return_value = transcript

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "video_id": "vid123",
            "chunks_created": 5,
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_httpx_client_cls.return_value = mock_client

        from scripts.ingest_videos import main
        main()

        mock_load_secrets.assert_called_once()
        mock_client.post.assert_called_once()
        post_call = mock_client.post.call_args
        assert post_call[0][0] == "/api/v1/youtube/upload"

    @patch("scripts.ingest_videos.fetch_transcript")
    @patch("scripts.ingest_videos.httpx.Client")
    @patch("scripts.ingest_videos.Path")
    @patch("scripts.ingest_videos.YouTubeService")
    @patch("scripts.ingest_videos.get_transcript_api")
    @patch("scripts.ingest_videos.RequestSigner.from_file")
    @patch("scripts.ingest_videos.load_secrets_file")
    def test_handles_transcript_fetch_failure(
        self,
        mock_load_secrets,
        mock_signer_from_file,
        mock_get_api,
        mock_yt_service_cls,
        mock_path_cls,
        mock_httpx_client_cls,
        mock_fetch_transcript,
    ):
        """Test that transcript fetch failure is caught and continues."""
        mock_signer = MagicMock()
        mock_signer_from_file.return_value = mock_signer

        mock_yt_service = MagicMock()
        mock_yt_service.extract_video_id.return_value = "vid_fail"
        mock_yt_service_cls.return_value = mock_yt_service

        video_url = "https://www.youtube.com/watch?v=vid_fail"
        mock_videos_file = MagicMock()
        mock_videos_file.read_text.return_value = video_url
        mock_path_instance = MagicMock()
        mock_path_instance.parent.parent.parent.__truediv__.return_value = (
            MagicMock(__truediv__=MagicMock(return_value=mock_videos_file))
        )
        mock_path_cls.return_value = mock_path_instance

        mock_fetch_transcript.side_effect = Exception("Network error")

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_httpx_client_cls.return_value = mock_client

        from scripts.ingest_videos import main
        main()

        mock_client.post.assert_not_called()

    @patch("scripts.ingest_videos.fetch_transcript")
    @patch("scripts.ingest_videos.httpx.Client")
    @patch("scripts.ingest_videos.Path")
    @patch("scripts.ingest_videos.YouTubeService")
    @patch("scripts.ingest_videos.get_transcript_api")
    @patch("scripts.ingest_videos.RequestSigner.from_file")
    @patch("scripts.ingest_videos.load_secrets_file")
    def test_handles_api_upload_failure(
        self,
        mock_load_secrets,
        mock_signer_from_file,
        mock_get_api,
        mock_yt_service_cls,
        mock_path_cls,
        mock_httpx_client_cls,
        mock_fetch_transcript,
        capsys,
    ):
        """Test that non-200 API response is handled gracefully."""
        mock_signer = MagicMock()
        mock_signer.sign_request.return_value = {
            "signature-input": "sig1=test",
            "signature": "sig1=:abc:",
        }
        mock_signer_from_file.return_value = mock_signer

        mock_yt_service = MagicMock()
        mock_yt_service.extract_video_id.return_value = "vid_err"
        mock_yt_service_cls.return_value = mock_yt_service

        video_url = "https://www.youtube.com/watch?v=vid_err"
        mock_videos_file = MagicMock()
        mock_videos_file.read_text.return_value = video_url
        mock_path_instance = MagicMock()
        mock_path_instance.parent.parent.parent.__truediv__.return_value = (
            MagicMock(__truediv__=MagicMock(return_value=mock_videos_file))
        )
        mock_path_cls.return_value = mock_path_instance

        transcript = self._build_transcript("vid_err")
        mock_fetch_transcript.return_value = transcript

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_httpx_client_cls.return_value = mock_client

        from scripts.ingest_videos import main
        main()

        captured = capsys.readouterr()
        assert "ERROR 500" in captured.out
