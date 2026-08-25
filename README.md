# Text2Pandas

Pipeline trả lời câu hỏi tiếng Việt trên báo cáo tài chính bằng retrieval,
Pandas execution và evidence có thể kiểm chứng. Repository này dùng một data
lineage rõ ràng, không trộn dữ liệu nguồn với output sinh ra:

```text
data/raw/btc
    │  BTC source: 1.973 báo cáo, 1.012 câu hỏi, 100 mã cổ phiếu
    ▼
data/processed/a6/<build_id>
    │  normalized tables, observations, metadata
    ▼
data/indexes/retrieval/<a6_build_id>/<index_id>
    │  index chỉ hợp lệ với đúng A6 build
    ▼
answering → validation → artifacts/submissions
```

## Quick start

Yêu cầu Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

make paths-check
text2pandas verify all
make test-offline
```

`test-offline` là CI gate, không yêu cầu materialized dataset. `test-integration`
chạy các gate cần raw/A6/retrieval/submission artifacts và fail rõ đường dẫn còn
thiếu; không chuyển prerequisite thiếu thành false-green skip.

## Active snapshots

Source of truth là `configs/datasets/active_snapshot.yaml`:

| Layer | Identity hiện tại | Canonical location |
|---|---|---|
| Raw BTC | `ca033190f2e9e99f` | `data/raw/btc/` |
| A6 processed | `b3e9684004679ffb` | `data/processed/a6/b3e9684004679ffb/` |
| Retrieval | `286973b134a189ee` | `data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/` |

Kiểm từng layer:

```bash
text2pandas verify raw
text2pandas verify a6
text2pandas verify retrieval
```

Verifier kiểm config, manifest, count, A6 `build_meta`, kích thước retrieval DB và
các SQLite index bắt buộc. Kiểm integrity raw sâu hơn bằng:

```bash
python tools/data_acquisition/download_vifinqa.py --verify-only --skip-github
```

Payload lớn không nằm trong Git. Git chỉ giữ code, config, documentation, curated
fixture nhỏ, manifest và provenance. Có thể mount data/artifact ở volume khác qua
`T2P_DATA_ROOT` và `T2P_ARTIFACT_ROOT`.

## Project layout

```text
configs/       active snapshots, pipeline config, policies
src/text2pandas/
  domain/      pure domain rules and value objects
  application/ use cases
  pipelines/   a6, retrieval, answering
  infrastructure/ filesystem, SQLite, parsing, indexing
  interface/   unified CLI
tests/         unit, contract, regression, materialized integration
data/          raw, processed A6, retrieval indexes, curated inputs
artifacts/     generated runs, reports, submissions, handoffs
experiments/   ablation and re-audit; never imported by production
provenance/    committed identities, seals and baseline checksums
ops/           Docker and environment evidence
vendor/        locally materialized upstream reference code
tools/         migration, audit and legacy thin commands
docs/          competition source, ADRs and refactor records
```

Public runtime namespace là `text2pandas`. `data_pipeline`, `retrieval` và
`text2pandas.answer_pipeline` hiện chỉ là compatibility shims trong một migration
window; code mới không được import các namespace này.

## Commands

```bash
text2pandas --help
make help
make lint
make test-offline
make test-integration
make materialize-h0
make snapshots-verify
```

Canonical answering run bắt buộc có immutable `run-id` và tự ghi manifest
lineage vào `artifacts/runs/answer/<run-id>/manifest.json`:

```bash
text2pandas run --run-id local-smoke-001 --offset 0 --limit 10 --no-package
text2pandas run --run-id submission-candidate-001
```

Full run chỉ publish ZIP sang `artifacts/submissions/` khi strict validator và
replay cùng pass; output fail vẫn nằm trong run stage kèm
`submission_manifest.json` để điều tra.

Các target `dp-*` trong `Makefile` là delivery contract hiện hữu của A6 build,
measurement, deterministic rebuild và release packaging; chúng được giữ nguyên
để không đổi behavior trong folder refactor.

## Engineering rules

- Đọc `CLAUDE.md` trước khi thay đổi model/data/rules của cuộc thi.
- Raw BTC là immutable input; không ghi output vào `data/raw/btc`.
- A6 là processed snapshot có `build_id`; không chọn ngầm thư mục `latest`.
- Retrieval manifest phải trỏ đúng active A6 build.
- Production không import từ `tools/` hoặc `experiments/`.
- Generated DB, Parquet, ZIP và run output không commit vào Git.
- `submission.answer` phải bằng kết quả chạy thật của `pandas_query` trên evidence
  đóng trong chính ZIP.

Các H0 integration artifacts nhỏ không phải source input. Khi đã materialize
legacy A6 records/submissions, tái tạo chúng bằng `make materialize-h0`; chỉ dùng
`FORCE=1` khi chủ động refresh cùng output.

## Documentation

- `docs/REFACTOR_PLAN.md`: baseline, target architecture và migration gates.
- `docs/REFACTOR_STATUS.md`: phần đã triển khai và compatibility debt còn lại.
- `docs/adr/`: quyết định data layout, namespace và artifact retention.
- `data/README.md`: ownership/lifecycle của từng data class.
- `docs/competition/Text2Pandas.docx`: đề bài gốc.
