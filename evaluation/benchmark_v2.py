"""Expanded benchmark: 42 questions across three difficulty categories.

The original 10 questions could not separate the system's components. Six of
them scored a perfect 5.0 under plain fixed-size RAG, leaving no headroom, and
every one targeted a single standard, so standard-specific retrieval had
nothing to do. This set is built to fix both problems.

Categories:
  single_fact    a precise lookup, deeper in the documents than the v1 set
  multi_standard requires facts from two or more standards in one answer
  multi_step     requires combining or reasoning over several facts

Every ground truth is taken from the corpus in knowledge_data/. Nothing here
is from outside it, so a wrong answer is a retrieval or reasoning failure
rather than a gap in the corpus.

The holdout split is reserved. Do not tune prompts or retrieval against it.
"""

RUBRIC = """Scoring rubric, fixed before any answer was scored.

Each answer is scored 1 to 5 on three dimensions.

citation_accuracy
  5  Every identifier cited (clause, article, section, requirement, control)
     is correct and appears in the corpus. No invented identifiers.
  4  All identifiers correct but at least one expected identifier is missing.
  3  Mostly correct, with one wrong or imprecise identifier.
  2  Several identifiers wrong, or vague references instead of identifiers.
  1  Identifiers invented, or none given where the question requires them.

hallucination_rate  (higher is better: 5 means no hallucination)
  5  Every factual claim is supported by the corpus.
  4  All material claims supported; a minor unsupported aside.
  3  One unsupported claim that affects the answer.
  2  Several unsupported claims, or a fabricated figure.
  1  The central claim is fabricated.

answer_relevance
  5  Answers every part of the question, at the right level of detail.
  4  Answers the question with a minor omission.
  3  Answers the main part but misses a sub-question.
  2  Partially responsive, or padded with irrelevant material.
  1  Does not answer what was asked.

For multi_standard questions, an answer that covers only one standard scores
no higher than 3 on answer_relevance, however accurate that one standard is.
"""

