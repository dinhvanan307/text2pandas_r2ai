# RC-00 · §3.2 — MỘT giao diện lệnh duy nhất cho người review.
#
# Người nhận gói không được phải đoán CLI nội bộ. Bảy target dưới đây là hợp
# đồng; chúng gọi CLI hiện có ở bên trong, nhưng tên và tham số thì cố định.
#
# Quy tắc (§3.2), thi hành chứ không chỉ ghi:
#   · mọi target chạy từ repository root
#   · không absolute path của máy dev
#   · lệnh thất bại trả exit code khác 0  -> .SHELLFLAGS có -e -o pipefail
#   · không nuốt exception rồi vẫn sinh package
#   · mọi lệnh ghi invocation và environment vào log

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PY      ?= python
SRC     := src
export PYTHONPATH := $(SRC)

# Môi trường TẤT ĐỊNH (RC-13). Đặt ở đây, không rải trong từng script, để
# build A và build B không thể vô tình chạy khác nhau.
export PYTHONHASHSEED := 0
export TZ             := UTC
export LC_ALL         := C.UTF-8
export LANG           := C.UTF-8

.PHONY: help paths-check lint typecheck docs-check test-offline test-integration test-historical \
        verify-active-candidate semantic-coverage snapshots-verify \
        semantic-gold-v2-prepare semantic-gold-v2-local-e2e \
        data-verify a6-verify retrieval-verify materialize-h0 ci \
        dp-env-check dp-test dp-build dp-measure dp-release dp-verify \
        dp-rebuild-check dp-package

help:
	@grep -E '^[a-z0-9-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-20s\033[0m %s\n",$$1,$$2}'

paths-check: ## In repository/data/artifact roots và kiểm active snapshot config
	@test -f configs/datasets/active_snapshot.yaml
	@$(PY) -c 'from text2pandas.infrastructure.paths import ProjectPaths; p=ProjectPaths.discover(); print("repo_root="+str(p.repo_root)); print("data_root="+str(p.data_root)); print("artifact_root="+str(p.artifact_root)); print("active_snapshot="+str(p.active_snapshot_config))'

lint: ## Correctness-oriented static gate (syntax, names, closure and finite-value traps)
	@$(PY) -m ruff check --select E9,F63,F7,F82,B,PLR0124,PLE2515,F841 src tests

typecheck: ## Strict mypy cho production architecture (domain/application/infrastructure/interface)
	@$(PY) -m mypy src/text2pandas/domain src/text2pandas/application \
		src/text2pandas/infrastructure src/text2pandas/interface

docs-check: ## Validate relative links in tracked Markdown files
	@$(PY) tools/check_docs.py

test-offline: ## Unit/contract/regression không cần materialized artifacts
	@$(PY) -m pytest -q -m "not integration and not historical"

test-integration: ## Active gate cần raw/A6/retrieval; không đọc pre-refactor ZIP
	@$(PY) -m pytest -q -m "integration and not historical"

test-historical: ## Optional monitor; cần mount authentic pre-refactor artifacts
	@$(PY) -m pytest -q -m historical

verify-active-candidate: ## Gate hai canonical run. RUN_A= RUN_B= [REPORT_OUT=]
	@test -n "$(RUN_A)" -a -n "$(RUN_B)" \
	  || { echo "LỖI: cần RUN_A=<run-id> RUN_B=<run-id>" >&2; exit 2; }
	@$(PY) tools/execution/verify_active_candidate.py \
	  --run-a "$(RUN_A)" --run-b "$(RUN_B)" \
	  $(if $(REPORT_OUT),--report-out "$(REPORT_OUT)")

semantic-coverage: ## Đo route coverage trên 1.012 câu; không thay thế accuracy eval
	@$(PY) -m text2pandas.interface.cli.main coverage --summary-only

semantic-gold-v2-prepare: ## Tạo packet Phase 1.5 prediction-blind; PROTOCOL= PACKET=
	@test -n "$(PROTOCOL)" -a -n "$(PACKET)" \
	  || { echo "LỖI: cần PROTOCOL=<path> PACKET=<artifacts/path>" >&2; exit 2; }
	@$(PY) tools/evaluation/prepare_semantic_gold_v2.py \
	  --protocol "$(PROTOCOL)" --output "$(PACKET)"

