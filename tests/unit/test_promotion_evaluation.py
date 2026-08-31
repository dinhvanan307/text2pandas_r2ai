from __future__ import annotations

from text2pandas.application.usecases.promotion_evaluation import evaluate_semantic_gold


def test_promotion_evaluation_measures_parser_candidate_binding_and_answer() -> None:
    ast = {"schema_version": 3, "expression": {"type": "metric_ref"}}
    records = [
        {
            "qid": 1,
            "status": "OK",
            "answer": "10",
            "ast": ast,
            "evidence": [{"observation_uids": ["obs-1"]}],
            "trace": [
                {
                    "stage": "RETRIEVE_OPERANDS",
                    "requests": {
                        "operand:1": {
                            "trace": {
                                "candidate_observation_uids": ["obs-1", "obs-2"]
                            }
                        }
                    },
                }
            ],
        },
        {
            "qid": 2,
            "status": "ABSTAIN",
            "answer": None,
            "ast": None,
            "evidence": [],
            "trace": [],
        },
    ]
    gold = [
        {
            "qid": 1,
            "answer": {"status": "OK", "value": 10},
            "semantic_parser": {"status": "OK", "ast": ast},
            "evidence_binding": {
                "status": "OK",
                "ordered_operands": [{"observation_uid": "obs-1"}],
            },
        }
    ]

    report = evaluate_semantic_gold(records, gold)

    assert report.parser_ast_exact == 1.0
    assert report.candidate_recall == 1.0
    assert report.binding_exact == 1.0
    assert report.answer_accuracy == 1.0


def test_promotion_evaluation_distinguishes_candidate_hit_from_wrong_binding() -> None:
    records = [
        {
            "qid": 1,
            "status": "OK",
            "answer": 5,
            "ast": {},
            "evidence": [{"observation_uids": ["wrong"]}],
            "trace": [
                {
                    "stage": "RETRIEVE_OPERANDS",
                    "requests": {
                        "operand:1": {
                            "trace": {"candidate_observation_uids": ["gold", "wrong"]}
                        }
                    },
                }
            ],
        }
    ]
    gold = [
        {
            "qid": 1,
            "answer": {"status": "OK", "value": 10},
            "semantic_parser": {"status": "OK", "ast": {"expected": True}},
            "evidence_binding": {
                "status": "OK",
                "ordered_operands": [{"observation_uid": "gold"}],
            },
        }
    ]

    report = evaluate_semantic_gold(records, gold)

    assert report.candidate_recall == 1.0
    assert report.binding_exact == 0.0
    assert report.answer_accuracy == 0.0