QUESTIONS_V2 = [
    {
        "id": "MS-01",
        "category": "multi_standard",
        "split": "dev",
        "standard": "SBP Regulations, GDPR, PECA 2016",
        "question": "A Pakistani fintech serving EU customers suffers a personal data "
                    "breach. What are its notification deadlines under SBP rules, under "
                    "GDPR, and under PECA 2016?",
        "ground_truth": "SBP requires notification to SBP within 72 hours of discovering a "
                        "personal data breach that may affect customer interests or "
                        "regulatory compliance. GDPR requires notification to the "
                        "supervisory authority within 72 hours of becoming aware, and "
                        "notification to affected individuals if the breach poses a high "
                        "risk to their rights. PECA 2016 does not mandate specific data "
                        "breach notification timelines, though the FIA Cybercrime Wing "
                        "handles complaints and investigations.",
    },
    {
        "id": "MS-02",
        "category": "multi_standard",
        "split": "dev",
        "standard": "Pakistan AML/CFT, GDPR",
        "question": "Pakistani AML/CFT rules require records to be kept for years, while "
                    "GDPR requires data not to be kept longer than necessary. What are the "
                    "specific retention periods, and how are the two reconciled?",
        "ground_truth": "AML/CFT requires a minimum of 5 years: CDD records for 5 years after "
                        "the end of the business relationship, transaction records for 5 "
                        "years from the date of transaction, and STRs and CTRs for 5 years "
                        "from the date of filing. GDPR's storage limitation principle "
                        "(Article 5) requires data to be kept in identifiable form only as "
                        "long as necessary. The two are reconciled because GDPR Article 6 "
                        "provides legal obligation as a lawful basis for processing, so the "
                        "mandated AML retention is itself the necessity.",
    },
    {
        "id": "MS-03",
        "category": "multi_standard",
        "split": "dev",
        "standard": "SBP Data Localisation Requirements, GDPR",
        "question": "What approvals or safeguards are needed to transfer customer data out "
                    "of Pakistan, and separately out of the EU, under SBP rules and GDPR?",
        "ground_truth": "SBP requires prior written approval for any transfer of customer "
                        "financial data, transaction records or PII outside Pakistan, and "
                        "the primary copy must remain on servers physically located in "
                        "Pakistan. Restricted categories include KYC records, account and "
                        "transaction history, credit information, and AML/CFT suspicious "
                        "activity data. GDPR requires adequate safeguards for transfers "
                        "outside the EU/EEA: Standard Contractual Clauses, Binding Corporate "
                        "Rules, or an adequacy decision.",
    },
    {
        "id": "MS-04",
        "category": "multi_standard",
        "split": "dev",
        "standard": "SBP Data Localisation Requirements, PCI DSS",
        "question": "What does SBP require for encrypting data in transit across borders, "
                    "and what is the corresponding PCI DSS requirement for cardholder data?",
        "ground_truth": "SBP requires all cross-border data in transit, where permitted, to "
                        "use strong encryption with a minimum of TLS 1.2 and TLS 1.3 "
                        "recommended, and transmissions must be logged for audit purposes. "
                        "PCI DSS Requirement 4 requires cardholder data to be protected with "
                        "strong cryptography during transmission over open, public networks.",
    },
    {
        "id": "MS-05",
        "category": "multi_standard",
        "split": "holdout",
        "standard": "PECA 2016, GDPR",
        "question": "Compare the maximum monetary penalty for electronic fraud under PECA "
                    "2016 with the maximum penalty under the more severe GDPR tier.",
        "ground_truth": "PECA 2016 Section 13, electronic fraud, carries imprisonment up to "
                        "2 years or a fine up to PKR 10 million, or both. GDPR Tier 2 "
                        "penalties reach up to EUR 20 million or 4 percent of global annual "
                        "turnover, whichever is higher. The GDPR maximum is substantially "
                        "larger and is turnover linked, whereas the PECA fine is a fixed cap.",
    },
    {
        "id": "MS-06",
        "category": "multi_standard",
        "split": "dev",
        "standard": "Pakistan AML/CFT, SBP Regulations",
        "question": "Which compliance activities must be performed at least annually under "
                    "Pakistani AML/CFT rules and under SBP information security guidelines?",
        "ground_truth": "Under AML/CFT: staff training at least annually, the institutional "
                        "ML/TF risk assessment documented and updated at least annually, and "
                        "an independent internal or external AML/CFT audit annually. Under "
                        "SBP Information Security Guidelines: an annual IT audit by qualified "
                        "external auditors.",
    },
    {
        "id": "MS-07",
        "category": "multi_standard",
        "split": "holdout",
        "standard": "SBP Regulations, Pakistan AML/CFT, GDPR",
        "question": "Which named officer or role must be appointed under SBP information "
                    "security guidelines, under AML/CFT rules, and under GDPR?",
        "ground_truth": "SBP Information Security Guidelines require appointment of a Chief "
                        "Information Security Officer (CISO). AML/CFT rules require a "
                        "designated Compliance Officer with direct Board reporting. GDPR "
                        "requires a Data Protection Officer for public authorities, "
                        "organisations conducting large-scale monitoring, or those processing "
                        "special categories of data.",
    },
    {
        "id": "MS-08",
        "category": "multi_standard",
        "split": "dev",
        "standard": "ISO 27001, PCI DSS",
        "question": "Which ISO 27001:2022 Annex A controls govern access control and "
                    "privileged access, and which PCI DSS requirements cover the same ground?",
        "ground_truth": "ISO 27001:2022 Annex A: A.5.15 Access control, A.5.18 Access rights, "
                        "A.8.2 Privileged access rights, and A.8.3 Information access "
                        "restriction. A.5.16 Identity management and A.8.5 Secure "
                        "authentication are also relevant. PCI DSS Requirement 7 restricts "
                        "access to system components and cardholder data by business "
                        "need-to-know, and Requirement 8 covers identifying users and "
                        "authenticating access, including multi-factor authentication.",
    },

    {
        "id": "MST-01",
        "category": "multi_step",
        "split": "dev",
        "standard": "SBP Branchless Banking Regulations",
        "question": "A customer holds a Level 1 branchless banking account and wants to "
                    "maintain a balance of PKR 450,000. Is this permitted? If not, what tier "
                    "is required and what verification does it demand?",
        "ground_truth": "Not permitted. A Level 1 account has a balance limit of PKR 400,000 "
                        "and a monthly transaction limit of PKR 80,000, and requires biometric "
                        "verification. PKR 450,000 exceeds that limit, so the customer must "
                        "upgrade to Level 2, which has a balance limit of PKR 500,000, no "
                        "monthly transaction limit, and requires full KYC with source of "
                        "income documentation.",
    },
    {
        "id": "MST-02",
        "category": "multi_step",
        "split": "dev",
        "standard": "Pakistan AML/CFT",
        "question": "A customer makes a cash deposit of PKR 2.5 million and the branch "
                    "suspects money laundering. Which reports must be filed, to whom, and "
                    "within what deadlines? Is there anything staff must not do?",
        "ground_truth": "Two reports. A Currency Transaction Report, because the cash "
                        "transaction exceeds PKR 2 million, filed with the Financial "
                        "Monitoring Unit within 7 working days after the end of the month. A "
                        "Suspicious Transaction Report, which has no monetary threshold and is "
                        "triggered by suspicion, filed with the FMU within 3 working days of "
                        "forming that suspicion. Staff must not tip off the customer, which is "
                        "prohibited. Internally, staff report to the Compliance Officer, who "
                        "reviews and files with the FMU.",
    },
    {
        "id": "MST-03",
        "category": "multi_step",
        "split": "dev",
        "standard": "SBP EMI Regulations 2019",
        "question": "A startup wants to launch as an Electronic Money Institution in "
                    "Pakistan. What is the minimum capital, what corporate form is required, "
                    "and how must customer funds be held once operating?",
        "ground_truth": "Minimum paid-up capital of PKR 200 million. The entity must be "
                        "incorporated as a public or private limited company under the "
                        "Companies Act 2017, and directors and key executives must meet fit "
                        "and proper criteria. A comprehensive business plan with 5-year "
                        "financial projections is required. Once operating, customer funds "
                        "must be safeguarded in scheduled banks and cannot be commingled with "
                        "the EMI's own operational funds.",
    },
    {
        "id": "MST-04",
        "category": "multi_step",
        "split": "holdout",
        "standard": "GDPR, SBP Regulations, PECA 2016",
        "question": "A breach at a Pakistani fintech exposes records of both EU and Pakistani "
                    "customers. Set out every notification obligation, the recipient, and the "
                    "deadline for each.",
        "ground_truth": "Under GDPR, notify the supervisory authority within 72 hours of "
                        "becoming aware, and notify affected individuals directly if the "
                        "breach poses a high risk to their rights. Under SBP rules, notify SBP "
                        "within 72 hours of discovering a personal data breach that may affect "
                        "customer interests or regulatory compliance. PECA 2016 sets no "
                        "specific notification deadline, but the FIA Cybercrime Wing is the "
                        "investigation and enforcement body and incident response plans should "
                        "include FIA reporting procedures.",
    },
    {
        "id": "MST-05",
        "category": "multi_step",
        "split": "dev",
        "standard": "PECA 2016",
        "question": "An employee copies the customer database and sells it to a competitor. "
                    "Which PECA 2016 offences could apply, and what is the maximum penalty "
                    "for each?",
        "ground_truth": "Section 4, unauthorised copying or transmission of data, carries "
                        "imprisonment up to 6 months or a fine up to PKR 100,000, or both. "
                        "Section 26, violation of the right to privacy through unauthorised "
                        "disclosure of personal data, carries imprisonment up to 3 years or a "
                        "fine up to PKR 1 million, or both. If identity information is "
                        "subsequently misused, Section 16 identity theft carries imprisonment "
                        "up to 3 years or a fine up to PKR 5 million, or both.",
    },
    {
        "id": "MST-06",
        "category": "multi_step",
        "split": "dev",
        "standard": "PCI DSS",
        "question": "A merchant processes 3 million card transactions a year. Which PCI DSS "
                    "compliance level applies, what validation is required at that level, and "
                    "what does v4.0 require for authentication into the cardholder data "
                    "environment?",
        "ground_truth": "Level 2 applies, covering merchants processing 1 to 6 million "
                        "transactions per year. Level 2 requires an annual Self-Assessment "
                        "Questionnaire rather than an on-site assessment by a QSA, which is "
                        "required only at Level 1 for merchants above 6 million transactions. "
                        "PCI DSS v4.0 requires multi-factor authentication for all access into "
                        "the cardholder data environment.",
    },

    {
        "id": "SF-01",
        "category": "single_fact",
        "split": "dev",
        "standard": "SBP Branchless Banking Regulations",
        "question": "For a Level 0 branchless banking account, what is the monthly "
                    "transaction limit, the balance limit, and the documentation needed to "
                    "open it?",
        "ground_truth": "Monthly transaction limit of PKR 25,000, balance limit of PKR 15,000, "
                        "and the account is opened with CNIC only.",
    },
    {
        "id": "SF-02",
        "category": "single_fact",
        "split": "dev",
        "standard": "Pakistan AML/CFT",
        "question": "What is the reporting threshold for a Currency Transaction Report in "
                    "Pakistan and by when must it be filed?",
        "ground_truth": "Cash transactions exceeding PKR 2 million, or the equivalent in "
                        "foreign currency, must be reported to the Financial Monitoring Unit. "
                        "Electronic fund transfers exceeding PKR 2 million are also "
                        "reportable. CTRs must be filed within 7 working days after the end "
                        "of the month.",
    },
    {
        "id": "SF-03",
        "category": "single_fact",
        "split": "dev",
        "standard": "ISO 27001",
        "question": "How many controls does ISO 27001:2022 Annex A contain, and how are they "
                    "organised?",
        "ground_truth": "93 controls organised into 4 themes: Organizational controls "
                        "(A.5.1 to A.5.37), People controls (A.6.1 to A.6.8), Physical "
                        "controls (A.7.1 to A.7.14), and Technological controls (A.8.1 to "
                        "A.8.34).",
    },
    {
        "id": "SF-04",
        "category": "single_fact",
        "split": "holdout",
        "standard": "PECA 2016",
        "question": "What is the maximum penalty for system interference under PECA 2016, and "
                    "which section covers it?",
        "ground_truth": "Section 5 covers system interference, defined as intentionally "
                        "interfering with or damaging an information system, including DDoS "
                        "attacks, malware deployment and sabotage of financial systems. The "
                        "penalty is imprisonment up to 2 years, or a fine up to PKR 500,000, "
                        "or both.",
    },
    {
        "id": "SF-05",
        "category": "single_fact",
        "split": "dev",
        "standard": "ISO 27001",
        "question": "Which ISO 27001:2022 Annex A control covers data leakage prevention, and "
                    "which covers data masking?",
        "ground_truth": "A.8.12 covers data leakage prevention and A.8.11 covers data masking. "
                        "Both sit in Annex A Theme 4, Technological controls.",
    },
    {
        "id": "SF-06",
        "category": "single_fact",
        "split": "holdout",
        "standard": "PECA 2016",
        "question": "Under PECA 2016, for how long may a service provider be required to "
                    "preserve specified data on government request, and under which section?",
        "ground_truth": "Up to 90 days, under Section 29. Section 30 separately provides for "
                        "production orders for data and records.",
    },

    {
        "id": "MS-09",
        "category": "multi_standard",
        "split": "dev",
        "standard": "ISO 22301, SBP Regulations",
        "question": "How often must business continuity plans be exercised under ISO 22301, "
                    "and what does SBP require of financial institutions on the same point?",
        "ground_truth": "ISO 22301 requires, under Exercise and Testing (8.5) within Clause 8 "
                        "Operation, regular exercises to validate business "
                        "continuity plans, at least annually, using tabletop exercises, "
                        "simulations or full-scale drills, with post-exercise reviews and "
                        "results documented and used for plan improvement. SBP requires "
                        "financial institutions to maintain tested business continuity and "
                        "disaster recovery plans, and its Information Security Guidelines "
                        "list business continuity and disaster recovery plans as a "
                        "requirement.",
    },
    {
        "id": "MS-10",
        "category": "multi_standard",
        "split": "dev",
        "standard": "SOC 2, SBP Regulations, PCI DSS",
        "question": "What do SOC 2, SBP digital lending rules and PCI DSS each require for "
                    "encrypting data at rest and in transit?",
        "ground_truth": "SOC 2 Security criteria requires encryption of data at rest and in "
                        "transit. SBP digital lending regulations require mandatory data "
                        "encryption in transit and at rest. PCI DSS Requirement 3 covers "
                        "protecting stored account data through encryption, masking, "
                        "truncation or hashing, and Requirement 4 requires cardholder data "
                        "to be protected with strong cryptography during transmission over "
                        "open, public networks.",
    },
    {
        "id": "MS-11",
        "category": "multi_standard",
        "split": "dev",
        "standard": "ISO 27001, SOC 2, PCI DSS",
        "question": "Compare the audit or certification cycle for ISO 27001, SOC 2 and PCI "
                    "DSS at the highest merchant level.",
        "ground_truth": "ISO 27001 certification is achieved through a two-stage external "
                        "audit by an accredited certification body, Stage 1 documentation "
                        "review and Stage 2 on-site assessment, with surveillance audits "
                        "annually and recertification every 3 years. SOC 2 Type I assesses "
                        "control design at a point in time, while Type II assesses "
                        "operational effectiveness over a period of 3 to 12 months, typically "
                        "6 to 12. PCI DSS Level 1, for merchants above 6 million transactions "
                        "per year, requires an annual on-site assessment by a QSA.",
    },
    {
        "id": "MS-12",
        "category": "multi_standard",
        "split": "dev",
        "standard": "PCI DSS, SOC 2, ISO 27001",
        "question": "Which requirement or control covers multi-factor authentication under "
                    "PCI DSS v4.0, SOC 2 and ISO 27001:2022?",
        "ground_truth": "PCI DSS v4.0 requires multi-factor authentication for all access "
                        "into the cardholder data environment, under Requirement 8, which "
                        "covers identifying users and authenticating access. SOC 2 lists "
                        "multi-factor authentication under the Security Trust Service "
                        "Criteria as protection against unauthorized access. ISO 27001:2022 "
                        "Annex A control A.8.5 covers secure authentication, supported by "
                        "A.5.17 authentication information.",
    },
    {
        "id": "MS-13",
        "category": "multi_standard",
        "split": "holdout",
        "standard": "ISO 27001, SOC 2, SBP Regulations",
        "question": "Which ISO 27001:2022 controls cover information security incident "
                    "management, and what do SOC 2 and SBP require on incident response?",
        "ground_truth": "ISO 27001:2022 covers this across A.5.24 incident management "
                        "planning and preparation, A.5.25 assessment and decision on "
                        "information security events, A.5.26 response to information security "
                        "incidents, A.5.27 learning from incidents, and A.5.28 collection of "
                        "evidence. SOC 2 includes incident response procedures under the "
                        "Availability criteria and incident response planning among its key "
                        "controls. SBP Information Security Guidelines require an incident "
                        "response plan with defined escalation procedures.",
    },
    {
        "id": "MS-14",
        "category": "multi_standard",
        "split": "dev",
        "standard": "ISO 27001, SBP Regulations, SOC 2",
        "question": "How do ISO 27001, SBP and SOC 2 each address third-party and outsourcing "
                    "risk?",
        "ground_truth": "ISO 27001:2022 covers this in A.5.19 information security in "
                        "supplier relationships, A.5.20 addressing information security within "
                        "supplier agreements, A.5.21 managing information security in the ICT "
                        "supply chain, and A.5.22 monitoring, review and change management of "
                        "supplier services. SBP requires third-party risk assessments for "
                        "outsourced services, an outsourcing risk management policy, and "
                        "notification to SBP of all material outsourcing arrangements, with "
                        "data sovereignty clauses where operations are outsourced to foreign "
                        "providers. SOC 2 lists vendor management among its key controls.",
    },
    {
        "id": "MS-15",
        "category": "multi_standard",
        "split": "dev",
        "standard": "GDPR, Pakistan AML/CFT",
        "question": "A customer invokes the GDPR right to erasure, but the institution holds "
                    "their records under AML/CFT rules. Which provisions are in tension and "
                    "how is the conflict resolved?",
        "ground_truth": "GDPR Article 17 gives the right to erasure, the right to be "
                        "forgotten, under certain circumstances. Pakistani AML/CFT rules "
                        "require CDD records to be retained for a minimum of 5 years after "
                        "the end of the business relationship, transaction records for 5 "
                        "years from the transaction date, and STRs and CTRs for 5 years from "
                        "filing. The right to erasure is not absolute: GDPR Article 6 "
                        "recognises compliance with a legal obligation as a lawful basis for "
                        "processing, so records held under a statutory retention requirement "
                        "may be kept for that period.",
    },
    {
        "id": "MS-16",
        "category": "multi_standard",
        "split": "dev",
        "standard": "ISO 27001, Pakistan AML/CFT, SOC 2",
        "question": "What are the staff training obligations under ISO 27001, Pakistani "
                    "AML/CFT rules and SOC 2, and how often must training occur?",
        "ground_truth": "ISO 27001:2022 Annex A control A.6.3 covers information security "
                        "awareness, education and training, without prescribing a frequency. "
                        "Pakistani AML/CFT rules require staff training initially and as "
                        "refresher training at least annually, and SBP separately requires "
                        "staff training on AML/CFT at least annually. SOC 2 lists employee "
                        "security awareness training among its key controls.",
    },
    {
        "id": "MS-17",
        "category": "multi_standard",
        "split": "dev",
        "standard": "ISO 27001, Pakistan AML/CFT",
        "question": "What does ISO 27001:2022 require regarding employee screening, and does "
                    "the Pakistani AML/CFT framework impose a comparable obligation?",
        "ground_truth": "ISO 27001:2022 Annex A control A.6.1 covers screening, within the "
                        "People controls theme. The Pakistani AML/CFT compliance programme "
                        "requirements include screening of employees during hiring, so both "
                        "frameworks impose a pre-employment screening obligation.",
    },
    {
        "id": "MS-18",
        "category": "multi_standard",
        "split": "dev",
        "standard": "ISO 27001, PCI DSS, SOC 2",
        "question": "Which ISO 27001:2022 controls cover logging and monitoring, and what are "
                    "the corresponding PCI DSS and SOC 2 requirements?",
        "ground_truth": "ISO 27001:2022 covers this in A.8.15 logging, A.8.16 monitoring "
                        "activities, and A.8.17 clock synchronisation. PCI DSS Requirement 10 "
                        "requires logging and monitoring of all access to system components "
                        "and cardholder data, including audit trails and SIEM. SOC 2 lists "
                        "logging and monitoring among its key controls.",
    },
    {
        "id": "MS-19",
        "category": "multi_standard",
        "split": "holdout",
        "standard": "SBP Regulations, PCI DSS, SOC 2",
        "question": "What do SBP, PCI DSS and SOC 2 each require in relation to vulnerability "
                    "assessment and penetration testing?",
        "ground_truth": "SBP Information Security Guidelines require regular vulnerability "
                        "assessments and penetration testing. PCI DSS Requirement 11 requires "
                        "regular testing of the security of systems and networks, including "
                        "vulnerability scans and penetration testing, and Requirement 6 covers "
                        "patch management and secure development. SOC 2 includes vulnerability "
                        "management and penetration testing under the Security criteria.",
    },
    {
        "id": "MS-20",
        "category": "multi_standard",
        "split": "dev",
        "standard": "ISO 27001, SBP Regulations, SOC 2",
        "question": "Which ISO 27001:2022 controls govern information classification, and what "
                    "do SBP and SOC 2 require on the same subject?",
        "ground_truth": "ISO 27001:2022 covers this in A.5.12 classification of information "
                        "and A.5.13 labelling of information. SBP Information Security "
                        "Guidelines require data classification and handling procedures. SOC 2 "
                        "requires under the Confidentiality criteria that data classified as "
                        "confidential is protected as committed or agreed, supported by "
                        "encryption, access controls and data masking.",
    },
]


