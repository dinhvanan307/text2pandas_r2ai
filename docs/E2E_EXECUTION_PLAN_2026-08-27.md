# PROJECT_NEW — E2E Execution Plan

**Ngày:** 2026-08-27 · **Trạng thái:** PLAN ONLY — chưa sửa code, chưa chạy lệnh
**NEW** = `text2pandas/` · **OLD** = `Text2Pandas-1/` (chỉ dùng làm reference)

---

## 1. EXECUTIVE SUMMARY

### 1.1 Phát hiện quyết định cả kế hoạch

> **Lineage active của NEW — A6 `c6887fb633374fad` — KHÔNG TỒN TẠI Ở BẤT KỲ ĐÂU.**
> Không copy được. **Bắt buộc rebuild.**

Bằng chứng (FACT):

| | |
|---|---|
| `NEW/data/` | **32 file, 0 byte payload** — chỉ `README.md` + `manifest.json`. Glob `data/**/*` xác nhận: không `.db`, không `.txt`, không `.parquet` |
| Grep `c6887fb633374fad` trên toàn OLD | Khớp **1 file duy nhất**, và đó là tài liệu audit: `OLD/docs/181_INDEPENDENT_AUDIT…md:443` ghi *"Chỉ làm baseline lịch sử"*; `:545` liệt kê chính ID này trong mục **"chưa được cung cấp"** |
| Lý do | `folder_migration_20260825.json` ghi ngày **25/08**, chỉ ánh xạ tới `b3e9684004679ffb`. A6 `c6887` được tạo **26/08** (`manifest.json` `created_at: 2026-08-26T16:55:52Z`) — **sau** migration, **bên trong NEW** |

### 1.2 Tin tốt — ba điều làm kế hoạch khả thi

1. **Corpus gốc CÓ trong OLD, đã kiểm chứng trực tiếp.** `OLD/data/external/vifinqa/financial_statements/AAA/` chứa đúng 22 file `.txt` (2015–2025 × consolidated/separate), đúng cấu trúc `*/*/*/*.txt` mà `configs/corpus.yaml:4-9` yêu cầu.
2. **`build_id` là hàm thuần, không phụ thuộc máy.** `pipelines/a6/storage.py:85-96` — `sha256` của `{source_hash, config_hash, component_versions, counts, schema_version}`. **Không timestamp, không hostname, không absolute path, không random seed.** `ACCEPTANCE_TEST_REPORT_2026-08-27.md:45` ghi hai clean build cùng ra `c6887fb633374fad`, **byte-identical**.
3. **`index_id` là hằng số tuyệt đối.** `infrastructure/retrieval/snapshot.py:43-50` — `retrieval_index_id()` băm 2 hằng số (`INDEX_SPECS` + version), **không đụng dữ liệu**. `872ccb0dda9a2bb6` sẽ luôn tái tạo được. Rủi ro = 0.

### 1.3 Đòn bẩy lớn nhất: một phép kiểm 1 giây thay cho canh bạc 10 phút + 11 GB

Vì `build_id` chỉ phụ thuộc **nội dung 25 file `a6/*.py` + 11 file `configs/*.yaml`**, ta **dự đoán được kết quả build trước khi build**:

```python
from text2pandas.pipelines.a6.storage import source_fingerprint
print(source_fingerprint())
# PHẢI ra: {'source_hash': '0719b86ff68679a3', 'config_hash': 'd4ff2b5cbc589d6c'}
```

Khớp ⇒ rebuild gần như chắc chắn ra `c6887fb633374fad`. Lệch ⇒ **build_id sẽ khác**, và toàn bộ chiến lược lineage phải quyết định lại **trước khi** tiêu 10 phút CPU và 11 GB đĩa. Đây là **GATE 1a**, phép kiểm rẻ nhất và có giá trị nhất trong kế hoạch này.

### 1.4 Đường tới E2E — 5 chặng

```
[CÓ SẴN]  configs · code · manifest · gold nhỏ
    ↓  copy từ OLD (~363 MiB)
[P0-1]    data/raw/btc/  (1973 txt · 1012 câu · 100 ticker)
    ↓  make dp-build + dp-release  (~10 phút, 6,5 GiB)
[P0-2]    data/processed/a6/c6887fb633374fad/silver.db  (4.140.924.928 B)
    ↓  tools/build_retrieval_snapshot.py  (copy + 4 index, 3,95 GiB)
[P0-3]    data/indexes/retrieval/c6887fb633374fad/872ccb0dda9a2bb6/retrieval.db
    ↓  text2pandas run
[E2E]     artifacts/submissions/submission_<run_id>.zip
```

### 1.5 Ba giới hạn phải nói trước

| # | Giới hạn | Hệ quả |
|---|---|---|
| 1 | **Sandbox Linux wedged** (`no space left on device`, 5 lần liên tiếp) | Reviewer **không chạy được lệnh nào**. Mọi command dưới đây **truy ngược từ source code**, chưa chạy thử. Đánh dấu `UNVERIFIED-BY-EXECUTION` |
| 2 | **`make snapshots-verify` KHÔNG hash payload** | `snapshots.py:132-137` nói thẳng: *"deliberately avoids hashing multi-gigabyte databases"*. Phép kiểm nội dung duy nhất là **so kích thước byte** của `retrieval.db`. ⇒ Gate xanh **không** chứng minh payload đúng bit. Phải tự `sha256sum` |
| 3 | **Official accuracy vẫn `NOT_MEASURED` sau khi E2E PASS** | Không có gold của BTC. E2E PASS chỉ chứng minh *hệ thống chạy đúng hợp đồng*, không chứng minh *đáp án đúng* |

---

## 2. PROJECT_NEW — ARCHITECTURE UNDERSTANDING

### 2.1 Entry points (FACT — không lấy từ README, lấy từ dispatch table `main.py:885-889`)

Có **ba** CLI độc lập, không phải một:

| # | Entry point | Vai trò | Ghi ra đâu |
|---|---|---|---|
| **A** | `python -m text2pandas.interface.cli.main <cmd>` | **Runtime** — 11 lệnh | `artifacts/` (không bao giờ `data/`) |
| **B** | `python -m text2pandas.pipelines.a6.cli <cmd>` (`prog="data_pipeline"`) | **Data build** — 6 stage | `data/processed/a6/` |
| **C** | `python tools/build_retrieval_snapshot.py` | **Index build** | `data/indexes/retrieval/` |

> ⚠️ **Đây là điểm dễ hiểu sai nhất của repo.** Entry point A có lệnh tên `silver`, nhưng nó **KHÔNG** build `silver.db` mà `run` đọc. Xem §2.4.

### 2.2 11 lệnh của entry point A

| Lệnh | Handler | Flag bắt buộc | Đọc | Ghi |
|---|---|---|---|---|
| `catalog` | `main.py:66` | `--run-id` | `data/raw/btc/financial_statements` | `artifacts/runs/legacy-build/<id>/catalog.sqlite` |
| `parse-check` | `:97` | `--catalog-db` | catalog tuỳ ý | stdout |
| `index` | `:160` | `--run-id` | catalog.sqlite | `…/table_index.sqlite` |
| **`run`** | **`:176`** | `--run-id` | **silver.db + retrieval.db (từ active snapshot)** | `artifacts/runs/answer/<id>/` |
| `package` | `:315` | `--run-id` | `…/answer/<id>/records.jsonl` | `…/package-<v>-<b>.zip` |
| `silver` | `:520` | `--run-id` | catalog.sqlite | `…/legacy-build/<id>/silver.sqlite` ⚠️ |
| `cards` | `:552` | `--run-id` | silver.sqlite | `…/card_index.sqlite` |
| `verify` | `:570` | (positional `all\|raw\|a6\|retrieval`, default `all`) | manifest + DB schema | stdout |
| `coverage` | `:581` | — | `data/curated/evaluation/legacy/question_plans_1012.jsonl` ✅ **có sẵn** | stdout hoặc `--output` |
| `shadow-v3` | `:612` | `--run-id` | **chỉ silver.db** (không retrieval) | `artifacts/runs/semantic-v3/<id>/` |
| `package-v3` | `:413` | `--run-id` | `…/semantic-v3/<id>/records.jsonl` + `table_cards.csv` | `…/package-<v>-<b>.zip` ⚠️ **không publish** |

### 2.3 Hằng số chạy khi IMPORT — `main.py:26-36` (FACT)

```
PROJECT_PATHS    = ProjectPaths.discover()        # data_root=<repo>/data, artifact_root=<repo>/artifacts
ACTIVE_SNAPSHOTS = ActiveSnapshots.load()         # ← ĐỌC configs/datasets/active_snapshot.yaml NGAY LÚC IMPORT
CORPUS           = <repo>/data/raw/btc/financial_statements
QUESTIONS        = <repo>/data/raw/btc/questions/questions.jsonl
SUBMIT_DIR       = <repo>/artifacts/submissions
SCRATCH          = $TEXT2PANDAS_SCRATCH  hoặc  /tmp/text2pandas_work
```

⚠️ **Bẫy 1:** `ActiveSnapshots.load()` ở dòng 28 chạy lúc import. `ProjectPathError` **không được bắt** (`main.py:892` chỉ bắt `BuildSafetyError`) ⇒ nếu `active_snapshot.yaml` hỏng, **mọi lệnh chết, kể cả `--help`**.

⚠️ **Bẫy 2:** `-v/--verbose` khai ở parser **cha** (`main.py:816`) ⇒ phải viết **trước** subcommand. `main -v run …` đúng; `main run -v` = lỗi argparse.

### 2.4 Bốn lệnh legacy-build KHÔNG nằm trên đường E2E — bằng chứng

| # | Bằng chứng | File:line |
|---|---|---|
| 1 | **Tên file khác nhau**: `cmd_silver` ghi `silver.**sqlite**`, `cmd_run` đọc `silver.**db**` | `main.py:525` vs `:209` |
| 2 | **Thư mục khác nhau và bị chặn cứng**: `_legacy_output` hardcode `pipeline="legacy-build"`; `assert_not_active_snapshot` **raise** nếu đích rơi vào `data/processed/a6/…` | `main.py:50`; `builds.py:33-42` |
| 3 | **`run_canonical_pipeline` chỉ mở 2 DB**, không đọc `catalog.sqlite`/`table_index.sqlite`/`silver.sqlite`/`card_index.sqlite` | `canonical_run.py:519-562` |

⇒ **`catalog`/`index`/`silver`/`cards` là một nhánh dữ liệu song song mồ côi.** Kế hoạch này **không dùng chúng** cho E2E.

### 2.5 Full execution graph (đã reconstruct từ code)

```
                    ┌─── configs/corpus.yaml (glob */*/*/*.txt)
                    │
data/raw/btc/ ──────┤
  financial_statements/  1973 .txt · 100 ticker
  questions/questions.jsonl  1012 dòng
  metadata/companies.csv
                    │
                    ▼   [ENTRY B] pipelines/a6/cli.py
        snapshot → catalog → silver → quality → publish → release
                    │        └─ storage.py:287-290 đóng dấu build_id
                    ▼
data/processed/a6/c6887fb633374fad/
  silver.db                 4.140.924.928 B  sha fa6c46d6…
  dataframe/csv/table_cards.csv     ← package-v3 cần
  metadata/{documents,pages,tables}
  manifest.json             16.586 file · 6.955.080.658 B
                    │
                    ▼   [ENTRY C] tools/build_retrieval_snapshot.py
        copy2 silver.db → retrieval.db  +  4 CREATE INDEX  +  ANALYZE
                    │        (staging → atomic rename)
                    ▼
data/indexes/retrieval/c6887fb633374fad/872ccb0dda9a2bb6/
  retrieval.db              4.239.663.104 B  sha 72d307f8…
  manifest.json
                    │
    ┌───────────────┴───────────────┐
    ▼ [ENTRY A] run                 ▼ [ENTRY A] shadow-v3
 preflight: verify all           preflight: verify a6 only
 S1 hard filter                  SemanticParser → AST
 S2 BM25 + structural            operand planning
 S3 IdentityReranker             SqliteOperandRetriever(top_k=20)
 6 answering engine              JointBinder (beam 64)
   formula/count/entity_*        typed Decimal executor
    │                             │
    ▼                             ▼
 artifacts/runs/answer/<id>/   artifacts/runs/semantic-v3/<id>/
   records.jsonl · data/*.csv    records.jsonl · data/*.csv
   manifest.json                 manifest.json
    │                             │
    ▼ build_submission            ▼ package-v3
 ZIP → validate_zip → replay_zip
    │
    ├─ package_ok=True  → artifacts/submissions/submission_<id>.zip   exit 0
    └─ package_ok=False → "CHẶN PUBLISH" stderr, KHÔNG copy          exit 1
```

