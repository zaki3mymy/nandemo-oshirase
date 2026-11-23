from hypothesis import HealthCheck, settings

# mutmut は同じプロセスで pytest を何度も実行するので、differing_executors に引っかかる。
# mutmut からは --hypothesis-profile=mutmut を渡してこのプロファイルを使う（pyproject.toml 参照）
settings.register_profile(
    "mutmut",
    suppress_health_check=[HealthCheck.differing_executors],
    deadline=None,
    database=None,
)
