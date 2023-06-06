from transformers import PreTrainedModel, GPT2Tokenizer, GPT2Model
import pandas as pd
import numpy as np
import openai
import configparser
import os
import h5py
import time 
from tqdm import tqdm

# Set up the API once for all models
config = configparser.ConfigParser()
config.read("config.ini")
openai.api_key = config.get("API_KEYS", "openai_api_key")

in_context_examples = """Context:
House of Anubis: House of Anubis is a mystery television series developed for Nickelodeon based on the Dutch-Belgian television series "Het Huis Anubis".
Question 1:
The Dutch-Belgian television series that "House of Anubis" was based on first aired in what year?
Question 2:
In what year did "Het Huis Anubis" air?

Context:
Oberoi family: The Oberoi family is an Indian family that is famous for its involvement in hotels, namely through The Oberoi Group.'
Question 1:
The Oberoi family is part of a hotel company that has a head office in what city?
Question 2:
What city holds the head office of The Oberoi Group?

Context:
Zilpo Road: The nine mile byway starts south of Morehead, Kentucky and can be accessed by U.S. Highway 60. Arkansas Highway 113: The route runs 29.48 mi from Arkansas Highway 10 to Morrilton.
Question 1:
What U.S Highway gives access to Zilpo Road, and is also known as Midland Trail?
Question 2:
what U.S. Highway is also known as Midland Trail?

Context:
My Finale: "My Finale" is the hour-long season finale for season eight of the American sitcom "Scrubs". Human Error (House): "Human Error" is the twenty-fourth episode and season finale of the third season of "House" and the seventieth episode overall.
Question 1:
Human Error" is the season finale of the third season of a tv show that aired on what network?
Question 2:
What network aired the season finale of the third season of "House"?

Context:
Annette Bening: Annette Carol Bening (born May 29, 1958) is an American actress. She is a four-time Academy Award nominee; for "The Grifters" (1990), "American Beauty" (1999), "Being Julia" (2004) and "The Kids Are All Right" (2010). In 2006, she received a star on the Hollywood Walk of Fame. The Great Outdoors (film): The Great Outdoors is a 1988 American comedy film directed by Howard Deutch, and written and produced by John Hughes. John Lithgow: John Arthur Lithgow ( ; born October 19 , 1945) is an American actor, musician, singer, comedian, voice actor, and author.
Question 1:
The 1988 American comedy film, The Great Outdoors, starred a four-time Academy Award nominee, who received a star on the Hollywood Walk of Fame in what year?
Question 2:
Who starred in the 1988 American comedy film, The Great Outdoors?"""


# Abstract class for secondary models
class Secondary_Model:
    def __init__(
        self,
        prompt_id,
    ):
        self.model_name = "dummy"
        self.prompt_id = "p1"  # the id of the prompt to use for this model
        self.prompt_dict = {
            "p1": "Ask another question that would help you answer the following question:\n\n{context}\n\n{q1}",
            "p2": "Some information is missing from this context. Ask a simpler question that would help you answer it.\n\nContext:\n\n{context}\n\nMain Question:\n\n{q1}\n\nSimpler question:",
            "p3": "What question can you ask to help you answer the final question?\n\n{context}\n\n{q1}\n\nYou can ask:",
            "p4": "".join(
                [
                    "Ask another question that would help you answer the previous question:\n\n",
                    in_context_examples,
                    "\n\nContext:\n{context}\nQuestion 1:\n{q1}\nQuestion 2:\n",
                ]
            ),
            "p5": "".join(
                [
                    "Some information is missing from each context. Ask a simpler question that would help you answer it.\n\n",
                    in_context_examples,
                    "\n\nContext:\n{context}\nQuestion 1:\n{q1}\nQuestion 2:\n",
                ]
            ),
            "p6": "".join(
                [
                    "What question can you ask to help you answer the final question?\n\n",
                    in_context_examples,
                    "\n\nContext:\n{context}\nQuestion 1:\n{q1}\nQuestion 2:\n",
                ]
            ),
        }
        self.template = self.prompt_dict[self.prompt_id]

    def prepare_data(self, masking_scheme):
        pass

    def forward(self, example, question_col, context_col):
        return "What is six times seven?"

    def process(self, ds, q1_col, masking_scheme):
        """Ask a secondary question about each primary question. Returns a new dataset with the secondary question added as a column called 'q2'."""

        def _add_q2(example):
            example[f"q2_{masking_scheme}"] = self.forward(
                example, q1_col, f"fc_{masking_scheme}"
            )
            return example

        ds = ds.add_column(name=f"q2_{masking_scheme}", column=[""] * len(ds))
        ds = ds.map(
            lambda x: _add_q2(x),
            load_from_cache_file=False,
        )
        return ds


