from eval import run_eval


def test_dataset_and_evaluation_construct_without_network():
    dataset = run_eval.build_dataset()
    evaluation = run_eval.build_evaluation()

    assert len(dataset) >= 4
    assert {
        "anomaly",
        "expected_op",
        "expected_subcause",
    }.issubset(dataset[0])
    assert len(evaluation.dataset.rows) == len(dataset)
    assert len(evaluation.scorers) == 3


def test_eval_scorers_return_expected_dicts():
    output = {
        "blamed_op": "process_batch",
        "suspected_subcause": "unbounded_collection",
        "diagnosis": "process_batch retains batches",
        "root_cause": "unbounded list",
        "fix_strategy": "trim to a sliding window",
        "test_result": {"tests_passed": True},
    }

    assert run_eval.correct_op(output, "process_batch") == {"correct_op": True}
    assert run_eval.correct_op(output, "other_op") == {"correct_op": False}
    assert run_eval.correct_subcause(output, "unbounded_collection") == {
        "correct_subcause": True
    }
    assert run_eval.correct_subcause(output, "unknown") == {"correct_subcause": False}
    assert run_eval.fix_present(output) == {"fix_present": True}
    assert run_eval.fix_present({"test_result": {"tests_passed": False}}) == {
        "fix_present": False
    }
