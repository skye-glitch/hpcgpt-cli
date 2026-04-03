import os
import json
import logging
import argparse
import pandas as pd

SYSTEM_PROMPT = """\
You are an expert HPC (High Performance Computing) support assistant.
You will be given a support ticket including its title, description, and any comments from the support thread.

Your task is to summarize the ticket as a single question-and-answer pair:
- The "Q" (Question) should concisely capture the user's core issue or request, written as a natural question a user might ask.
- The "A" (Answer) should concisely capture the resolution, explanation, or guidance that was provided. If the issue was never resolved, note that.

Keep each part to 1–6 sentences. Do not include any extra formatting or commentary — output only the Q and A. When creating the Q and A provide responses that can be generalized to any user and do not reference any specific user or project.
Do not include any personal identifiable information (PII) in the response. PII includes names, email addresses, project identifiers, and any other information that could be used to identify a specific user or project.

If using an example project name or code in the response, use XXXX or delta-XXXX-gpu placeholder or XXXYYYYYY for access project codes
Do not include any information on whether the specfic ticket was closed or not. 
Do not include ticket ids in the response.

Format your response exactly like this:
Q: <the user's issue as a question>
A: <the resolution or guidance provided>
"""

def parse_command_line() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Summarize Jira tickets")
    p.add_argument('-i', '--input', 
                    required=True,
                    type=str, 
                    help="Input CSV file containing Jira ticket data")
    p.add_argument('-o', '--output', 
                    type=str, 
                    help='Name of the file to output prompt data in jsonl format to.')
    return p.parse_args()

def prep_ticket(row: pd.Series) -> str:
    """
    Generates the user text for an individual ticket.
    Args:
        row: A pandas series containing the ticket data.
    Returns:
        A string containing the user text for the ticket.
    """
    ticket_data = f"---\n"
    ticket_data += f"Title: {row['Summary']}\n"
    ticket_data += f"Description: {row['Description']}\n"
    ticket_data += f"Comments:\n"
    if pd.notnull(row["Comment"]):
        ticket_data += f"Comment: {row['Comment']}\n"
    for i in range(1, 110):
        if f"Comment.{i}" in row.keys() and pd.notnull(row[f"Comment.{i}"]):
            ticket_data += f"Comment {i}: {row[f'Comment.{i}']}\n"
        else:
            break
    ticket_data += "---"
    return ticket_data

def prep_ticket_data(df: pd.DataFrame, output_file: str="prompts.jsonl") -> str:
    """
    Takes ticket data from a pandas dataframe and writes it as a list of prompts in jsonl format to a file.
    Args:
        df: A pandas dataframe containing the ticket data.
        output_file: The name of the file to output the prompts to. Defaults to prompts.jsonl.
    Returns:
        None. Writes the prompts to the output file.
    """

    # Create directory if necessary
    dirname = os.path.dirname(output_file)
    if not os.path.exists(dirname) and dirname != '':
        os.makedirs(os.path.dirname(output_file))

    # Write the prompts to the output file
    with open(output_file, "w") as f:
        for _, row in df.iterrows():
            ticket_data = prep_ticket(row)
            f.write(json.dumps({
                "custom_id": row["Issue key"],
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {"messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": ticket_data}], "temperature": 0.7, "max_tokens": 500}
            }) + "\n")
    logging.info(f"Wrote {_} prompts to {output_file}")

def main(args: argparse.Namespace):
    logging.basicConfig(level=logging.INFO)
    logging.info(f"Reading input data from: {args.input}")
    df = pd.read_csv(args.input, dtype=str)
    logging.info(f"Loaded {len(df)} tickets from {args.input}")
    
    prep_ticket_data(df, args.output)

if __name__ == "__main__":
    args = parse_command_line()
    main(args)