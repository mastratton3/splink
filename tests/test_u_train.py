import numpy as np
import pandas as pd
import pytest

import splink.duckdb.duckdb_comparison_library as cld
import splink.spark.spark_comparison_library as clsp
from splink.duckdb.duckdb_linker import DuckDBLinker
from splink.spark.spark_linker import SparkLinker


def test_u_train():
    data = [
        {"unique_id": 1, "name": "Amanda"},
        {"unique_id": 2, "name": "Robin"},
        {"unique_id": 3, "name": "Robyn"},
        {"unique_id": 4, "name": "David"},
        {"unique_id": 5, "name": "Eve"},
        {"unique_id": 6, "name": "Amanda"},
    ]
    df = pd.DataFrame(data)

    settings = {
        "link_type": "dedupe_only",
        "comparisons": [cld.levenshtein_at_thresholds("name", 2)],
        "blocking_rules_to_generate_predictions": ["l.name = r.name"],
    }

    linker = DuckDBLinker(df, settings)
    linker.debug_mode = True
    linker.estimate_u_using_random_sampling(max_pairs=1e6)
    cc_name = linker._settings_obj.comparisons[0]

    denom = (6 * 5) / 2  # n(n-1) / 2
    cl_exact = cc_name._get_comparison_level_by_comparison_vector_value(2)
    assert cl_exact.u_probability == 1 / denom
    cl_lev = cc_name._get_comparison_level_by_comparison_vector_value(1)
    assert cl_lev.u_probability == 1 / denom
    cl_no = cc_name._get_comparison_level_by_comparison_vector_value(0)
    assert cl_no.u_probability == (denom - 2) / denom

    br = linker._settings_obj._blocking_rules_to_generate_predictions[0]
    assert br.blocking_rule == "l.name = r.name"


def test_u_train_link_only():
    data_l = [
        {"unique_id": 1, "name": "Amanda"},
        {"unique_id": 2, "name": "Robin"},
        {"unique_id": 3, "name": "Robyn"},
        {"unique_id": 4, "name": "David"},
        {"unique_id": 5, "name": "Eve"},
        {"unique_id": 6, "name": "Amanda"},
        {"unique_id": 7, "name": "Stuart"},
    ]
    data_r = [
        {"unique_id": 1, "name": "Eva"},
        {"unique_id": 2, "name": "David"},
        {"unique_id": 3, "name": "Sophie"},
        {"unique_id": 4, "name": "Jimmy"},
        {"unique_id": 5, "name": "Stuart"},
        {"unique_id": 6, "name": "Jimmy"},
    ]
    df_l = pd.DataFrame(data_l)
    df_r = pd.DataFrame(data_r)

    settings = {
        "link_type": "link_only",
        "comparisons": [cld.levenshtein_at_thresholds("name", 2)],
        "blocking_rules_to_generate_predictions": [],
    }

    linker = DuckDBLinker([df_l, df_r], settings)
    linker.debug_mode = True
    linker.estimate_u_using_random_sampling(max_pairs=1e6)
    cc_name = linker._settings_obj.comparisons[0]

    check_blocking_sql = """
    SELECT COUNT(*) AS count FROM __splink__df_blocked
    WHERE source_dataset_l = source_dataset_r
    """
    self_table_count = linker._sql_to_splink_dataframe_checking_cache(
        check_blocking_sql, "__splink__df_blocked_same_table_count"
    )

    result = self_table_count.as_record_dict()
    self_table_count.drop_table_from_database()
    assert result[0]["count"] == 0

    denom = 6 * 7  # only l <-> r candidate links
    cl_exact = cc_name._get_comparison_level_by_comparison_vector_value(2)
    # David, Stuart
    assert cl_exact.u_probability == 2 / denom
    # Eve/Eva
    cl_lev = cc_name._get_comparison_level_by_comparison_vector_value(1)
    assert cl_lev.u_probability == 1 / denom
    cl_no = cc_name._get_comparison_level_by_comparison_vector_value(0)
    assert cl_no.u_probability == (denom - 3) / denom


def test_u_train_link_only_sample():
    df_l = (
        pd.DataFrame(np.random.randint(0, 3000, size=(3000, 1)), columns=["name"])
        .reset_index()
        .rename(columns={"index": "unique_id"})
    )
    df_r = (
        pd.DataFrame(np.random.randint(0, 3000, size=(3000, 1)), columns=["name"])
        .reset_index()
        .rename(columns={"index": "unique_id"})
    )

    max_pairs = 1800000

    settings = {
        "link_type": "link_only",
        "comparisons": [cld.levenshtein_at_thresholds("name", 2)],
        "blocking_rules_to_generate_predictions": [],
    }

    linker = DuckDBLinker([df_l, df_r], settings)
    linker.debug_mode = True
    linker.estimate_u_using_random_sampling(max_pairs=max_pairs)
    linker._settings_obj.comparisons[0]

    check_blocking_sql = """
    SELECT COUNT(*) AS count FROM __splink__df_blocked
    """
    self_table_count = linker._sql_to_splink_dataframe_checking_cache(
        check_blocking_sql, "__splink__df_blocked_same_table_count"
    )

    result = self_table_count.as_record_dict()

    self_table_count.drop_table_from_database()
    max_pairs_proportion = result[0]["count"] / max_pairs
    # equality only holds probabilistically
    # chance of failure is approximately 1e-06
    assert pytest.approx(max_pairs_proportion, 0.15) == 1.0


