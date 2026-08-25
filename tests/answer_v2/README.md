# Answer v2 contract tests

`test_reranker_v2.py` là contract hiện hành: stable candidate ID, JSON schema,
whitelist và abstain. `legacy_reranker_v1.py` được giữ làm historical regression
record nhưng không chạy, vì contract index-based v1 mâu thuẫn trực tiếp với v2
và không còn được production chấp nhận.

`test_zz_pytest_wrapper.py` bridge các custom `@ca` cases sang pytest và chỉ
discover file mang prefix `test_`.
