# PSD2 — Payment Services Directive 2 and Open Banking

## Overview
The Payment Services Directive 2 (PSD2) is the European Union regulation (Directive 2015/2366) governing electronic payment services. It entered into force in January 2018 and replaced the original PSD. PSD2 introduced regulatory requirements for third-party payment providers, mandated Strong Customer Authentication (SCA), and established the legal basis for Open Banking. While PSD2 is EU legislation, its principles influence global fintech regulation, including Pakistan's evolving open banking and payment system frameworks.

## Scope
Applies to all payment service providers operating within the European Economic Area (EEA), including banks, EMIs, payment institutions, and third-party providers (TPPs). Relevant globally as a benchmark for open banking regulation in other jurisdictions.

## Key Provisions

### Third-Party Provider (TPP) Access
PSD2 mandates that banks (Account Servicing Payment Service Providers — ASPSPs) must provide access to customer accounts to licensed TPPs via secure APIs.

#### Account Information Service Providers (AISPs)
- Aggregate account information from multiple banks for the customer
- Read-only access to account data with customer consent
- Must be authorized or registered with competent authority
- No handling of customer funds

#### Payment Initiation Service Providers (PISPs)
- Initiate payments from a customer's bank account on their behalf
- Must be authorized with competent authority
- Professional indemnity insurance or comparable guarantee required
- Real-time confirmation of payment initiation

### Strong Customer Authentication (SCA) — Article 97
- Required for: accessing payment accounts online, initiating electronic payments, and actions through remote channels that carry risk of fraud
- SCA requires at least 2 of 3 factors:
  - **Knowledge**: something only the user knows (password, PIN)
  - **Possession**: something only the user has (phone, hardware token)
  - **Inherence**: something the user is (fingerprint, face recognition)
- Dynamic linking: authentication code must be linked to specific amount and payee
- Exemptions: low-value transactions (under EUR 30 / cumulative EUR 100), trusted beneficiaries, recurring transactions, merchant-initiated transactions

### Regulatory Technical Standards (RTS) on SCA
- Defines technical requirements for SCA implementation
- Specifies API interface requirements for TPP access
- Fallback mechanism: if dedicated interface unavailable, TPPs may use the customer-facing interface
- 90-day re-authentication for account access
- Transaction risk analysis exemption (Transaction Risk Analysis — TRA) up to EUR 500 based on fraud rate thresholds

## Open Banking Standards

### API Standards
- **Berlin Group NextGenPSD2**: standardized API framework used across Europe
- **UK Open Banking Standard**: JSON REST APIs defined by Open Banking Implementation Entity (OBIE)
- **STET PSD2 API**: French standard for PSD2-compliant APIs
- Common elements: RESTful design, OAuth 2.0 authorization, eIDAS certificates for identification, JSON data format

### Consent Management
- Customer must explicitly consent to data sharing
- Granular consent: specific accounts, data types, and duration
- Consent revocation at any time
- Consent dashboard: customers can view and manage active consents
- Maximum consent duration: 90 days (re-authorization required)

### Security Requirements
- Qualified Website Authentication Certificates (QWACs) for mutual TLS
- Qualified electronic Seal Certificates (QSealCs) for message signing
- eIDAS framework for TPP identification
- Secure communication channels (TLS 1.2+)
- API rate limiting and abuse prevention

## Consumer Protection

### Liability for Unauthorized Transactions
- Maximum customer liability for unauthorized payments: EUR 50 (reduced from EUR 150 under PSD1)
- Zero liability in case of gross negligence by the PSP
- Refund within 1 business day for unauthorized transactions
- Right to dispute and provisional refund

### Transparency Requirements
- Clear fee disclosure before transaction execution
- Pre-contractual information in plain language
- No surcharging on consumer debit and credit card payments (within EEA)
- Real-time payment status notifications

### Complaint Handling
- Internal complaint resolution within 15 business days (max 35 days in exceptional cases)
- Access to out-of-court dispute resolution (ombudsman, ADR)
- Right to complain to competent authority

## Relevance to Pakistani Fintech

### SBP Open Banking Initiative
- SBP is developing an open banking framework influenced by PSD2 principles
- RAAST system provides foundational infrastructure for third-party payment integration
- API standardization efforts for interbank and fintech connectivity

### Lessons for Pakistan
- TPP licensing framework provides a model for regulating fintech aggregators
- SCA requirements inform security standards for digital payment authentication
- Consent management principles applicable to data sharing regulations
- Consumer protection provisions as benchmark for local regulation