class Repeater_Secondary_Model(Secondary_Model):
    def __init__(
        self,
    ):
        self.model_name = "repeater"

    def forward(self, example, question_col, context_col):
        # Always return the original question q1
        return example[question_col]


class OpenAI_Secondary_Model(Secondary_Model):
    def __init__(self, cache_path, prompt_id):
        # call the parent constructor
        super().__init__(prompt_id)
        self.model_name = "chatGPT"
        self.model = "gpt-3.5-turbo"
        self.cache_path = cache_path
        self.oai_model_id = (
            None  # the current openai model id. set on the first api call
        )
        if self.cache_path is None:
            self.cache_df = pd.DataFrame(columns=["response"])
        else:
            if not os.path.exists(self.cache_path):
                self.cache_df = pd.DataFrame(columns=["response"])
                self.cache_df.to_csv(self.cache_path)
                # Create the cache file
            else:
                self.cache_df = pd.read_csv(self.cache_path, index_col=0)

    def prepare_data(self, masking_scheme):
        pass

    def forward(self, example, question_col, context_col):
        idx = None

        def call_oai_api(prompt):
            while True:
                try:
                    response = openai.ChatCompletion.create(
                        model=self.model,
                        messages=[
                            {"role": "user", "content": prompt},
                        ],
                    )
                    break
                except Exception as e:
                    print(e)
                    print("Retrying...")
                    # pause a second
                    time.sleep(1)
                    continue
                
            q2 = response["choices"][0]["message"]["content"].strip()
            self.oai_model_id = response.model
            idx = f"{self.oai_model_id} {prompt}"
            # Cache the response in ram
            if idx in self.cache_df.index:
                self.cache_df.loc[idx, "response"] = q2
                self.cache_df.to_csv(self.cache_path)
            else:
                new_line = pd.DataFrame(columns=["response"], index=[idx], data=[q2])
                self.cache_df = pd.concat([self.cache_df, new_line])
                new_line.to_csv(self.cache_path, mode="a", header=False, escapechar="🦆")
            return q2

        q1 = example[question_col]
        context = example[context_col]
        # prompt = f"Ask another question that would help you answer the following question:\n\n{context}\n\n{q1}"
        prompt = self.template.format(context=context, q1=q1)

        # if self.oai_model_id is not None:
        #     idx = f"{self.oai_model_id} {prompt}"
        # else:
        #     # Check if the response is cached
        #     # If not, call the API to get the model id
        #     output = call_oai_api(prompt)
        # if idx in self.cache_df.index and self.oai_model_id is not None:
        #     output = self.cache_df.loc[idx, "response"]
        # else:
        #     output = call_oai_api(prompt)
        output = call_oai_api(prompt)
        # assert type(output) == str, f"OpenAI API call failed: {output}"
        return output

    def process(self, ds, q1_col, masking_scheme):
        """Ask a secondary question about each primary question. Returns a new dataset with the secondary question added as a column called 'q2'."""

        def _add_q2(example):
            example[f"q2_{masking_scheme}"] = self.forward(
                example, q1_col, f"fc_{masking_scheme}"
            )
            return example

        ds = ds.add_column(name=f"q2_{masking_scheme}", column=[""] * len(ds))
        for i in tqdm(range(len(ds))):
            _add_q2(ds[i])  # debugging
        ds = ds.map(
            lambda x: _add_q2(x),
            load_from_cache_file=False,
        )
        return ds


class Gt_Secondary_Model(Secondary_Model):
    def __init__(self, gt_df):
        self.model_name = "groundtruth"
        self.gt_df = gt_df
        # self.gt_q2_path = "q2_gt_dataset.csv"
        # self.df = pd.read_csv(self.gt_q2_path)

    def forward(self, example, question_col, context_col):
        # Always return the original question q1
        id = example["id"].split("_")[0]
        if id in self.gt_df["id"].values:
            gt_q2 = self.gt_df[self.gt_df["id"] == id]["gt_q2"].values[0]
            if gt_q2 is not np.nan:
                return gt_q2
            else:
                raise NotImplementedError(
                    f"id {example['id']} has empty gt_q2 in self.gt_df"
                )
        else:
            raise NotImplementedError(f"id {example['id']} not found in self.gt_df")
