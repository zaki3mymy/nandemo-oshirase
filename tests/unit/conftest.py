import pytest

from nandemo_oshirase import lambda_function


@pytest.fixture(autouse=True)
def _clear_sent_batches_cache():
    """同じメッセージを送るテストが、前のテストの送信済みキャッシュでスキップされないようにする。"""
    lambda_function.clear_sent_batches_cache()
    yield
    lambda_function.clear_sent_batches_cache()
