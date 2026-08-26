# Annotation guideline — semantic gold v1

Every assumption an annotator is allowed to make is written here. If a case
requires an assumption **not** listed, the annotator must mark it
`annotation_status = AMBIGUOUS` and say why, rather than inventing a rule.

## 0. What may and may not be looked at

**Allowed:** the question text; general Vietnamese financial/accounting meaning;
the A6 corpus CSVs (for provenance only).

**Forbidden:** the parent submission's `answer`, its `pandas_query`, its
`evidence`, any pipeline prediction or trace, any heuristic subtype audit.
Gold that is derived from a prediction cannot measure that prediction.

## 1. Entity

- `ticker` = the 3–4 letter code, when the question states one.
- A full company name without a ticker → record `name`, leave `ticker` null,
  and set `entity_resolution = NAME_ONLY`. Do **not** guess a ticker.
- Multiple companies named → `entity_set` has one entry each, in text order.
- "công ty mẹ X" refers to entity X. It constrains the **basis**, not identity.

## 2. Basis

| Surface form | basis |
|---|---|
| "công ty mẹ", "riêng lẻ", "báo cáo riêng" | `separate` |
| "hợp nhất" | `consolidated` |
| nothing stated | `consolidated` **(the unmarked default)** |

The default is not a guess: in this corpus, questions with no basis marker were
answered from consolidated statements 579 times out of 635. Annotators must
still record `basis_explicit = false` so the default can be measured separately
from an explicit statement.

## 3. Period

- Record each year the question names. A range ("giai đoạn 2021–2024") expands
  to every year in it.
- `point`:
  - `PERIOD` — a flow over the year (doanh thu, lợi nhuận, chi phí)
  - `CLOSING` — a balance at year end ("cuối năm", "số cuối năm", "đến ngày 31/12")
  - `OPENING` — a balance at year start ("đầu năm", "số đầu năm")
- A balance-sheet item is `CLOSING` unless stated otherwise. An income-statement
  or cash-flow item is `PERIOD`.
- Quarter/half-year: record `quarter`; if the question mixes annual and interim
  periods, mark `AMBIGUOUS`.

## 4. Metric

- `metric_id` is a **snake_case English canonical name** chosen from the
  vocabulary below, extended as needed. Record the Vietnamese surface form in
  `metric_surface`.
- Starter vocabulary: `revenue`, `net_revenue`, `gross_profit`, `operating_profit`,
  `profit_before_tax`, `profit_after_tax`, `total_assets`, `total_equity`,
  `total_liabilities`, `cash_and_equivalents`, `inventory`, `receivables`,
  `bad_debt`, `total_loans`, `customer_deposits`, `interest_income`,
  `interest_expense`, `cfo`, `capex`, `charter_capital`, `eps`, `roe`, `roa`,
  `net_margin`, `debt_to_equity`, `inventory_days`, `asset_turnover`,
  `goodwill`, `provision_expense`, `deposit_interest`.
- **A ratio named in the question is ONE metric if the source reports it, and a
  DIVIDE of two metrics if the question spells out both parts.**
  - "tỷ lệ nợ xấu là bao nhiêu %" → `LOOKUP(metric=bad_debt_ratio)`
  - "tỷ lệ nợ xấu **trên tổng dư nợ**" → `DIVIDE(bad_debt, total_loans)`
  When unsure which, mark `AMBIGUOUS`.
- Derived ranking keys (ROE, biên lợi nhuận, vòng quay) go in
  `metric_expression` if the question defines them, otherwise `metric_id`.

## 5. Operation tree

Write a real tree, never a flat label:

```
SUBTRACT(LOOKUP(metric=m, period=2023), LOOKUP(metric=m, period=2022))
DIVIDE(LOOKUP(metric=bad_debt), LOOKUP(metric=total_loans))
ARG_EXTREME_PERIOD(rank_key=capex, axis=PERIOD, direction=MAX, over=[2021..2024])
SELECT_AT_ARG(rank=ARG_EXTREME_PERIOD(...), return_metric=standard_loans)
AVG(SUBTRACT(...), SUBTRACT(...))          # average of changes
```

Ordered roles are mandatory and non-commutative:
`numerator/denominator`, `minuend/subtrahend`, `new/old`, `summand`.

## 6. ReturnSpec and result kind

| Question shape | result_kind | notes |
|---|---|---|
| "... là bao nhiêu <tiền>" | `MONEY` | |
| "... bao nhiêu %" | `PERCENT_VALUE` | |
| "... bao nhiêu điểm phần trăm" | `PERCENT_POINT` | a DIFFERENCE of two percentages |
| "... bao nhiêu lần" | `RATIO_FRACTION` | |
| "**năm nào** ..." | `PERIOD_YEAR` | answer is a year, serialised `2017.0` |
| "công ty nào ..." | `ENTITY_LABEL` | **not serialisable as float — mark AMBIGUOUS** |
| "có bao nhiêu công ty" | `COUNT` | |

`PERCENT_VALUE` vs `PERCENT_POINT` is decided by the question's own words, not
by the operation. If it says "điểm phần trăm", it is `PERCENT_POINT`.

## 7. Filters and ranking

- A qualifying clause ("chỉ xét các năm có biên lợi nhuận trên 10%") is a
  `FilterSpec` on the *ranking population*, not on the returned operand.
- "cao hơn trung vị của nhóm" → `threshold_is_group_statistic = MEDIAN`.

## 8. Provenance

Record `source_provenance` as `{csv_path, row_path, col_label}` when the cell can
be located in the corpus. If it cannot be located within reasonable effort, set
`provenance_status = NOT_LOCATED`. **Do not** copy the parent's evidence path.

## 9. Status vocabulary

| status | meaning |
|---|---|
| `RESOLVED` | every required field determined with confidence |
| `AMBIGUOUS` | the question genuinely admits >1 reading; record the readings |
| `UNRESOLVED` | annotator could not determine a field; record which |

Never force a label to reach a target count.
