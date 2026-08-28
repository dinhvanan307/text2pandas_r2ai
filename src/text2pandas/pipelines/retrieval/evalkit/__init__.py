"""Khung ĐÁNH GIÁ + CHẨN ĐOÁN tầng Retrieval. Không sinh đáp án.

    src/text2pandas/pipelines/retrieval/evalkit/
      metrics.py   hàm thuần — recall/precision/F2 thật/MRR/nDCG, test offline
      taxonomy.py  6 rổ thất bại, phủ kín, mỗi câu ĐÚNG MỘT nhãn
      stages.py    tách bạch sinh-ứng-viên / xếp-hạng / xếp-hạng-lại bằng KIỂU
      goldset.py   ProxyGoldV2 (đã bỏ vòng tròn theo mã) · ManualGold · FreeScan
      runner.py    collect hai pha, checkpoint có cfg_sha, attribution lọc cứng
      report.py    text + JSON + CSV, mọi bảng kèm MẪU SỐ
      cli.py       điểm vào: collect | report | ab

Ranh giới phạm vi, cố ý: KHÔNG import `pandas`, KHÔNG sinh `answer`, KHÔNG chạm
`src/text2pandas/`. Tầng này chỉ trả lời một câu hỏi — "bảng đúng có được tìm
ra và xếp lên cao không" — và trả lời nó bằng số có mẫu số.
"""

from __future__ import annotations

__all__ = ["SCHEMA_VERSION"]

# Public package marker; keep synchronized with ``evalkit.runner`` so external
# checkpoint tooling cannot stamp the historical v1 value by importing here.
SCHEMA_VERSION = "evalkit-13"
