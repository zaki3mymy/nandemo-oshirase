"""Tests for split_into_batches function."""

from nandemo_oshirase.lambda_function import split_into_batches


class TestSplitIntoBatches:
    """Test splitting messages into batches."""

    def test_split_into_batches_under_limit(self):
        messages = [{"type": "text", "text": f"msg{i}"} for i in range(3)]
        result = split_into_batches(messages)
        assert result == [messages]

    def test_split_into_batches_exactly_five(self):
        messages = [{"type": "text", "text": f"msg{i}"} for i in range(5)]
        result = split_into_batches(messages)
        assert result == [messages]

    def test_split_into_batches_six_messages(self):
        messages = [{"type": "text", "text": f"msg{i}"} for i in range(6)]
        result = split_into_batches(messages)
        assert len(result) == 2
        assert len(result[0]) == 5
        assert len(result[1]) == 1

    def test_split_into_batches_ten_messages(self):
        messages = [{"type": "text", "text": f"msg{i}"} for i in range(10)]
        result = split_into_batches(messages)
        assert len(result) == 2
        assert len(result[0]) == 5
        assert len(result[1]) == 5

    def test_split_into_batches_eleven_messages(self):
        messages = [{"type": "text", "text": f"msg{i}"} for i in range(11)]
        result = split_into_batches(messages)
        assert len(result) == 3
        assert len(result[0]) == 5
        assert len(result[1]) == 5
        assert len(result[2]) == 1

    def test_split_into_batches_empty(self):
        messages = []
        result = split_into_batches(messages)
        assert result == []

    def test_split_into_batches_custom_size(self):
        messages = [{"type": "text", "text": f"msg{i}"} for i in range(7)]
        result = split_into_batches(messages, batch_size=3)
        assert len(result) == 3
        assert len(result[0]) == 3
        assert len(result[1]) == 3
        assert len(result[2]) == 1