def test_u_train_multilink():
    datas = [
        [
            {"unique_id": 1, "name": "John"},
            {"unique_id": 2, "name": "Robin"},
        ],
        [
            {"unique_id": 1, "name": "Jon"},
            {"unique_id": 2, "name": "David"},
            {"unique_id": 3, "name": "Sophie"},
        ],
        [
            {"unique_id": 1, "name": "Eva"},
            {"unique_id": 2, "name": "David"},
            {"unique_id": 3, "name": "Alex"},
            {"unique_id": 4, "name": "Chris"},
        ],
        [
            {"unique_id": 1, "name": "Andy"},
            {"unique_id": 2, "name": "David"},
            {"unique_id": 3, "name": "Reece"},
            {"unique_id": 4, "name": "Adil"},
            {"unique_id": 5, "name": "Adil"},
            {"unique_id": 6, "name": "Adil"},
            {"unique_id": 7, "name": "Adil"},
        ],
    ]
    dfs = list(map(pd.DataFrame, datas))

    expected_total_links = 2 * 3 + 2 * 4 + 2 * 7 + 3 * 4 + 3 * 7 + 4 * 7
    expected_total_links_with_dedupes = (2 + 3 + 4 + 7) * (2 + 3 + 4 + 7 - 1) / 2

    settings = {
        "link_type": "link_only",
        "comparisons": [cld.levenshtein_at_thresholds("name", 2)],
        "blocking_rules_to_generate_predictions": [],
    }

    linker = DuckDBLinker(dfs, settings)
    linker.debug_mode = True
    linker.estimate_u_using_random_sampling(max_pairs=1e6)
    cc_name = linker._settings_obj.comparisons[0]

    check_blocking_sql = """
    SELECT COUNT(*) AS count FROM __splink__df_blocked
    WHERE source_dataset_l = source_dataset_r
    """

    self_table_count = linker._sql_to_splink_dataframe_checking_cache(
        check_blocking_sql, "__splink__df_blocked_same_table_count"
    )

    result = self_table_count.as_record_dict()
    self_table_count.drop_table_from_database()
    assert result[0]["count"] == 0

    denom = expected_total_links
    cl_exact = cc_name._get_comparison_level_by_comparison_vector_value(2)

    # David - three pairwise comparisons
    assert cl_exact.u_probability == 3 / denom
    # John, Jon
    cl_lev = cc_name._get_comparison_level_by_comparison_vector_value(1)

    assert cl_lev.u_probability == 1 / denom
    cl_no = cc_name._get_comparison_level_by_comparison_vector_value(0)
    assert cl_no.u_probability == (denom - 4) / denom

    # also check the numbers on a link + dedupe with same inputs
    settings["link_type"] = "link_and_dedupe"
    linker = DuckDBLinker(dfs, settings)
    linker.debug_mode = True
    linker.estimate_u_using_random_sampling(max_pairs=1e6)
    cc_name = linker._settings_obj.comparisons[0]

    check_blocking_sql = """
    SELECT COUNT(*) AS count FROM __splink__df_blocked
    WHERE source_dataset_l = source_dataset_r
    """

    self_table_count = linker._sql_to_splink_dataframe_checking_cache(
        check_blocking_sql, "__splink__df_blocked_same_table_count"
    )

    result = self_table_count.as_record_dict()
    self_table_count.drop_table_from_database()
    assert result[0]["count"] == (2 * 1 / 2 + 3 * 2 / 2 + 4 * 3 / 2 + 7 * 6 / 2)

    denom = expected_total_links_with_dedupes
    cl_exact = cc_name._get_comparison_level_by_comparison_vector_value(2)

    # David and Adil
    assert cl_exact.u_probability == (3 + 6) / denom
    # John, Jon
    cl_lev = cc_name._get_comparison_level_by_comparison_vector_value(1)

    assert cl_lev.u_probability == 1 / denom
    cl_no = cc_name._get_comparison_level_by_comparison_vector_value(0)
    assert cl_no.u_probability == (denom - 10) / denom


@pytest.mark.parametrize(
    ("Linker", "cll"),
    [
        pytest.param(DuckDBLinker, cld, id="Test DuckDB random seeds"),
        pytest.param(SparkLinker, clsp, id="Test Spark random seeds"),
    ],
)
def test_seed_u_outputs(df_spark, Linker, cll):
    if Linker == SparkLinker:
        df = df_spark
    else:
        df = pd.read_csv("./tests/datasets/fake_1000_from_splink_demos.csv")

    settings = {
        "link_type": "dedupe_only",
        "comparisons": [cll.levenshtein_at_thresholds("first_name", 2)],
    }

    linker_1 = Linker(df, settings)
    linker_2 = Linker(df, settings)
    linker_3 = Linker(df, settings)

    linker_1.estimate_u_using_random_sampling(max_pairs=1e3, seed=1)
    linker_2.estimate_u_using_random_sampling(max_pairs=1e3, seed=1)
    linker_3.estimate_u_using_random_sampling(max_pairs=1e3, seed=2)

    assert (
        linker_1._settings_obj._parameter_estimates_as_records
        == linker_2._settings_obj._parameter_estimates_as_records
    )
    assert (
        linker_1._settings_obj._parameter_estimates_as_records
        != linker_3._settings_obj._parameter_estimates_as_records
    )
