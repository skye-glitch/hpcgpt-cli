# NCSA Ticket Ingest

These are NCSA's scripts for converting Jira support ticket data in a dataset suitable for querying with an mcp server. 

Tickets are downloaded on a regular basis from jira in csv format, then run through prep_tickets.py which converts them into the jsonl format that can then be submitted to an llm for processing. We use LLM (via [llmflux](https://github.com/ncsa/llmflux)) to process each ticket and generate a concise Q&A pair, stripping any PII in the process.

The resulting Q&A list is intended to be indexed and searched using a RAG chatbot.

### prep_tickets.py
Converts a CSV exported by JIRA into a `.jsonl` formatted batch prompt file that can be processed by LLMFlux.

```bash
python prep_tickets.py -i data/raw/<tickets>.csv -o data/input/<tickets>.jsonl
```

Each ticket is formatted with its title, description, and all comments, then wrapped in a system prompt that instructs the LLM to produce a generalized Q&A pair and remove PII.

### summarize_tickets.py
Submits a `.jsonl` prompt file for processing using `llmflux`.

```bash
python summarize_tickets.py
```

This uses `vllm` as the inference engine and submits a Slurm job to a GPU partition. Output results are written to `data/output/`.

## Notes

- **LLM Backend:** Uses [llmflux](https://github.com/ncsa/llmflux) with `vllm` for batch inference on Slurm.
- **PII Removal:** The LLM prompt instructs the model to omit names, emails, project identifiers, and other PII. This process was tested on 100 NCSA Delta tickets using the Qwen3-8B model with minimal PII being detected in outputs. (1 ticket's Q/A result had a users name in it.)

## TODO

- [ ] Add duplicate Q&A removal step
- [ ] Add support for ticket attachments