### 2.6 Điều kiện publish ZIP (FACT — `main.py:284-296`)

```python
package_ok = val.ok                              # 0 validator error
         and stat["error"] == 0                  # 0 replay error
         and stat["matched"] == stat["executed"] # mọi query replay khớp
```

**Đây chính là định nghĩa "E2E PASS" của repo, được cưỡng chế bằng code.** Không cần tự nghĩ ra tiêu chí.

### 2.7 Bất biến immutability (FACT)

| Cơ chế | File:line | Hệ quả |
|---|---|---|
| `mkdir(exist_ok=False)` cho run dir | `canonical_run.py:534` | `run_id` **không tái sử dụng được** — chạy lại phải đổi ID |
| `open("x")` cho `records.jsonl` | `main.py` shadow-v3 | như trên |
| `zipfile.ZipFile(…, "x")` | `submission.py:116` | không ghi đè ZIP |
| `publish_new_file` mở `"xb"` | `builds.py:52-55` | không ghi đè artifact |
| `output_root.exists() → FileExistsError` | `snapshot.py:68-69` | retrieval snapshot bất biến |
| `_safe_id` regex `^[A-Za-z0-9][A-Za-z0-9_.-]*$` | `paths.py:12` | chặn path traversal qua `run_id` |

---

## 3. PROJECT_OLD — EXECUTION BASELINE

### 3.1 OLD chạy E2E như thế nào (FACT)

**Không qua `src/`.** Đường ship thật của OLD:

```
tools/answer_a6/01_resolver.py  (PRIMARY_A6)  ─┐
tools/so_hoc/02_engine.py       (số học)      ─┤→ records_*.jsonl
                                               │
tools/answer_a6/06_dong_goi.py ────────────────┘
  :11  NEN   = data/submissions/submission_P0G2.zip   ← VÁ ZIP CŨ
  :43  ghi đè r["answer"], r["pandas_query"], r["evidence"]
  :46-50  ABORT nếu relevant_tables/docs/question đổi  ← ĐÓNG BĂNG retrieval
  → data/submissions/submission_P0I.zip
```

### 3.2 Baseline có thể tái dùng làm reference

| Hạng mục | Giá trị | Nguồn |
|---|---|---|
| **EXECUTION chính thức** | **0,1225** (ID 3392, hạng 28) | `OLD/reports/answer_v2/OFFICIAL_SCORE.json:3,9,11` |
| Câu phát ra | **1011/1012** (1 `NO_QUERY`) | `OLD/reports/answer_v2/clean_replay.json:6-9` |
| `invariant_answer_eq_query` | 1011 | `:9` |
| Corpus | 1973 doc · 121.756 trang · 146.246 bảng · 2.646.976 obs | `OLD/HANDOFF.md:200-204` |
| A6 build cũ | `b3e9684004679ffb`, sha `6622b913…` | `NEW/provenance/baseline_20260825.json` |
| Retrieval cũ | `work.db` 4.240.060.416 B, sha `e9f62775…` | như trên |

### 3.3 Known pitfalls từ OLD — phải mang sang plan

| Pitfall | Nguồn | Áp dụng cho NEW |
|---|---|---|
| **`parse_vn_number("1.234.567")` bằng `float()` kiểu Anh → sai 1000×** | `OLD/CLAUDE.md §5` | Vẫn **không có test** ở NEW. Ghi vào Phase 5 |
| **Số âm dạng `(1.234)` bị đảo dấu** | như trên | như trên |
| **RC1 không tái hiện được** — revision nguồn không resolve | `OLD/HANDOFF.md:21,195` | Bài học: **ghim commit trước khi build** |
| **Môi trường đóng băng `NOT_VERIFIED`** | `OLD/HANDOFF.md:17` | NEW có `--require-hashes`; **phải chạy thật**, không chỉ khai |
| **Test xanh vì skip nuốt gate** — 20/28 điểm skip biến mất khi thiếu artifact | `OLD/tests/*` | NEW có allowlist; nhưng **collection-time skip vẫn lọt** (§7 P2-3) |
| `silver_release.zip` KHÔNG phải SSOT | `OLD/identity/data_identity.json:17` — *"ban release 06/08 CU HON A6 run1"* | **Đừng dùng 1,6 GB này** |

---

## 4. OLD vs NEW — EXECUTION COMPARISON

| Concern | OLD | NEW | Reusable? | Action |
|---|---|---|---|---|
| **Environment** | Không CI, 2 venv trên đĩa (3.11 + 3.13), `NOT_VERIFIED` | Python ≥3.11, `requirements.lock` có hash, `make dp-env-check`, CI workflow | **Adapt** | Dựng venv sạch theo `README.md:89-97`; chạy `dp-env-check` đòi `lock_matches_installed=True` |
| **Dependencies** | `requirements.lock` 67.586 dòng (giống hệt NEW) | cùng file, cùng kích thước | **Reuse directly** | `pip install --require-hashes -r requirements.lock` |
| **Data — corpus** | `data/external/vifinqa/` ✅ **kiểm chứng có thật** | `data/raw/btc/` ❌ rỗng | **Reuse directly** | **COPY** 3 mục theo bảng §8-P1 |
| **Data — A6** | `b3e9684004679ffb` tại `artifacts/rc2/release_finala6/` | cần `c6887fb633374fad` | ❌ **New implementation required** | **REBUILD** — không có đường copy |
| **Data — retrieval** | `work.db` = index `286973b134a189ee` | cần `872ccb0dda9a2bb6` | ❌ **New implementation required** | **BUILD** từ A6 mới |
| **Database init** | Ad-hoc, nhiều script | `dp-build` → `dp-release` → `build_retrieval_snapshot` | **Adapt** | Theo Phase 1 |
| **Artifacts** | 68 ZIP, 5 bản sao source tree | 6 file | **Not applicable** | Sinh mới; **không** import ZIP cũ vào đường chạy |
| **Pipeline** | `tools/answer_a6/06_dong_goi.py` vá ZIP | `text2pandas run` → `canonical_run` | ❌ **New implementation required** | Dùng CLI của NEW; **không** port script vá ZIP |
| **Tests** | 80 file, không conftest, không CI, skip nuốt gate | 120 file, conftest + allowlist 42, `make ci` | **Adapt** | `make ci` rồi `make test-integration` |
| **Validation** | `reports/submission_gate_v1.json` thủ công | `validate_zip` + `replay_zip` **trong code**, quyết định publish | **Adapt** | Dùng `package_ok` làm tiêu chí PASS |
| **E2E** | Vá ZIP cha, retrieval đóng băng | `run` sinh toàn bộ từ đầu | ❌ **New implementation required** | Phase 4 |
| **Gold nhỏ** | `evaluation/` 8 file, `data/gold/` 12 file | đã migrate ✅ **còn đủ** | **Reuse directly** | Không cần làm gì |
| **`data/dev/`** | 11 file gold/label | ❌ **mất** (`curated/dev-legacy/` không tồn tại) | **Reuse directly** | COPY — Phase 1 T1.4 |
| **Identity seal** | `identity/` 11 file | `provenance/identity/` 11 file ✅ | **Reuse directly** | — |

**Nguyên tắc:** OLD chỉ cho ta **corpus** và **kỳ vọng số liệu**. **Không port một dòng execution flow nào của OLD sang NEW** — đường vá-ZIP của OLD là thứ NEW cố ý loại bỏ.

---

## 5. PROJECT_NEW — E2E CONTRACT

```
════════════════════════════════════════════════════════════════
E2E CONTRACT — text2pandas canonical V2
════════════════════════════════════════════════════════════════

INPUT
  Bắt buộc (payload):
    data/raw/btc/financial_statements/*/*/*/*.txt   đúng 1973 file, 100 thư mục ticker
    data/raw/btc/questions/questions.jsonl          đúng 1012 dòng non-blank, id 1..1012
    data/raw/btc/metadata/companies.csv             100 mã CK
    data/processed/a6/<a6>/silver.db                4.140.924.928 B · sha fa6c46d6…
    data/indexes/retrieval/<a6>/<idx>/retrieval.db  4.239.663.104 B · sha 72d307f8…
  Bắt buộc (metadata, ĐÃ CÓ):
    configs/datasets/active_snapshot.yaml
    data/raw/btc/manifest.json
    data/processed/a6/<a6>/manifest.json
    data/indexes/retrieval/<a6>/<idx>/manifest.json
    configs/retrieval/company_alias_v1.yaml
    configs/retrieval/company_brand_attested_v1.yaml     ⚠️ UNKNOWN — chưa xác minh tồn tại
  Bắt buộc (trạng thái):
    artifacts/runs/answer/<run_id>/  phải CHƯA tồn tại

PIPELINE
  0. import main.py → ActiveSnapshots.load()                    [fail ⇒ exit 1, traceback]
  1. guard  --question-id ⊕ (--limit|--offset)                  [main.py:194 ⇒ exit 2]
  2. guard  slice ⇒ bắt buộc --no-package                       [main.py:196 ⇒ exit 2]
  3. verify_active_snapshots(scope="all")                       [main.py:198 ⇒ exit 2]
  4. mở silver.db, retrieval.db  (mode=ro&immutable=1)          [canonical_run.py:561-562]
  5. load_aliases("a6")
  6. mỗi câu: S1 hard filter → S2 BM25+structural → S3 rerank
              → 6 answering engine → typed execute → render pandas
              → emit HOẶC abstain (mã lý do có tên)
  7. ghi records.jsonl + data/*.csv + manifest.json
  8. [nếu KHÔNG --no-package] build_submission → ZIP
  9. validate_zip   (hợp đồng JSON/ZIP)
 10. replay_zip     (answer == eval(pandas_query), sandbox sạch)
 11. package_ok ⇒ publish; ngược lại CHẶN

OUTPUT
  artifacts/runs/answer/<run_id>/
    records.jsonl              1012 bản ghi
    data/*.csv                 evidence, tên = biến evidence
    manifest.json              lineage: raw/a6/retrieval id + config + commit
    submission_manifest.json   validator + replay stats
  artifacts/submissions/submission_<run_id>.zip   ← CHỈ khi package_ok

  Hợp đồng ZIP (AGENTS.md:180-192):
    đúng 1 file JSON ở gốc archive
    mọi member khác là CSV dưới data/, có tham chiếu
    đúng 1012 bản ghi id duy nhất
    question text khớp CHÍNH XÁC nguồn
    answer là số hữu hạn                    ⚠️ abstain ⇒ 0.0 (submission.py:104)
    evidence variable hợp lệ, không trùng
    pandas_query thuộc grammar hạn chế
    locator document/table có thật
    answer == eval(pandas_query) cho MỌI query phát ra
    0 validator error, 0 replay error

VALIDATION
  Tự động, cưỡng chế bằng code:
    val.ok == True
    stat["error"] == 0
    stat["matched"] == stat["executed"]
    exit code == 0
    artifacts/submissions/submission_<run_id>.zip tồn tại
  Thủ công, bắt buộc thêm:
    sha256(silver.db)    == fa6c46d6d46b4735f6a23fe1f2b8e2be16c206b712f47b8f22a5f0647f5dc3c8
    sha256(retrieval.db) == 72d307f8a2bb542a40f97e112456d537b90823e7b57a20eaef04a94545ab6daf
    tree_sha256(raw)     == 57fd7ca41903dbb749d774b1ee34373c8243faec7ba0fd91c8b51fb082b0282a
    ZIP build 2 lần → byte-identical
  Đối chiếu kỳ vọng (CLAIM từ ACCEPTANCE:140-148):
    records = 1012 · emitted ≈ 561 (55,43%) · abstain ≈ 451 · replay 561/561

SUCCESS CRITERIA — E2E PASS khi VÀ CHỈ KHI cả 6 điều:
  1. exit code == 0
  2. artifacts/submissions/submission_<run_id>.zip tồn tại
  3. validator errors == 0
  4. replay errors == 0 VÀ matched == executed
  5. records.jsonl có đúng 1012 dòng, id duy nhất
  6. Evidence package (§12) đầy đủ

  ⚠️ KHÔNG được tuyên bố PASS chỉ vì lệnh chạy không báo lỗi (Rule 4).
  ⚠️ E2E PASS ≠ đáp án đúng. Official accuracy vẫn NOT_MEASURED.
════════════════════════════════════════════════════════════════
```