def _load_v1():
    """The original 10 questions, tagged so the two sets can be told apart."""
    from evaluation.quantitative_eval import QUESTIONS

    tagged = []
    for q in QUESTIONS:
        entry = dict(q)
        entry.setdefault("category", "single_fact")
        entry.setdefault("split", "dev")
        entry["source_set"] = "v1"
        tagged.append(entry)
    return tagged


def all_questions(include_holdout: bool = False):
    """The full 30-question benchmark, holdout excluded unless asked for."""
    combined = _load_v1() + [dict(q, source_set="v2") for q in QUESTIONS_V2]
    if include_holdout:
        return combined
    return [q for q in combined if q.get("split") != "holdout"]


def by_category(include_holdout: bool = False):
    grouped = {}
    for q in all_questions(include_holdout):
        grouped.setdefault(q["category"], []).append(q)
    return grouped


if __name__ == "__main__":
    everything = all_questions(include_holdout=True)
    dev = all_questions()
    print(f"total questions: {len(everything)}")
    print(f"  development:   {len(dev)}")
    print(f"  holdout:       {len(everything) - len(dev)}")
    print()
    for category, items in sorted(by_category(True).items()):
        multi = sum(
            1 for q in items
            if len([s for s in q["standard"].split(",") if s.strip()]) > 1
        )
        print(f"{category:16} {len(items):3}  ({multi} spanning multiple standards)")
