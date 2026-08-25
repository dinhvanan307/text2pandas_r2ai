# Generated artifacts

Output của build/evaluation/submission được ghi dưới đây và mặc định không commit:

```text
runs/{a6,retrieval,answering,evaluation}/<run_id>/
reports/
submissions/
packages/
handoffs/
legacy/
```

Artifact phải truy ngược được raw snapshot, A6 build, retrieval index, config và
source commit thông qua manifest. Git chỉ giữ manifest/checksum nhỏ khi cần audit.