---

## 6. DEPENDENCY GRAPH

```
[EXT] Python ≥3.11 · SQLite · ~40 GB đĩa trống
   │
   ▼
Phase 0 ── venv + pip --require-hashes + pip install -e .
   │        GATE 0: dp-env-check → lock_matches_installed=True
   │
   ├──────────────────────────────┐
   ▼                              ▼
Phase 1a ── source_fingerprint()  Phase 1b ── COPY corpus từ OLD
   │  🔴 BLOCKING · 1 giây            │  ~363 MiB
   │  GATE 1a: 0719b86f/d4ff2b5c      │  GATE 1b: 1973/1012/100 + tree sha
   │                                   │
   └───────────────┬───────────────────┘
                   ▼
Phase 1c ── dp-build FINALIZE=1  →  dp-release
   │  ~10 phút · 6,5 GiB
   │  🔴 GATE 1c: build_id == c6887fb633374fad  ← CỔNG DỪNG
   ▼
Phase 1d ── build_retrieval_snapshot.py
   │  ~4 GiB · index_id tất định
   │  GATE 1d: database_bytes == 4239663104
   ▼
GATE 1: make snapshots-verify → verify all PASS
   │
   ├──────────────┬──────────────┬──────────────┐
   ▼              ▼              ▼              ▼
Phase 2a       Phase 2b       Phase 2c       Phase 2d
verify all     coverage       make ci        parse-check
(không cần     (không cần     (không cần     (cần catalog,
 payload sau    payload)       payload)       tuỳ chọn)
 GATE 1)
   │              │              │
   └──────────────┴──────────────┘
                  ▼
         GATE 2: COMPONENT READY
                  │
                  ▼
Phase 3 ── run --limit 10 --no-package      ← smoke, KHÔNG đóng gói
   │       run --question-id … --no-package  ← boundary
   │       make test-integration
   │       GATE 3: INTEGRATION READY
   ▼
Phase 4 ── run --run-id <id>   (đủ 1012 câu, có đóng gói)
   │       GATE 4: package_ok == True
   ▼
Phase 5 ── validation: sha256 · determinism 2-build · đối chiếu kỳ vọng
   │       GATE 5: VALIDATION PASSED
   ▼
Phase 6 ── evidence package
           GATE 6: EVIDENCE COMPLETE

──────────── NHÁNH TUỲ CHỌN (không chặn E2E) ────────────
GATE 1 ──▶ shadow-v3 (chỉ cần A6, KHÔNG cần retrieval) ──▶ package-v3
```

### Phân loại dependency

| Loại | Danh sách |
|---|---|
| **Blocking** | Phase 0 → 1b → 1c → 1d → GATE 1 → Phase 3 → 4. Không bước nào bỏ được |
| **Blocking, rẻ, phải làm SỚM** | Phase 1a (`source_fingerprint`) — 1 giây, quyết định cả chiến lược |
| **Generated artifact** | `silver.db`, `retrieval.db`, `records.jsonl`, ZIP, mọi `manifest.json` mới |
| **External** | Python/SQLite/đĩa. HF Hub **chỉ khi** không copy từ OLD |
| **Optional, không chặn** | `shadow-v3`, `package-v3`, 4 lệnh legacy-build, copy artifact lịch sử |
| **Không phải dependency** | `catalog`/`index`/`silver`/`cards` — nhánh mồ côi (§2.4) |

---

## 7. BLOCKER LIST

### P0 — Không chạy được

| ID | Blocker | File/path | Bằng chứng | Fix đề xuất | Validation |
|---|---|---|---|---|---|
| **P0-1** | Corpus raw vắng mặt | `data/raw/btc/{financial_statements,questions,metadata}` | Glob `data/**/*` → chỉ `README.md` + `manifest.json` | COPY từ `OLD/data/external/vifinqa/` | `make data-verify` + tree sha `57fd7ca4…` |
| **P0-2** | `silver.db` vắng mặt | `data/processed/a6/c6887fb633374fad/silver.db` | như trên | **REBUILD** (không copy được — §1.1) | `make a6-verify` + sha `fa6c46d6…` |
| **P0-3** | `retrieval.db` vắng mặt | `data/indexes/retrieval/c6887fb633374fad/872ccb0dda9a2bb6/retrieval.db` | như trên | BUILD từ P0-2 | `make retrieval-verify` + 4239663104 B |
| **P0-4** | Trạng thái Python env **UNKNOWN** | — | Sandbox wedged, không kiểm được | Dựng venv sạch | `make dp-env-check` |
| **P0-5** | `curated/dev-legacy/` không tồn tại → dangling refs sẽ raise | `configs/evaluation/gold_registry_v1.yaml`, `tests/test_answer_gold_provenance.py:12` | Glob: `data/curated/dev*` → 0 kết quả; `folder_migration_20260825.json:34` khai đích này | COPY `OLD/data/dev/` → `data/curated/dev-legacy/` | `make test-offline` không `FileNotFoundError` |
| **P0-6** | ⚠️ **UNVERIFIED** — `configs/retrieval/company_brand_attested_v1.yaml` có tồn tại không? | `alias_store.py:50-53` | Chưa kiểm | — | **Cần inspect `ls configs/retrieval/`** trước Phase 3. Thiếu ⇒ `run`, `shadow-v3`, `coverage` đều chết |
| **P0-7** | ⚠️ **UNKNOWN** — cấu trúc output của `dp-build` | `tools/build_runner.py` | Chưa đọc file | — | **Cần inspect** để biết tên chính xác `quality_report.json` / `gate_report.json` mà `dp-release` cần |

### P1 — Chạy được nhưng không validate được

| ID | Blocker | Bằng chứng |
|---|---|---|
| **P1-1** | Không có gold của BTC ⇒ **official Answer/Execution Accuracy = NOT_MEASURED** | `README.md:20-21`. **Không fix được nội bộ** — chỉ giải quyết bằng nộp leaderboard |
| **P1-2** | Retrieval gold chỉ 95/1012 (9,39%); 917 câu `NOT_MEASURED`. File gold **không có trên đĩa** | `ACCEPTANCE:97,101` |
| **P1-3** | Reranker held-out: 120 QID đã seal, **0 nhãn** ⇒ `evaluate_reranker_heldout.py` trả `BLOCKED` exit 2 | `evaluate_reranker_heldout.py:72-74` |
| **P1-4** | Không có kỳ vọng cho `shadow-v3`: `README:12` = 269/743 (r17) vs `ACCEPTANCE:158` = 207/805 (r5), **cùng ngày** | Không biết số nào đúng ⇒ không đặt được gate cho V3 |
| **P1-5** | `manifest.database_sha256` và `source_a6_db_sha256` **có trong manifest nhưng verify code không đọc** | `snapshots.py:200-244` — phải tự `sha256sum` |

### P2 — Vấn đề chất lượng

| ID | Vấn đề | Bằng chứng | Ghi chú cho plan |
|---|---|---|---|
| **P2-1** | `for ent in set(found): s = s.replace(...)` phụ thuộc `PYTHONHASHSEED` | `pipelines/a6/cleaning.py:269` | 🔴 **Bẫy lớn**: `Makefile:23` export `PYTHONHASHSEED=0` ⇒ **che** lỗi khi đi qua `make`. Gọi thẳng `python -m …` **KHÔNG** set ⇒ build có thể lệch. **Luôn dùng `make`, hoặc export thủ công** |
| **P2-2** | `snapshots-verify` chỉ so **kích thước** `retrieval.db`, không hash | `snapshots.py:132-137` | Manifest giả **sẽ PASS**. Bắt buộc sha256 thủ công |
| **P2-3** | 3 `importorskip("pandas")` cấp module raise lúc **collection** ⇒ 46 hàm test biến mất, allowlist mù | `test_pipeline_e2e.py:15`, `test_percent_point_e2e.py:29`, `test_policy_and_result_kind.py:16` | Ghi số test collected vào evidence để phát hiện |
| **P2-4** | `legacy_reranker_v1.py` không khớp glob `test_*.py` ⇒ 14 ca không chạy; guard chống trôi dùng **cùng glob** | `test_zz_pytest_wrapper.py:35,71` | Không chặn E2E |
| **P2-5** | Docs trỏ 3 thư mục artifact không tồn tại | `ACCEPTANCE:203-205` | Cần xác nhận là bị xoá hay report viết về máy khác |

### P3 — Nice to have

`evaluate_reranker_heldout.py:87` tautology checksum (fix 1 dòng) · 5 package rỗng · `run_pipeline.py` dead code · benchmark latency/memory chưa có · coverage % chưa đo.

---

## 8. PHASE-BY-PHASE EXECUTION PLAN

> **Quy ước:** mọi command chạy từ repo root `text2pandas/`, trong venv đã activate.
> Mọi command đánh dấu `[UNVERIFIED-BY-EXECUTION]` — truy ngược từ source, chưa chạy thử (sandbox hỏng).
> **Luôn ưu tiên `make`** vì nó set `PYTHONHASHSEED=0 · TZ=UTC · LC_ALL=C.UTF-8` (`Makefile:21-26`) — xem P2-1.

---

### PHASE 0 — Environment

**Objective:** môi trường tất định, khớp lockfile, đủ đĩa.

#### T0.1 — Kiểm tiên quyết hệ thống

```
Task:            Xác nhận Python ≥3.11, SQLite, ≥40 GB đĩa trống
Purpose:         Tránh fail giữa chừng build 6,5 GiB
Input:           —
Preconditions:   —
Command:         python3 -V
                 python3 -c "import sqlite3; print(sqlite3.sqlite_version)"
                 df -h .
Expected Output: Python 3.11+; đĩa trống ≥40 GB (README.md:81)
Validation:      Ba giá trị thoả điều kiện
Artifact:        evidence/phase0/system.txt
Failure:         Python <3.11 · đĩa <40 GB
Recovery:        Cài Python mới · giải phóng đĩa · hoặc dùng T2P_DATA_ROOT trỏ volume khác
Gate:            → T0.2
```

#### T0.2 — Dựng venv hash-locked

```
Task:            Cài môi trường acceptance
Purpose:         Tái lập được; OLD thất bại đúng ở điểm này (HANDOFF.md:17 NOT_VERIFIED)
Input:           requirements.lock · pyproject.toml
Preconditions:   T0.1 PASS
Command:         python3 -m venv .venv
                 source .venv/bin/activate
                 python -m pip install --require-hashes -r requirements.lock
                 python -m pip install --no-deps -e .
Expected Output: Cài xong không lỗi hash
Validation:      T0.3
Artifact:        evidence/phase0/pip_freeze.txt
Failure:         Hash mismatch · wheel thiếu cho nền tảng
Recovery:        KHÔNG bỏ --require-hashes. Ghi lại gói lỗi, báo trước khi nới
Gate:            → T0.3
```

