# Citation grounding over benchmark answers

**Date**: 2026-09-28 01:36
**Source**: ablation_20260903_014438.csv
**Answers checked**: 245

Every regulatory identifier in each answer was checked against the context that answer actually saw. This reports grounding as a share of claims rather than as a rating, which is what an ordinal judge score cannot give.

An identifier counts as supported if it appears in a retrieved chunk. This verifies provenance, not truth: an identifier taken from a poisoned or incorrect source still counts as supported. See the fabricated regulation test for why that distinction matters.

| Condition | Answers | Identifiers | Unsupported | Unsupported share | Fully grounded answers |
|---|---|---|---|---|---|
| no_retrieval | 35 | 71 | 71 | 100.0% | 0% |
| fixed_rag | 35 | 61 | 6 | 9.8% | 79% |
| section_aware_rag | 35 | 41 | 5 | 12.2% | 82% |
| standard_specific_fixed | 35 | 64 | 6 | 9.4% | 82% |
| standard_specific_section_aware | 35 | 39 | 5 | 12.8% | 81% |
| ecf_original | 35 | 59 | 9 | 15.3% | 70% |
| ecf_tuned | 35 | 74 | 11 | 14.9% | 76% |

## By question category

| Condition | Category | Identifiers | Unsupported share |
|---|---|---|---|
| no_retrieval | multi_standard | 38 | 100.0% |
| no_retrieval | multi_step | 20 | 100.0% |
| no_retrieval | single_fact | 13 | 100.0% |
| fixed_rag | multi_standard | 20 | 5.0% |
| fixed_rag | multi_step | 10 | 20.0% |
| fixed_rag | single_fact | 31 | 9.7% |
| section_aware_rag | multi_standard | 16 | 0.0% |
| section_aware_rag | multi_step | 10 | 20.0% |
| section_aware_rag | single_fact | 15 | 20.0% |
| standard_specific_fixed | multi_standard | 23 | 4.3% |
| standard_specific_fixed | multi_step | 10 | 20.0% |
| standard_specific_fixed | single_fact | 31 | 9.7% |
| standard_specific_section_aware | multi_standard | 14 | 0.0% |
| standard_specific_section_aware | multi_step | 10 | 20.0% |
| standard_specific_section_aware | single_fact | 15 | 20.0% |
| ecf_original | multi_standard | 21 | 9.5% |
| ecf_original | multi_step | 9 | 22.2% |
| ecf_original | single_fact | 29 | 17.2% |
| ecf_tuned | multi_standard | 35 | 22.9% |
| ecf_tuned | multi_step | 10 | 20.0% |
| ecf_tuned | single_fact | 29 | 3.4% |