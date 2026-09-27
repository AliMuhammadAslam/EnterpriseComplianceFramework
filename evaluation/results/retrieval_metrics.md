# Retrieval quality

**Date**: 2026-09-02 02:14
**Questions**: 30 (holdout included, no model calls involved)

Relevance is judged at source-document level: a retrieved chunk counts as relevant if it came from the corpus file for the standard the question asks about. This needs no manual annotation, but it measures only whether the right document was found, not whether the specific passage that answers the question was among the chunks.

recall@k is the share of questions with at least one relevant chunk in the top k. coverage@k is the share of the required sources retrieved, which matters for questions spanning several standards. all@k is the share of questions where every required source appeared.

| Strategy | n | recall@1 | recall@5 | coverage@5 | all@5 | MRR | Never found |
|---|---|---|---|---|---|---|---|
| section-aware, single query | 30 | 0.97 | 1.00 | 0.93 | 0.83 | 0.98 | 0 |
| fixed-size, single query | 30 | 0.93 | 1.00 | 0.96 | 0.90 | 0.97 | 0 |
| section-aware, per standard | 30 | 0.97 | 1.00 | 0.94 | 0.87 | 0.98 | 0 |
| fixed-size, per standard | 30 | 0.93 | 1.00 | 0.96 | 0.90 | 0.96 | 0 |

## Multi-standard questions only

The case standard-specific retrieval exists for.

| Strategy | n | recall@5 | coverage@5 | all@5 | MRR |
|---|---|---|---|---|---|
| section-aware, single query | 9 | 1.00 | 0.78 | 0.44 | 1.00 |
| fixed-size, single query | 9 | 1.00 | 0.85 | 0.67 | 0.94 |
| section-aware, per standard | 9 | 1.00 | 0.81 | 0.56 | 1.00 |
| fixed-size, per standard | 9 | 1.00 | 0.85 | 0.67 | 0.93 |

## By category

| Strategy | Category | n | recall@5 | coverage@5 | MRR |
|---|---|---|---|---|---|
| section-aware, single query | multi_standard | 8 | 1.00 | 0.79 | 1.00 |
| section-aware, single query | multi_step | 6 | 1.00 | 0.94 | 1.00 |
| section-aware, single query | single_fact | 16 | 1.00 | 1.00 | 0.97 |
| fixed-size, single query | multi_standard | 8 | 1.00 | 0.83 | 0.94 |
| fixed-size, single query | multi_step | 6 | 1.00 | 1.00 | 1.00 |
| fixed-size, single query | single_fact | 16 | 1.00 | 1.00 | 0.97 |
| section-aware, per standard | multi_standard | 8 | 1.00 | 0.83 | 1.00 |
| section-aware, per standard | multi_step | 6 | 1.00 | 0.94 | 0.92 |
| section-aware, per standard | single_fact | 16 | 1.00 | 1.00 | 1.00 |
| fixed-size, per standard | multi_standard | 8 | 1.00 | 0.83 | 0.92 |
| fixed-size, per standard | multi_step | 6 | 1.00 | 1.00 | 1.00 |
| fixed-size, per standard | single_fact | 16 | 1.00 | 1.00 | 0.97 |