#### T0.3 — `dp-env-check`

```
Task:            Xác nhận lock khớp môi trường đã cài
Command:         make dp-env-check
                 # = python tools/env_check.py --config configs/vifinqa_silver_v1.yaml
                 # ⚠️ KHÔNG truyền INPUT= — Makefile:79-82 giải thích: truyền vào sẽ
                 #    ĐÈ config và băm nhầm 15 tệp _codebase/prompts vào corpus_hash
Expected Output: lock_matches_installed=True · lock_has_hashes=True · không untracked source path
Validation:      Ba trường đúng như README.md:97
Artifact:        evidence/phase0/env_check.json
Failure:         lock_matches_installed=False
Recovery:        Xoá .venv, làm lại T0.2. KHÔNG pip install thêm gói ngoài lock
Gate:            🚪 GATE 0
```

#### T0.4 — Ghim identity source

```
Task:            Ghim commit + trạng thái worktree TRƯỚC khi build
Purpose:         OLD thất bại vì revision nguồn không resolve (HANDOFF.md:21)
Command:         git rev-parse HEAD
                 git status --short
                 git diff --check
Expected Output: worktree sạch; commit hash ghi lại
Validation:      git status --short rỗng
Artifact:        evidence/phase0/source_identity.txt
Failure:         Worktree bẩn
Recovery:        Commit hoặc stash. Build trên worktree bẩn = không tái lập được
Gate:            🚪 GATE 0
```

---

### PHASE 1 — Data / Artifact Preparation

**Objective:** dựng đủ 3 tầng payload, mỗi tầng có identity kiểm chứng được.

#### T1.1 — 🔴 Dự đoán build_id (**làm TRƯỚC mọi thứ khác trong Phase 1**)

```
Task:            Tính source_fingerprint và so với manifest
Purpose:         Biết TRƯỚC liệu rebuild có ra c6887fb633374fad không.
                 1 giây thay cho 10 phút CPU + 11 GB đĩa.
Input:           src/text2pandas/pipelines/a6/*.py (25 file — đã xác minh)
                 configs/*.yaml (11 file — đã xác minh)
Preconditions:   GATE 0
Command:         PYTHONPATH=src python -c "from text2pandas.pipelines.a6.storage import source_fingerprint; print(source_fingerprint())"
Expected Output: {'source_hash': '0719b86ff68679a3', 'config_hash': 'd4ff2b5cbc589d6c'}
                 (nguồn: data/processed/a6/c6887fb633374fad/manifest.json header)
Validation:      Khớp CẢ HAI giá trị
Artifact:        evidence/phase1/source_fingerprint.txt
Failure:         Lệch bất kỳ giá trị nào
Recovery:        🛑 DỪNG, BÁO NGƯỜI DÙNG. Ai đó sửa a6/*.py hoặc configs/*.yaml sau 26/08.
                 Hai lựa chọn, người dùng quyết:
                   (a) revert về source_commit 7837635188639c7fb68b167b2b80ddfbc3935d30
                   (b) chấp nhận build_id mới → phải cập nhật active_snapshot.yaml
                       + thay CẢ HAI manifest.json bằng bản do build mới sinh
                 ⛔ TUYỆT ĐỐI KHÔNG sửa tay manifest.json cho "khớp" — đó là làm giả lineage,
                    và snapshots-verify SẼ PASS với manifest giả (P2-2)
Gate:            🚪 GATE 1a
```

#### T1.2 — Khôi phục corpus raw

```
Task:            Copy 3 mục corpus từ OLD
Purpose:         Đóng P0-1
Input:           OLD/data/external/vifinqa/  (đã xác minh trực tiếp: AAA có 22 .txt)
Preconditions:   GATE 1a
Command:         [UNVERIFIED-BY-EXECUTION]
                 OLD=../Text2Pandas-1
                 cp -R "$OLD/data/external/vifinqa/financial_statements" data/raw/btc/
                 cp -R "$OLD/data/external/vifinqa/questions"            data/raw/btc/
                 mkdir -p data/raw/btc/metadata
                 cp    "$OLD/data/external/vifinqa/code_stock.csv"       data/raw/btc/metadata/companies.csv
Expected Output: 1973 .txt · 100 thư mục ticker · questions.jsonl 1012 dòng · companies.csv
⚠️ CẤM:          KHÔNG ghi đè data/raw/btc/{manifest.json,README.md} — chúng đã đúng
⚠️ CẤM:          KHÔNG copy README.md/dataset_report.md/.gitattributes của OLD vào raw/btc/.
                 baseline_20260825.json:13-17 khai included_paths chỉ gồm
                 financial_statements/** · questions/** · code_stock.csv.
                 File thừa ⇒ sai payload_tree_sha256.
Validation:      T1.3
Artifact:        evidence/phase1/copy_manifest.txt (ls -R + du -sh)
Failure:         Số file ≠ 1973 · thiếu ticker
Recovery:        Fallback: python tools/data_acquisition/download_vifinqa.py
                 (HF repo AIGuruTinix/ViFinQA, revision 0450088ab22ec946f04f097586967ca405955b3b)
                 ⚠️ UNKNOWN: revision có còn không. Copy từ OLD an toàn hơn.
Gate:            → T1.3
```

#### T1.3 — Verify corpus

```
Task:            Kiểm kê + hash cây corpus
Command:         python tools/data_acquisition/download_vifinqa.py --verify-only --skip-github
                 make data-verify
                 # ⚠️ CẢ HAI lệnh trên CHỈ ĐẾM, KHÔNG hash. Bắt buộc thêm:
                 # [UNKNOWN — cần xác định công cụ tính tree sha256 của repo;
                 #  không tìm thấy script sẵn. Nếu không có, ghi UNVERIFIED và nêu rõ]
Expected Output: download_vifinqa exit 0, "ĐẠT — dữ liệu khớp hoàn toàn với Dataset Card"
                 make data-verify: [PASS] raw.dataset_id / raw.snapshot_id /
                                   raw.financial_statement_txt (1973) /
                                   raw.question (1012) / raw.ticker (100) / raw.companies
Validation:      6/6 item PASS
Artifact:        evidence/phase1/data_verify.txt · vifinqa_dataset_report.md
Failure:         Đếm lệch (exit 1) · tree sha lệch 57fd7ca4…
Recovery:        Xoá data/raw/btc/{financial_statements,questions,metadata}, làm lại T1.2.
                 Nếu vẫn lệch: corpus OLD đã bị đụng sau 25/08 → dùng đường HF
Gate:            🚪 GATE 1b
```

#### T1.4 — Vá lỗ hổng migration `data/dev`

```
Task:            Copy gold/label legacy
Purpose:         Đóng P0-5
Command:         [UNVERIFIED-BY-EXECUTION]
                 cp -R "$OLD/data/dev" data/curated/dev-legacy
Expected Output: 11 file (gold_v1.jsonl, gold_v2.jsonl, gold_tay_pool_v3..v7, …)
⚠️ MÂU THUẪN:    data/README.md:9 khai `curated/dev/`;
                 provenance/folder_migration_20260825.json:34 khai `curated/dev-legacy/`.
                 CẢ HAI đích đang vắng. Theo CLAUDE.md §6 — KHÔNG tự chọn bên nào.
                 🙋 CẦN NGƯỜI DÙNG QUYẾT trước khi chạy task này.
Validation:      make test-offline không raise FileNotFoundError ở
                 tests/test_answer_gold_provenance.py:12
Artifact:        evidence/phase1/dev_legacy_listing.txt
Gate:            → T1.5
```

#### T1.5 — 🔴 Rebuild A6

```
Task:            Dựng A6 build từ corpus
Purpose:         Đóng P0-2 — không có đường copy (§1.1)
Input:           data/raw/btc/financial_statements · configs/vifinqa_silver_v1.yaml
Preconditions:   GATE 1a + GATE 1b · ≥15 GB đĩa trống
Command:         [UNVERIFIED-BY-EXECUTION]
                 make dp-build CONFIG=configs/vifinqa_silver_v1.yaml \
                               INPUT=data/raw/btc/financial_statements \
                               OUTPUT=artifacts/runs/a6/staging_A \
                               FINALIZE=1
                 # 🔴 FINALIZE=1 BẮT BUỘC. Makefile:93-100 nói rõ: thiếu nó,
                 #    dp-release đọc nhầm manifest CORPUS (trùng tên file) và
                 #    phát hành với build_id: "unknown".
Expected Output: build_id in ra == c6887fb633374fad
                 counts: documents 1973 · pages 121756 · tables 146246 · columns 591775 ·
                         rows 1524071 · observations 2634120 · dropped_cells 779087 ·
                         quality_issues 50314 · build_meta 40
Runtime:         ~10 phút (CLAIM từ README.md:81 — chưa xác minh)
Validation:      build_id khớp CHÍNH XÁC
Artifact:        evidence/phase1/dp_build.log
Failure:         build_id ≠ c6887 · counts lệch · OOM · hết đĩa
Recovery:        🛑 build_id lệch ⇒ DỪNG, BÁO NGƯỜI DÙNG (như T1.1 Recovery).
                 counts lệch ⇒ corpus sai, quay lại T1.2.
                 ⚠️ Nếu chạy KHÔNG qua make: bắt buộc export PYTHONHASHSEED=0 TZ=UTC
                    LC_ALL=C.UTF-8 — xem P2-1 (cleaning.py:269)
Gate:            🚪 GATE 1c — CỔNG DỪNG CỨNG
```

#### T1.6 — Release A6

```
Task:            Dựng thư mục phát hành A6 + silver.db + manifest
Preconditions:   GATE 1c
Command:         [UNVERIFIED-BY-EXECUTION]
                 make dp-measure DB=<staging>/silver.sqlite REPORT_DIR=artifacts/reports/a6_rebuild
                 make dp-release DB=<staging>/silver.sqlite \
                                 BRONZE=<staging>/catalog.sqlite \
                                 QUALITY=<staging>/quality_report.json \
                                 OUTPUT=data/processed/a6/c6887fb633374fad \
                                 REPORT_DIR=artifacts/reports/a6_rebuild \
                                 GATE_REPORT=<staging>/gate_report.json
                 # ⚠️ P0-7: tên file chính xác của quality_report.json / gate_report.json /
                 #    catalog.sqlite trong <staging> là UNKNOWN.
                 #    CẦN INSPECT tools/build_runner.py TRƯỚC KHI CHẠY.
                 # --profile slim và --per-table primary là mặc định, khớp manifest c6887
⚠️ XUNG ĐỘT:     data/processed/a6/c6887fb633374fad/ ĐANG TỒN TẠI (README.md + manifest.json).
                 Phải di chuyển manifest.json cũ ra chỗ khác TRƯỚC, để đối chiếu sau.
Expected Output: silver.db 4.140.924.928 B · manifest n_files 16586 · total_bytes 6955080658
                 dataframe/csv/table_cards.csv (package-v3 cần)
Validation:      make a6-verify → 6/6 PASS
                 sha256(silver.db) == fa6c46d6d46b4735f6a23fe1f2b8e2be16c206b712f47b8f22a5f0647f5dc3c8
                 diff manifest mới vs cũ: build_id, table_cards.rows=146246, files["silver.db"].digest
Artifact:        evidence/phase1/a6_verify.txt · a6_manifest_diff.txt · sha256sums.txt
Failure:         sha256 lệch · a6.build_meta.build_id ≠ c6887 · table_cards ≠ 146246
Recovery:        sha lệch nhưng build_id đúng ⇒ nội dung khác dù identity đúng.
                 Chạy make dp-rebuild-check BUILD_A= BUILD_B= để định vị.
                 ⛔ KHÔNG sửa manifest cho khớp.
Gate:            → T1.7
```

