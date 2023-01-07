from numpy import random
from utils import dc, tokenizer

def mask_random_sentence(example):
    # TODO: mask the input ids instead of the context
    """Mask random useful sentence in example"""
    titles = example["context"]["title"]
    # create a dictionary mapping each title to its index
    title_to_index = {title: i for i, title in enumerate(titles)}

    n_supporting_facts = len(example["supporting_facts"])
    assert n_supporting_facts > 0, "No supporting facts found"

    # randomly select a supporting fact
    i = random.randint(0, n_supporting_facts - 1)
    fact_title = example["supporting_facts"]["title"][i]
    fact_title_index = title_to_index[fact_title]
    fact_sent_index = example["supporting_facts"]["sent_id"][i]
    fact_sent = example["context"]["sentences"][fact_title_index][fact_sent_index]
    len_fact = len(
        fact_sent.split()
    )
    replacement = " ".join(["[MASK]"] * len_fact)

    example["context"]["sentences"][fact_title_index][fact_sent_index] = replacement

    debug_context = "[SEP]".join([" ".join(x) for x in example["context"]["sentences"]])

    return example