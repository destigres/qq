import os

import numpy as np
import torch
import torch.nn as nn
import click
from datasets import load_dataset

from transformers import (
    BigBirdForQuestionAnswering,
    BigBirdTokenizer,
    Trainer,
    TrainingArguments,
)


def collate_fn_nq(features, pad_id=0, threshold=1024):
    def pad_elems(ls, pad_id, maxlen):
        while len(ls) < maxlen:
            ls.append(pad_id)
        return ls

    maxlen = max([len(x["input_ids"]) for x in features])
    # avoid attention_type switching
    if maxlen < threshold:
        maxlen = threshold

    # dynamic padding
    input_ids = [pad_elems(x["input_ids"], pad_id, maxlen) for x in features]
    input_ids = torch.tensor(input_ids, dtype=torch.long)

    # padding mask
    attention_mask = input_ids.clone()
    attention_mask[attention_mask != pad_id] = 1
    attention_mask[attention_mask == pad_id] = 0
    output = {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "start_positions": torch.tensor(
            [x["start_token"] for x in features], dtype=torch.long
        ),
        "end_positions": torch.tensor(
            [x["end_token"] for x in features], dtype=torch.long
        ),
        "pooler_label": torch.tensor([x["category"] for x in features]),
    }
    return output

def collate_fn_hotpot(features):
    pass


class BigBirdForNaturalQuestions(BigBirdForQuestionAnswering):
    """BigBirdForQuestionAnswering with CLS Head over the top for predicting category"""

    def __init__(self, config):
        super().__init__(config, add_pooling_layer=True)
        self.cls = nn.Linear(config.hidden_size, 5)

    def forward(
        self,
        input_ids,
        attention_mask=None,
        start_positions=None,
        end_positions=None,
        pooler_label=None,
    ):

        outputs = super().forward(input_ids, attention_mask=attention_mask)
        cls_out = self.cls(outputs.pooler_output)

        loss = None
        if start_positions is not None and end_positions is not None:
            loss_fct = nn.CrossEntropyLoss()
            # If we are on multi-GPU, split add a dimension
            if len(start_positions.size()) > 1:
                start_positions = start_positions.squeeze(-1)
            if len(end_positions.size()) > 1:
                end_positions = end_positions.squeeze(-1)

            start_loss = loss_fct(outputs.start_logits, start_positions)
            end_loss = loss_fct(outputs.end_logits, end_positions)

            if pooler_label is not None:
                cls_loss = loss_fct(cls_out, pooler_label)
                loss = (start_loss + end_loss + cls_loss) / 3
            else:
                loss = (start_loss + end_loss) / 2

        return {
            "loss": loss,
            "start_logits": outputs.start_logits,
            "end_logits": outputs.end_logits,
            "cls_out": cls_out,
        }


# TRAIN_ON_SMALL = os.environ.pop("TRAIN_ON_SMALL", "false")
RESUME_TRAINING = None

# os.environ["WANDB_WATCH"] = "false"
# os.environ["WANDB_PROJECT"] = "bigbird-natural-questions"
SEED = 42
GROUP_BY_LENGTH = True
LEARNING_RATE = 1.0e-4
WARMUP_STEPS = 100
MAX_EPOCHS = 3
FP16 = False
SCHEDULER = "linear"
MODEL_ID = "google/bigbird-roberta-base"


@click.command()
@click.option("--train_on_small", default="false", help="Use small dataset")
@click.option(
    "--dataset", help="{natural_questions | hotpot}"
)
@click.option(
    "--local_rank",
    default=-1,
    type=int,
    help="local_rank for distributed training on gpus",
)
@click.option("--nproc_per_node", default=1, type=int, help="num of processes per node")
def main(train_on_small, dataset, local_rank, nproc_per_node):
    # "nq-training.jsonl" & "nq-validation.jsonl" are obtained from running `prepare_nq.py`

    if dataset == "natural_questions":
        tr_dataset = load_dataset("json", data_files="data/nq-training.jsonl")["train"]
        val_dataset = load_dataset("json", data_files="data/nq-validation.jsonl")[
            "train"
        ]
        output_dir = "bigbird-nq-complete-tuning"
        collate_fn = collate_fn_nq
    elif dataset == "hotpot":
        tr_dataset = load_dataset(
            "hotpot_qa", "fullwiki", split="train"
        )
        val_dataset = load_dataset(
            "hotpot_qa", "fullwiki", split="validation"
        )
        output_dir = "bigbird-hotpot-complete-tuning"
        collate_fn = collate_fn_hotpot

        # testing
        collate_fn(tr_dataset[0])
    else:
        raise ValueError(f"dataset {dataset} not supported")

    if train_on_small == "true":
        # this will run for ~12 hrs on 2 K80 GPU (natural questions)
        np.random.seed(SEED)
        indices = np.random.randint(0, 298152, size=8000)
        tr_dataset = tr_dataset.select(indices)
        np.random.seed(SEED)
        indices = np.random.randint(0, 9000, size=1000)
        val_dataset = val_dataset.select(indices)

    print(tr_dataset, val_dataset)

    tokenizer = BigBirdTokenizer.from_pretrained(MODEL_ID)
    model = BigBirdForNaturalQuestions.from_pretrained(
        MODEL_ID, gradient_checkpointing=True
    )

    args = TrainingArguments(
        output_dir=output_dir,
        overwrite_output_dir=False,
        do_train=True,
        do_eval=True,
        evaluation_strategy="epoch",
        # eval_steps=4000,
        per_device_train_batch_size=4,
        per_device_eval_batch_size=4,
        gradient_accumulation_steps=4,
        group_by_length=GROUP_BY_LENGTH,
        learning_rate=LEARNING_RATE,
        warmup_steps=WARMUP_STEPS,
        lr_scheduler_type=SCHEDULER,
        num_train_epochs=MAX_EPOCHS,
        logging_strategy="steps",
        logging_steps=10,
        save_strategy="steps",
        save_steps=250,
        run_name=f"bigbird-{dataset}-complete-tuning",
        disable_tqdm=False,
        # load_best_model_at_end=True,
        # report_to="wandb",
        remove_unused_columns=False,
        fp16=FP16,
        label_names=[
            "pooler_label",
            "start_positions",
            "end_positions",
        ],  # it's important to log eval_loss
    )
    print("Batch Size", args.train_batch_size)
    print("Parallel Mode", args.parallel_mode)

    trainer = Trainer(
        model=model,
        args=args,
        data_collator=collate_fn,
        train_dataset=tr_dataset,
        eval_dataset=val_dataset,
    )
    try:
        trainer.train(resume_from_checkpoint=RESUME_TRAINING)
        trainer.save_model("final-model")
    except KeyboardInterrupt:
        trainer.save_model("interrupted-natural-questions")
    # wandb.finish()


if __name__ == "__main__":
    main()