#### T1.7 — Dựng retrieval snapshot

```
Task:            Sinh retrieval.db + 4 index
Purpose:         Đóng P0-3
Preconditions:   T1.6 PASS
Command:         [UNVERIFIED-BY-EXECUTION]
                 # Di chuyển manifest cũ ra trước — snapshot.py:68-69 raise FileExistsError
                 mv data/indexes/retrieval/c6887fb633374fad/872ccb0dda9a2bb6/manifest.json \
                    evidence/phase1/retrieval_manifest_expected.json
                 rmdir data/indexes/retrieval/c6887fb633374fad/872ccb0dda9a2bb6

                 python tools/build_retrieval_snapshot.py \
                   --source-db data/processed/a6/c6887fb633374fad/silver.db \
                   --build-id  c6887fb633374fad
                 # Đích tự tính = paths.retrieval_snapshot(build_id, retrieval_index_id())
                 # retrieval_index_id() là hàm thuần ⇒ luôn ra 872ccb0dda9a2bb6 (snapshot.py:43-50)
Quy trình bên trong (snapshot.py:53-120):
                 validate source schema → copy2 silver.db → retrieval.db
                 → 4 CREATE INDEX + ANALYZE → PRAGMA quick_check
                 → ghi manifest → staging.rename() atomic
Expected Output: retrieval.db 4.239.663.104 B
                 index: ix_tc_ticker_year · ix_tc_stmt_ticker · ix_doc_tky · ix_obs_tab_period
                 row_counts: documents 1973 · observations 2634120 · rows 1524071 ·
                             table_cards 146246 · tables 146246
Validation:      make retrieval-verify → 9/9 PASS
                 sha256(retrieval.db) == 72d307f8a2bb542a40f97e112456d537b90823e7b57a20eaef04a94545ab6daf
                 diff manifest mới vs retrieval_manifest_expected.json
Artifact:        evidence/phase1/retrieval_verify.txt · retrieval_manifest_diff.txt
Failure:         database_bytes ≠ 4239663104 (verify sẽ bắt) · index thiếu · quick_check fail
Recovery:        rmtree thư mục đích, chạy lại. Snapshot bất biến nên không có trạng thái bẩn.
Gate:            🚪 GATE 1d
```

#### T1.8 — Gate dữ liệu tổng

```
Task:            Verify toàn bộ lineage
Command:         make paths-check
                 make snapshots-verify
Expected Output: paths-check in 4 đường dẫn hợp lệ
                 snapshots-verify: MỌI item [PASS], exit 0
                 (raw 6 item · a6 8 item · retrieval 9 item)
Validation:      exit 0 và không có dòng [FAIL] nào
⚠️ LƯU Ý:        Gate này KHÔNG hash payload (P2-2). sha256 ở T1.6/T1.7 mới là bằng chứng nội dung.
Artifact:        evidence/phase1/snapshots_verify.txt
Gate:            🚪 GATE 1
```

---

### PHASE 2 — Component Smoke Test

**Objective:** mỗi component chạy độc lập trước khi ghép.

| Task | Command | Expected | Gate |
|---|---|---|---|
| **T2.1** static | `make lint` | ruff E9,F63,F7,F82,B,PLR0124,PLE2515,F841 → 0 lỗi | |
| **T2.2** types | `make typecheck` | mypy strict trên 4 layer → 0 lỗi (kỳ vọng 78–83 file; **README:201 nói 83, GAP_CLOSURE:64 nói 78** — mâu thuẫn, ghi số thực đo) | |
| **T2.3** docs | `make docs-check` | 0 link hỏng | |
| **T2.4** unit | `make test-offline` | **CLAIM kỳ vọng: 2019–2057 passed · 42 skip · 25 deselected · 0 fail**. ⚠️ Ghi lại **số collected** để phát hiện P2-3 (46 hàm biến mất nếu thiếu pandas) | |
| **T2.5** parser | `make semantic-coverage` | route coverage. ⚠️ **CLAIM mâu thuẫn: REFACTOR_STATUS:69 = 669/1012 (66,11%), GAP_CLOSURE:11 = 684/1012 (67,59%)**. Ghi số thực đo, **không** coi là accuracy | |
| **T2.6** verify | `make snapshots-verify` | (lặp lại GATE 1, xác nhận không trôi) | |

```
Gate 2 pass criteria:  T2.1–T2.6 đều exit 0; test-offline 0 failed 0 error;
                       số skip == 42 (nhiều hơn ⇒ conftest.py:71 đã fail session)
Gate 2 fail criteria:  bất kỳ exit ≠ 0
Evidence:              evidence/phase2/{lint,typecheck,docs,test_offline,coverage}.txt
```

⛔ **Không sang Phase 3 khi Phase 2 còn đỏ** — component failure sẽ hiện ra dưới dạng lỗi E2E khó chẩn đoán.

---

### PHASE 3 — Integration

**Objective:** kiểm biên A→B→C với payload thật, chi phí thấp, **không** đóng gói.

#### T3.1 — Smoke 10 câu

```
Task:            Chạy 10 câu đầu, không đóng gói
Purpose:         Chứng minh silver.db + retrieval.db + alias + engine ghép được
Preconditions:   GATE 1 + GATE 2
Command:         python -m text2pandas.interface.cli.main run \
                   --run-id local_smoke_001 --offset 0 --limit 10 --no-package
                 # 🔴 --no-package BẮT BUỘC khi có --limit/--offset:
                 #    main.py:196 raise BuildSafetyError → exit 2 nếu thiếu
Expected Output: artifacts/runs/answer/local_smoke_001/{records.jsonl, data/*.csv, manifest.json}
                 records.jsonl có 10 dòng
                 exit 0 (main.py:254-257 return sớm, KHÔNG validate/replay)
Validation:      10 dòng · manifest.json ghi đúng 3 identity (raw/a6/retrieval)
                 mỗi record có id, question, answer, relevant_docs, relevant_tables,
                 evidence, pandas_query
Artifact:        evidence/phase3/smoke_10.log + records.jsonl
Failure:         exit 2 (guard/verify) · exit 1 traceback (run dir đã tồn tại)
Recovery:        exit 2 ⇒ đọc stderr, verify item nào FAIL, quay lại GATE 1
                 FileExistsError ⇒ ĐỔI run_id (immutable, canonical_run.py:534). KHÔNG xoá thư mục cũ
Gate:            → T3.2
```

#### T3.2 — Boundary: câu chỉ định

```
Task:            Chạy vài qid đã biết đặc tính
Command:         python -m text2pandas.interface.cli.main run \
                   --run-id local_smoke_002 --question-id 1 --question-id 2 --no-package
                 # ⚠️ --question-id KHÔNG dùng chung --limit/--offset (main.py:194 → exit 2)
Expected Output: 2 record
Validation:      Có ít nhất 1 record emit và 1 record abstain có mã lý do đặt tên
                 ⇒ chứng minh CẢ HAI nhánh (emit + fail-closed) hoạt động
Artifact:        evidence/phase3/smoke_qid.log
Gate:            → T3.3
```

#### T3.3 — Integration test suite

```
Task:            Chạy gate cần materialized artifact
Command:         make test-integration
Expected Output: CLAIM kỳ vọng: 25 passed, 2061 deselected (ACCEPTANCE:181)
                 (3 file mang @pytest.mark.integration: test_h0_gates.py,
                  test_semantic_v3_select_at_arg.py, test_semantic_v3_filtered_extrema.py)
Validation:      0 failed, 0 error
Artifact:        evidence/phase3/test_integration.txt
Failure:         test_h0_gates.py cần adjudication ledger
Recovery:        make materialize-h0   (tools/execution/materialize_h0.py; FORCE=1 để ghi đè)
Gate:            🚪 GATE 3
```

---

### PHASE 4 — E2E

**Objective:** chạy đủ 1012 câu, đóng gói, validate, replay, publish.

#### T4.1 — Full run

```
Task:            E2E canonical V2
Purpose:         Sinh submission candidate
Input:           silver.db · retrieval.db · questions.jsonl · alias configs
Preconditions:   GATE 3 · artifacts/runs/answer/<run_id>/ CHƯA tồn tại
Command:         python -m text2pandas.interface.cli.main run --run-id submission_candidate_001
                 # KHÔNG --limit/--offset/--question-id (sẽ ép --no-package)
                 # Mặc định: --n-tables 20 --answer-pool-tables 50
                 #           --doc-id stripped --locator-base 1
Expected Output: artifacts/runs/answer/submission_candidate_001/
                   records.jsonl              1012 dòng
                   data/*.csv                 evidence
                   manifest.json              lineage
                   submission_manifest.json   validator + replay stats
                 artifacts/submissions/submission_submission_candidate_001.zip   ← chỉ khi package_ok
Runtime:         UNKNOWN — không có benchmark cho V2 ở repo nào.
                 Tham chiếu duy nhất: V3 xử lý 1012 câu / 63,22 s (ACCEPTANCE:158)
Validation:      T4.2
Artifact:        evidence/phase4/run_full.log (stdout + stderr + thời gian)
Failure:         exit 1 + "CHẶN PUBLISH" ⇒ package_ok=False
                 exit 2 ⇒ BuildSafetyError
                 exit 1 traceback ⇒ FileExistsError
Recovery:        CHẶN PUBLISH ⇒ đọc submission_manifest.json, phân loại lỗi là
                 validator hay replay, xử lý rồi chạy lại với run_id MỚI.
                 ⛔ KHÔNG xoá run dir cũ — nó là bằng chứng chẩn đoán.
Gate:            → T4.2
```

#### T4.2 — Xác nhận điều kiện publish

```
Task:            Đọc submission_manifest.json, đối chiếu package_ok
Command:         cat artifacts/runs/answer/submission_candidate_001/submission_manifest.json
                 ls -l artifacts/submissions/
Expected Output: validator errors == 0
                 replay: {"total":1012, "executed":N, "matched":N, "error":0, "no_evidence":M}
                 matched == executed
                 ZIP tồn tại
Validation:      🔴 CẢ 6 tiêu chí §5 SUCCESS CRITERIA
Đối chiếu CLAIM: emitted ≈ 561 (55,43%) · abstain ≈ 451 · replay 561/561 (ACCEPTANCE:140-148)
                 ⚠️ Lệch đáng kể ⇒ KHÔNG tự sửa; ghi lại và báo — có thể là regression
                    hoặc có thể là báo cáo cũ. Cần đối chiếu commit.
Artifact:        evidence/phase4/submission_manifest.json · zip_listing.txt
Gate:            🚪 GATE 4
```

#### T4.3 — (Tuỳ chọn, không chặn) V3 shadow

```
Task:            Chạy V3 ở shadow mode
Preconditions:   GATE 1 (chỉ cần scope a6 — main.py:641-650 KHÔNG kiểm retrieval)
Command:         python -m text2pandas.interface.cli.main shadow-v3 \
                   --run-id semantic_v3_shadow_001 --operand-k 20 \
                   --legacy-run-id submission_candidate_001
                 python -m text2pandas.interface.cli.main package-v3 \
                   --run-id semantic_v3_shadow_001 --doc-id stripped --locator-base 1
Expected Output: artifacts/runs/semantic-v3/semantic_v3_shadow_001/{records.jsonl,data,manifest.json}
                 package-v3 ghi ZIP vào stage, ⚠️ KHÔNG publish vào artifacts/submissions/
                 manifest ghi ≥15 blocker NOT_MEASURED:* (main.py:740-750 chỉ truyền 2 metric)
Validation:      replay mismatch == 0; promotion decision == BLOCKED (đúng thiết kế)
⚠️ P1-4:         Kỳ vọng emitted KHÔNG XÁC ĐỊNH — README:12 nói 269, ACCEPTANCE:158 nói 207.
                 Ghi số thực đo, KHÔNG đặt gate pass/fail cho con số này.
Precondition đặc biệt: package-v3 cần data/processed/a6/<a6>/dataframe/csv/table_cards.csv
                 (main.py:428) — thiếu ⇒ FileNotFoundError KHÔNG bắt ⇒ traceback exit 1
Gate:            Không chặn GATE 4
```