semantic-gold-v2-local-e2e: ## Chạy WP3-WP10 local 2 lần; MODE= PACKET= RUN_A= RUN_B= REPORT=
	@test "$(MODE)" = "LOCAL_SYNTHETIC" \
	  || { echo "LỖI: MODE phải là LOCAL_SYNTHETIC" >&2; exit 2; }
	@test -n "$(PACKET)" -a -n "$(RUN_A)" -a -n "$(RUN_B)" -a -n "$(REPORT)" \
	  || { echo "LỖI: cần PACKET= RUN_A= RUN_B= REPORT=" >&2; exit 2; }
	@SEMANTIC_GOLD_V2_MODE="$(MODE)" $(PY) \
	  tools/evaluation/run_semantic_gold_v2_local_e2e.py \
	  --packet "$(PACKET)" --run-a "$(RUN_A)" --run-b "$(RUN_B)" \
	  --report "$(REPORT)" $(if $(INCLUDE_RESERVE),--include-reserve)

materialize-h0: ## Tái tạo adjudication ledger + ZIP determinism report; FORCE=1 để ghi đè
	@$(PY) tools/execution/materialize_h0.py $(if $(FORCE),--force)

snapshots-verify: ## Kiểm toàn bộ active raw → A6 → retrieval lineage
	@$(PY) -m text2pandas.interface.cli.main verify all

data-verify: ## Kiểm active raw snapshot
	@$(PY) -m text2pandas.interface.cli.main verify raw

a6-verify: ## Kiểm active A6 identity và table-card count
	@$(PY) -m text2pandas.interface.cli.main verify a6

retrieval-verify: ## Kiểm retrieval identity, size và index contract
	@$(PY) -m text2pandas.interface.cli.main verify retrieval

ci: lint typecheck docs-check test-offline ## Local equivalent của CI offline gate

## ── RC-00 ────────────────────────────────────────────────────────────────
dp-env-check: ## In OS/Python/SQLite/deps/commit/config hash — chạy TRƯỚC mọi thứ
	# KHÔNG truyền `--corpus` khi người dùng không chỉ định: để `env_check` tự
	# đọc `corpus.root` từ config. Bản đầu đặt mặc định `data/raw/btc`
	# ngay tại đây, nên nó ĐÈ LÊN config và băm nhầm 15 tệp `_codebase/prompts`
	# vào `corpus_hash` — hai nguồn sự thật cho cùng một đường dẫn.
	@$(PY) tools/env_check.py --config "$(or $(CONFIG),configs/vifinqa_silver_v1.yaml)" \
	                          $(if $(INPUT),--corpus "$(INPUT)")

## ── RC-11 ────────────────────────────────────────────────────────────────
dp-test: ## Chạy full test, ghi report JSON. REPORT_DIR=<path>
	@test -n "$(REPORT_DIR)" || { echo "LỖI: cần REPORT_DIR=<path>" >&2; exit 2; }
	@$(PY) tools/run_tests.py --report-dir "$(REPORT_DIR)"

## ── RC-12 / RC-13 ────────────────────────────────────────────────────────
dp-build: ## Build Silver. CONFIG= INPUT= OUTPUT= [FINALIZE=1]  (OUTPUT phải CHƯA tồn tại)
	# FINALIZE=1 chạy tiếp `quality` + `publish` trong CÙNG output. BẮT BUỘC cho
	# cả A lẫn B nếu dùng C0-final làm acceptance (B0-06), và bắt buộc để có
	# manifest BẢN DỰNG — thiếu nó, `dp-release` đọc phải manifest CORPUS do
	# `snapshot` ghi (trùng tên tệp) và phát hành với `build_id: "unknown"`.
	#
	# Không có đường truyền cờ này thì giao diện hợp đồng KHÔNG dựng nổi một
	# candidate hợp lệ — phải gọi thẳng `build_runner.py`, tức `make` thôi là
	# chưa đủ, và đó là một hợp đồng nói dối.
	@test -n "$(CONFIG)" -a -n "$(INPUT)" -a -n "$(OUTPUT)" \
	  || { echo "LỖI: cần CONFIG= INPUT= OUTPUT=" >&2; exit 2; }
	@$(PY) tools/build_runner.py --config "$(CONFIG)" --input "$(INPUT)" \
	                             --output "$(OUTPUT)" $(if $(FINALIZE),--finalize)

