# SEMANTIC PARSER WAVE 6 — MODEL DRAFT CHECKPOINT

**Ngày:** 2026-08-31  
**Repository:** Text2Pandas  
**Branch:** `mentor-grounded-v6`  
**Kết luận:** `COMPLETE_PENDING_HUMAN_REVIEW`  
**Promotion gate:** `BLOCKED`

## 1. Kết quả điều hành

Đã triển khai và chạy hết scope 60 QID của bước tạo semantic draft bằng model
`qwen2.5:14b`. Generator chỉ nhận câu hỏi và ontology hints; không đọc parser prediction,
retrieval output, answer hoặc gold runtime. Toàn bộ 60 record được giữ trong mẫu số,
kể cả record không tạo được AST hợp lệ.

Kết quả cuối:

| Chỉ số | Giá trị |
| --- | ---: |
| Scope hoàn tất | 60/60 |
| Development/Holdout | 40/20 |
| Draft đạt structural gates (`OK`) | 16 |
| Draft fail-closed (`UNRESOLVED`) | 44 |
| Human-reviewed | 0 |
| Independent gold | `false` |
| Correctness | `NOT_MEASURED` |

`16 OK` chỉ là **structural coverage 26,67%**, không phải parser accuracy. Không có draft
nào được đưa vào SemanticParser, Canonical V2 hoặc submission.

## 2. Artifacts bàn giao

Run directory:

- [generation state](../../artifacts/runs/evaluation/semantic-parser-wave6-model-draft-20260831-v4/generation_state.json)
- [generation summary](../../artifacts/runs/evaluation/semantic-parser-wave6-model-draft-20260831-v4/generation_summary.json)
- [60 model drafts](../../artifacts/runs/evaluation/semantic-parser-wave6-model-draft-20260831-v4/model_draft.jsonl)
- [60-record user review queue](../../artifacts/runs/evaluation/semantic-parser-wave6-model-draft-20260831-v4/user_review_queue.jsonl)
- [raw attempts](../../artifacts/runs/evaluation/semantic-parser-wave6-model-draft-20260831-v4/attempts)
- [Q629 attempts trước hotfix](../../artifacts/runs/evaluation/semantic-parser-wave6-model-draft-20260831-v4/attempts_pre_hotfix)
- [machine-readable provenance](../../provenance/semantic_parser/semantic_parser_wave6_model_draft_checkpoint.json)

| Artifact | Records | SHA-256 |
| --- | ---: | --- |
| `model_draft.jsonl` | 60 | `8ff74cee54127ad8fda96ba73110e852203637b4f447720d3ea77db64f439e38` |
| `user_review_queue.jsonl` | 60 | `6b66b8377a9d2e81505d48abea6c7b95c70ef29783df257dafd81b39603e079f` |
| `generation_state.json` | 1 | `ff58de221f3bf7d4a415e16dec9c85ab12fc21c173dcc5f8a7a9ca7af836134e` |
| `generation_summary.json` | 1 | `a57c1e1fcb44784b95ab31dcb8076e47ad867b9395361f291e762e3e6e259ab6` |

## 3. Governance và identity

| Thành phần | Giá trị |
| --- | --- |
| Scope SHA-256 | `9d77ec98fd7a1c2562ec94e4929d023dfbb0552560515c187b20593226d44899` |
| Prompt SHA-256 | `1bcb919e46e43cd9f48e57bfd2173d92293f70dd07bdc40b4c0f8d87a2b3ae03` |
| Response schema SHA-256 | `f6553272dd794a5fa1bbd7b4512f5a08b6c4d4488b18cd3c2cbe3a911ae1b791` |
| Protocol SHA-256 | `09f3ff48b8f3d2d97987a2a7c88b1461103a80dfd08b069f0aa0fadc35104aa6` |
| Ontology fingerprint | `bdef88d94b814ae60109f3da486a627d02dfbbe5d1e3ad6ede942598532644c8` |
| Model digest | `sha256:7cdf5a0187d5c58cc5d369b255592f7841d1c4696d45a8c8a9489440385b22f6` |

Mọi draft có:

- `review_status=MODEL_DRAFT_PENDING_HUMAN_REVIEW`;
- `independent_human_gold=false`;
- question checksum và split cố định;
- tối đa ba attempts;
- raw response và validation error riêng;
- AST chỉ được giữ khi schema, dimension, period, mention closure và semantic AST validator đều PASS.

## 4. Kết quả theo split

| Split | Records | `OK` | `UNRESOLVED` | Structural coverage |
| --- | ---: | ---: | ---: | ---: |
| Development | 40 | 11 | 29 | 27,50% |
| Holdout | 20 | 5 | 15 | 25,00% |
| **Tổng** | **60** | **16** | **44** | **26,67%** |