---

### PHASE 5 — Validation

**Objective:** chứng minh kết quả đúng hợp đồng, tái lập được, không regression.

| # | Task | Command / Action | Pass criteria |
|---|---|---|---|
| **T5.1** | sha256 payload | `sha256sum data/processed/a6/*/silver.db data/indexes/retrieval/*/*/retrieval.db` | `fa6c46d6…` và `72d307f8…` |
| **T5.2** | ZIP determinism | Chạy `run` lần 2 với `--run-id submission_candidate_002`, so **byte thô** hai ZIP | Byte-identical. Cơ sở: `_ZIP_TIME` ghim + `ZipInfo` + sort theo qid (`submission.py:37,96,125-130`); test tương tự `test_submission_contract.py:59-65` |
| **T5.3** | Replay độc lập | `python tools/replay_submission_v1.py <zip> --report-out evidence/phase5/replay.json` **[UNVERIFIED — script tồn tại ở OLD; cần xác nhận đường dẫn ở NEW]** | `answer == eval(pandas_query)` cho mọi query |
| **T5.4** | Hợp đồng ZIP | Kiểm 10 bất biến ở §5 OUTPUT | Đủ 10 |
| **T5.5** | Regression vs OLD | So `emitted` với OLD 1011/1012 | ⚠️ **Kỳ vọng NEW THẤP HƠN** (≈561). Đây là **thay đổi có chủ đích** (fail-closed), **không phải** bug. Ghi lại, không alarm |
| **T5.6** | Đối chiếu số CLAIM | So với ACCEPTANCE:140-154 | Lệch ⇒ ghi, không tự sửa |
| **T5.7** | Metric phân tách | Ghi RIÊNG: route coverage · candidate recall · ranking F2 · binding exact · replay consistency · Answer Accuracy · Execution Accuracy | 🔴 `AGENTS.md:174`: **không được gọi route coverage hay replay consistency là accuracy**. Thiếu gold ⇒ ghi `NOT_MEASURED` |
| **T5.8** | Bẫy số VN | Kiểm tay `parse_vn_number("1.234.567")` và `("(1.234)")` | ⚠️ **Không có test nào ở cả hai repo** dù `CLAUDE.md §5` gọi tên đây là lỗi 1000× và đảo dấu lịch sử. Kiểm thủ công |

```
Gate 5 pass:   T5.1 sha khớp · T5.2 byte-identical · T5.3 replay sạch · T5.4 đủ 10 bất biến
Gate 5 fail:   sha lệch · ZIP không tất định · bất kỳ bất biến nào vỡ
Evidence:      evidence/phase5/*
```

---

### PHASE 6 — Evidence Package

| Nhóm | Nội dung |
|---|---|
| **Environment** | `python -V` · `sqlite3.sqlite_version` · `pip freeze` · `env_check.json` · OS/arch · `PYTHONHASHSEED/TZ/LC_ALL` |
| **Source identity** | `git rev-parse HEAD` · `git status --short` (phải rỗng) · `source_fingerprint()` |
| **Data identity** | `snapshots_verify.txt` · sha256 của `silver.db`/`retrieval.db` · tree sha raw · diff manifest cũ↔mới |
| **Build logs** | `dp_build.log` · `dp_release.log` · `build_retrieval_snapshot.log` |
| **Test results** | `lint/typecheck/docs/test_offline/test_integration` + `dp-test` JSON/JUnit/text |
| **E2E** | `run_full.log` · `records.jsonl` · `manifest.json` · `submission_manifest.json` · ZIP + sha256 |
| **Validation** | `replay.json` · `determinism_diff.txt` · bảng 7 metric phân tách (T5.7) |
| **Reproduction** | `REPRODUCE.md` — chuỗi command chính xác, từ clone tới ZIP |
| **Known gaps** | Danh sách `NOT_MEASURED` (P1-1..P1-5) — **bắt buộc**, không được im lặng |

```
Gate 6 pass:  đủ 9 nhóm; REPRODUCE.md chạy được trên máy sạch;
              mọi metric có nhãn MEASURED hoặc NOT_MEASURED, không có ô trống
```

---

## 9. GATE DEFINITIONS

| Gate | Tên | Pass criteria | Fail criteria | Evidence bắt buộc |
|---|---|---|---|---|
| **0** | Environment Ready | Python ≥3.11 · `lock_matches_installed=True` · `lock_has_hashes=True` · worktree sạch · ≥40 GB | Hash mismatch · worktree bẩn · đĩa thiếu | `env_check.json` · `pip_freeze.txt` · `source_identity.txt` |
| **1a** | 🔴 Build ID Predicted | `source_hash=0719b86ff68679a3` **và** `config_hash=d4ff2b5cbc589d6c` | Lệch bất kỳ | `source_fingerprint.txt` |
| **1b** | Corpus Ready | 1973 txt · 1012 câu · 100 ticker · `data-verify` 6/6 PASS · tree sha `57fd7ca4…` | Đếm lệch · tree sha lệch | `data_verify.txt` · `vifinqa_dataset_report.md` |
| **1c** | 🔴 A6 Build ID | build_id == `c6887fb633374fad` · counts khớp 9 giá trị | build_id khác · counts lệch | `dp_build.log` |
| **1d** | Retrieval Ready | `database_bytes == 4239663104` · 4 index đủ · `retrieval-verify` 9/9 | bytes lệch · index thiếu | `retrieval_verify.txt` · `sha256sums.txt` |
| **1** | DATA READY | `snapshots-verify` mọi item PASS, exit 0 · **và** sha256 khớp cả hai DB | bất kỳ `[FAIL]` · sha lệch | `snapshots_verify.txt` |
| **2** | COMPONENT READY | lint/typecheck/docs/test-offline đều exit 0 · 0 failed · skip **đúng 42** | exit ≠ 0 · skip > 42 (conftest đã fail session) | 5 file log |
| **3** | INTEGRATION READY | smoke 10 câu sinh 10 record · qid boundary có cả emit lẫn abstain · `test-integration` 0 failed | exit 2 · record ≠ kỳ vọng | `smoke_10.log` · `smoke_qid.log` · `test_integration.txt` |
| **4** | E2E PASSED | exit 0 · ZIP tồn tại trong `artifacts/submissions/` · validator 0 · replay error 0 · matched==executed · 1012 record | "CHẶN PUBLISH" · exit ≠ 0 · ZIP vắng | `run_full.log` · `submission_manifest.json` · ZIP sha256 |
| **5** | VALIDATION PASSED | sha256 khớp · ZIP 2 build byte-identical · replay độc lập sạch · 10 bất biến ZIP đủ | bất kỳ mục nào vỡ | `evidence/phase5/*` |
| **6** | EVIDENCE COMPLETE | 9 nhóm đủ · `REPRODUCE.md` chạy được · mọi metric có nhãn | thiếu nhóm · metric bỏ trống | toàn bộ `evidence/` |

**Quy tắc chuyển phase:** không sang phase sau khi gate trước chưa đạt.
**Ngoại lệ duy nhất được phép:** Phase 4.3 (V3 shadow) chạy song song, không chặn GATE 4.

---

## 10. FAILURE & RECOVERY PLAN

| # | Failure | Likely Cause | Detection | Recovery | Re-run From |
|---|---|---|---|---|---|
| F1 | `source_fingerprint` lệch | `a6/*.py` hoặc `configs/*.yaml` bị sửa sau 26/08 | GATE 1a | 🛑 DỪNG, hỏi user: revert `7837635…` **hay** chấp nhận build_id mới + cập nhật CẢ HAI manifest | T1.1 |
| F2 | `build_id ≠ c6887` dù F1 pass | Corpus lệch ⇒ `counts` lệch | GATE 1c | Đối chiếu 9 counts, tìm cái lệch → truy về corpus | T1.2 |
| F3 | Corpus đếm lệch | Copy sót · file thừa · OLD bị đụng sau 25/08 | `data-verify` FAIL | Xoá 3 thư mục, copy lại. Vẫn lệch ⇒ đường HF | T1.2 |
| F4 | tree sha ≠ `57fd7ca4…` | File thừa (README/`.DS_Store`/`.gitattributes`) | Hash thủ công | Xoá file ngoài `included_paths` (`baseline_20260825.json:13-17`) | T1.2 |
| F5 | `FileExistsError` khi build snapshot | Thư mục đích đã có `manifest.json` | Traceback | `mv` manifest cũ ra `evidence/`, `rmdir`, chạy lại | T1.7 |
| F6 | `ProjectPathError` lúc import, **mọi lệnh chết** | `active_snapshot.yaml` sai canonical path · `retrieval.source_a6_build_id ≠ a6.build_id` | Traceback ngay cả với `--help` | Sửa YAML theo 4 quy tắc `snapshots.py:93-105` | — |
| F7 | `run` exit 2 ngay lập tức | `verify_active_snapshots(scope="all")` FAIL | stderr liệt kê item | `make snapshots-verify` xem item nào đỏ | GATE 1 |
| F8 | `run` exit 2 với guard | Dùng `--limit/--offset/--question-id` mà thiếu `--no-package` | `main.py:196` | Thêm `--no-package`, hoặc bỏ slice | T3.1 |
| F9 | `FileExistsError` ở run dir | `run_id` đã dùng | Traceback | **ĐỔI `run_id`.** ⛔ Không xoá thư mục cũ (bằng chứng) | T4.1 |
| F10 | "CHẶN PUBLISH", exit 1 | validator error · replay error · matched≠executed | `submission_manifest.json` | Phân loại lỗi, sửa nguyên nhân, chạy lại với `run_id` MỚI | T4.1 |
| F11 | ZIP không byte-identical | `zlib`/`compresslevel` khác · chạy không qua `make` (thiếu `TZ=UTC`) | T5.2 | Chạy lại qua `make`; ghim zlib version vào evidence | T5.2 |
| F12 | Rebuild lệch giữa hai máy | 🔴 `cleaning.py:269` `for ent in set(found)` — `PYTHONHASHSEED` | `dp-rebuild-check` | **Luôn dùng `make`** (set `PYTHONHASHSEED=0`). Fix gốc: `sorted(set(found))` — **1 từ**, nhưng là code change ⇒ cần user duyệt | T1.5 |
| F13 | `test-offline` skip > 42 | Skip mới không nằm trong allowlist | `conftest.py:71` set exit FAIL | Đọc violation, **không** thêm vào allowlist để né | T2.4 |
| F14 | 46 hàm test biến mất im lặng | `importorskip("pandas")` cấp module (P2-3) | So **số collected** giữa các lần | Xác nhận pandas đã cài | T2.4 |
| F15 | `test_answer_gold_provenance.py` `FileNotFoundError` | `curated/dev-legacy/` thiếu (P0-5) | `test-offline` | T1.4 | T1.4 |
| F16 | `package-v3` traceback | thiếu `dataframe/csv/table_cards.csv` | `main.py:428` | Xác nhận `--profile slim --per-table primary` ở T1.6 | T1.6 |
| F17 | `load_aliases` `FileNotFoundError` | thiếu `company_brand_attested_v1.yaml` (P0-6) | `run`/`coverage`/`shadow-v3` chết | **Inspect `configs/retrieval/` TRƯỚC Phase 3** | — |
| F18 | Hết đĩa giữa build | A6 6,5 GiB + retrieval 4 GiB + staging | `No space left` | Dọn đĩa hoặc `export T2P_DATA_ROOT=/volume/khac` | T1.5 |
| F19 | Số emitted khác 561 nhiều | Regression **hoặc** báo cáo cũ | T4.2 | ⛔ **Không tự sửa.** Ghi lại, đối chiếu commit của ACCEPTANCE (`a21eff4c…`), báo user | — |

