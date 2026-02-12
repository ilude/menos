"""Tests for pipeline job retention/purge."""

from unittest.mock import MagicMock

import pytest

from menos.services.jobs import JobRepository


class TestPurgeExpiredJobs:
    @pytest.fixture
    def job_repo(self):
        db = MagicMock()
        return JobRepository(db), db

    @pytest.mark.asyncio
    async def test_purge_returns_counts(self, job_repo):
        repo, db = job_repo
        db.query.side_effect = [
            [{"result": [{"id": "1"}, {"id": "2"}, {"id": "3"}]}],  # compact
            [{"result": [{"id": "4"}]}],  # full
        ]
        counts = await repo.purge_expired_jobs()
        assert counts == {"compact": 3, "full": 1}

    @pytest.mark.asyncio
    async def test_purge_correct_queries(self, job_repo):
        repo, db = job_repo
        db.query.return_value = [{"result": []}]
        await repo.purge_expired_jobs()

        calls = db.query.call_args_list
        assert len(calls) == 2
        assert "data_tier = 'compact'" in calls[0][0][0]
        assert "180d" in calls[0][0][0]
        assert "data_tier = 'full'" in calls[1][0][0]
        assert "60d" in calls[1][0][0]

    @pytest.mark.asyncio
    async def test_purge_empty_table(self, job_repo):
        repo, db = job_repo
        db.query.return_value = [{"result": []}]
        counts = await repo.purge_expired_jobs()
        assert counts == {"compact": 0, "full": 0}

    @pytest.mark.asyncio
    async def test_purge_requires_finished_at(self, job_repo):
        repo, db = job_repo
        db.query.return_value = [{"result": []}]
        await repo.purge_expired_jobs()

        for call in db.query.call_args_list:
            assert "finished_at != NONE" in call[0][0]

    @pytest.mark.asyncio
    async def test_purge_uses_return_before(self, job_repo):
        repo, db = job_repo
        db.query.return_value = [{"result": []}]
        await repo.purge_expired_jobs()

        for call in db.query.call_args_list:
            assert "RETURN BEFORE" in call[0][0]