Không dùng development output để đổi prompt trước holdout. Không mở correctness metric vì
chưa có human adjudication.

## 5. Failure profile

Generator lưu 163 raw responses và 147 validation errors. Phân loại error:

| Error class | Số attempt |
| --- | ---: |
| Invalid AST schema | 72 |
| AST semantic validation | 26 |
| Missing AST output | 17 |
| Metric mention không được AST sử dụng | 16 |
| Output dimension mismatch | 12 |
| Metric mention không align được câu hỏi | 3 |
| JSON decode | 1 |

Tỷ lệ `UNRESOLVED` cao cho thấy model draft hiện tại chưa thể thay reviewer hoặc trở thành
runtime oracle. Fail-closed validator đang chặn đúng các lỗi schema và semantic thay vì tăng
coverage bằng AST không an toàn.

## 6. Blocker và hotfix trong quá trình chạy

Sau 21 record, generator gặp exception khi tạo fallback cho Q629: câu hỏi có basis rõ
`công ty mẹ`, trong khi failure frame để `basis=null`. Validator từ chối đúng, nhưng wrapper
fallback không bắt được lỗi lần hai.

Fix:

1. failure draft kế thừa explicit basis `separate`/`consolidated` từ câu hỏi;
2. thêm regression test cho unresolved record có basis;
3. sửa typing của `validation_feedback` thành tuple;
4. commit `b4c7313`;
5. lưu riêng 6 raw/error files Q629 trước hotfix;
6. ghi source transition trong generation state;
7. resume run, nhận đúng 21 cached records và hoàn tất 39 record còn lại.

Q629 sau hotfix được đóng đúng:

```text
structural_status=UNRESOLVED
basis=separate
expected_ast=null
```

Prompt, schema, scope, ontology và model digest không thay đổi qua source transition.

## 7. Verification

| Gate | Kết quả |
| --- | --- |
| Scope QID exact match | PASS, 60/60 unique |
| Draft/review queue count | PASS, 60/60 |
| All records silver | PASS |
| Review decisions empty | PASS |
| `OK` record có AST | PASS, 16/16 |
| `UNRESOLVED` không có AST | PASS, 44/44 |
| Unit regression tests | PASS, 7/7 |
| Lint | PASS |
| Typecheck | PASS, 122 source files |
| Offline tests | PASS, 2.460 passed, 42 skipped, 29 deselected |
| Integration tests | PASS, 22 passed, 2.509 deselected |
| Docs link check | BLOCKED bởi 15 broken links lịch sử ngày 29/08 |

15 broken links đã tồn tại trong các báo cáo cũ và trỏ tới artifacts không có trong checkout;
không link nào do implementation này tạo. Không sửa ngoài scope hoặc hạ gate để che blocker.

## 8. Trạng thái plan sau checkpoint

| Phase | Trạng thái | Bằng chứng |
| --- | --- | --- |
| P0 parser-only baseline | PASS | 1.012 QID, correctness `NOT_MEASURED` |
| P1 model draft 60 QID | COMPLETE | 16 `OK`, 44 `UNRESOLVED` |
| P1 independent A/B/C gold | BLOCKED | A 0/60, B 0/60, C 0/60 |
| P2 CompositionFrame runtime | NOT STARTED | Bị chặn bởi independent review |
| P3 nested parser | NOT STARTED | Bị chặn bởi independent review |
| P4–P7 integration/evaluation | NOT STARTED | Bị chặn bởi independent review |

## 9. Việc người dùng cần review

Mở `user_review_queue.jsonl` và với từng QID:

1. `accept` nếu semantic frame/AST hoàn toàn đúng;
2. `correct` và điền annotation chuẩn nếu draft sai;
3. `reject` nếu câu hỏi thực sự ambiguous/unresolvable;
4. ghi reviewer identity và source evidence đã kiểm tra.

Model draft có thể hỗ trợ tốc độ review nhưng không thay thế ba vai trò độc lập A/B/C. Chỉ
khi packet A/B/C đạt 60/60, ba identity khác nhau và audit trả `READY_TO_SEAL` mới được mở
Phase 2 và dùng 40 development records để sửa runtime. Holdout 20 tiếp tục sealed tới khi
implementation freeze.

## 10. Kết luận

Đã hoàn tất phần có thể tự động hóa an toàn của plan và tạo đủ 60 review records. Không có
bằng chứng accuracy mới, không có candidate ZIP và baseline leaderboard không thay đổi.
Bottleneck thực tế tiếp theo là human semantic adjudication, không phải thêm runtime rules
dựa trên silver draft chưa được kiểm chứng.