---

## 11. VALIDATION STRATEGY

### 11.1 Ba tầng, không được trộn

| Tầng | Chứng minh gì | Công cụ | Trạng thái sau plan này |
|---|---|---|---|
| **Structural** | Hệ thống chạy đúng hợp đồng | `validate_zip` · `snapshots-verify` · schema check | ✅ Đạt được |
| **Self-consistency** | Hệ thống nhất quán với chính nó | `replay_zip` (`answer == eval(query)`) · typed-vs-pandas · ZIP determinism | ✅ Đạt được |
| **Correctness** | Đáp án **đúng** | Gold độc lập | ❌ **NOT_MEASURED** — không giải quyết được nội bộ |

🔴 **`AGENTS.md:174` cấm gọi tầng 1–2 là accuracy.** Replay 561/561 nghĩa là *"561 query khớp kết quả pandas của chính nó"*, **không** phải *"561 đáp án đúng"*.

### 11.2 Proxy vs Gold — bảng phải điền trong evidence

| Metric | Loại | Nguồn | Ghi |
|---|---|---|---|
| Route coverage | **PROXY** | `make semantic-coverage` | số thực đo |
| Candidate recall | GOLD (95/1012) | evalkit | 917 câu `NOT_MEASURED` |
| Ranking F2@10 | GOLD (95/1012) | evalkit | như trên |
| Binding exact | — | — | `NOT_MEASURED` |
| Replay consistency | **PROXY** | `replay_zip` | ≠ accuracy |
| Emitted / abstain count | **PROXY** | `records.jsonl` | ⚠️ **không phải "result"** |
| **Answer Accuracy** | **GOLD** | BTC | **NOT_MEASURED** |
| **Execution Accuracy** | **GOLD** | BTC | **NOT_MEASURED** |

### 11.3 Baseline so sánh

| | OLD | NEW kỳ vọng | Diễn giải |
|---|---|---|---|
| Emitted | **1011/1012** (FACT) | ≈561 | ⚠️ Thấp hơn **có chủ đích** (fail-closed) — không phải regression về chất lượng |
| EXECUTION | **0,1225** (FACT, ID 3392) | NOT_MEASURED | Trần theo coverage = 0,5543 |
| Precision cần để hoà OLD | — | **22,10%** | `0,1225 / 0,5543` |

---

## 12. EVIDENCE PACKAGE

```
evidence/
├── REPRODUCE.md                    ← chuỗi command từ clone tới ZIP
├── KNOWN_GAPS.md                   ← P1-1..P1-5, mọi NOT_MEASURED
├── phase0/  system.txt · pip_freeze.txt · env_check.json · source_identity.txt
├── phase1/  source_fingerprint.txt · copy_manifest.txt · data_verify.txt
│            dp_build.log · dp_release.log · a6_verify.txt · a6_manifest_diff.txt
│            retrieval_manifest_expected.json · retrieval_verify.txt
│            retrieval_manifest_diff.txt · sha256sums.txt · snapshots_verify.txt
├── phase2/  lint.txt · typecheck.txt · docs.txt · test_offline.txt · coverage.txt
├── phase3/  smoke_10.log · smoke_qid.log · test_integration.txt
├── phase4/  run_full.log · records.jsonl · manifest.json
│            submission_manifest.json · zip_listing.txt · zip_sha256.txt
├── phase5/  replay.json · determinism_diff.txt · metrics_separated.md
│            vn_number_manual_check.txt
└── phase6/  dp_test_report.{json,txt,xml}
```

**Ba số phải xuất hiện nguyên văn trong evidence:**

```
silver.db     4.140.924.928 B   sha256 fa6c46d6d46b4735f6a23fe1f2b8e2be16c206b712f47b8f22a5f0647f5dc3c8
retrieval.db  4.239.663.104 B   sha256 72d307f8a2bb542a40f97e112456d537b90823e7b57a20eaef04a94545ab6daf
raw tree                        sha256 57fd7ca41903dbb749d774b1ee34373c8243faec7ba0fd91c8b51fb082b0282a
```

---

## 13. REPRODUCIBILITY PLAN

> **Một developer khác clone PROJECT_NEW từ đầu có thể chạy lại E2E không?**
> **Hiện tại: KHÔNG.** Sau plan này: **CÓ, với một điều kiện ngoài Git.**

| Yếu tố | Trạng thái | Ghi chú |
|---|---|---|
| Clean environment | ✅ | `requirements.lock` có hash · `make dp-env-check` |
| Dependency lock | ✅ | `--require-hashes` |
| Configuration | ✅ | `configs/` trong Git · `active_snapshot.yaml` là SSOT |
| **Corpus** | ❌ → ⚠️ | **Không trong Git** (đúng thiết kế). Hai đường: copy từ OLD, hoặc HF `AIGuruTinix/ViFinQA` rev `0450088a…`. ⚠️ **UNKNOWN: revision còn tồn tại không** |
| **A6 + retrieval** | ✅ **rebuild được** | Đây là điểm mạnh thật: `build_id` tất định (`storage.py:85-96`), `index_id` là hàm thuần (`snapshot.py:43-50`). **Không cần phân phối 11 GB** |
| Seed / determinism | ⚠️ | `Makefile:21-26` ép `PYTHONHASHSEED=0 · TZ=UTC · LC_ALL=C.UTF-8`. 🔴 **Chỉ khi đi qua `make`.** `cleaning.py:269` vẫn là lỗ hổng nếu gọi trực tiếp |
| Commands | ⚠️ | CLI khớp README, nhưng chuỗi `dp-build → dp-release` cần tên artifact trung gian **UNKNOWN (P0-7)** |
| Expected outputs | ✅ | Manifest ghim sha256 + bytes + counts cho mọi tầng |

### Việc phải làm để đạt reproducibility đầy đủ

| # | Việc | Vì sao |
|---|---|---|
| R1 | Viết `evidence/REPRODUCE.md` với chuỗi command đã **chạy thật** | Plan này chưa chạy được (sandbox hỏng) |
| R2 | Ghi rõ tên artifact trung gian của `dp-build` sau lần chạy đầu | Đóng P0-7 |
| R3 | Ghim `zlib`/`compresslevel` vào evidence | Byte-identity ZIP phụ thuộc DEFLATE |
| R4 | Đề xuất fix `sorted(set(found))` tại `cleaning.py:269` | Bỏ phụ thuộc `PYTHONHASHSEED`. **BLOCKER → code change → cần user duyệt (Rule 1)** |
| R5 | Ghi lại HF revision + ngày kiểm | Chống drift |
| R6 | Quyết `curated/dev/` vs `curated/dev-legacy/` | Mâu thuẫn tài liệu, cần user |

---

## 14. FINAL E2E ROADMAP

```
┌──────────────────────────────────────────────────────────────────────┐
│ Phase 0 — ENVIRONMENT                                    ~30 phút    │
│ venv · --require-hashes · -e . · dp-env-check · ghim commit          │
│ 🚪 GATE 0: lock_matches_installed=True                               │
└──────────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│ Phase 1 — DATA                                       ~45–60 phút     │
│ 1a source_fingerprint()      🔴 1 GIÂY — LÀM ĐẦU TIÊN                │
│    🚪 GATE 1a: 0719b86ff68679a3 / d4ff2b5cbc589d6c                   │
│ 1b copy corpus từ OLD (~363 MiB)  🚪 GATE 1b: 1973/1012/100          │
│ 1c dp-build FINALIZE=1 → dp-release (~10 phút, 6,5 GiB)              │
│    🚪 GATE 1c: build_id == c6887fb633374fad  ← CỔNG DỪNG CỨNG        │
│ 1d build_retrieval_snapshot.py (~4 GiB)                              │
│    🚪 GATE 1d: 4239663104 B                                          │
│ 🚪 GATE 1: snapshots-verify all PASS + sha256 khớp                   │
└──────────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│ Phase 2 — COMPONENT                                      ~15 phút    │
│ lint · typecheck · docs-check · test-offline · semantic-coverage     │
│ 🚪 GATE 2: mọi lệnh exit 0 · 0 failed · skip đúng 42                 │
└──────────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│ Phase 3 — INTEGRATION                                    ~20 phút    │
│ run --limit 10 --no-package · run --question-id --no-package         │
│ make test-integration                                                 │
│ 🚪 GATE 3: 10 record · có cả emit lẫn abstain · 0 failed             │
└──────────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│ Phase 4 — E2E                                        UNKNOWN runtime │
│ run --run-id submission_candidate_001  (đủ 1012, có package)         │
│ 🚪 GATE 4: exit 0 · ZIP published · validator 0 · replay 0 ·         │
│            matched==executed · 1012 record                            │
│ [tuỳ chọn, song song] shadow-v3 → package-v3                         │
└──────────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│ Phase 5 — VALIDATION                                     ~30 phút    │
│ sha256 · ZIP 2-build byte-identical · replay độc lập ·               │
│ 10 bất biến · 7 metric PHÂN TÁCH · bẫy số VN                         │
│ 🚪 GATE 5                                                             │
└──────────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│ Phase 6 — EVIDENCE                                       ~30 phút    │
│ 9 nhóm · REPRODUCE.md · KNOWN_GAPS.md                                │
│ 🚪 GATE 6: EVIDENCE COMPLETE                                          │
└──────────────────────────────────────────────────────────────────────┘
```

**Tổng ước lượng:** ~3–4 giờ người, cộng runtime E2E chưa xác định.
**Đường găng:** GATE 1a → 1b → 1c → 1d → 1 → 3 → 4.
**Điểm rủi ro cao nhất:** GATE 1c. Được **giảm thiểu gần như hoàn toàn** bằng GATE 1a — 1 giây trả lời cho câu hỏi mà bình thường phải trả bằng 10 phút CPU.

---

## 15. DEFINITION OF DONE

### Checklist

```
[ ] Environment verified          GATE 0 — dp-env-check lock_matches_installed=True
[ ] Dependencies verified         GATE 0 — pip install --require-hashes không lỗi
[ ] Build ID predicted            GATE 1a — 0719b86ff68679a3 / d4ff2b5cbc589d6c
[ ] Data verified                 GATE 1b — 1973 txt · 1012 câu · 100 ticker · tree sha
[ ] Database verified             GATE 1c/1d — build_id c6887… · retrieval 4239663104 B
[ ] Artifacts verified            GATE 1 — snapshots-verify all PASS + sha256 khớp
[ ] Component smoke tests passed  GATE 2 — lint/typecheck/docs/test-offline exit 0
[ ] Integration tests passed      GATE 3 — smoke 10 câu + test-integration 0 failed
[ ] E2E pipeline completed        GATE 4 — exit 0 + ZIP published
[ ] Output validated              GATE 4 — validator 0 · replay 0 · matched==executed
[ ] Regression checked            GATE 5 — đối chiếu OLD 1011 vs NEW ≈561 (có chủ đích)
[ ] Metrics collected             GATE 5 — 7 metric PHÂN TÁCH, NOT_MEASURED ghi rõ
[ ] Reproducibility verified      GATE 5 — ZIP 2-build byte-identical
[ ] Evidence package generated    GATE 6 — 9 nhóm + REPRODUCE.md + KNOWN_GAPS.md
```

### DONE khi và chỉ khi

```
Execution successful          exit 0
+ Expected output exists      artifacts/submissions/submission_<run_id>.zip
+ Output contract valid       10 bất biến ZIP (§5)
+ Correctness validation      validator 0 · replay 0 · matched == executed
+ Required metrics            7 metric ghi riêng, thiếu gold ⇒ NOT_MEASURED
+ Evidence captured           9 nhóm đầy đủ
```