## ── RC-12 ────────────────────────────────────────────────────────────────
dp-measure: ## Đo toàn bộ chỉ số trên một DB. DB= REPORT_DIR=
	@test -n "$(DB)" -a -n "$(REPORT_DIR)" || { echo "LỖI: cần DB= REPORT_DIR=" >&2; exit 2; }
	@$(PY) tools/measure_all.py "$(DB)" -o "$(REPORT_DIR)"

## ── RC-21 ────────────────────────────────────────────────────────────────
dp-release: ## Dựng thư mục phát hành. DB= BRONZE= QUALITY= OUTPUT= REPORT_DIR= GATE_REPORT=
	# B0-01 · BỐN artifact phải được chỉ ĐÍCH DANH, không có mặc định ngầm.
	#
	# Bản trước chỉ truyền `--db`, nên `--bronze` rơi về biến toàn cục
	# `BRONZE_OUT`: release có thể ghép silver.sqlite của build B với
	# catalog.sqlite của build A mà KHÔNG AI BIẾT — hai artifact khác build
	# nằm trong cùng một gói phát hành, và không có trường nào ghi lại điều đó.
	#
	# Bắt buộc ở tầng Makefile, không chỉ ở CLI: đây là giao diện mà người
	# review dùng, và một mặc định ngầm ở đây vô hiệu hoá phép kiểm ở dưới.
	@test -n "$(DB)" -a -n "$(BRONZE)" -a -n "$(QUALITY)" \
	     -a -n "$(OUTPUT)" -a -n "$(REPORT_DIR)" \
	  || { echo "LỖI: cần DB= BRONZE= QUALITY= OUTPUT= REPORT_DIR=" >&2; exit 2; }
	# C3 · GATE_REPORT là nguồn DUY NHẤT của `release_label` và
	# `acceptance_status`. Không truyền thì manifest ghi
	# `not_accepted_no_gate_report` — nói thẳng là chưa có cổng, thay vì suy ra
	# một trạng thái nghe có vẻ đúng.
	@$(PY) -m text2pandas.pipelines.a6.cli release --db "$(DB)" --bronze "$(BRONZE)" \
	                                     --quality "$(QUALITY)" \
	                                     --out "$(OUTPUT)" \
	                                     --report-dir "$(REPORT_DIR)" \
	                                     $(if $(GATE_REPORT),--gate-report "$(GATE_REPORT)")

## ── RC-23 ────────────────────────────────────────────────────────────────
dp-package: ## Đóng gói zip tất định (không __MACOSX/.DS_Store). DIR= OUT=
	@test -n "$(DIR)" -a -n "$(OUT)" || { echo "LỖI: cần DIR= OUT=" >&2; exit 2; }
	@$(PY) tools/package_release.py --dir "$(DIR)" --out "$(OUT)"

## ── RC-24 ────────────────────────────────────────────────────────────────
# PACKAGE la tep ZIP, KHONG phai thu muc da giai nen. Verifier tu tao thu muc
# tam va giai nen - verify thang thu muc vua build la kiem MOT THU KHAC voi
# thu se gui di (review 28 §RC-24).
dp-verify: ## Verify tu ban giai nen sach. PACKAGE=<file.zip> [TYPE=release|source]
	@test -n "$(PACKAGE)" || { echo "LOI: can PACKAGE=<file.zip>" >&2; exit 2; }
	@$(PY) tools/verify_package.py --package "$(PACKAGE)" --type "$(or $(TYPE),release)"

## ── RC-14 ────────────────────────────────────────────────────────────────
# Nhan HAI thu muc build da co, khong tu build lai: build A va B phai la hai
# process doc lap (RC-13), nen viec chay chung thuoc dp-build.
dp-rebuild-check: ## So hai clean rebuild. BUILD_A= BUILD_B= [REPORT=]
	@test -n "$(BUILD_A)" -a -n "$(BUILD_B)" \
	  || { echo "LOI: can BUILD_A= BUILD_B=" >&2; exit 2; }
	@$(PY) tools/rebuild_check.py --build-a "$(BUILD_A)" --build-b "$(BUILD_B)" \
	                              $(if $(REPORT),--report "$(REPORT)")
