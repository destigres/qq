import os

import numpy as np
from tqdm import tqdm

import jsonlines
import click
from datasets import load_dataset
import datasets
from transformers import BigBirdTokenizer
from typing import List, Optional, Tuple
from collections import defaultdict, Counter

from masking import mask_random_sentence, mask_None
from utils import make_cache_file_name, get_downsample_dataset_size_str, dc


DOC_STRIDE = 2048
MAX_LENGTH = 4096
SEED = 42
PROCESS_TRAIN = os.environ.pop("PROCESS_TRAIN", "false")
CATEGORY_MAPPING = {"null": 0, "short": 1, "long": 2, "yes": 3, "no": 4}


def flatten_context(example, masking_scheme):
    masking_str = f"context_{masking_scheme}"
    output = ""
    titles = example[masking_str]["title"]  # list of str
    sentences = example[masking_str]["sentences"]  # list of list of str
    paragraphs = [" ".join(s) for s in sentences]
    # John F Kennedy: John F Kennedy was the 35th president of the United States. He was born in 1917. He was assassinated in 1963. \n\n
    contexts = [f"{t}: {p}" for t, p in zip(titles, paragraphs)]
    context = "\n\n".join(contexts)
    return {f"fc_{masking_scheme}": context}


@click.command()
@click.option("--split", type=str, help="{train | validation | both}")
@click.option("--dataset", type=str, help="{natural_questions | hotpot}")
@click.option("--masking_schemes", type=str, multiple=True, default=None)
@click.option("--downsample_data_size", type=str, default=None)
@click.option("--cache_dir", type=str, help="Path to cache directory")
@click.option("--load_from_cache", type=bool, default=True)
def main(
    split,
    dataset,
    masking_schemes,
    downsample_data_size,
    cache_dir,
    load_from_cache,
):
    # Unit Tests

    assert split in ["train", "validation"], "Invalid split"
    assert dataset in ["hotpot"], "Invalid dataset"
    assert "None" not in masking_schemes, "`None` masking will be included by default."
    masking_dict = {"randomsentence": mask_random_sentence}
    for masking_scheme in masking_schemes:
        assert (
            masking_scheme in masking_dict.keys()
        ), f"Invalid masking scheme {masking_scheme}"

    # Load the Dataset

    raw_dataset = load_dataset(
        "hotpot_qa",
        "distractor",
        cache_dir=cache_dir,
        split=f"{split}{get_downsample_dataset_size_str(downsample_data_size)}",
    )
    new_dataset = raw_dataset.rename_column("context", "context_None")

    # Apply Each Masking Scheme

    for masking_scheme in masking_schemes:
        masking_str = f"context_{masking_scheme}"
        cache_file_name = make_cache_file_name(
            split, dataset, downsample_data_size, masking_scheme
        )

        masking_fn = masking_dict[masking_scheme]
        masked_col = new_dataset.map(
            masking_fn,
            cache_file_name=cache_file_name,
            load_from_cache_file=load_from_cache,
        )["masked_col"]
        new_dataset = new_dataset.add_column(name=masking_str, column=masked_col)

    # Flatten Each Context

    for masking_scheme in list(masking_schemes) + ["None"]:
        masking_str = f"context_{masking_scheme}"
        flat_col = new_dataset.map(
            lambda x: flatten_context(x, masking_scheme),
            cache_file_name=cache_file_name,
            load_from_cache_file=load_from_cache,
        )[f"fc_{masking_scheme}"] # fc == flattened context
        new_dataset = new_dataset.add_column(
            name=f"flat_{masking_str}", column=flat_col
        )
        new_dataset = new_dataset.remove_columns([f"context_{masking_scheme}"])

    # Save the Dataset
    save_path = f"data2/{dataset}-{split}-{downsample_data_size}-{''.join(masking_schemes)}"
    new_dataset.save_to_disk(save_path)


    print


if __name__ == "__main__":
    main()