### KHÔNG được tuyên bố DONE nếu

- Lệnh chạy không lỗi nhưng **chưa đọc `submission_manifest.json`** (Rule 4)
- Gọi replay consistency hay route coverage là "accuracy" (`AGENTS.md:174`)
- Sửa tay `manifest.json` để qua gate — **`snapshots-verify` SẼ PASS với manifest giả** (P2-2)
- Bỏ `--require-hashes` để cài cho xong
- Thêm skip vào allowlist để né `conftest.py:71`
- Xoá run dir cũ để tái dùng `run_id` (phá bất biến, mất bằng chứng)

### E2E PASS nghĩa là gì — và KHÔNG nghĩa là gì

| ✅ Chứng minh | ❌ KHÔNG chứng minh |
|---|---|
| Pipeline chạy từ corpus tới ZIP | Đáp án **đúng** |
| Lineage truy ngược được, có checksum | NEW tốt hơn OLD |
| Mọi query phát ra tự nhất quán | Sẽ ăn điểm cao hơn 0,1225 |
| ZIP tất định, tái lập được | Retrieval hay parser đủ tốt |
| Fail-closed hoạt động đúng thiết kế | 451 câu abstain là lựa chọn đúng |

> **Câu duy nhất kết thúc tranh luận vẫn là: nộp một lần lên leaderboard.**
> Plan này đưa NEW tới **đủ điều kiện để nộp**. Nó không thay thế việc nộp.

---

## PHỤ LỤC — Việc cần người dùng quyết trước khi chạy

| # | Vấn đề | Vì sao cần user |
|---|---|---|
| **Q1** | `curated/dev/` hay `curated/dev-legacy/`? | `data/README.md:9` và `folder_migration_20260825.json:34` mâu thuẫn; cả hai đích đều vắng. `CLAUDE.md §6`: phát hiện cùng thông tin ở hai nơi ⇒ báo, không tự chọn |
| **Q2** | Có được sửa `cleaning.py:269` thành `sorted(set(found))` không? | Rule 1 — plan không sửa code. Nhưng đây là lỗ hổng determinism duy nhất còn lại |
| **Q3** | `ACCEPTANCE:203-205` trỏ 3 thư mục artifact không tồn tại | Bị xoá khi refactor, hay report viết về máy khác? Ảnh hưởng độ tin cậy của mọi số trong report đó |
| **Q4** | V3 emitted = 269 (README:12) hay 207 (ACCEPTANCE:158)? | Không đặt được gate cho Phase 4.3 khi chưa biết số nào đúng |
| **Q5** | Mục tiêu là **chỉ chứng minh E2E** hay **tạo bài nộp thật**? | Nếu chỉ chứng minh: dừng ở Phase 3 + smoke, tiết kiệm 11 GB và phần lớn thời gian |

## PHỤ LỤC — UNKNOWN cần inspect trước khi chạy

| # | UNKNOWN | Cần inspect |
|---|---|---|
| ~~U1~~ | ~~Tên artifact trung gian của `dp-build`~~ | ✅ **ĐÓNG 27/08** — xem §16 |
| ~~U2~~ | ~~`company_brand_attested_v1.yaml` có tồn tại?~~ | ✅ **ĐÓNG 27/08** — có, cùng `company_alias_v1.yaml`, `company_brand_v1.yaml`, `eval_v1.yaml`, `models/linear_reranker_v1.json` |
| U3 | Công cụ tính `payload_tree_sha256` | Không tìm thấy script sẵn — **chặn T1.3** |
| U4 | `tools/replay_submission_v1.py` có ở NEW không? | Glob — chặn T5.3 |
| U5 | HF revision `0450088a…` còn tồn tại? | Chỉ cần nếu không copy được từ OLD |
| U6 | Runtime thật của `run` trên 1012 câu | Không có benchmark ở repo nào |

---

## 16. ĐÓNG U1 + U2 — bố cục artifact chính xác của `dp-build`

**Cập nhật 2026-08-27.** GATE 1a đã PASS trên máy người dùng (`source_hash=0719b86ff68679a3`, `config_hash=d4ff2b5cbc589d6c`). Hai UNKNOWN chặn T1.6 đã đóng bằng cách đọc `tools/build_runner.py` (220 dòng) + `pipelines/a6/cli.py`.

### 16.1 `build_runner.py` set gì (FACT — `:141-148`)

```python
DATA_PIPELINE_SCRATCH    = <OUTPUT>
DATA_PIPELINE_CONFIG     = <config đã resolve>
DATA_PIPELINE_CORPUS     = <input đã resolve>
DATA_PIPELINE_BRONZE     = <OUTPUT>/bronze/catalog_v2.sqlite
DATA_PIPELINE_SILVER_DIR = <OUTPUT>/silver
PYTHONPATH=src · PYTHONHASHSEED=0 · TZ=UTC · LC_ALL=LANG=C.UTF-8
```

🟢 **`build_runner.py` TỰ set môi trường tất định** (`:147`) ⇒ đường build được bảo vệ khỏi `cleaning.py:269` **kể cả khi không đi qua `make`**. Đây là tin tốt, thu hẹp P2-1 xuống chỉ còn ảnh hưởng `text2pandas run`.

Vì `_work(name) = SCRATCH / name` (`cli.py:96-98`) và `SCRATCH = <OUTPUT>`, bố cục sau `make dp-build OUTPUT=<OUT> FINALIZE=1` là:

```
<OUT>/
├── build_invocation.json        preflight: fingerprint · commit · dirty · env · disk   ← EVIDENCE MIỄN PHÍ
├── manifest.json                ⚠️ manifest CORPUS (snapshot ghi) — KHÔNG phải build manifest
├── catalog.sqlite               work
├── silver.sqlite                work
├── quality_report.json          work
├── build.log
├── bronze/
│   └── catalog_v2.sqlite        ← BRONZE=
├── silver/
│   └── <build_id>/
│       ├── silver.sqlite        ← DB=
│       ├── manifest.json        ← manifest BẢN DỰNG (build_id · counts · silver_sha256)
│       └── quality_report.json  ← QUALITY=
└── completion_marker.json       ← chứa "build_id"  ⭐ NGUỒN ĐỌC GATE 1c
```

Nếu build hỏng: `<OUT>/BUILD_FAILED` được ghi (`:179-181`) — không để lại thứ trông giống candidate hợp lệ.

### 16.2 T1.5 / T1.6 — lệnh CHÍNH XÁC (thay thế bản UNVERIFIED)

```bash
OUT=artifacts/runs/a6/staging_A

make dp-build CONFIG=configs/vifinqa_silver_v1.yaml \
              INPUT=data/raw/btc/financial_statements \
              OUTPUT=$OUT \
              FINALIZE=1

# 🚪 GATE 1c — đọc từ máy, không đoán:
python -c "import json;print(json.load(open('$OUT/completion_marker.json'))['build_id'])"
# PHẢI in: c6887fb633374fad

BID=c6887fb633374fad
make dp-release DB=$OUT/silver/$BID/silver.sqlite \
                BRONZE=$OUT/bronze/catalog_v2.sqlite \
                QUALITY=$OUT/silver/$BID/quality_report.json \
                OUTPUT=data/processed/a6/$BID \
                REPORT_DIR=artifacts/reports/a6_rebuild
```

🟢 **Xác nhận độc lập:** `tools/run_acceptance_chain.sh:96-101` dùng **đúng ba đường dẫn này**:
```bash
make dp-release DB="$A/silver/$BID/silver.sqlite" \
                BRONZE="$A/bronze/catalog_v2.sqlite" \
                QUALITY="$A/silver/$BID/quality_report.json"
```

### 16.3 Bốn cạm bẫy đã lộ ra

| # | Bẫy | Bằng chứng | Xử lý |
|---|---|---|---|
| **B1** | **`MIN_FREE_GB = 40.0` hardcode**, kiểm trên `Path.cwd()`. `make dp-build` **không** truyền `--allow-low-disk` ⇒ đĩa <40 GB thì **exit 2 ngay preflight** | `build_runner.py:17,92-95` | `df -h .` **TRƯỚC** khi chạy. Đây là gate rẻ nhất còn lại |
| **B2** | **Hai file cùng tên `manifest.json`**: `<OUT>/manifest.json` là manifest CORPUS; `<OUT>/silver/<bid>/manifest.json` mới là manifest BẢN DỰNG | `cli.py:151-152` vs `:471` | `dp-release` tự suy `manifest = db.parent/"manifest.json"` (`:638`) rồi **`_is_build_manifest` chặn** (`:639`) ⇒ trỏ `--db` sai sẽ **fail loud exit 2**, không im lặng. Nhưng phải trỏ đúng `silver/<bid>/silver.sqlite`, **không** phải `<OUT>/silver.sqlite` |
| **B3** | Chạy `dp-release` **độc lập** thì `DATA_PIPELINE_BRONZE` không còn set ⇒ `--bronze` mặc định rơi về `artifacts/runs/a6/bronze/catalog_v2.sqlite` — **ghép nhầm bronze của build khác** | `cli.py:65-67,637` | **Luôn truyền `BRONZE=` tường minh.** Đây đúng là lỗi mà `Makefile:113-121` cảnh báo |
| **B4** | `run_acceptance_chain.sh` mặc định `BID=b3e9684004679ffb`, `A=artifacts/rc2/buildA6` — **đường dẫn của OLD, không tồn tại ở NEW** | `:17-31` | Script có tham số hoá; nếu dùng phải override `BID/A/B/BASE`. Không chạy với mặc định |

### 16.4 🔴 Phát hiện làm đổi phạm vi: `GATE_REPORT=` đắt hơn tưởng

`tools/gate_report.py` sinh `gate_report.json`, nhưng `run_acceptance_chain.sh:113-121` cho thấy nó cần **7 report thượng nguồn** với `--require-all`:

```
rebuild_check · no_loss · differential · readiness · unresolved · replay · quality
```

Và `rebuild_check --mode final` (`:78-80`) so **HAI bản dựng độc lập A và B** ⇒ **phải build 2 lần** (~2× 10 phút, ~2× 6,5 GiB).

**Nhưng `--gate-report` là TUỲ CHỌN cho `dp-release`** (`cli.py:653` dùng `getattr(..., None)`). Thiếu nó, manifest ghi `not_accepted_no_gate_report` — **và `snapshots-verify` KHÔNG kiểm trường đó** (`snapshots.py:180-197` chỉ kiểm `build_id`, `silver.db`, schema, `build_meta.build_id`, `table_cards` count).

⇒ **Hai đường, người dùng chọn (đây chính là Q5 nay đã cụ thể hoá):**

| | **FAST — chỉ để chạy E2E** | **FULL — acceptance-grade** |
|---|---|---|
| Build | 1 lần (A) | 2 lần (A + B) |
| Thời gian build | ~10 phút | ~20 phút |
| Đĩa | ~6,5 GiB + 4 GiB | ~13 GiB + 4 GiB |
| `dp-release` | **không** `GATE_REPORT=` | có, sau chuỗi 7 bước |
| Manifest label | `not_accepted_no_gate_report` | `release_label` + `acceptance_status` thật |
| `snapshots-verify` | ✅ **PASS** | ✅ PASS |
| `text2pandas run` | ✅ **chạy được** | ✅ chạy được |
| Dùng khi | Mục tiêu là **E2E + nộp bài** | Mục tiêu là **gói bàn giao có bằng chứng acceptance** |

**Khuyến nghị: đi đường FAST trước.** Nó đủ để đóng GATE 1→4 và tạo submission. Đường FULL chỉ cần khi đóng gói bàn giao cho bên thứ ba — và có thể làm sau, trên cùng corpus, không phải làm lại từ đầu.
