"""
Utilities for processing datasets
"""
from hotpot_evaluate_v1 import f1_score, normalize_answer
from utils import sublist_is_in_list
from datasets import Dataset
import pandas as pd

PUNCTUATION_SET_TO_EXCLUDE = set("".join(["‘", "’", "´", "`", ".", ",", "-", '"']))


def get_sub_answers(answers, begin=0, end=None):
    return [" ".join(x.split(" ")[begin:end]) for x in answers if len(x.split(" ")) > 1]


def expand_to_aliases(given_answers, make_sub_answers=False):
    if make_sub_answers:
        # if answers are longer than one word, make sure a predictions is correct if it coresponds to the complete 1: or :-1 sub word
        # *e.g.* if the correct answer contains a prefix such as "the", or "a"
        given_answers = (
            given_answers
            + get_sub_answers(given_answers, begin=1)
            + get_sub_answers(given_answers, end=-1)
        )
    answers = []
    for answer in given_answers:
        alias = answer.replace("_", " ").lower()
        alias = "".join(
            c if c not in PUNCTUATION_SET_TO_EXCLUDE else " " for c in alias
        )
        answers.append(" ".join(alias.split()).strip())
    return set(answers)


# dataset formatting
def format_dataset_hotpot(example):
    # the context might be comprised of multiple contexts => me merge them here
    example["context"] = "\n".join(
        [x for y in example["context"]["sentences"] for x in y]
    )
    example["targets"] = [example["a1"]]
    return example


def format_dataset_trivia(example):
    # the context might be comprised of multiple contexts => me merge them here
    example["context"] = " ".join(
        ("\n".join(example["entity_pages"]["wiki_context"])).split("\n")
    )
    example["targets"] = example["a1"]["aliases"]
    example["norm_target"] = example["a1"]["normalized_value"]
    return example







def clean_answer(ex, tk):
    ex["a1"] = tk.decode(tk.encode(ex["a1"]))
    return ex


def check_example(ex, tk):
    st = ex["labels"]["start_token"][0]
    et = ex["labels"]["end_token"][0]
    input_ids = ex["input_ids"]
    answer = ex["a1"]
    answer_tokens = input_ids[st : et + 1]
    answer_indexed = tk.decode(answer_tokens)
    # assert (
    #     answer == answer_indexed
    # ), f"answer {answer} != {answer_indexed} at {st}:{et}"
    if st == -100 and et == -100:
        if answer not in ["yes", "no"]:
            print(f"answer {answer} should be 'yes' or 'no' if st and et are -100")
    else:
        # run the answer through the tokenizer so it doesn't trigger on tokenizer failures
        # since the input_ids are tokenized elsewhere
        tk_answer = tk.decode(tk.encode(answer)[1:-1])
        f1, precision, recall = f1_score(tk_answer, answer_indexed)
        if not (f1 == 1 and precision == 1 and recall == 1):
            print(f"answer {tk_answer} != {answer_indexed} at {st}:{et}")


def check_dataset(dataset, tk):
    """Check that answers are actually at their identified position in the context and other sanity checks"""
    print("Checking dataset...")
    dataset.map(
        lambda x: check_example(x, tk),
        batched=False,
        load_from_cache_file=False,
    )


def bf_filtering(ds: Dataset) -> Dataset:
    df = ds.to_pandas()
    df["was_damaged"] = (df["m1_supporting_None_f1"] > 0) & (
        df["m1_bfdelsentence_None_f1"] == 0
    )
    df = df[df["was_damaged"]]
    ds = Dataset.from_pandas(df)
    return ds


def make_id_col_unique(ds: Dataset, suffix: str = "") -> pd.DataFrame:
    df = ds.to_pandas()
    # get a list of dataframes where each dataframe only contains examples of a single id
    df_list = [df[df["id"] == x] for x in df["id"].unique()]
    new_list = []
    def append_id(x):
        x['id'] = x['id'] + "_" + suffix + str(x.name)
        return x

    for dfx in df_list:
        # dfx["id"] = [dfx.loc[i,"id"] + "_" + suffix + str(i) for i in range(len(dfx))]
        new_list.append(dfx.apply(append_id, axis=1))
    new_df = pd.concat(new_list)
    return new_df


def combine_adversarial_ds(ds_add: Dataset, ds_del: Dataset) -> Dataset:
    """combine the two adversarially created datasets, standardize columns, and make ids unique again"""
    df_add = make_id_col_unique(ds_add, "a")
    df_del = make_id_col_unique(ds_del, "d")

    # df_add["masked_sentence"] = ["" for _ in range(len(df_add))]
    df_del["distractor_sentence"] = ["" for _ in range(len(df_del))]
    col_name_map = {
        "m1_bfaddsentence_None_gen": "m1_masked_None_gen",
        "m1_bfdelsentence_None_gen": "m1_masked_None_gen",
        "prepped_bfaddsentence_None": "prepped_masked_None",
        "prepped_bfdelsentence_None": "prepped_masked_None",
        "fc_bfdelsentence": "fc_masked",
        "fc_bfaddsentence": "fc_masked",
        "m1_bfaddsentence_None_f1": "m1_masked_None_f1",
        "m1_bfdelsentence_None_f1": "m1_masked_None_f1",
        "m1_bfaddsentence_None_em": "m1_masked_None_em",
        "m1_bfdelsentence_None_em": "m1_masked_None_em",
    }

    df_del = df_del.rename(columns=col_name_map)
    df_add = df_add.rename(columns=col_name_map)

    df = pd.concat([df_add, df_del], ignore_index=True).sort_values(by="id")
    ds = Dataset.from_pandas(df)
    ds = ds.remove_columns(["__index_level_0__"])
    return ds
