# Abbreviations:
#  p: primary
#  pm: primary model
#  pt: primary task

import click
import configparser
from datasets import load_from_disk
from oracles import Dummy_Oracle, T5_Oracle
from secondary_model import Dummy_Secondary_Model, Repeater_Secondary_Model
from primary_models import BigBird_PM, T5_PM
from dataset_utils import drop_unanswerable
from datetime import datetime

import pandas as pd


@click.command()
@click.option("--pt_dataset_path", help="path to primary task dataset")
@click.option("--m1_path", help="path to primary model")
@click.option("--m1_arch", help="primary model architecture")
@click.option("--eval_batch_size", default=2, help="batch size for eval")
@click.option("--masking_scheme", help="{randomsentence | None")
@click.option(
    "--downsample_pt_size",
    default=None,
    help="use at most this many examples in validation",
)
@click.option("--results_filename", help="path to save results")
def main(
    pt_dataset_path,
    m1_path,
    m1_arch,
    eval_batch_size,
    masking_scheme,
    downsample_pt_size,
    results_filename,
):

    # testing chatgpt
    # read the chatgpt api key from config.ini
    config = configparser.ConfigParser()
    config.read("config.ini")
    openai_api_key = config.get("API_KEYS", "openai_api_key")

    now = datetime.now().strftime("Y%m%d-%H%M%S")
    if results_filename is None:
        results_filename = f"{m1_arch}-{downsample_pt_size}-{masking_scheme}-{now}"

    with open(f"inf_logs/{results_filename}.txt", "a") as f:

        masking_str = f"fc_{masking_scheme}"

        # Unit Tests
        assert m1_arch in [
            "bigbird",
            "t5-small",
            "t5-base",
            "t5-large",
            "t5-xl",
            "t5-xxl",
        ]

        # Receive and prepare the primary task
        raw_dataset = load_from_disk(pt_dataset_path)
        original_raw_dataset_len = len(raw_dataset)
        if str(downsample_pt_size) != "None":
            raw_dataset = raw_dataset.select(range(int(downsample_pt_size)))

        # Load primary model
        if m1_arch == "bigbird":
            m1 = BigBird_PM(m1_path, eval_batch_size=eval_batch_size)
        elif m1_arch.startswith("t5"):
            m1 = T5_PM(
                eval_batch_size=eval_batch_size,
                model_name=m1_arch,
            )
        else:
            raise NotImplementedError

        ds = raw_dataset

        # Evaluate the primary model
        metrics = {}
        ds, metrics[masking_scheme] = m1.evaluate(
            masking_scheme=masking_scheme, ds=ds, a2_col=None
        )
        ds, metrics["supporting"] = m1.evaluate(
            masking_scheme="supporting", ds=ds, a2_col=None
        )
        # Create the secondary model
        m2 = Repeater_Secondary_Model()
        # Apply the secondary model
        ds = m2.process(
            ds,
            q1_col="q1",
            context_col=masking_str,
        )
        # Create the oracle
        oracle = T5_Oracle(model_name="t5-small")
        # Answer questions with the oracle
        ds = oracle.process(ds, q2_col="q2")

        ds, metrics["answered"] = m1.evaluate(masking_scheme=masking_scheme, ds=ds, a2_col="a2")


        # Analysis
        df = pd.DataFrame(ds)
        percent_oracle_correct = df["a2_is_correct"].mean()
        print(metrics)

        f.write(
            f"""Model:     {m1_path if m1_path else m1_arch}
Datetime:  {now}
Data:      {pt_dataset_path} {original_raw_dataset_len}/{len(raw_dataset)}
Masking:   {masking_scheme}
F1:        {metrics["f1"]}
Precision: {metrics["precision"]}
Recall:    {metrics["recall"]}\n\n"""
        )


if __name__ == "__main__":
    main()
